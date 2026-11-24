"""Generate the table DDL, the load package and the utPLSQL tests from an
approved mapping workbook.

    python tools/codegen/generate.py M_CUSTOMER_ACCOUNT
    python tools/codegen/generate.py M_CUSTOMER_ACCOUNT --check

Deterministic: the same workbook and the same templates always produce the
same files (apart from the generation date in the header). The SQL wording
lives in tools/codegen/templates/*.j2 - adapt those to your own coding
conventions without touching this file; see templates/README.md.

Writes next to the workbook, into the mapping's own folder specs/<folder>/
(or --out-dir):
  <TABLE>.sql                         full CREATE TABLE - always regenerated
  <TABLE>_LOAD_LOG.sql                scd2 only: the table of loaded dates - always regenerated
  <MAPPING_ID>.sql                    ALTER script, only when the table already has a script in sql/
  <PACKAGE>.sql                       load package - always regenerated
  UT_<TABLE>.sql                      utPLSQL tests - always regenerated
  UT_<TABLE>_DATA.sql                 test data - written ONCE, never overwritten
                                      (--reset-test-data to start it over)

Refuses to run for a mapping that is not approved or not valid. Deploying the
files is deliberately NOT done here: a developer reviews and deploys them.

--check verifies instead of writing: every generated file exists, carries the
workbook's current fingerprint (so nothing changed since generation), and the
test data package has no TODO left. Exit 1 if not.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import os
import re
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mapping_spec"))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
except ImportError as exc:  # pragma: no cover - guidance path only
    raise SystemExit("jinja2 is required: pip install -r requirements.txt") from exc

import schema_catalog  # noqa: E402
from mapping_validation import column_refs, referenced_source_columns, validate_mapping  # noqa: E402
from sqlmodel import (  # noqa: E402
    TargetColumn,
    history_columns,
    parse_type,
    primary_key,
    source_query,
    sql_string,
    table_columns,
    target_columns,
)
from workbook_format import (  # noqa: E402
    OPEN_VALID_TO,
    REPO_ROOT,
    Mapping,
    bare_table,
    read_mapping,
    resolve_mapping_path,
)

TEMPLATE_DIR = os.path.join(HERE, "templates")
FINGERPRINT_PATTERN = re.compile(r"mapping fingerprint ([0-9a-f]{16})")
JOIN_EQUALITY_PATTERN = re.compile(
    r"\b([A-Za-z][\w$#]*)\.([A-Za-z][\w$#]*)\s*=\s*([A-Za-z][\w$#]*)\.([A-Za-z][\w$#]*)\b"
)

STRATEGY_SUMMARY = {
    "full": "every run deletes the whole table and reloads it",
    "delete_insert": "every run replaces the rows matching the Reload_Predicate",
    "merge": "every run updates existing business keys and inserts new ones",
    "append": "every run only inserts; re-running the same parameters fails on the primary key",
    "scd2": "every run closes the current version of each changed key and adds a new one; "
            "a run for an earlier date rebuilds the later history",
}

# The test data package's second load date for the scd2 history tests.
SCD2_NEXT_DATE = "NEXT_DATE"

# The error a generated load raises when a guard (Check_Type guard) finds rows.
# The generator's own codes are -20001 to -20005; templates/README.md lists them.
GUARD_ERROR_CODE = -20005


class GenerationError(Exception):
    pass


@dataclass
class Plan:
    """What generation decided, for the report and for the change script."""

    table_exists: bool = False
    compared_against: str = ""
    add_columns: list = field(default_factory=list)
    widen_columns: list = field(default_factory=list)
    relax_null_columns: list = field(default_factory=list)
    manual_notes: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def test_package_name(mapping: Mapping) -> str:
    return "UT_" + mapping.target_table


def data_package_name(mapping: Mapping) -> str:
    return "UT_" + mapping.target_table + "_DATA"


def load_log_name(mapping: Mapping) -> str:
    """scd2 only: the table recording which dates were loaded, so a run for an
    earlier date knows which later dates to replay."""
    return mapping.target_table + "_LOAD_LOG"


def output_dir(mapping: Mapping, out_dir=None) -> str:
    """Where the code goes: --out-dir when given, else the mapping's own
    folder, next to its workbook (specs/<folder>/)."""
    return os.path.abspath(out_dir) if out_dir else os.path.dirname(os.path.abspath(mapping.path))


def output_paths(mapping: Mapping, out_dir: str) -> dict:
    """One file per database object, all flat in out_dir, each named after
    the object it creates (the change script after the mapping)."""
    _schema, package, _proc = mapping.proc_parts
    paths = {
        "table": os.path.join(out_dir, mapping.target_table + ".sql"),
        "change": os.path.join(out_dir, mapping.mapping_id + ".sql"),
        "package": os.path.join(out_dir, package + ".sql"),
        "tests": os.path.join(out_dir, test_package_name(mapping) + ".sql"),
        "test_data": os.path.join(out_dir, data_package_name(mapping) + ".sql"),
    }
    if mapping.is_scd2:
        paths["load_log"] = os.path.join(out_dir, load_log_name(mapping) + ".sql")
    names = [os.path.normcase(p) for p in paths.values()]
    if len(set(names)) != len(names):
        raise GenerationError(
            "{0}: two generated files would share one name in {1} - the target table, the "
            "package and the mapping ID must differ".format(mapping.mapping_id, out_dir)
        )
    return paths


# ---------------------------------------------------------------------------
# Comparing with the table script in sql/
# ---------------------------------------------------------------------------


def _type_parts(text: str):
    return parse_type(text)


def _is_widening(current_type: str, wanted_type: str) -> bool:
    current = _type_parts(current_type)
    wanted = _type_parts(wanted_type)
    if current[0] != wanted[0] or current == wanted:
        return False
    if wanted[0] in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "RAW"):
        return current[1] is not None and wanted[1] is not None and wanted[1] > current[1]
    if wanted[0] == "NUMBER" and current[1] is not None and wanted[1] is not None:
        return (wanted[2] or 0) == (current[2] or 0) and wanted[1] > current[1]
    return False


def existing_target(mapping: Mapping):
    """({COLUMN: (type, 'Y'/'N')}, [pk columns], description of the source).
    Read from the table script in the sql/ folder; no database is involved.
    An empty column dict means the target has no script there yet."""
    found = schema_catalog.deployed_table(mapping.target)
    if found is None or not found.has_ddl:
        return {}, [], "the sql/ folder (no script for {0})".format(mapping.target)
    cols = {name: (col.type, "Y" if col.nullable else "N") for name, col in found.columns.items()}
    return cols, list(found.primary_key), "the sql/ folder ({0})".format(", ".join(found.source_files))


def plan_changes(mapping: Mapping, columns: list, current_cols: dict, current_pk: list, source: str) -> Plan:
    """Compare every column of the target table (table_columns: the mapped
    ones plus, for scd2, the history columns) with the table script."""
    plan = Plan(table_exists=bool(current_cols), compared_against=source)
    if not current_cols:
        return plan
    if mapping.is_scd2 and "VALID_FROM" not in current_cols:
        plan.manual_notes.append(
            "{0} exists without history columns and becomes an SCD2 table. Its existing rows need VALID_FROM "
            "and VALID_TO (and IS_DELETED when Source_Snapshot is full) filled, the primary key becomes ({1}), "
            "and the check constraints and the one-open-version index in {2}.sql must be created by hand. "
            "Then insert every date the existing history was loaded for into {3}, or a run for an earlier "
            "date cannot rebuild it.".format(
                mapping.target, ", ".join(primary_key(mapping)), mapping.target_table,
                mapping.target_schema + "." + load_log_name(mapping),
            )
        )
    for col in columns:
        existing = current_cols.get(col.name)
        if existing is None:
            plan.add_columns.append(col)
            if not col.nullable:
                plan.manual_notes.append(
                    "{0} is added as nullable because existing rows have no value for it. Once every "
                    "row is filled, run: ALTER TABLE {1} MODIFY ({0} NOT NULL);".format(col.name, mapping.target)
                )
            continue
        current_type, current_nullable = existing
        if _type_parts(current_type) != _type_parts(col.type):
            if _is_widening(current_type, col.type):
                plan.widen_columns.append({"name": col.name, "type": col.type, "current_type": current_type})
            else:
                plan.manual_notes.append(
                    "{0}: the table script has {1}, mapping says {2}. Not a pure widening, so existing data could be "
                    "lost or rejected - decide and write the change by hand.".format(col.name, current_type, col.type)
                )
        if current_nullable == "N" and col.nullable:
            plan.relax_null_columns.append(col)
        elif current_nullable == "Y" and not col.nullable:
            plan.manual_notes.append(
                "{0}: the mapping says NOT NULL but the table script allows NULL. Check no row is NULL, "
                "then: ALTER TABLE {1} MODIFY ({0} NOT NULL);".format(col.name, mapping.target)
            )
    wanted = {c.name for c in columns}
    for name, (current_type, current_nullable) in current_cols.items():
        if name not in wanted:
            plan.manual_notes.append(
                "{0} ({1}) is in the table script but not in the mapping. It is not dropped; the load leaves it "
                "{2}.".format(name, current_type, "empty on new rows" if current_nullable == "Y" else "empty - and it is NOT NULL, so inserts will FAIL")
            )
    if current_pk and current_pk != primary_key(mapping):
        plan.manual_notes.append(
            "The primary key in the table script is ({0}) but the mapping needs ({1}). Changing a primary key "
            "needs a person's decision.".format(", ".join(current_pk), ", ".join(primary_key(mapping)))
        )
    return plan


# ---------------------------------------------------------------------------
# Test data (fixture) skeleton
# ---------------------------------------------------------------------------


def _placeholder(column: str, ctype: str, group_value, date_param, group_number="900001"):
    """A test value. Columns equated by a join share group_value; a numeric one
    gets group_number (the scd2 second date uses another, so a load ID of the
    second date does not collide with the first)."""
    base, length, _scale = _type_parts(ctype)
    if group_value is not None:
        if base in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR"):
            return "'{0}'".format(group_value[: length or 20])
        return group_number
    if base == "DATE":
        return date_param or "DATE '2000-01-01'"
    if base == "TIMESTAMP":
        return "CAST({0} AS TIMESTAMP)".format(date_param) if date_param else "TIMESTAMP '2000-01-01 00:00:00'"
    if base == "NUMBER":
        return "100"
    if base in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR"):
        text = "UT_" + column
        if length is not None and length < 3:
            text = "Y"[: length]
        return "'{0}'".format(text[: length or 30])
    return "NULL"


def fixture_context(mapping: Mapping) -> dict:
    # Which columns of each source table the mapping touches.
    used = {bare_table(t): set() for t in mapping.source_tables}
    for col in mapping.columns:
        if not col.is_pseudo and col.source_table:
            used.setdefault(bare_table(col.source_table), set()).update(col.source_columns)
        if col.transformation_rule.strip().lower() not in ("direct", "null"):
            for table, column in column_refs(col.transformation_rule):
                used.setdefault(table, set()).add(column)
    for item in mapping.item_columns:
        for table, column in column_refs(item.transformation_rule):
            used.setdefault(table, set()).add(column)
    for join in mapping.joins:
        for table, column in column_refs(join.condition):
            used.setdefault(table, set()).add(column)
    if mapping.has_filter:
        for table, column in column_refs(mapping.filter):
            used.setdefault(table, set()).add(column)

    # Columns equated by join conditions share one value, so the happy path joins.
    parent = {}

    def find(node):
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for join in mapping.joins:
        for a_tab, a_col, b_tab, b_col in JOIN_EQUALITY_PATTERN.findall(join.condition):
            parent[find((a_tab.upper(), a_col.upper()))] = find((b_tab.upper(), b_col.upper()))
    group_value = {}
    for node in list(parent):
        root = find(node)
        group_value.setdefault(root, "UT_" + root[1])

    date_param = next((name for name, ptype in mapping.parameters if _type_parts(ptype)[0] == "DATE"), None)
    tables = []
    for index, qualified in enumerate(mapping.source_tables):
        bare = bare_table(qualified)
        catalog_cols = schema_catalog.columns_of(qualified) or {}
        ordered = [c for c in catalog_cols if c in used.get(bare, set())] or sorted(used.get(bare, set()))
        columns = []
        for name in ordered:
            ctype = catalog_cols.get(name, "VARCHAR2(30)")
            root = find((bare, name)) if (bare, name) in parent else None
            group = group_value.get(root) if root else None
            columns.append(
                {
                    "name": name,
                    "type": ctype,
                    "value": _placeholder(name, ctype, group, date_param),
                    "next_value": _placeholder(name, ctype, group, SCD2_NEXT_DATE, "900002"),
                }
            )
        if index == 0 and mapping.is_aggregating:
            role = "driving table: the rows that pass the Filter are summed into one target row per ({0})".format(
                ", ".join(mapping.group_by))
        elif index == 0:
            role = "driving table: each row that passes the Filter becomes one target row"
        else:
            join = mapping.joins[index - 1]
            role = "{0} join: {1}".format(join.join_type.lower(), join.condition)
        tables.append({"qualified": qualified, "role": role, "columns": columns})

    driving = bare_table(mapping.driving_table)
    cases = ["Happy path: one {0} row that passes the Filter, with its matching joined rows.".format(driving)]
    if mapping.is_aggregating:
        cases.append(
            "Two source rows (of {0} or of a joined table) with the same Group_By values ({1}) - must become "
            "ONE target row whose aggregates cover both.".format(driving, ", ".join(mapping.group_by))
        )
    if mapping.item_columns:
        cases.append(
            "Rows of one group whose order matters to the Item_Columns ({0}): e.g. two items where the "
            "second is cut by what the first already covers, so a wrong ORDER BY or PARTITION BY in "
            "a window function would change the result.".format(", ".join(mapping.item_names))
        )
    for join in mapping.joins:
        joined = bare_table(join.table)
        if join.join_type.lower() == "inner":
            cases.append("One {0} row with no matching {1} row - must NOT be loaded (inner join).".format(driving, joined))
        else:
            cases.append(
                "One {0} row with no matching {1} row - loaded with the {1} columns empty (left join).".format(driving, joined)
            )
    if mapping.has_filter:
        cases.append("One {0} row outside the Filter ({1}) - must NOT be loaded.".format(driving, mapping.filter))
    for ac in mapping.criteria:
        if ac.check_type.lower() in ("zero_rows", "expected_value"):
            cases.append("Data that {0} would catch if the load were wrong: {1}".format(ac.ac_id, " ".join(ac.description.split())))
    if any(ac.check_type.lower() == "guard" for ac in mapping.criteria):
        cases.append(
            "Nothing that breaks a guard: seed's data must pass every guard, or every test fails with "
            "ORA{0}. Data that breaks a guard goes in that guard's own seed_ procedure below.".format(GUARD_ERROR_CODE)
        )
    next_cases = []
    if mapping.is_scd2:
        next_cases = [
            "A key seed inserted, with a changed value in a tracked (SCD_Type 2) column - must close "
            "its version and add a new one from {0}.".format(SCD2_NEXT_DATE),
            "A key seed did not insert - must get its first version from {0}.".format(SCD2_NEXT_DATE),
        ]
        if mapping.source_snapshot == "full":
            next_cases.append(
                "Leave out a key seed inserted - must get a deleted version (IS_DELETED = 'Y') from "
                "{0}. So seed needs at least two keys.".format(SCD2_NEXT_DATE)
            )
    return {"fixture_tables": tables, "cases": cases, "next_cases": next_cases}


# ---------------------------------------------------------------------------
# Context and rendering
# ---------------------------------------------------------------------------


def _indent_block(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.splitlines())


def _parameter_context(mapping: Mapping) -> list:
    params = []
    for name, ptype in mapping.parameters:
        base = _type_parts(ptype)[0]
        decl = ptype
        if base in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR") and "(" not in ptype:
            decl = base + "(4000)"
        test_value = {
            "DATE": "DATE '2000-01-01'",
            "TIMESTAMP": "TIMESTAMP '2000-01-01 00:00:00'",
            "NUMBER": "1",
        }.get(base, "'UT'")
        params.append({"name": name, "plsql_type": base, "decl_type": decl, "test_value": test_value})
    return params


def _parameter_message(mapping: Mapping) -> str:
    """A PL/SQL expression naming the parameter values of a run, for an error
    message: 'P_BUSINESS_DATE=' || TO_CHAR(P_BUSINESS_DATE, 'YYYY-MM-DD')."""
    parts = []
    for name, ptype in mapping.parameters:
        base = _type_parts(ptype)[0]
        if base == "DATE":
            value = "TO_CHAR({0}, 'YYYY-MM-DD')".format(name)
        elif base == "TIMESTAMP":
            value = "TO_CHAR({0}, 'YYYY-MM-DD HH24:MI:SS')".format(name)
        elif base in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR"):
            value = name
        else:
            value = "TO_CHAR({0})".format(name)
        parts.append("'{0}=' || {1}".format(name, value))
    return " || ', ' || ".join(parts) if parts else "'no parameters'"


def _tests_context(mapping: Mapping) -> list:
    tests = []
    for ac in mapping.criteria:
        slug = re.sub(r"[^A-Za-z0-9_]", "_", ac.ac_id).lower()
        proc = "t_" + slug
        expected = ac.expected.strip()
        is_number = bool(re.fullmatch(r"-?\d+(\.\d+)?", expected))
        tests.append(
            {
                "id": ac.ac_id,
                "proc": proc[:128],
                "seed_proc": ("seed_" + slug)[:128],
                "description": " ".join(ac.description.split()),
                "check_type": ac.check_type.strip().lower(),
                "check_sql": ac.check_sql.strip().rstrip(";"),
                "expected_is_number": is_number,
                "expected_literal": expected if is_number else "'{0}'".format(sql_string(expected)),
            }
        )
    return tests


def _scd2_context(mapping: Mapping, columns: list) -> dict:
    """Names the scd2 templates use; empty values for any other strategy."""
    table = mapping.target_table
    return {
        "is_scd2": mapping.is_scd2,
        "has_is_deleted": mapping.is_scd2 and mapping.source_snapshot == "full",
        "effective_param": mapping.parameter_names[0] if mapping.is_scd2 else "",
        "next_date": SCD2_NEXT_DATE,
        "open_valid_to": OPEN_VALID_TO,
        "history_columns": history_columns(mapping),
        "tracked_columns": [c for c in columns if not c.is_key and c.scd_type == "2" and not c.is_expr],
        "load_log_table": load_log_name(mapping),
        "load_log": mapping.target_schema + "." + load_log_name(mapping),
        "pk_log_name": ("PK_" + load_log_name(mapping))[:128],
        "ck_period_name": ("CK_" + table + "_PERIOD")[:128],
        "ck_deleted_name": ("CK_" + table + "_DELETED")[:128],
        "uq_open_name": ("UQ_" + table + "_OPEN")[:128],
    }


def build_context(mapping: Mapping, plan: Plan, today: _dt.date) -> dict:
    schema, package, procedure = mapping.proc_parts
    columns = target_columns(mapping)
    all_columns = table_columns(mapping)
    update_columns = [c for c in columns if not c.is_key and c.scd_type == "1"]
    query = source_query(mapping)
    tests = _tests_context(mapping)
    context = {
        "mapping_id": mapping.mapping_id,
        "workbook": os.path.relpath(mapping.path, REPO_ROOT).replace(os.sep, "/") if mapping.path else "",
        "fingerprint": mapping.fingerprint(),
        "approved_by": mapping.get("Approved_By"),
        "approved_on": mapping.get("Approved_On"),
        "generated_on": today.isoformat(),
        "target": mapping.target,
        "target_schema": mapping.target_schema,
        "target_table": mapping.target_table,
        "table_description": mapping.get("Table_Description"),
        "intent_one_line": " ".join(mapping.get("Intent").split())[:160],
        "pk_name": ("PK_" + mapping.target_table)[:128],
        "columns": columns,
        "table_columns": all_columns,
        "name_width": max(len(c.name) for c in all_columns),
        "key_columns": mapping.business_key,
        "primary_key": primary_key(mapping),
        "update_columns": update_columns,
        "change_columns": [c for c in update_columns if not c.is_expr],
        "hash_expr": " + ".join("NVL(ORA_HASH({0}), 0)".format(c.name) for c in all_columns if not c.is_expr),
        "package_schema": schema,
        "package": package,
        "procedure": procedure,
        "parameters": _parameter_context(mapping),
        "load_strategy": mapping.load_strategy,
        "strategy_summary": STRATEGY_SUMMARY[mapping.load_strategy],
        "reload_predicate": mapping.reload_predicate,
        "source_query": query,
        "source_query_8": _indent_block(query, 8),
        "source_query_12": _indent_block(query, 12),
        "source_query_16": _indent_block(query, 16),
        "group_by": mapping.group_by,
        "is_aggregating": mapping.is_aggregating,
        "savepoint_name": ("SP_" + package)[:128],
        "tests": tests,
        "guards": [t for t in tests if t["check_type"] == "guard"],
        "guard_error": GUARD_ERROR_CODE,
        "parameter_message": _parameter_message(mapping),
        "test_package": test_package_name(mapping),
        "data_package": data_package_name(mapping),
        "add_columns": plan.add_columns,
        "widen_columns": plan.widen_columns,
        "relax_null_columns": plan.relax_null_columns,
        "manual_notes": plan.manual_notes,
    }
    context.update(fixture_context(mapping))
    context.update(_scd2_context(mapping, columns))
    return context


def environment(template_dir: str = TEMPLATE_DIR) -> Environment:
    env = Environment(
        loader=FileSystemLoader(template_dir),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["sqlstr"] = sql_string
    env.filters["ljust"] = lambda value, width: str(value).ljust(width)
    env.filters["pad"] = _indent_block
    return env


def render_all(mapping: Mapping, plan: Plan, today: _dt.date, template_dir: str = TEMPLATE_DIR) -> dict:
    """{kind: sql_text} for every artifact this mapping needs."""
    env = environment(template_dir)
    context = build_context(mapping, plan, today)
    rendered = {
        "table": env.get_template("table_create.sql.j2").render(context),
        "package": env.get_template("package.sql.j2").render(context),
        "tests": env.get_template("test_package.sql.j2").render(context),
        "test_data": env.get_template("test_data_package.sql.j2").render(context),
    }
    if plan.table_exists:
        rendered["change"] = env.get_template("table_change.sql.j2").render(context)
    if mapping.is_scd2:
        rendered["load_log"] = env.get_template("load_log_create.sql.j2").render(context)
    return rendered


def load_approved(arg: str) -> Mapping:
    path = resolve_mapping_path(arg)
    if not os.path.exists(path):
        raise GenerationError("no mapping workbook at {0}".format(path))
    mapping = read_mapping(path)
    report = validate_mapping(mapping)
    if not mapping.is_approved:
        raise GenerationError(
            "{0} is '{1}', not approved. Code is only generated from an approved mapping - "
            "a named person sets Status = approved in the workbook.".format(mapping.mapping_id, mapping.status)
        )
    if not report.ok:
        raise GenerationError(
            "{0} is approved but does not validate:\n  ".format(mapping.mapping_id) + "\n  ".join(report.errors)
        )
    return mapping


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
    except ValueError:
        return path


def planned_prerequisites(mapping: Mapping) -> list:
    """What must be deployed before this load: the planned source tables, and the planned
    columns of a source table that the mapping actually reads. A planned column the mapping
    does not read (another mapping adds it to the same table) is not a prerequisite."""
    referenced = referenced_source_columns(mapping)
    planned = set()
    for qualified in mapping.source_tables:
        found = schema_catalog.table(qualified)
        if found is None:
            continue
        if found.planned:
            planned.add(found.planned)
            continue
        for table, column in referenced:
            if table == bare_table(qualified) and column in found.columns and found.columns[column].planned:
                planned.add(found.columns[column].planned)
    return sorted(planned)


def cmd_generate(args) -> int:
    mapping = load_approved(args.mapping)
    today = _dt.date.today()
    out_dir = output_dir(mapping, args.out_dir)
    current_cols, current_pk, source = existing_target(mapping)
    columns = table_columns(mapping)
    plan = plan_changes(mapping, columns, current_cols, current_pk, source)
    rendered = render_all(mapping, plan, today)
    paths = output_paths(mapping, out_dir)

    print("Generating code for {0} (fingerprint {1})".format(mapping.mapping_id, mapping.fingerprint()))
    print("Target compared against {0}: {1}".format(
        plan.compared_against, "table exists" if plan.table_exists else "table does not exist yet"))
    for qualified in mapping.source_tables:
        if schema_catalog.table_state(qualified) != "ok":
            print("WARNING: no CREATE TABLE script for {0} in sql/, so test data types are guesses.".format(qualified))

    written = []
    for kind, text in rendered.items():
        path = paths[kind]
        if kind == "test_data" and os.path.exists(path) and not args.reset_test_data:
            print("  kept     {0} (test data is never overwritten; --reset-test-data to start over)".format(_rel(path)))
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        written.append(path)
        print("  wrote    {0}".format(_rel(path)))

    # Change scripts used to carry the generation date in their name; the name is now fixed.
    older = glob.glob(os.path.join(out_dir, glob.escape(mapping.mapping_id) + "_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].sql"))
    for path in older:
        print("  NOTE     {0} is an old, dated change script and is no longer used (the change script is "
              "{1}.sql) - delete it".format(_rel(path), mapping.mapping_id))
    if not plan.table_exists and os.path.exists(paths["change"]):
        print("  NOTE     {0} exists but the table does not - it is stale".format(_rel(paths["change"])))

    if plan.manual_notes:
        print("\nMANUAL DECISIONS (also listed at the bottom of the change script):")
        for note in plan.manual_notes:
            print("  - " + note)

    planned = planned_prerequisites(mapping)
    schema = mapping.proc_parts[0]
    print("\nDeploy in this order (a developer does this by hand, after review):")
    staging = [p for p in planned if not p.startswith("mapping ")]
    upstream = [p for p in planned if p.startswith("mapping ")]
    if staging:
        print("  first: the staging change for the planned source columns, generated with")
        print("         python tools/codegen/generate_staging.py <CR_ID> from {0}".format(", ".join(staging)))
    if upstream:
        print("  first: the loads that create the planned source tables and columns: {0}".format(
            ", ".join(p[len("mapping "):] for p in upstream)))
    print("  0. grants, run by a user allowed to grant on the source schema:")
    for table in mapping.source_tables:
        print("       GRANT SELECT ON {0} TO {1};".format(table, schema))
    for table in mapping.source_tables:
        print("       GRANT INSERT ON {0} TO {1};   -- test data only".format(table, schema))
    steps = [_rel(paths["change"] if plan.table_exists else paths["table"])]
    if mapping.is_scd2:
        log_exists = schema_catalog.table_state(mapping.target_schema + "." + load_log_name(mapping)) == "ok"
        steps.append("{0}{1}".format(
            _rel(paths["load_log"]), "   (skip: the table already exists in sql/)" if log_exists else ""))
    steps += [
        _rel(paths["package"]),
        _rel(paths["test_data"]),
        "{0}   (also runs the tests, as its last statement)".format(_rel(paths["tests"])),
        "to rerun the tests later: EXEC ut.run('{0}.{1}');".format(schema, test_package_name(mapping)),
    ]
    for number, step in enumerate(steps, start=1):
        print("  {0}. {1}".format(number, step))
    return 0


def cmd_check(args) -> int:
    mapping = load_approved(args.mapping)
    out_dir = output_dir(mapping, args.out_dir)
    paths = output_paths(mapping, out_dir)
    fingerprint = mapping.fingerprint()
    problems = []
    for kind in ("table", "load_log", "package", "tests"):
        if kind not in paths:
            continue
        path = paths[kind]
        if not os.path.exists(path):
            problems.append("missing {0}".format(_rel(path)))
            continue
        with open(path, "r", encoding="utf-8") as handle:
            match = FINGERPRINT_PATTERN.search(handle.read())
        if not match or match.group(1) != fingerprint:
            problems.append(
                "{0} was generated from fingerprint {1}, the workbook is now {2} - regenerate".format(
                    _rel(path), match.group(1) if match else "?", fingerprint
                )
            )
    data_path = paths["test_data"]
    if not os.path.exists(data_path):
        problems.append("missing {0}".format(_rel(data_path)))
    else:
        with open(data_path, "r", encoding="utf-8") as handle:
            todos = [i for i, line in enumerate(handle, start=1) if "TODO" in line]
        if todos:
            problems.append("{0} still has TODO on line(s) {1}".format(_rel(data_path), ", ".join(map(str, todos))))
    if problems:
        print("NOT READY for hand-over:")
        for problem in problems:
            print("  - " + problem)
        return 1
    print("{0}: generated code is current (fingerprint {1}) and the test data is complete.".format(
        mapping.mapping_id, fingerprint))
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("mapping", help="Mapping_ID or path to an approved workbook")
    parser.add_argument("--out-dir", help="default: the mapping's own folder, next to its workbook")
    parser.add_argument("--check", action="store_true", help="verify generated files instead of writing them")
    parser.add_argument("--reset-test-data", action="store_true", help="overwrite the test data package too")
    args = parser.parse_args(argv)
    try:
        return cmd_check(args) if args.check else cmd_generate(args)
    except GenerationError as exc:
        print("ERROR: {0}".format(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
