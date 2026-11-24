"""The mapping workbook: the one file an analyst produces for a load.

A mapping lives in its own folder, ``specs/<folder>/<MAPPING_ID>.xlsx``,
where the folder is the Mapping_ID without its ``M_`` prefix, in lower case
(M_LOAN_LIMIT_DAILY -> specs/loan_limit_daily/M_LOAN_LIMIT_DAILY.xlsx). One
workbook per mapping, never several mappings in one file (a binary file cannot be merged
in git, so one file per mapping keeps history and ownership clean). It is
the single source of truth for that load: the validator, the verifier and
the code generators all read it directly. There is no Markdown or YAML copy.

Sheets (in this order):

  Mapping              one row per field: Field | Value | Help
  Columns              one row per target column, in table column order
  Item_Columns         aggregating loads only, optional: values computed per source row
                       (window functions such as a running total) before the grouping
  Joins                one row per joined table, in join order
  Acceptance_Criteria  one row per testable assertion
  Sources              where each finding came from (the sql/ folder, a person...)
  Decisions            questions raised while drafting, and their answers
  How_To               instructions for whoever fills the workbook in
  _meta                hidden: workbook format version

This module is the only code that knows the physical layout. Everything
else works with the ``Mapping`` object it returns, or with the JSON form
(``mapping_to_dict``/``mapping_from_dict``) that an AI assistant writes and
``mapping_workbook.py write`` turns into a workbook.

Needs openpyxl (see requirements.txt).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field, fields

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
except ImportError as exc:  # pragma: no cover - guidance path only
    raise ImportError(
        "openpyxl is required to read and write mapping workbooks. "
        "Install it with:  pip install -r requirements.txt"
    ) from exc

FORMAT_VERSION = 3

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# Every mapping has its own folder directly under specs/. The folder holds the
# workbook and the code tools/codegen/generate.py generates from it.
SPEC_DIR = os.path.join(REPO_ROOT, "specs")

VALID_STATUSES = ("draft", "in_review", "approved")
VALID_LOAD_STRATEGIES = ("full", "delete_insert", "merge", "append", "scd2")
VALID_JOIN_TYPES = ("inner", "left")
VALID_NULLABLE = ("Y", "N")
VALID_SCD_TYPES = ("0", "1", "2")
VALID_SOURCE_SNAPSHOTS = ("full", "delta")
VALID_CHECK_TYPES = (
    "unique_key",
    "rerun_idempotent",
    "all_source_rows_loaded",
    "zero_rows",
    "expected_value",
    "guard",
)
# "sql" = a script in the sql/ folder (table, constraint, comment or package).
VALID_SOURCE_TYPES = ("sql", "user", "other")
VALID_DECISION_STATUSES = ("open", "decided")

# Source_Table values that are not a real table: PARAM is a procedure input
# parameter (Source_Column names it), EXPR a value computed in the rule with
# no source column at all (SYSTIMESTAMP, a literal), ITEM an Item_Columns
# value (Source_Column names the item column(s)).
PSEUDO_SOURCES = ("PARAM", "EXPR", "ITEM")

# Item_Columns: the alias of the per-row step an aggregating load groups. A
# Columns row reads an item column as ITEM.<Item_Column> (Source_Table ITEM).
ITEM_ALIAS = "ITEM"

# The columns an scd2 load adds to the target by itself. They are never listed
# on the Columns sheet. VALID_TO is exclusive and OPEN_VALID_TO marks the
# current version; IS_DELETED exists only when Source_Snapshot is full.
SCD2_HISTORY_COLUMNS = ("VALID_FROM", "VALID_TO", "IS_DELETED")
OPEN_VALID_TO = "DATE '9999-12-31'"

# Mapping fields added after mappings were already approved. Left empty, they
# are kept out of the fingerprint, so adding them did not invalidate any
# approval or any generated code.
FINGERPRINT_SKIPS_WHEN_EMPTY = ("Source_Snapshot", "Group_By")
# The same for sheets (their JSON keys) added after mappings were approved.
SHEETS_SKIPPED_WHEN_EMPTY = ("item_columns",)

# The fields that record approval. They are excluded from the content
# fingerprint: approving a mapping must not change what was approved.
APPROVAL_FIELDS = ("Status", "Approved_By", "Approved_On")


@dataclass(frozen=True)
class FieldSpec:
    name: str
    help: str
    multiline: bool = False
    choices: tuple = ()


# The Mapping sheet, top to bottom. `help` is what the analyst sees in the
# workbook, so it is written for them, not for a developer.
MAPPING_FIELDS = (
    FieldSpec("Mapping_ID", "Stable ID, e.g. M_CUSTOMER_ACCOUNT. Must equal the file name; the folder is the ID without M_, lower case (specs/customer_account/)."),
    FieldSpec("Status", "draft -> in_review -> approved. Only a named person sets approved.", choices=VALID_STATUSES),
    FieldSpec("Owner", "The person accountable for this load."),
    FieldSpec("Approved_By", "Name of the person who approved it. Never filled in by an AI."),
    FieldSpec("Approved_On", "Approval date, YYYY-MM-DD."),
    FieldSpec("Source_Ref", "Where the requirement came from: ticket key, URL, or 'chat'."),
    FieldSpec("Intent", "Why this load exists and what report or question it serves.", multiline=True),
    FieldSpec("Target_Table", "Fully qualified target, SCHEMA.TABLE, e.g. UBB_CORE2.CUSTOMER_ACCOUNT."),
    FieldSpec("Table_Description", "What one row of the target table means, in business language.", multiline=True),
    FieldSpec("Grain", "One row per what? e.g. 'one row per account per business date'."),
    FieldSpec("Business_Key", "Target columns that identify a row, comma separated. Becomes the primary key."),
    FieldSpec("PLSQL_Proc", "Procedure that loads the table, SCHEMA.PACKAGE.PROCEDURE."),
    FieldSpec("Parameters", "Procedure parameters as NAME TYPE, separated by ';', e.g. 'P_BUSINESS_DATE DATE'. Write 'none' if it takes none."),
    FieldSpec("Driving_Table", "The source table whose rows define the grain (the FROM table), SCHEMA.TABLE."),
    FieldSpec("Filter", "Which source rows a run reads: a SQL condition without WHERE, e.g. STG_PARTNER.PARTNER_TYPE = 'PERSON', or 'none'."),
    FieldSpec("Group_By", "Aggregating loads only: the target columns that define one target row when several source rows are summed into it, comma separated, e.g. LOAN_ID, LOAD_ID. Must include every Business_Key column. Every other column must then use only aggregates (SUM, MIN, MAX, COUNT, AVG...) of source columns, parameters or constants. Leave empty when one source row gives one target row."),
    FieldSpec("Load_Strategy", "full = replace the whole table; delete_insert = replace the rows matched by Reload_Predicate; merge = update/insert on the business key; append = insert only (a re-run fails); scd2 = keep history: a change closes the current version and adds a new one (VALID_FROM/VALID_TO).", choices=VALID_LOAD_STRATEGIES),
    FieldSpec("Reload_Predicate", "delete_insert only: which target rows one run replaces, e.g. BUSINESS_DATE = P_BUSINESS_DATE."),
    FieldSpec("Source_Snapshot", "scd2 only: full = every run's source holds every key, so a missing key is recorded as deleted (IS_DELETED = Y); delta = the source holds only changed keys, so a missing key is unchanged.", choices=VALID_SOURCE_SNAPSHOTS),
    FieldSpec("Not_For", "What this load deliberately does NOT do. One item per line.", multiline=True),
    FieldSpec("Preconditions", "What must be true before the load runs. One item per line.", multiline=True),
    FieldSpec("Error_Handling", "What happens to bad or incomplete source rows. One item per line.", multiline=True),
)
MAPPING_FIELD_NAMES = tuple(f.name for f in MAPPING_FIELDS)

COLUMN_HEADERS = (
    "Target_Column",
    "Target_Type",
    "Nullable",
    "Source_Table",
    "Source_Column",
    "Transformation_Rule",
    "SCD_Type",
    "Business_Name",
    "Description",
    "Notes",
)
ITEM_COLUMN_HEADERS = ("Item_Column", "Transformation_Rule", "Description", "Notes")
JOIN_HEADERS = ("Table", "Join_Type", "Condition", "Notes")
CRITERIA_HEADERS = ("AC_ID", "Description", "Check_Type", "Check_SQL", "Expected", "Notes")
SOURCE_HEADERS = ("Topic", "Source_Type", "Reference", "Finding")
DECISION_HEADERS = ("ID", "Topic", "Question", "Decision", "Decided_By", "Decided_On", "Status")


@dataclass
class ColumnRule:
    target_column: str = ""
    target_type: str = ""
    nullable: str = ""
    source_table: str = ""
    source_column: str = ""
    transformation_rule: str = ""
    scd_type: str = ""
    business_name: str = ""
    description: str = ""
    notes: str = ""

    @property
    def is_pseudo(self) -> bool:
        return self.source_table.strip().upper() in PSEUDO_SOURCES

    @property
    def is_direct(self) -> bool:
        return self.transformation_rule.strip().lower() == "direct"

    @property
    def source_columns(self) -> list:
        return [c.strip().upper() for c in re.split(r"[,;]", self.source_column) if c.strip()]


@dataclass
class ItemColumn:
    item_column: str = ""
    transformation_rule: str = ""
    description: str = ""
    notes: str = ""

    @property
    def name(self) -> str:
        return self.item_column.strip().upper()


@dataclass
class Join:
    table: str = ""
    join_type: str = ""
    condition: str = ""
    notes: str = ""


@dataclass
class Criterion:
    ac_id: str = ""
    description: str = ""
    check_type: str = ""
    check_sql: str = ""
    expected: str = ""
    notes: str = ""


@dataclass
class SourceRef:
    topic: str = ""
    source_type: str = ""
    reference: str = ""
    finding: str = ""


@dataclass
class Decision:
    id: str = ""
    topic: str = ""
    question: str = ""
    decision: str = ""
    decided_by: str = ""
    decided_on: str = ""
    status: str = ""


# Sheet name -> (headers, row class). Header i maps to dataclass field i.
_TABLE_SHEETS = {
    "Columns": (COLUMN_HEADERS, ColumnRule),
    "Item_Columns": (ITEM_COLUMN_HEADERS, ItemColumn),
    "Joins": (JOIN_HEADERS, Join),
    "Acceptance_Criteria": (CRITERIA_HEADERS, Criterion),
    "Sources": (SOURCE_HEADERS, SourceRef),
    "Decisions": (DECISION_HEADERS, Decision),
}
_SHEET_ATTR = {
    "Columns": "columns",
    "Item_Columns": "item_columns",
    "Joins": "joins",
    "Acceptance_Criteria": "criteria",
    "Sources": "sources",
    "Decisions": "decisions",
}


def _split_qualified(name: str):
    parts = [p.strip() for p in str(name).split(".") if p.strip()]
    return parts


def bare_table(qualified: str) -> str:
    """`UBB_STAGING2.STG_LOAN` -> `STG_LOAN` (upper-cased)."""
    parts = _split_qualified(qualified)
    return parts[-1].upper() if parts else ""


@dataclass
class Mapping:
    """One parsed mapping workbook."""

    fields: dict = field(default_factory=dict)
    columns: list = field(default_factory=list)
    item_columns: list = field(default_factory=list)
    joins: list = field(default_factory=list)
    criteria: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    path: str = ""
    format_version: int = FORMAT_VERSION

    # -- plain field access ------------------------------------------------

    def get(self, name: str) -> str:
        return str(self.fields.get(name) or "").strip()

    def lines(self, name: str) -> list:
        return [line.strip() for line in self.get(name).splitlines() if line.strip()]

    @property
    def mapping_id(self) -> str:
        return self.get("Mapping_ID")

    @property
    def status(self) -> str:
        return self.get("Status").lower()

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def rel_path(self) -> str:
        if not self.path:
            return "<{0}>".format(self.mapping_id or "unsaved mapping")
        try:
            return os.path.relpath(self.path, REPO_ROOT).replace(os.sep, "/")
        except ValueError:
            return self.path.replace(os.sep, "/")

    # -- derived facts the generators need --------------------------------

    @property
    def target(self) -> str:
        return self.get("Target_Table").upper()

    @property
    def target_schema(self) -> str:
        parts = _split_qualified(self.target)
        return parts[0] if len(parts) == 2 else ""

    @property
    def target_table(self) -> str:
        return bare_table(self.target)

    @property
    def business_key(self) -> list:
        return [k.strip().upper() for k in re.split(r"[,;]", self.get("Business_Key")) if k.strip()]

    @property
    def plsql_proc(self) -> str:
        return self.get("PLSQL_Proc").upper()

    @property
    def proc_parts(self):
        """(schema, package, procedure) or None when not 3-part."""
        parts = _split_qualified(self.plsql_proc)
        return tuple(parts) if len(parts) == 3 else None

    @property
    def parameters(self) -> list:
        """[(NAME, TYPE)] from the Parameters field; [] for 'none'."""
        text = self.get("Parameters")
        if not text or text.lower() == "none":
            return []
        result = []
        for chunk in re.split(r"[;\n]", text):
            chunk = chunk.strip().rstrip(",")
            if not chunk:
                continue
            bits = chunk.split(None, 1)
            name = bits[0].upper()
            ptype = bits[1].strip().upper() if len(bits) > 1 else ""
            result.append((name, ptype))
        return result

    @property
    def parameter_names(self) -> list:
        return [name for name, _ in self.parameters]

    @property
    def driving_table(self) -> str:
        return self.get("Driving_Table").upper()

    @property
    def source_tables(self) -> list:
        """Qualified source tables in FROM/JOIN order: driving table first."""
        tables = []
        if self.driving_table:
            tables.append(self.driving_table)
        for join in self.joins:
            if join.table.strip():
                tables.append(join.table.strip().upper())
        return tables

    @property
    def filter(self) -> str:
        return self.get("Filter")

    @property
    def has_filter(self) -> bool:
        return bool(self.filter) and self.filter.lower() != "none"

    @property
    def group_by(self) -> list:
        """Target columns an aggregating load groups by; [] when one source
        row gives one target row."""
        return [c.strip().upper() for c in re.split(r"[,;]", self.get("Group_By")) if c.strip()]

    @property
    def is_aggregating(self) -> bool:
        return bool(self.group_by)

    @property
    def item_names(self) -> list:
        return [item.name for item in self.item_columns if item.name]

    @property
    def load_strategy(self) -> str:
        return self.get("Load_Strategy").lower()

    @property
    def reload_predicate(self) -> str:
        return self.get("Reload_Predicate")

    @property
    def is_scd2(self) -> bool:
        return self.load_strategy == "scd2"

    @property
    def source_snapshot(self) -> str:
        return self.get("Source_Snapshot").lower()

    def column(self, name: str):
        wanted = name.strip().upper()
        for col in self.columns:
            if col.target_column.strip().upper() == wanted:
                return col
        return None

    # -- identity -----------------------------------------------------------

    def fingerprint(self) -> str:
        """Short hash of everything except the approval fields.

        Two workbooks with the same fingerprint say the same thing. Used to
        tell whether content changed since approval (the writer drops an
        approval when it did) and stamped into every generated SQL file, so
        the deployed code can be traced back to the exact workbook content.
        """
        data = mapping_to_dict(self)
        for name in APPROVAL_FIELDS:
            data["mapping"].pop(name, None)
        for name in FINGERPRINT_SKIPS_WHEN_EMPTY:
            if not data["mapping"].get(name):
                data["mapping"].pop(name, None)
        for sheet in SHEETS_SKIPPED_WHEN_EMPTY:
            if not data.get(sheet):
                data.pop(sheet, None)
        canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# JSON interchange
# ---------------------------------------------------------------------------


def _norm(value) -> str:
    """Normalise a cell or JSON value to a stripped string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Y" if value else "N"
    if isinstance(value, _dt.datetime):
        return value.date().isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (list, tuple)):
        return "\n".join(_norm(v) for v in value if _norm(v))
    return str(value).replace("\r\n", "\n").strip()


