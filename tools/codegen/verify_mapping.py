"""Check a mapping workbook against the table scripts in the sql/ folder.

No database is involved: every fact comes from the scripts in ``sql/``, read
by ``tools/mapping_spec/schema_catalog.py``. Run it before handing a mapping
to a developer (ba-4-create-mapping-spec) and again before generating code from it
(dev-2-implement-mapping):

    python tools/codegen/verify_mapping.py M_CUSTOMER_ACCOUNT

What it proves, in order:
 1. The workbook itself validates (same checks as validate_spec.py).
 2. Every source table has a CREATE TABLE script, every column the mapping
    names exists in it, every 'direct' column fits its target type, and a
    nullable source column is not copied into a NOT NULL target column
    unchecked.
 3. The target table: does its script exist, and how do its columns differ
    from the mapping (new, retyped, missing)? This decides whether the
    generator writes a CREATE TABLE or an ALTER TABLE. A NOT NULL column
    without a default that the mapping does not fill is a failure. A package
    in sql/ other than the mapping's own that already writes the target is a
    warning (package_usage.py): two loads on one table.
 4. Grain, from the keys in the scripts: for each join, do the joined columns
    cover a primary or unique key of the joined table? If they do, a driving
    row has at most one match and the join cannot multiply rows. If they do
    not, the join may multiply rows and the grain may be broken. In an
    aggregating mapping (Group_By) such a join is what gets summed; two of
    them multiply each other and count values twice, which is a warning.
 5. The business key: when it is a direct copy of a unique key of the driving
    table and no join can multiply rows, it is unique by construction. In an
    aggregating mapping it is unique by construction when it equals Group_By.
 6. The Reload_Predicate uses target columns only.

What it cannot prove, because there are no rows to look at: how many rows a
run produces, whether the key really is unique in the data, how many rows an
inner join leaves out, or whether real values fit the target types. The
acceptance criteria of the workbook become utPLSQL tests, and those are what
check the data once a developer has deployed the code.

Exit code 1 when anything FAILs.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mapping_spec"))

import package_usage  # noqa: E402
import schema_catalog  # noqa: E402
from mapping_validation import STRING_LITERAL_PATTERN, aggregate_spans, column_refs, referenced_source_columns, validate_mapping  # noqa: E402
from sqlmodel import fits, parse_type, primary_key, table_columns, target_columns  # noqa: E402
from workbook_format import ITEM_ALIAS, bare_table, read_mapping, resolve_mapping_path  # noqa: E402

# Words that can appear in a Reload_Predicate and are not column names.
SQL_WORDS = {
    "AND", "OR", "NOT", "IN", "IS", "NULL", "BETWEEN", "LIKE", "DATE", "TIMESTAMP", "TRUE", "FALSE",
    "CASE", "WHEN", "THEN", "ELSE", "END", "EXISTS", "SELECT", "FROM", "WHERE", "INTERVAL", "DAY", "MONTH", "YEAR",
}
IDENTIFIER = re.compile(r"(?<![\w.:'])([A-Za-z][A-Za-z0-9_$#]*)\b(?!\s*\()")
RANGE_OPERATORS = re.compile(r"<=|>=|<|>|\bBETWEEN\b", re.IGNORECASE)


class Result:
    def __init__(self):
        self.lines = []
        self.failed = 0

    def add(self, level: str, message: str) -> None:
        self.lines.append((level, message))
        if level == "FAIL":
            self.failed += 1
        print("  {0:4}  {1}".format(level, message))


def _source_tables(mapping) -> dict:
    """{BARE: schema_catalog.Table or None} for the driving table and every joined table."""
    return {bare_table(q): schema_catalog.table(q) for q in mapping.source_tables}


def _qualified_by_bare(mapping) -> dict:
    return {bare_table(q): q for q in mapping.source_tables}


# ---------------------------------------------------------------------------
# 2. Sources
# ---------------------------------------------------------------------------


def check_sources(mapping, result: Result) -> bool:
    ok = True
    tables = {}
    for qualified in mapping.source_tables:
        state = schema_catalog.table_state(qualified)
        found = schema_catalog.table(qualified)
        if state == "unknown":
            result.add("FAIL", "source table {0} is not in the sql/ folder".format(qualified))
            ok = False
        elif state == "no_ddl":
            result.add(
                "FAIL",
                "source table {0} has no CREATE TABLE script in the sql/ folder (only a grant), "
                "so its columns cannot be verified - export the table script".format(qualified),
            )
            ok = False
        tables[bare_table(qualified)] = (qualified, found if state == "ok" else None)

    referenced = referenced_source_columns(mapping)

    missing = 0
    for table, column in sorted(referenced):
        if table not in tables:
            continue  # validation already reported an unknown table
        qualified, found = tables[table]
        if found is not None and column not in found.columns:
            result.add("FAIL", "{0}.{1} does not exist in {2} (sql/ folder)".format(table, column, qualified))
            missing += 1
            ok = False
    checked = sum(1 for t, _c in referenced if t in tables and tables[t][1] is not None)
    if not missing and checked:
        result.add("PASS", "all {0} referenced source columns exist in the sql/ folder".format(checked))
    _warn_planned(tables, referenced, result)

    left_joined = {bare_table(j.table) for j in mapping.joins if j.join_type.strip().lower() == "left"}
    for col in mapping.columns:
        if not (col.is_direct and not col.is_pseudo):
            continue
        table = bare_table(col.source_table)
        qualified, found = tables.get(table, ("", None))
        source = found.columns.get(col.source_columns[0]) if found is not None else None
        if source is None:
            continue
        if col.target_type and not fits(source.type, col.target_type):
            result.add(
                "WARN",
                "{0}: direct copy of {1}.{2} ({3}) into {4} may not fit - check the type".format(
                    col.target_column, table, col.source_columns[0], source.type, col.target_type,
                ),
            )
        if col.nullable.strip().upper() == "N":
            if source.nullable:
                result.add(
                    "WARN",
                    "{0} is NOT NULL but is copied directly from {1}.{2}, which allows NULL - the load "
                    "fails on a row where it is empty; filter those rows or give the rule a default".format(
                        col.target_column, table, col.source_columns[0]
                    ),
                )
            elif table in left_joined:
                result.add(
                    "WARN",
                    "{0} is NOT NULL but is copied from {1}, which is left-joined - a driving row with "
                    "no match gives NULL and the load fails".format(col.target_column, table),
                )
    return ok


def _warn_planned(tables: dict, referenced: set, result: Result) -> None:
    """A planned table or column is promised by an approved delivery agreement
    (the staging change must go first) or by another mapping of the change
    request (its code must go first), but is not deployed: the mapping is right."""
    by_source = {}
    for table, column in sorted(referenced):
        qualified, found = tables.get(table, ("", None))
        if found is None:
            continue
        if found.planned:
            by_source.setdefault((qualified, found.planned), set()).add("(new table)")
        elif column in found.columns and found.columns[column].planned:
            by_source.setdefault((qualified, found.columns[column].planned), set()).add(column)
    for (qualified, source), columns in sorted(by_source.items()):
        if source.startswith("mapping "):
            result.add(
                "WARN",
                "{0}: {1} not in sql/ yet - planned by {2}. That mapping's code must be generated, reviewed "
                "and deployed before this load, and sql/ exported again.".format(
                    qualified, ", ".join(sorted(columns)), source),
            )
            continue
        result.add(
            "WARN",
            "{0}: {1} not in sql/ yet - planned by the approved {2}. The staging change "
            "(tools/codegen/generate_staging.py) must be deployed before this load, and sql/ exported "
            "again.".format(qualified, ", ".join(sorted(columns)), source),
        )


# ---------------------------------------------------------------------------
# 3. Target
# ---------------------------------------------------------------------------


def check_target(mapping, result: Result) -> None:
    found = schema_catalog.deployed_table(mapping.target)
    if found is None or not found.has_ddl:
        result.add("INFO", "target {0} has no script in the sql/ folder - generation writes a CREATE TABLE".format(mapping.target))
        return
    cols = found.columns
    wanted = {c.name: c for c in table_columns(mapping)}
    new = [name for name in wanted if name not in cols]
    result.add(
        "INFO",
        "target {0} exists in the sql/ folder - generation writes an ALTER script for {1} new column(s){2}".format(
            mapping.target, len(new), ": " + ", ".join(new) if new else ""
        ),
    )
    for name, col in wanted.items():
        if name not in cols:
            continue
        existing = cols[name]
        if parse_type(existing.type) != parse_type(col.type):
            result.add("WARN", "{0}: the table script has {1}, mapping says {2} - needs a manual decision".format(name, existing.type, col.type))
        if (not existing.nullable) != (not col.nullable):
            result.add(
                "WARN",
                "{0}: table script has nullable={1}, mapping says Nullable={2}".format(
                    name, "Y" if existing.nullable else "N", "Y" if col.nullable else "N"
                ),
            )
    for name, existing in cols.items():
        if name in wanted:
            continue
        if not existing.nullable and not existing.default:
            result.add(
                "FAIL",
                "{0} is in the table script, is NOT NULL and has no default, but is not in the mapping - "
                "the load would fail on insert".format(name),
            )
        else:
            result.add(
                "WARN",
                "{0} is in the table script but not in the mapping - the load will not write it{1}".format(
                    name, " (it has a default)" if existing.default else ""
                ),
            )
    if found.primary_key and found.primary_key != primary_key(mapping):
        result.add(
            "WARN",
            "primary key of the table script ({0}) differs from the mapping's ({1}) - needs a manual decision".format(
                ", ".join(found.primary_key), ", ".join(primary_key(mapping))
            ),
        )


def check_other_writers(mapping, result: Result) -> None:
    """Does a package in sql/, other than this mapping's own, already write the target?"""
    own_package = ".".join(mapping.plsql_proc.strip().upper().split(".")[:2])
    for where, path, line in package_usage.writers(mapping.target):
        if ".".join(where.split(".")[:2]) == own_package:
            continue
        result.add(
            "WARN",
            "target {0} is already written by {1} ({2}:{3}) - two loads would write one table; "
            "confirm with the analyst that this mapping replaces it".format(
                mapping.target, where, os.path.basename(path), line
            ),
        )


