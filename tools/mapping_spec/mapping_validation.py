"""Check a mapping workbook: is its content valid, and is it complete enough to approve?

A mapping is an Excel workbook, ``specs/<folder>/<MAPPING_ID>.xlsx``. Its
layout lives in ``workbook_format.py``; this module decides whether its content
is valid.

Validation is tiered: shape is checked whenever a value is present;
completeness only once a mapping is ``approved``. An approved mapping is the
input to generating DDL, PL/SQL and tests without asking anyone anything, so
"complete" means every fact the SQL needs is in a structured cell - see
``validate_mapping``.

Column facts come from ``schema_catalog.py``, which reads the table scripts in
the ``sql/`` folder. No database connection is used anywhere. That is what lets
``validate_mapping`` reject a rule that names a column that does not exist - the
class of bug that broke PKG_LOAN_EXPOSURE in this repo's history.

Dependency-light by design: openpyxl only, because this runs inside editor
hooks.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import schema_catalog  # noqa: E402
from workbook_format import (  # noqa: E402
    VALID_CHECK_TYPES,
    VALID_DECISION_STATUSES,
    VALID_JOIN_TYPES,
    VALID_LOAD_STRATEGIES,
    VALID_NULLABLE,
    VALID_SCD_TYPES,
    VALID_SOURCE_SNAPSHOTS,
    VALID_SOURCE_TYPES,
    VALID_STATUSES,
    SCD2_HISTORY_COLUMNS,
    ITEM_ALIAS,
    SPEC_DIR,
    Mapping,
    bare_table,
    list_mapping_paths,
    mapping_folder_name,
    mapping_to_dict,
    read_mapping,
)

# Repository root, derived from this file's location (tools/mapping_spec/...).
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# Mapping fields required whatever the status: without them the workbook
# isn't recognisably about one load at all.
REQUIRED_MAPPING_FIELDS = ("Mapping_ID", "Status", "Target_Table", "Business_Key", "PLSQL_Proc")

# Additionally required before approval: everything the generators need,
# plus the approval record itself.
REQUIRED_FOR_APPROVAL = (
    "Owner",
    "Approved_By",
    "Approved_On",
    "Intent",
    "Table_Description",
    "Grain",
    "Parameters",
    "Driving_Table",
    "Filter",
    "Load_Strategy",
)

# Every column needs these before approval: Target_Type/Nullable make the
# DDL, Business_Name/Description become the column comment, and SCD_Type
# decides what a merge overwrites.
REQUIRED_COLUMN_CELLS_FOR_APPROVAL = ("target_type", "nullable", "scd_type", "business_name", "description")

MIN_ACCEPTANCE_CRITERIA = 2

ORACLE_TYPE_PATTERN = re.compile(
    r"^\s*(VARCHAR2|NVARCHAR2|CHAR|NCHAR|NUMBER|INTEGER|FLOAT|DATE|TIMESTAMP|CLOB|BLOB|RAW)"
    r"\s*(\(\s*\d+\s*(,\s*-?\d+\s*)?(\s+(CHAR|BYTE))?\s*\))?\s*$",
    re.IGNORECASE,
)
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")
QUALIFIED_TABLE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*\.[A-Za-z][A-Za-z0-9_$#]*$")

# Heuristic only (a warning, never an error): English words that don't occur
# in Oracle SQL expressions. Deliberately excludes words that ARE SQL
# (IS, NOT, WHEN, AND, OR, NULL) so `CASE WHEN x IS NOT NULL` never trips it.
PROSE_PATTERN = re.compile(
    r"\b(the|until|which|should|via|because|see|derived|passed|joined)\b", re.IGNORECASE
)

TODO_PATTERN = re.compile(r"\bTODO\b", re.IGNORECASE)

# TABLE.COLUMN references inside a SQL snippet (after string literals are
# blanked out, so 'a.b' inside quotes is never mistaken for one).
COLUMN_REF_PATTERN = re.compile(r"\b([A-Za-z][A-Za-z0-9_$#]*)\.([A-Za-z][A-Za-z0-9_$#]*)\b")
STRING_LITERAL_PATTERN = re.compile(r"'(?:[^']|'')*'")

# Oracle aggregate functions an aggregating mapping (Group_By) may use. A call
# followed by OVER (...) is an analytic function, not an aggregate.
AGGREGATE_FUNCTIONS = (
    "SUM", "MIN", "MAX", "COUNT", "AVG", "LISTAGG", "MEDIAN", "STDDEV", "VARIANCE", "ANY_VALUE",
)
AGGREGATE_CALL_PATTERN = re.compile(
    r"(?<![\w$#.])(" + "|".join(AGGREGATE_FUNCTIONS) + r")\s*\(", re.IGNORECASE
)
# What may follow an aggregate's own parentheses and still belong to it:
# MAX(x) KEEP (DENSE_RANK LAST ORDER BY ...), LISTAGG(x) WITHIN GROUP (ORDER BY ...).
AGGREGATE_TAIL_PATTERN = re.compile(r"\s*(?:KEEP|WITHIN\s+GROUP)\s*\(", re.IGNORECASE)
ANALYTIC_PATTERN = re.compile(r"\s*OVER\b", re.IGNORECASE)
ROUNDING_PATTERN = re.compile(r"(?<![\w$#.])(ROUND|TRUNC)\s*\(", re.IGNORECASE)
PRECISE_NUMBER_PATTERN = re.compile(r"^\s*NUMBER\s*\(", re.IGNORECASE)


@dataclass
class Report:
    """Collected problems for one mapping or for a whole run."""

    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def merge(self, other: "Report") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)



def load_mappings(spec_dir: str = SPEC_DIR):
    """Load every mapping workbook in spec_dir. Returns (mappings, report)."""
    report = Report()
    mappings = []
    if not os.path.isdir(spec_dir):
        report.errors.append("mapping directory does not exist: " + spec_dir)
        return mappings, report
    for path in list_mapping_paths(spec_dir):
        try:
            mappings.append(read_mapping(path))
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
            report.errors.append("{0}: cannot read ({1})".format(rel, exc))
    return mappings, report


def column_refs(sql: str) -> list:
    """[(TABLE, COLUMN)] referenced as TABLE.COLUMN in a SQL snippet."""
    blanked = STRING_LITERAL_PATTERN.sub("''", sql or "")
    return [(t.upper(), c.upper()) for t, c in COLUMN_REF_PATTERN.findall(blanked)]


def referenced_source_columns(mapping) -> set:
    """{(TABLE, COLUMN)}: every source column a mapping reads, by bare table name."""
    referenced = set()
    for col in mapping.columns:
        if not col.is_pseudo and col.source_table:
            for src in col.source_columns:
                referenced.add((bare_table(col.source_table), src))
        if col.transformation_rule.strip().lower() not in ("direct", "null"):
            referenced.update(column_refs(col.transformation_rule))
    for item in mapping.item_columns:
        referenced.update(column_refs(item.transformation_rule))
    for join in mapping.joins:
        referenced.update(column_refs(join.condition))
    if mapping.has_filter:
        referenced.update(column_refs(mapping.filter))
    return referenced


def _unapproved_upstream(mapping, source_tables: dict) -> dict:
    """{upstream Mapping_ID: status} of the mappings, not approved yet, that
    plan a table or column this mapping reads (schema_catalog's planned label
    'mapping <ID> (<status>)')."""
    pending = {}
    for table, column in referenced_source_columns(mapping):
        qualified = source_tables.get(table)
        found = schema_catalog.table(qualified) if qualified else None
        if found is None:
            continue
        planned = found.planned
        if column in found.columns and found.columns[column].planned:
            planned = found.columns[column].planned
        label = re.match(r"^mapping (\S+) \((\w+)\)$", planned or "")
        if label and label.group(2) != "approved" and label.group(1).upper() != mapping.mapping_id.upper():
            pending[label.group(1)] = label.group(2)
    return pending


def _blank_literals(sql: str) -> str:
    """The SQL with every string literal's content replaced by spaces, so
    positions stay the same and nothing inside quotes is mistaken for code."""
    return STRING_LITERAL_PATTERN.sub(lambda m: "'" + " " * (len(m.group(0)) - 2) + "'", sql or "")


def _closing_paren(text: str, open_index: int) -> int:
    """Index of the ')' matching the '(' at open_index (the last index when unbalanced)."""
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return len(text) - 1


def aggregate_spans(sql: str) -> list:
    """[(start, end)] of every aggregate call in a SQL snippet, including a
    KEEP (...) or WITHIN GROUP (...) tail. Analytic calls (... OVER (...)) are
    not aggregates and are left out."""
    text = _blank_literals(sql)
    spans, position = [], 0
    while True:
        match = AGGREGATE_CALL_PATTERN.search(text, position)
        if not match:
            return spans
        end = _closing_paren(text, match.end() - 1)
        tail = AGGREGATE_TAIL_PATTERN.match(text, end + 1)
        if tail:
            end = _closing_paren(text, tail.end() - 1)
        if ANALYTIC_PATTERN.match(text, end + 1):
            position = match.end()
            continue
        spans.append((match.start(), end + 1))
        position = end + 1


def has_aggregate(sql: str) -> bool:
    return bool(aggregate_spans(sql))


def refs_outside_aggregates(sql: str) -> list:
    """[(TABLE, COLUMN)] referenced in a SQL snippet outside every aggregate call."""
    text = _blank_literals(sql)
    for start, end in reversed(aggregate_spans(sql)):
        text = text[:start] + " " * (end - start) + text[end:]
    return column_refs(text)


def _check_sql_refs(sql: str, what: str, where: str, source_tables: dict, report: Report, items=None) -> None:
    """Every TABLE.COLUMN in `sql` must name a source table of this mapping
    and, where the sql/ folder describes that table, a real column of it.
    With `items` (the Item_Columns names), ITEM.<name> is allowed too."""
    for table, column in column_refs(sql):
        if items is not None and table == ITEM_ALIAS:
            if column not in items:
                report.errors.append(
                    "{0}: {1} references {2}.{3}, which is not on the Item_Columns sheet".format(
                        where, what, table, column
                    )
                )
            continue
        qualified = source_tables.get(table)
        if qualified is None:
            report.errors.append(
                "{0}: {1} references {2}.{3}, but {2} is not the Driving_Table or a "
                "Joins table of this mapping".format(where, what, table, column)
            )
            continue
        known = schema_catalog.columns_of(qualified)
        if known is not None and column not in known:
            report.errors.append(
                "{0}: {1} references {2}.{3}, which does not exist in {4}".format(
                    where, what, table, column, qualified
                )
            )


def _check_tables_in_sql_folder(source_tables: dict, where: str, report: Report) -> None:
    """A source table the sql/ folder does not know is an error when its schema
    is one the folder describes (the name is wrong); a table that only has a
    GRANT there is a warning (its columns cannot be checked until the table
    script is exported)."""
    for qualified in source_tables.values():
        state = schema_catalog.table_state(qualified)
        if state == "unknown":
            schema = qualified.split(".", 1)[0]
            if schema in schema_catalog.schemas():
                report.errors.append(
                    "{0}: {1} is not a table in the sql/ folder (schema {2})".format(where, qualified, schema)
                )
            else:
                report.warnings.append(
                    "{0}: schema {1} is not described in the sql/ folder, so the columns of "
                    "{2} cannot be checked".format(where, schema, qualified)
                )
        elif state == "no_ddl":
            report.warnings.append(
                "{0}: the sql/ folder has no CREATE TABLE for {1} (only a grant), so its columns "
                "cannot be checked - export the table script".format(where, qualified)
            )


def validate_mapping(mapping: Mapping) -> Report:
    """Check one mapping workbook. Approval raises the bar to "complete"."""
    report = Report()
    where = mapping.rel_path
    approved = mapping.is_approved

    for name in REQUIRED_MAPPING_FIELDS:
        if not mapping.get(name):
            report.errors.append("{0}: Mapping field '{1}' is empty".format(where, name))

    if mapping.path and mapping.mapping_id:
        file_id = os.path.splitext(os.path.basename(mapping.path))[0]
        folder = os.path.basename(os.path.dirname(os.path.abspath(mapping.path)))
        try:
            expected_folder = mapping_folder_name(mapping.mapping_id)
        except ValueError as exc:
            report.errors.append("{0}: {1}".format(where, exc))
        else:
            if file_id != mapping.mapping_id or folder != expected_folder:
                report.errors.append(
                    "{0}: Mapping_ID '{1}' does not match the file's place (expected specs/{2}/{1}.xlsx)".format(
                        where, mapping.mapping_id, expected_folder
                    )
                )

    if mapping.status and mapping.status not in VALID_STATUSES:
        report.errors.append(
            "{0}: Status '{1}' must be one of {2}".format(where, mapping.status, ", ".join(VALID_STATUSES))
        )

    target = mapping.target
    if target and not QUALIFIED_TABLE_PATTERN.match(target):
        report.errors.append("{0}: Target_Table '{1}' must be SCHEMA.TABLE".format(where, target))

    if mapping.plsql_proc and mapping.proc_parts is None:
        report.errors.append(
            "{0}: PLSQL_Proc '{1}' must be SCHEMA.PACKAGE.PROCEDURE".format(where, mapping.plsql_proc)
        )
    elif mapping.proc_parts and mapping.target_schema and mapping.proc_parts[0] != mapping.target_schema:
        report.warnings.append(
            "{0}: PLSQL_Proc lives in {1} but the target table in {2}".format(
                where, mapping.proc_parts[0], mapping.target_schema
            )
        )

    # -- parameters -----------------------------------------------------
    param_text = mapping.get("Parameters")
    for name, ptype in mapping.parameters:
        if not IDENTIFIER_PATTERN.match(name):
            report.errors.append("{0}: parameter name '{1}' is not a valid identifier".format(where, name))
        if not ptype or not ORACLE_TYPE_PATTERN.match(ptype):
            report.errors.append(
                "{0}: parameter {1} needs an Oracle type, e.g. '{1} DATE' (got '{2}')".format(
                    where, name, ptype
                )
            )
    if param_text and param_text.lower() != "none" and not mapping.parameters:
        report.errors.append("{0}: Parameters '{1}' could not be read".format(where, param_text))

    # -- source tables: driving table + joins -----------------------------
    source_tables = {}  # bare -> qualified
    if mapping.driving_table:
        if not QUALIFIED_TABLE_PATTERN.match(mapping.driving_table):
            report.errors.append(
                "{0}: Driving_Table '{1}' must be SCHEMA.TABLE".format(where, mapping.driving_table)
            )
        else:
            source_tables[bare_table(mapping.driving_table)] = mapping.driving_table

    for index, join in enumerate(mapping.joins, start=1):
        label = "Joins row {0}".format(index)
        table = join.table.strip().upper()
        if not QUALIFIED_TABLE_PATTERN.match(table):
            report.errors.append("{0}: {1} Table '{2}' must be SCHEMA.TABLE".format(where, label, join.table))
            continue
        bare = bare_table(table)
        if bare in source_tables:
            report.errors.append(
                "{0}: {1} joins {2} a second time; a table may appear only once "
                "(self-joins are not supported by the generator)".format(where, label, table)
            )
            continue
        if join.join_type.lower() not in VALID_JOIN_TYPES:
            report.errors.append(
                "{0}: {1} Join_Type '{2}' must be one of {3}".format(
                    where, label, join.join_type, ", ".join(VALID_JOIN_TYPES)
                )
            )
        if not join.condition:
            report.errors.append("{0}: {1} has no Condition".format(where, label))
        elif "=" not in join.condition:
            report.errors.append(
                "{0}: {1} Condition '{2}' must be an equality condition".format(where, label, join.condition)
            )
        # A condition may reference the driving table, earlier joins and this one.
        visible = dict(source_tables)
        visible[bare] = table
        _check_sql_refs(join.condition, "{0} Condition".format(label), where, visible, report)
        if not any(t == bare for t, _c in column_refs(join.condition)):
            report.errors.append(
                "{0}: {1} Condition does not reference the joined table {2}".format(where, label, bare)
            )
        source_tables[bare] = table

    _check_tables_in_sql_folder(source_tables, where, report)
    _check_item_columns(mapping, where, source_tables, report)
    items = set(mapping.item_names) if mapping.item_columns else None

    if mapping.has_filter:
        _check_sql_refs(mapping.filter, "Filter", where, source_tables, report)

    # -- columns ---------------------------------------------------------
    if not mapping.columns:
        report.errors.append("{0}: the Columns sheet has no rows".format(where))
    seen = set()
    for index, col in enumerate(mapping.columns, start=1):
        name = col.target_column.strip().upper()
        label = "Columns row {0} ({1})".format(index, name or "?")
        if not name:
            report.errors.append("{0}: Columns row {1} has no Target_Column".format(where, index))
        elif not IDENTIFIER_PATTERN.match(name):
            report.errors.append("{0}: {1} is not a valid Oracle column name".format(where, label))
        elif name in seen:
            report.errors.append("{0}: target column {1} is mapped more than once".format(where, name))
        seen.add(name)

        if col.target_type and not ORACLE_TYPE_PATTERN.match(col.target_type):
            report.errors.append(
                "{0}: {1} Target_Type '{2}' is not an Oracle data type".format(where, label, col.target_type)
            )
        if col.nullable and col.nullable.upper() not in VALID_NULLABLE:
            report.errors.append("{0}: {1} Nullable must be Y or N".format(where, label))
        if col.scd_type and col.scd_type not in VALID_SCD_TYPES:
            report.errors.append(
                "{0}: {1} SCD_Type '{2}' must be one of {3}".format(
                    where, label, col.scd_type, ", ".join(VALID_SCD_TYPES)
                )
            )
        _check_scd2_column(mapping, col, name, label, where, report)
        if approved:
            for attr in REQUIRED_COLUMN_CELLS_FOR_APPROVAL:
                if not getattr(col, attr).strip():
                    report.errors.append(
                        "{0}: {1} has no {2}; an approved mapping needs it for every column".format(
                            where, label, attr.title().replace("Scd", "SCD")
                        )
                    )

        rule = col.transformation_rule.strip()
        if not col.source_table:
            report.errors.append("{0}: {1} has no Source_Table".format(where, label))
        if not rule:
            report.errors.append("{0}: {1} has no Transformation_Rule".format(where, label))
            continue
        if PROSE_PATTERN.search(rule):
            report.warnings.append(
                "{0}: {1} Transformation_Rule looks like prose ('{2}'); it must be SQL - "
                "'direct', NULL, or an Oracle expression. Put explanations in Notes".format(
                    where, label, rule[:60]
                )
            )

        source = col.source_table.strip().upper()
        if source == "PARAM":
            if len(col.source_columns) != 1:
                report.errors.append(
                    "{0}: {1} Source_Table PARAM needs exactly one parameter name in Source_Column".format(
                        where, label
                    )
                )
            elif mapping.parameters and col.source_columns[0] not in mapping.parameter_names:
                report.errors.append(
                    "{0}: {1} reads parameter {2}, which is not in Parameters".format(
                        where, label, col.source_columns[0]
                    )
                )
            if col.is_direct:
                report.errors.append(
                    "{0}: {1} a PARAM column cannot use 'direct'; write the parameter name as the "
                    "rule, e.g. {2}".format(where, label, (col.source_columns or ["P_X"])[0])
                )
        elif source == "EXPR":
            if col.is_direct:
                report.errors.append("{0}: {1} an EXPR column cannot use 'direct'".format(where, label))
        elif source == ITEM_ALIAS:
            if not mapping.item_columns:
                report.errors.append(
                    "{0}: {1} Source_Table ITEM reads the Item_Columns sheet, which is empty".format(where, label)
                )
            if col.is_direct:
                report.errors.append(
                    "{0}: {1} an ITEM column cannot use 'direct'; aggregate it, e.g. SUM(ITEM.{2})".format(
                        where, label, (col.source_columns or ["X"])[0]
                    )
                )
            for item in col.source_columns:
                if item not in mapping.item_names:
                    report.errors.append(
                        "{0}: {1} Source_Column {2} is not on the Item_Columns sheet".format(where, label, item)
                    )
        elif source:
            if not QUALIFIED_TABLE_PATTERN.match(source):
                report.errors.append(
                    "{0}: {1} Source_Table '{2}' must be SCHEMA.TABLE, PARAM or EXPR".format(
                        where, label, col.source_table
                    )
                )
            elif source_tables and bare_table(source) not in source_tables:
                report.errors.append(
                    "{0}: {1} reads {2}, which is neither the Driving_Table nor a Joins table".format(
                        where, label, source
                    )
                )
            known = schema_catalog.columns_of(source)
            if known is not None:
                for src_col in col.source_columns:
                    if src_col not in known:
                        report.errors.append(
                            "{0}: {1} Source_Column {2} does not exist in {3}".format(
                                where, label, src_col, source
                            )
                        )
            if col.is_direct and len(col.source_columns) != 1:
                report.errors.append(
                    "{0}: {1} 'direct' needs exactly one Source_Column".format(where, label)
                )
        if not col.is_direct and rule.upper() != "NULL":
            _check_sql_refs(rule, "{0} Transformation_Rule".format(label), where, source_tables, report, items)

    # In PL/SQL a column name wins over a variable of the same name, so a
    # parameter called like a column silently turns `WHERE BUSINESS_DATE =
    # BUSINESS_DATE` into "always true". Parameter names must be unique.
    all_columns = set(seen) | (set(SCD2_HISTORY_COLUMNS) if mapping.is_scd2 else set())
    for qualified in source_tables.values():
        all_columns |= set(schema_catalog.columns_of(qualified) or {})
    for name in mapping.parameter_names:
        if name in all_columns:
            report.errors.append(
                "{0}: parameter {1} has the same name as a source or target column; PL/SQL would "
                "read the column instead - rename it, e.g. P_{1}".format(where, name)
            )

    for key in mapping.business_key:
        col = mapping.column(key)
        if col is None:
            report.errors.append(
                "{0}: Business_Key column {1} is not a Target_Column on the Columns sheet".format(where, key)
            )
        elif col.nullable and col.nullable.upper() != "N":
            report.errors.append(
                "{0}: Business_Key column {1} must have Nullable = N".format(where, key)
            )

    # -- load strategy -----------------------------------------------------
    strategy = mapping.load_strategy
    if strategy and strategy not in VALID_LOAD_STRATEGIES:
        report.errors.append(
            "{0}: Load_Strategy '{1}' must be one of {2}".format(
                where, strategy, ", ".join(VALID_LOAD_STRATEGIES)
            )
        )
    if strategy == "delete_insert" and not mapping.reload_predicate:
        report.errors.append(
            "{0}: Load_Strategy delete_insert needs a Reload_Predicate (which target rows "
            "one run replaces, e.g. BUSINESS_DATE = P_BUSINESS_DATE)".format(where)
        )
    if strategy and strategy != "delete_insert" and mapping.reload_predicate:
        report.errors.append(
            "{0}: Reload_Predicate is only used by delete_insert; clear it or change "
            "Load_Strategy".format(where)
        )
    if mapping.reload_predicate:
        refs = column_refs(mapping.reload_predicate)
        if refs:
            report.errors.append(
                "{0}: Reload_Predicate must use bare target column names, not TABLE.COLUMN "
                "(found {1}.{2})".format(where, refs[0][0], refs[0][1])
            )

    _check_aggregation(mapping, where, report)
    _check_compared_rounding(mapping, where, report)

    if mapping.is_scd2:
        _check_scd2_mapping(mapping, where, report)
    elif mapping.source_snapshot:
        report.errors.append(
            "{0}: Source_Snapshot is only used by scd2; clear it or change Load_Strategy".format(where)
        )

    # -- acceptance criteria -------------------------------------------------
    ids = set()
    for index, ac in enumerate(mapping.criteria, start=1):
        label = "Acceptance_Criteria row {0}".format(index)
        if not ac.ac_id:
            report.errors.append("{0}: {1} has no AC_ID".format(where, label))
        elif ac.ac_id in ids:
            report.errors.append("{0}: AC_ID {1} is used twice".format(where, ac.ac_id))
        ids.add(ac.ac_id)
        if not ac.description:
            report.errors.append("{0}: {1} has no Description".format(where, label))
        check_type = ac.check_type.strip().lower()
        if check_type not in VALID_CHECK_TYPES:
            report.errors.append(
                "{0}: {1} Check_Type '{2}' must be one of {3}".format(
                    where, label, ac.check_type, ", ".join(VALID_CHECK_TYPES)
                )
            )
        if check_type in ("zero_rows", "expected_value", "guard") and not ac.check_sql:
            report.errors.append("{0}: {1} ({2}) needs Check_SQL".format(where, label, check_type))
        if check_type == "expected_value" and not ac.expected:
            report.errors.append("{0}: {1} (expected_value) needs Expected".format(where, label))
        if check_type == "rerun_idempotent" and strategy == "append":
            report.errors.append(
                "{0}: {1} expects a re-run to be idempotent, but Load_Strategy append makes a "
                "re-run fail on the primary key".format(where, label)
            )
        if ac.check_sql.strip().rstrip().endswith(";"):
            report.errors.append(
                "{0}: {1} Check_SQL must not end with ';' - it is embedded in generated PL/SQL".format(
                    where, label
                )
            )

    # -- sources and decisions ---------------------------------------------------
    for index, src in enumerate(mapping.sources, start=1):
        if src.source_type and src.source_type.lower() not in VALID_SOURCE_TYPES:
            report.errors.append(
                "{0}: Sources row {1} Source_Type '{2}' must be one of {3}".format(
                    where, index, src.source_type, ", ".join(VALID_SOURCE_TYPES)
                )
            )
    open_decisions = []
    for index, decision in enumerate(mapping.decisions, start=1):
        status = decision.status.lower()
        if status and status not in VALID_DECISION_STATUSES:
            report.errors.append(
                "{0}: Decisions row {1} Status '{2}' must be open or decided".format(
                    where, index, decision.status
                )
            )
        if status != "decided":
            open_decisions.append(decision.id or str(index))

    # -- completeness for approval ------------------------------------------------
    if approved:
        for name in REQUIRED_FOR_APPROVAL:
            if not mapping.get(name):
                report.errors.append(
                    "{0}: approved mapping has an empty '{1}'; a mapping cannot be approved "
                    "while it is incomplete".format(where, name)
                )
        approved_on = mapping.get("Approved_On")
        if approved_on:
            try:
                _dt.date.fromisoformat(approved_on)
            except ValueError:
                report.errors.append(
                    "{0}: Approved_On '{1}' must be a date, YYYY-MM-DD".format(where, approved_on)
                )
        if len(mapping.criteria) < MIN_ACCEPTANCE_CRITERIA:
            report.errors.append(
                "{0}: approved mapping has {1} acceptance criteria; at least {2} are "
                "required - they become the tests".format(
                    where, len(mapping.criteria), MIN_ACCEPTANCE_CRITERIA
                )
            )
        if open_decisions:
            report.errors.append(
                "{0}: approved mapping still has open decision(s): {1}".format(
                    where, ", ".join(open_decisions)
                )
            )
        for upstream, upstream_status in sorted(_unapproved_upstream(mapping, source_tables).items()):
            report.errors.append(
                "{0}: reads a table or column that {1} ({2}) plans; approve {1} first".format(
                    where, upstream, upstream_status
                )
            )
        for location, text in _all_cells(mapping):
            if TODO_PATTERN.search(text):
                report.errors.append(
                    "{0}: approved mapping still contains a TODO ({1}: {2})".format(
                        where, location, text[:80]
                    )
                )
    elif len(mapping.criteria) < MIN_ACCEPTANCE_CRITERIA:
        report.warnings.append(
            "{0}: {1} acceptance criteria; at least {2} are needed before approval".format(
                where, len(mapping.criteria), MIN_ACCEPTANCE_CRITERIA
            )
        )

    return report


def _check_aggregation(mapping: Mapping, where: str, report: Report) -> None:
    """Group_By makes the load an aggregating one: GROUP BY the expressions of
    the Group_By columns. The rules are stricter than Oracle's on purpose: a
    column that is not grouped may read source columns only inside an
    aggregate, so 'not a GROUP BY expression' (ORA-00979) is caught here
    instead of when the developer compiles the package."""
    for what, text in [("Filter", mapping.filter if mapping.has_filter else "")] + [
        ("Joins row {0} Condition".format(i), j.condition) for i, j in enumerate(mapping.joins, start=1)
    ]:
        if has_aggregate(text):
            report.errors.append(
                "{0}: {1} uses an aggregate function; a condition on aggregated values (HAVING) is not "
                "supported - filter the source rows instead".format(where, what)
            )

    group_by = mapping.group_by
    if not group_by:
        for index, col in enumerate(mapping.columns, start=1):
            if has_aggregate(col.transformation_rule):
                report.errors.append(
                    "{0}: Columns row {1} ({2}) uses an aggregate function but Group_By is empty; list the "
                    "columns that identify one target row in Group_By".format(
                        where, index, col.target_column.strip().upper()
                    )
                )
        return

    names = {col.target_column.strip().upper() for col in mapping.columns}
    seen = set()
    for name in group_by:
        if name in seen:
            report.errors.append("{0}: Group_By lists {1} twice".format(where, name))
        seen.add(name)
        if name not in names:
            report.errors.append(
                "{0}: Group_By column {1} is not a Target_Column on the Columns sheet".format(where, name)
            )
    for key in mapping.business_key:
        if key not in group_by:
            report.errors.append(
                "{0}: Business_Key column {1} is not in Group_By; a key that is not grouped is not unique "
                "per target row".format(where, key)
            )

    reads_source = False
    for index, col in enumerate(mapping.columns, start=1):
        name = col.target_column.strip().upper()
        label = "Columns row {0} ({1})".format(index, name)
        rule = col.transformation_rule.strip()
        grouped = name in group_by
        if grouped:
            if has_aggregate(rule):
                report.errors.append(
                    "{0}: {1} is in Group_By, so its rule must not use an aggregate function".format(where, label)
                )
            if col.source_table.strip().upper() == ITEM_ALIAS or any(t == ITEM_ALIAS for t, _c in column_refs(rule)):
                report.errors.append(
                    "{0}: {1} is in Group_By, so it reads the source tables directly, never ITEM".format(where, label)
                )
            if (col.is_direct and not col.is_pseudo) or column_refs(rule):
                reads_source = True
            continue
        if col.is_direct:
            report.errors.append(
                "{0}: {1} copies one source value ('direct') but is not in Group_By; add it to Group_By, or "
                "write an aggregate such as MAX({2}.{3}) when the value is the same on every row of the "
                "group".format(where, label, bare_table(col.source_table), (col.source_columns or ["COLUMN"])[0])
            )
            continue
        direct_reads = sorted({t for t, _c in column_refs(rule) if t != ITEM_ALIAS})
        if mapping.item_columns and direct_reads:
            report.errors.append(
                "{0}: {1} reads {2} directly, but with Item_Columns a column outside Group_By reads item "
                "columns only (ITEM.<name>); add an item column for the value".format(
                    where, label, ", ".join(direct_reads)
                )
            )
            continue
        outside = refs_outside_aggregates(rule)
        if outside:
            report.errors.append(
                "{0}: {1} is not in Group_By, so it may read source columns only inside an aggregate "
                "(SUM, MIN, MAX, COUNT, AVG...), but {2}.{3} is outside one; wrap it, e.g. MAX({2}.{3}), "
                "or add the column to Group_By".format(where, label, outside[0][0], outside[0][1])
            )
    if names and not reads_source:
        report.errors.append(
            "{0}: Group_By needs at least one column read from a source table; a load that sums every "
            "source row into one row must group by a source column that is the same on every row, e.g. "
            "the load ID".format(where)
        )


def _check_item_columns(mapping: Mapping, where: str, source_tables: dict, report: Report) -> None:
    """Item_Columns: the per-row step under the grouping. The generated query
    is SELECT <aggregates of ITEM.x> FROM (SELECT <group columns>, <item
    rules> FROM <sources> WHERE <filter>) ITEM GROUP BY ..., so a window
    function (OVER) can feed an aggregate - Oracle forbids that in one query."""
    if not mapping.item_columns:
        return
    if not mapping.group_by:
        report.errors.append(
            "{0}: the Item_Columns sheet is only used by an aggregating mapping; fill in Group_By".format(where)
        )
    if ITEM_ALIAS in source_tables:
        report.errors.append(
            "{0}: a source table is called {1}, which is the alias of the Item_Columns step; "
            "Item_Columns cannot be used with it".format(where, ITEM_ALIAS)
        )
    taken = set(mapping.group_by)
    seen = set()
    for index, item in enumerate(mapping.item_columns, start=1):
        name = item.name
        label = "Item_Columns row {0} ({1})".format(index, name or "?")
        if not name:
            report.errors.append("{0}: Item_Columns row {1} has no Item_Column".format(where, index))
        elif not IDENTIFIER_PATTERN.match(name):
            report.errors.append("{0}: {1} is not a valid Oracle column name".format(where, label))
        elif name in seen:
            report.errors.append("{0}: item column {1} is listed twice".format(where, name))
        elif name in taken:
            report.errors.append(
                "{0}: {1} has the name of a Group_By column; the per-row step holds both, so rename "
                "it".format(where, label)
            )
        seen.add(name)
        rule = item.transformation_rule.strip()
        if not rule:
            report.errors.append("{0}: {1} has no Transformation_Rule".format(where, label))
            continue
        if PROSE_PATTERN.search(rule):
            report.warnings.append(
                "{0}: {1} Transformation_Rule looks like prose ('{2}'); it must be SQL".format(where, label, rule[:60])
            )
        if has_aggregate(rule):
            report.errors.append(
                "{0}: {1} uses an aggregate function; an item column is one value per source row - "
                "a window function (... OVER (...)) is allowed, the aggregate belongs on the Columns "
                "sheet".format(where, label)
            )
        if any(t == ITEM_ALIAS for t, _c in column_refs(rule)):
            report.errors.append(
                "{0}: {1} reads another item column; item columns are computed side by side, so "
                "repeat that expression instead".format(where, label)
            )
            continue
        _check_sql_refs(rule, "{0} Transformation_Rule".format(label), where, source_tables, report)


def _check_compared_rounding(mapping: Mapping, where: str, report: Report) -> None:
    """merge and scd2 compare the source value with the stored one. The stored
    value is rounded to the column's scale, so a multiplied or divided value
    that is not rounded differs on every run (scd2: a new version every day)."""
    strategy = mapping.load_strategy
    if strategy not in ("merge", "scd2"):
        return
    compared_type = "2" if strategy == "scd2" else "1"
    for index, col in enumerate(mapping.columns, start=1):
        name = col.target_column.strip().upper()
        if name in mapping.business_key or col.source_table.strip().upper() == "EXPR":
            continue
        if (col.scd_type.strip() or "1") != compared_type or not PRECISE_NUMBER_PATTERN.match(col.target_type):
            continue
        text = _blank_literals(col.transformation_rule).replace("(*)", "()")
        if ("*" in text or "/" in text) and not ROUNDING_PATTERN.search(text):
            report.warnings.append(
                "{0}: Columns row {1} ({2}) multiplies or divides without ROUND; the table stores it rounded "
                "to {3}, so the {4} compare sees a change on every run{5}. Write ROUND(..., <scale>)".format(
                    where, index, name, col.target_type.strip(), strategy,
                    " and adds a new version each time" if strategy == "scd2" else "",
                )
            )


def _check_scd2_column(mapping: Mapping, col, name: str, label: str, where: str, report: Report) -> None:
    """SCD_Type 2 only exists in an scd2 mapping, and there every non-key
    column is either tracked (2) or never compared (0)."""
    scd_type = col.scd_type.strip()
    is_key = name in mapping.business_key
    if not mapping.is_scd2:
        if scd_type == "2" and mapping.load_strategy:
            report.errors.append(
                "{0}: {1} SCD_Type 2 keeps history, which needs Load_Strategy scd2".format(where, label)
            )
        return
    if name in SCD2_HISTORY_COLUMNS:
        report.errors.append(
            "{0}: {1} is added by the scd2 load itself; remove it from the Columns sheet".format(where, label)
        )
    if is_key:
        return
    if scd_type == "1":
        report.errors.append(
            "{0}: {1} SCD_Type 1 (overwrite) does not exist in an scd2 mapping; use 2 (a change adds a "
            "new version) or 0 (written with each version, never compared)".format(where, label)
        )
    source = col.source_table.strip().upper()
    if scd_type == "2" and source == "EXPR":
        report.warnings.append(
            "{0}: {1} is computed (EXPR), so it is never compared even with SCD_Type 2 - a value like "
            "SYSTIMESTAMP would otherwise make every run a change; mark it 0".format(where, label)
        )
    elif scd_type == "2" and source == "PARAM":
        report.warnings.append(
            "{0}: {1} copies a parameter and is tracked (SCD_Type 2): if the value differs on every run, "
            "every run adds a new version of every key; mark it 0 unless that is intended".format(where, label)
        )


def _check_scd2_mapping(mapping: Mapping, where: str, report: Report) -> None:
    """An scd2 load is replayed date by date, so it needs exactly one DATE
    parameter (the date a run's source data is valid for), and the source
    must actually be read as of that date."""
    params = mapping.parameters
    if len(params) != 1 or _base_type(params[0][1]) != "DATE":
        report.errors.append(
            "{0}: Load_Strategy scd2 needs exactly one parameter, a DATE: the date the source data is "
            "valid for, e.g. 'P_BUSINESS_DATE DATE' (a run for an earlier date replays the later dates "
            "with it, so no other parameter can be part of the load)".format(where)
        )
    else:
        name = params[0][0]
        texts = [mapping.filter if mapping.has_filter else ""] + [j.condition for j in mapping.joins]
        pattern = re.compile(r"(?<![\w$#.]){0}(?![\w$#])".format(re.escape(name)), re.IGNORECASE)
        if not any(pattern.search(STRING_LITERAL_PATTERN.sub("''", t or "")) for t in texts):
            report.errors.append(
                "{0}: Load_Strategy scd2 reads the source as of {1}, but neither the Filter nor a join "
                "condition uses {1}; a run for an earlier date would load today's data under that "
                "date".format(where, name)
            )
    if not mapping.source_snapshot:
        report.errors.append(
            "{0}: Load_Strategy scd2 needs Source_Snapshot: full (a key missing from the source was "
            "deleted) or delta (it is unchanged)".format(where)
        )
    elif mapping.source_snapshot not in VALID_SOURCE_SNAPSHOTS:
        report.errors.append(
            "{0}: Source_Snapshot '{1}' must be one of {2}".format(
                where, mapping.source_snapshot, ", ".join(VALID_SOURCE_SNAPSHOTS)
            )
        )
    tracked = [
        col for col in mapping.columns
        if col.target_column.strip().upper() not in mapping.business_key
        and col.scd_type.strip() == "2"
        and col.source_table.strip().upper() != "EXPR"
    ]
    if mapping.columns and not tracked:
        report.errors.append(
            "{0}: Load_Strategy scd2 needs at least one tracked column (a non-key column with SCD_Type 2 "
            "that is not EXPR); without one no change can ever add a version".format(where)
        )
    for key in mapping.business_key:
        if key in SCD2_HISTORY_COLUMNS:
            report.errors.append(
                "{0}: Business_Key must not contain {1}; the scd2 load adds it to the primary key "
                "itself".format(where, key)
            )


def _base_type(text: str) -> str:
    """The base of an Oracle type: 'NUMBER(18,2)' -> 'NUMBER'."""
    match = re.match(r"\s*([A-Za-z0-9]+)", text or "")
    return match.group(1).upper() if match else ""


def _all_cells(mapping: Mapping):
    """(location, text) for every non-empty cell, for the TODO scan."""
    data = mapping_to_dict(mapping)
    for name, value in data["mapping"].items():
        if value:
            yield "Mapping.{0}".format(name), value
    for sheet, rows in data.items():
        if sheet == "mapping":
            continue
        for index, row in enumerate(rows, start=1):
            for key, value in row.items():
                if value:
                    yield "{0} row {1} {2}".format(sheet, index, key), value