def mapping_to_dict(mapping: Mapping) -> dict:
    data = {"mapping": {name: mapping.get(name) for name in MAPPING_FIELD_NAMES}}
    for sheet, attr in _SHEET_ATTR.items():
        data[_json_key(sheet)] = [asdict(row) for row in getattr(mapping, attr)]
    return data


def _json_key(sheet: str) -> str:
    return {"Acceptance_Criteria": "acceptance_criteria"}.get(sheet, sheet.lower())


def mapping_from_dict(data: dict, path: str = "") -> Mapping:
    """Build a Mapping from its JSON form. Unknown keys are rejected so a
    typo in a field name fails loudly instead of silently vanishing."""
    if not isinstance(data, dict):
        raise ValueError("mapping JSON must be an object")
    unknown_top = set(data) - {"mapping"} - {_json_key(s) for s in _SHEET_ATTR}
    if unknown_top:
        raise ValueError("unknown top-level key(s): {0}".format(", ".join(sorted(unknown_top))))

    raw_fields = data.get("mapping") or {}
    unknown = set(raw_fields) - set(MAPPING_FIELD_NAMES)
    if unknown:
        raise ValueError(
            "unknown Mapping field(s): {0}. Valid fields: {1}".format(
                ", ".join(sorted(unknown)), ", ".join(MAPPING_FIELD_NAMES)
            )
        )
    mapping = Mapping(fields={name: _norm(raw_fields.get(name)) for name in MAPPING_FIELD_NAMES}, path=path)

    for sheet, (_headers, cls) in _TABLE_SHEETS.items():
        rows = data.get(_json_key(sheet)) or []
        names = [f.name for f in fields(cls)]
        parsed = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ValueError("{0}[{1}] must be an object".format(_json_key(sheet), index))
            bad = set(row) - set(names)
            if bad:
                raise ValueError(
                    "{0}[{1}] has unknown key(s) {2}; valid keys: {3}".format(
                        _json_key(sheet), index, ", ".join(sorted(bad)), ", ".join(names)
                    )
                )
            parsed.append(cls(**{name: _norm(row.get(name)) for name in names}))
        setattr(mapping, _SHEET_ATTR[sheet], parsed)
    return mapping


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def is_mapping_workbook(workbook) -> bool:
    return "Mapping" in workbook.sheetnames and "Columns" in workbook.sheetnames