# ---------------------------------------------------------------------------
# 4. Grain: can a join multiply the driving rows?
# ---------------------------------------------------------------------------


def _split_conjuncts(condition: str) -> list:
    """Split a condition on AND, but not on the AND inside BETWEEN x AND y."""
    blanked = STRING_LITERAL_PATTERN.sub(lambda m: "'" + "_" * (len(m.group(0)) - 2) + "'", condition)
    blanked = re.sub(
        r"\bBETWEEN\b.*?\bAND\b", lambda m: m.group(0)[:-3] + "###", blanked, flags=re.IGNORECASE | re.DOTALL
    )
    pieces, start = [], 0
    for match in re.finditer(r"\bAND\b", blanked, re.IGNORECASE):
        pieces.append(condition[start:match.start()].strip())
        start = match.end()
    pieces.append(condition[start:].strip())
    return [p for p in pieces if p]


COMPARISON = re.compile(r"^\s*\(?\s*(.+?)\s*(<=|>=|<>|!=|=|<|>)\s*(.+?)\s*\)?\s*$", re.DOTALL)


def join_columns(condition: str, joined: str):
    """(equated, ranged): columns of the joined table that the condition pins to one
    value with '=', and columns it only constrains with <, <=, >, >= or BETWEEN."""
    equated, ranged = set(), set()
    joined = joined.upper()
    for conjunct in _split_conjuncts(condition):
        touched = {c for t, c in column_refs(conjunct) if t == joined}
        if not touched:
            continue
        match = COMPARISON.match(conjunct)
        pinned = set()
        if match and match.group(2) == "=":
            for side, other in ((match.group(1), match.group(3)), (match.group(3), match.group(1))):
                bare = re.fullmatch(r"\s*([A-Za-z]\w*)\.([A-Za-z]\w*)\s*", side)
                if bare and bare.group(1).upper() == joined and joined not in {t for t, _c in column_refs(other)}:
                    pinned.add(bare.group(2).upper())
        if pinned:
            equated |= pinned
        else:
            ranged |= touched
    return equated, ranged