def read_mapping(path: str) -> Mapping:
    workbook = load_workbook(path, data_only=True)
    if not is_mapping_workbook(workbook):
        raise ValueError("not a mapping workbook (needs 'Mapping' and 'Columns' sheets)")

    version = FORMAT_VERSION
    if "_meta" in workbook.sheetnames:
        for key, value, *_rest in workbook["_meta"].iter_rows(values_only=True):
            if _norm(key) == "Format_Version" and _norm(value).isdigit():
                version = int(_norm(value))
    if version != FORMAT_VERSION:
        raise ValueError(
            "workbook format version {0} is not supported (expected {1})".format(version, FORMAT_VERSION)
        )

    mapping_fields = {name: "" for name in MAPPING_FIELD_NAMES}
    for row in workbook["Mapping"].iter_rows(min_row=2, values_only=True):
        if not row or row[0] is None:
            continue
        key = _norm(row[0])
        if key in mapping_fields:
            mapping_fields[key] = _norm(row[1] if len(row) > 1 else None)

    mapping = Mapping(fields=mapping_fields, path=os.path.abspath(path), format_version=version)
    for sheet, (headers, cls) in _TABLE_SHEETS.items():
        if sheet not in workbook.sheetnames:
            continue
        setattr(mapping, _SHEET_ATTR[sheet], _read_table(workbook[sheet], headers, cls))
    return mapping


def _read_table(sheet, headers, cls) -> list:
    rows = sheet.iter_rows(values_only=True)
    try:
        header_row = next(rows)
    except StopIteration:
        return []
    positions = {}
    for index, cell in enumerate(header_row):
        name = _norm(cell)
        if name in headers:
            positions[name] = index
    names = [f.name for f in fields(cls)]
    result = []
    for row in rows:
        values = {}
        for header, attr in zip(headers, names):
            index = positions.get(header)
            values[attr] = _norm(row[index]) if index is not None and index < len(row) else ""
        if any(values.values()):
            result.append(cls(**values))
    return result


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_FIELD_FONT = Font(bold=True)
_HELP_FONT = Font(italic=True, color="595959")
_WRAP = Alignment(wrap_text=True, vertical="top")
_EMPTY_ROWS = 25  # blank, pre-validated rows below the data for manual entry

_WIDTHS = {
    "Columns": (26, 16, 9, 28, 26, 46, 9, 24, 48, 40),
    "Item_Columns": (26, 70, 48, 40),
    "Joins": (30, 11, 60, 40),
    "Acceptance_Criteria": (8, 56, 22, 60, 12, 36),
    "Sources": (28, 13, 50, 70),
    "Decisions": (5, 22, 50, 50, 18, 12, 10),
}