def check_grain(mapping, result: Result) -> bool:
    """Returns True when no join can multiply the driving rows (proved from the keys).

    In an aggregating mapping (Group_By) a join that returns several rows per
    driving row is what gets summed, so it is reported as INFO, not WARN. Two
    such joins multiply each other: every aggregate is then repeated for each
    row of the other join - double counting - which is a WARN."""
    all_safe = True
    aggregating = mapping.is_aggregating
    concern = "INFO" if aggregating else "WARN"
    fan_out = []  # joins whose condition pins no key of the joined table
    qualified_by_bare = _qualified_by_bare(mapping)
    for join in mapping.joins:
        bare = bare_table(join.table)
        qualified = qualified_by_bare.get(bare, join.table.strip().upper())
        found = schema_catalog.table(qualified)
        if found is None or not found.has_ddl:
            result.add("WARN", "join to {0}: no table script, so row multiplication cannot be checked".format(bare))
            all_safe = False
            continue
        equated, ranged = join_columns(join.condition, bare)
        unique_sets = found.unique_column_sets()
        if any(set(key) <= equated for key in unique_sets):
            key = next(k for k in unique_sets if set(k) <= equated)
            result.add("PASS", "join to {0} matches its key ({1}), so it cannot multiply the driving rows".format(bare, ", ".join(key)))
            continue
        all_safe = False
        if any(set(key) <= equated | ranged for key in unique_sets):
            key = next(k for k in unique_sets if set(k) <= equated | ranged)
            result.add(
                "WARN",
                "join to {0} reaches its key ({1}) only through a range condition on {2}: it returns one row "
                "only if those ranges never overlap{3}".format(
                    bare, ", ".join(key), ", ".join(sorted(set(key) & ranged)),
                    " (table comment: {0})".format(found.comment) if found.comment else "",
                ),
            )
        else:
            fan_out.append(bare)
            keys = "; ".join("(" + ", ".join(k) + ")" for k in unique_sets) or "none declared"
            if aggregating:
                message = (
                    "join to {0} may return several rows per driving row (the condition pins {1}, not a key "
                    "of {0}; keys: {2}) - in an aggregating mapping those rows are what Group_By ({3}) "
                    "sums into one target row".format(
                        bare, ", ".join(sorted(equated)) or "no column of it", keys, ", ".join(mapping.group_by)
                    )
                )
            else:
                message = (
                    "join to {0} may multiply rows: the condition pins {1}, which is not a primary or unique key "
                    "of {0} (keys: {2}). Confirm the grain, or add the missing key column to the condition".format(
                        bare, ", ".join(sorted(equated)) or "no column of it", keys
                    )
                )
            result.add(concern, message)
    if aggregating and fan_out:
        _check_sums_before_fan_out(mapping, fan_out[0], result)
    if aggregating and len(fan_out) > 1:
        result.add(
            "WARN",
            "double counting: the joins to {0} can each return several rows per driving row, so they multiply "
            "each other and every aggregate counts a value once per row of the other join(s). Confirm that "
            "at most one of them really returns several rows (add its key to the others' conditions), or "
            "split the load into two mappings".format(", ".join(fan_out)),
        )
    if not mapping.joins:
        result.add("PASS", "no joins, so every target row comes from exactly one {0} row".format(bare_table(mapping.driving_table)))
    return all_safe