_DROPDOWNS = {
    "Columns": {"Nullable": VALID_NULLABLE, "SCD_Type": VALID_SCD_TYPES},
    "Joins": {"Join_Type": VALID_JOIN_TYPES},
    "Acceptance_Criteria": {"Check_Type": VALID_CHECK_TYPES},
    "Sources": {"Source_Type": VALID_SOURCE_TYPES},
    "Decisions": {"Status": VALID_DECISION_STATUSES},
}

HOW_TO = (
    "HOW TO FILL IN THIS MAPPING WORKBOOK",
    "",
    "This workbook is the complete source-to-target specification for one load. A developer",
    "generates the table DDL, the PL/SQL load package and the utPLSQL tests from it without",
    "asking you anything, so every fact the SQL needs has to be written down here - precisely.",
    "",
    "Mapping sheet - one value per field. Grey text in column C explains each field.",
    "",
    "Columns sheet - one row per target column, in the order the table should have them.",
    "  Target_Type          Oracle data type, e.g. VARCHAR2(20), NUMBER(18,2), DATE, TIMESTAMP.",
    "  Nullable             Y or N. Business key columns are always N.",
    "  Source_Table         SCHEMA.TABLE the value comes from, or PARAM (a procedure parameter,",
    "                       named in Source_Column) or EXPR (computed, no source column).",
    "  Source_Column        The source column(s) the rule reads, comma separated.",
    "  Transformation_Rule  SQL only: 'direct' (copy the source column unchanged), NULL, or an Oracle",
    "                       expression usable in a SELECT, with columns written as TABLE.COLUMN,",
    "                       e.g. TRIM(UPPER(STG_PARTNER.PARTNER_NAME)). Explanations go in Notes.",
    "  SCD_Type             1 = a merge overwrites the value, 0 = never updated once written,",
    "                       2 = (scd2 only) a change closes the current version and adds a new one.",
    "                       In an scd2 mapping every non-key column is 2 (tracked) or 0 (written",
    "                       with each new version but never compared, e.g. a load timestamp).",
    "  Business_Name        Short business name, e.g. 'Available Balance'.",
    "  Description          What the value means for the business. Goes into the column comment.",
    "",
    "scd2 (history) loads - Load_Strategy scd2:",
    "  The procedure takes exactly one parameter, a DATE: the date the source data is valid for.",
    "  The Filter (or a join) must use it, so the source can be read as of any loaded date.",
    "  Do NOT list VALID_FROM, VALID_TO or IS_DELETED on the Columns sheet: the generator adds",
    "  them. VALID_TO is exclusive; DATE '9999-12-31' marks the current version.",
    "  Source_Snapshot says whether a key missing from the source was deleted (full) or not (delta).",
    "  A run for an earlier date than already loaded rebuilds the later history automatically.",
    "",
    "Aggregating loads - Group_By filled in (several source rows become one target row):",
    "  Group_By lists the target columns that identify one target row; it includes the whole",
    "  Business_Key. Every other column uses source columns only inside an aggregate, e.g.",
    "  SUM(COLL.VALUE_AMT * REL.ALLOCATION_PCT / 100), or MAX(LOAN.OUTSTANDING_AMT) for a value",
    "  that is the same on every row of the group. A computed amount that a merge or scd2 load",
    "  compares should be ROUNDed to the column's scale, or every run sees a change.",
    "  Joins that return several rows per driving row are what gets summed. Two such joins in",
    "  one mapping multiply each other and count values twice - verify_mapping.py warns.",
    "",
    "Item_Columns sheet - aggregating loads only, and only when a value must be computed per",
    "  source row BEFORE the grouping, typically with a window function (a running total):",
    "    Item_Column  PRIOR_VALUE",
    "    Rule         SUM(COLL.VALUE_AMT) OVER (PARTITION BY REL.LOAN_REF ORDER BY",
    "                 REL.ALLOCATION_PRIORITY ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)",
    "  A rule reads source tables and parameters, never another item column, and uses no",
    "  aggregate (a window function with OVER is fine).",
    "  With Item_Columns, a Columns row that is not in Group_By reads item columns only:",
    "  Source_Table ITEM, rule e.g. SUM(ITEM.RECOGNISED_AMT). Group_By columns still read the",
    "  source tables directly.",
    "",
    "Joins sheet - one row per table joined to the Driving_Table, in order.",
    "  Join_Type            inner = a source row with no match is left out of the target;",
    "                       left  = it is kept, with the looked-up columns empty (NULL).",
    "  Condition            The ON condition, e.g. STG_LOAN.CBS_PARTNER_REF = STG_PARTNER.CBS_PARTNER_REF.",
    "",
    "Acceptance_Criteria sheet - each row becomes one automated test.",
    "  unique_key              no two rows share a business key (generated automatically)",
    "  rerun_idempotent        running the load twice gives the same result (generated)",
    "  all_source_rows_loaded  every row the source query produces reaches the target (generated)",
    "  zero_rows               Check_SQL finds the rows that break the rule; the test expects none",
    "  expected_value          Check_SQL returns one value; the test expects it to equal Expected",
    "  guard                   Check_SQL finds SOURCE rows that must stop the whole run. The load",
    "                          checks it before writing anything and fails with ORA-20005, so no",
    "                          partial snapshot is ever written. The test feeds it such rows.",
    "  Check_SQL may use the procedure parameters by name, e.g. P_BUSINESS_DATE.",
    "",
    "Sources sheet - where each finding came from (a script in the sql/ folder, a person, other).",
    "Decisions sheet - every question raised while drafting and its answer. A mapping with an",
    "  open decision, or any TODO text anywhere, cannot be approved.",
    "",
    "APPROVAL: when the mapping is complete, the approving person sets Status = approved and",
    "fills Approved_By (their own name) and Approved_On (YYYY-MM-DD) on the Mapping sheet.",
    "An AI assistant never does this. Any later content change drops the approval again.",
)


def _style_header(sheet, headers, widths) -> None:
    for column, title in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=column, value=title)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center")
        letter = cell.column_letter
        sheet.column_dimensions[letter].width = widths[column - 1] if column - 1 < len(widths) else 20
    sheet.freeze_panes = "A2"


def _add_dropdown(sheet, column_index: int, choices, first_row: int, last_row: int) -> None:
    letter = sheet.cell(row=1, column=column_index).column_letter
    validation = DataValidation(
        type="list",
        formula1='"{0}"'.format(",".join(choices)),
        allow_blank=True,
        showErrorMessage=True,
        errorTitle="Not an allowed value",
        error="Pick one of: {0}".format(", ".join(choices)),
    )
    validation.add("{0}{1}:{0}{2}".format(letter, first_row, last_row))
    sheet.add_data_validation(validation)


def write_mapping(mapping: Mapping, path: str) -> None:
    """Render a Mapping as a workbook at `path` (overwrites)."""
    workbook = Workbook()

    sheet = workbook.active
    sheet.title = "Mapping"
    _style_header(sheet, ("Field", "Value", "Help"), (22, 80, 70))
    for row, spec in enumerate(MAPPING_FIELDS, start=2):
        name_cell = sheet.cell(row=row, column=1, value=spec.name)
        name_cell.font = _FIELD_FONT
        name_cell.alignment = _WRAP
        value = mapping.get(spec.name)
        value_cell = sheet.cell(row=row, column=2, value=value or None)
        value_cell.alignment = _WRAP
        help_cell = sheet.cell(row=row, column=3, value=spec.help)
        help_cell.font = _HELP_FONT
        help_cell.alignment = _WRAP
        if spec.choices:
            validation = DataValidation(
                type="list",
                formula1='"{0}"'.format(",".join(spec.choices)),
                allow_blank=True,
                showErrorMessage=True,
                error="Pick one of: {0}".format(", ".join(spec.choices)),
            )
            validation.add("B{0}".format(row))
            sheet.add_data_validation(validation)

    for sheet_name, (headers, cls) in _TABLE_SHEETS.items():
        sheet = workbook.create_sheet(sheet_name)
        _style_header(sheet, headers, _WIDTHS[sheet_name])
        rows = getattr(mapping, _SHEET_ATTR[sheet_name])
        attrs = [f.name for f in fields(cls)]
        for row_index, row in enumerate(rows, start=2):
            for col_index, attr in enumerate(attrs, start=1):
                value = getattr(row, attr)
                cell = sheet.cell(row=row_index, column=col_index, value=value or None)
                cell.alignment = _WRAP
        last_row = len(rows) + 1 + _EMPTY_ROWS
        for header, choices in _DROPDOWNS.get(sheet_name, {}).items():
            _add_dropdown(sheet, headers.index(header) + 1, choices, 2, last_row)

    how_to = workbook.create_sheet("How_To")
    how_to.column_dimensions["A"].width = 110
    for index, line in enumerate(HOW_TO, start=1):
        cell = how_to.cell(row=index, column=1, value=line)
        cell.font = Font(bold=True) if index == 1 else Font(name="Consolas")

    meta = workbook.create_sheet("_meta")
    meta.append(("Format_Version", FORMAT_VERSION))
    meta.append(("Note", "Written by tools/mapping_spec/workbook_format.py. Do not edit this sheet."))
    meta.sheet_state = "hidden"

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    workbook.save(path)