def _check_sums_before_fan_out(mapping, first_fan_out: str, result: Result) -> None:
    """A SUM or COUNT over a table joined before the first join that returns
    several rows (the driving table, or a join that matched a key) repeats each
    of its values once per row of that join: LOAN.OUTSTANDING_AMT summed over
    a loan's three collateral rows is three times too high."""
    before = {bare_table(mapping.driving_table)}
    for join in mapping.joins:
        bare = bare_table(join.table)
        if bare == first_fan_out:
            break
        before.add(bare)
    for col in mapping.columns:
        rule = col.transformation_rule
        for start, end in aggregate_spans(rule):
            call = rule[start:end]
            name = call.split("(", 1)[0].strip().upper()
            if name not in ("SUM", "COUNT") or re.search(r"\bDISTINCT\b", call, re.IGNORECASE):
                continue
            refs = []
            for table, column in column_refs(call):
                if table == ITEM_ALIAS:  # an item column: the tables its rule reads
                    refs += [r for i in mapping.item_columns if i.name == column
                             for r in column_refs(i.transformation_rule)]
                else:
                    refs.append((table, column))
            if refs and all(table in before for table, _c in refs):
                result.add(
                    "WARN",
                    "{0}: {1} adds up {2}, which has one row per driving row, but the join to {3} returns "
                    "several rows per driving row - each value is counted once per {3} row. Use MAX(...) "
                    "for a value that is the same on every row of the group".format(
                        col.target_column.strip().upper(), " ".join(call.split()),
                        ", ".join(sorted({t for t, _c in refs})), first_fan_out,
                    ),
                )