# ---------------------------------------------------------------------------
# Locating workbooks
# ---------------------------------------------------------------------------


def mapping_folder_name(mapping_id: str) -> str:
    """The folder a mapping lives in: its Mapping_ID without the M_ prefix,
    in lower case. M_LOAN_LIMIT_DAILY -> loan_limit_daily."""
    name = mapping_id.strip()
    if name.upper().startswith("M_"):
        name = name[2:]
    name = name.lower()
    if not name:
        raise ValueError("Mapping_ID '{0}' gives an empty folder name".format(mapping_id))
    return name


def mapping_path(mapping_id: str, spec_dir: str = SPEC_DIR) -> str:
    """specs/<folder>/<MAPPING_ID>.xlsx - see mapping_folder_name."""
    return os.path.join(spec_dir, mapping_folder_name(mapping_id), "{0}.xlsx".format(mapping_id))


def resolve_mapping_path(arg: str, spec_dir: str = SPEC_DIR) -> str:
    """Accept a Mapping_ID or a path to a workbook."""
    if arg.lower().endswith(".xlsx") or os.path.sep in arg or "/" in arg:
        return os.path.abspath(arg)
    return mapping_path(arg, spec_dir)


def list_mapping_paths(spec_dir: str = SPEC_DIR) -> list:
    """Every workbook one level down, in a mapping folder under spec_dir
    (specs/<folder>/*.xlsx), skipping Excel lock files.
    A workbook in the wrong folder or with the wrong name is still listed, so
    that validation reports it instead of silently ignoring it."""
    if not os.path.isdir(spec_dir):
        return []
    paths = []
    for folder in os.listdir(spec_dir):
        folder_path = os.path.join(spec_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        paths.extend(
            os.path.join(folder_path, name)
            for name in os.listdir(folder_path)
            if name.lower().endswith(".xlsx") and not name.startswith("~$")
        )
    return sorted(paths)