def check_business_key(mapping, joins_safe: bool, result: Result) -> None:
    keys = mapping.business_key
    if not keys:
        return
    if mapping.is_aggregating:
        extra = [c for c in mapping.group_by if c not in keys]
        if not extra:
            result.add(
                "PASS",
                "business key ({0}) is exactly Group_By, so the load writes one row per key by "
                "construction".format(", ".join(keys)),
            )
        else:
            result.add(
                "INFO",
                "Group_By also holds {0}, beyond the business key ({1}): a key with two different values "
                "of {0} gives two rows and the load fails on the primary key - the unique_key acceptance "
                "criterion tests it on data".format(", ".join(extra), ", ".join(keys)),
            )
        return
    driving = bare_table(mapping.driving_table)
    found = schema_catalog.table(mapping.driving_table)
    by_target = {c.target_column.strip().upper(): c for c in mapping.columns}
    source_keys = []
    for key in keys:
        col = by_target.get(key)
        if col and col.is_direct and not col.is_pseudo and bare_table(col.source_table) == driving:
            source_keys.append(col.source_columns[0])
    if found is not None and found.has_ddl and len(source_keys) == len(keys) and joins_safe:
        covered = [k for k in found.unique_column_sets() if set(k) <= set(source_keys)]
        if covered:
            result.add(
                "PASS",
                "business key ({0}) is a direct copy of the key ({1}) of {2} and no join multiplies rows, "
                "so it is unique by construction".format(", ".join(keys), ", ".join(covered[0]), driving),
            )
            return
    result.add(
        "INFO",
        "business key ({0}) cannot be proven unique from the table scripts alone; "
        "the unique_key acceptance criterion tests it on data".format(", ".join(keys)),
    )


# ---------------------------------------------------------------------------
# 6. Reload predicate
# ---------------------------------------------------------------------------


def check_reload_predicate(mapping, result: Result) -> None:
    if mapping.load_strategy != "delete_insert" or not mapping.reload_predicate:
        return
    target_names = {c.name for c in target_columns(mapping)}
    parameters = {n.upper() for n in mapping.parameter_names}
    blanked = STRING_LITERAL_PATTERN.sub("''", mapping.reload_predicate)
    unknown = sorted(
        {
            word.upper()
            for word in IDENTIFIER.findall(blanked)
            if word.upper() not in SQL_WORDS and word.upper() not in parameters and word.upper() not in target_names
        }
    )
    if unknown:
        result.add(
            "FAIL",
            "Reload_Predicate ({0}) uses {1}, which is not a target column of this mapping".format(
                mapping.reload_predicate, ", ".join(unknown)
            ),
        )
    else:
        result.add("PASS", "Reload_Predicate uses only target columns and parameters")


# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("mapping", help="Mapping_ID or path to a workbook")
    args = parser.parse_args(argv)

    path = resolve_mapping_path(args.mapping)
    if not os.path.exists(path):
        print("ERROR: no workbook at {0}".format(path))
        return 1
    mapping = read_mapping(path)

    result = Result()
    print("Verifying {0} against the table scripts in sql/ (no database is used)\n".format(mapping.mapping_id))

    print("1. Workbook")
    report = validate_mapping(mapping)
    for warning in report.warnings:
        result.add("WARN", warning)
    for error in report.errors:
        result.add("FAIL", error)
    if report.ok:
        result.add("PASS", "workbook validates (status: {0})".format(mapping.status))
    if not mapping.driving_table or not mapping.columns:
        print("\nCannot go further without a Driving_Table and Columns.")
        return 1

    print("\n2. Source tables and columns")
    check_sources(mapping, result)
    print("\n3. Target table")
    check_target(mapping, result)
    check_other_writers(mapping, result)
    print("\n4. Grain: can a join multiply rows?")
    joins_safe = check_grain(mapping, result)
    print("\n5. Business key")
    check_business_key(mapping, joins_safe, result)
    print("\n6. Reload predicate")
    check_reload_predicate(mapping, result)

    print()
    print("Not checked here (no data is read): row counts, whether the key is unique in the data,")
    print("rows an inner join leaves out, and whether real values fit. The acceptance criteria")
    print("become utPLSQL tests, and those check the data once the code is deployed.")
    print()
    if result.failed:
        print("RESULT: {0} FAIL(s). Fix the mapping before generating code.".format(result.failed))
        return 1
    print("RESULT: no failures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
