"""The analyst's change-request workbooks: Requirements and Gap Analysis.

A change request (CR) is worked on in its own folder,
``change-requests/<CR_ID>/``. Two of its documents are Excel workbooks that
this module reads, writes and validates:

  <CR_ID>_Requirements.xlsx   ba-1: requirements, KPIs, dimensions, business
                              rules, the data the KPIs need, proposed glossary
                              changes
  <CR_ID>_Gap_Analysis.xlsx   ba-2: where every required input is available
                              today, what has to change, and the load plan
                              (one mapping per target table)

(The delivery agreement changes are Word documents: delivery_agreement.py.)

The same rules as for mapping workbooks apply:

- An AI assistant never edits cells. It writes the document as JSON and
  ``cr.py write`` renders the workbook, so the layout, dropdowns and
  approval rules are always the same.
- Only a named person approves, in Excel (Document sheet: Status = approved,
  Approved_By, Approved_On). The writer refuses to record an approval and
  drops an existing one when the content changes.
- One file per document, updated in place. Every content change adds a row to
  the Change_Log sheet with a new revision number; git keeps every earlier
  state. (Baseline documents owned by others - delivery agreements, the
  glossary, the S2T baseline - are never changed in place: a change is a new
  file with a new version, see delivery_agreement.py.)
- ``Based_On`` records the fingerprint of the approved document this one was
  built from (the gap analysis is built from the requirements). When that
  document changes, this one has to be reviewed and approved again.

Needs openpyxl (see requirements.txt). No database is involved.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
from dataclasses import dataclass, field

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
except ImportError as exc:  # pragma: no cover - guidance path only
    raise ImportError("openpyxl is required: pip install -r requirements.txt") from exc

FORMAT_VERSION = 1
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CR_DIR_ENV = "UBB_CR_DIR"

VALID_STATUSES = ("draft", "in_review", "approved")
AI_WRITABLE_STATUSES = ("draft", "in_review")
APPROVAL_FIELDS = ("Status", "Approved_By", "Approved_On")
# Written by the tool, never by hand; not part of the content.
TOOL_FIELDS = ("Revision",)
CR_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TODO_PATTERN = re.compile(r"\bTODO\b")
# An AI proposal the analyst has not yet accepted (by removing the prefix) or replaced.
SUGGESTION_PATTERN = re.compile(r"\bSUGGESTION:")


def cr_root() -> str:
    """change-requests/ (or UBB_CR_DIR, for tests)."""
    return os.environ.get(CR_DIR_ENV) or os.path.join(REPO_ROOT, "change-requests")


def cr_folder(cr_id: str) -> str:
    return os.path.join(cr_root(), cr_id)


# ---------------------------------------------------------------------------
# Layout: what a document type consists of
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Col:
    name: str
    help: str
    choices: tuple = ()
    required: bool = False
    width: int = 28


@dataclass(frozen=True)
class SheetSpec:
    name: str  # the Excel sheet name; its JSON key is the lower-case name
    help: str
    columns: tuple
    id_column: str = ""
    id_prefix: str = ""

    @property
    def key(self) -> str:
        return self.name.lower()

    @property
    def column_names(self) -> tuple:
        return tuple(c.name for c in self.columns)


@dataclass(frozen=True)
class FieldSpec:
    name: str
    help: str
    multiline: bool = False
    choices: tuple = ()


@dataclass(frozen=True)
class DocType:
    key: str
    title: str
    file_suffix: str
    built_from: str  # the document type Based_On refers to, or ""
    sheets: tuple


DOCUMENT_FIELDS = (
    FieldSpec("CR_ID", "The change request, e.g. CR-ECB-001. Equals the folder name under change-requests/."),
    FieldSpec("Document_Type", "Written by the tool."),
    FieldSpec("Title", "One line: what this document is about."),
    FieldSpec("Status", "draft -> in_review -> approved. Only a named person sets approved.", choices=VALID_STATUSES),
    FieldSpec("Owner", "The analyst accountable for this document. Filled in by a person, never by an AI."),
    FieldSpec("Approved_By", "Name of the person who approved it. Never filled in by an AI."),
    FieldSpec("Approved_On", "Approval date, YYYY-MM-DD."),
    FieldSpec("Revision", "Written by the tool: goes up by one with every content change (see Change_Log)."),
    FieldSpec("Based_On", "Written by the tool: fingerprint of the approved document this one was built from. "
                          "When that document changes, this one must be reviewed and approved again."),
    FieldSpec("Source_Documents", "Every file read to write this document, one per line.", multiline=True),
    FieldSpec("Summary", "What this document concludes, in a few sentences for a reviewer.", multiline=True),
)
DOCUMENT_FIELD_NAMES = tuple(f.name for f in DOCUMENT_FIELDS)

OPEN_QUESTIONS = SheetSpec(
    "Open_Questions",
    "Every question raised and its answer. An open question blocks approval.",
    (
        Col("ID", "Q-01, Q-02, ...", required=True, width=8),
        Col("Topic", "What it is about, e.g. KPI-02 or IN-07.", width=18),
        Col("Question", "The question, so that someone else can answer it.", required=True, width=60),
        Col("Ask_Whom", "Who can answer: business, risk methodology, source owner CBS_SIM, ...", width=22),
        Col("Answer", "The answer, once given.", width=50),
        Col("Decided_By", "Who answered. Filled in only when a person states it.", width=18),
        Col("Decided_On", "YYYY-MM-DD. Filled in only when a person states it.", width=12),
        Col("Status", "open or decided.", choices=("open", "decided"), required=True, width=10),
    ),
    id_column="ID", id_prefix="Q-",
)
SOURCES = SheetSpec(
    "Sources",
    "Where each finding came from: a file and the place in it (sheet and row, section, script).",
    (
        Col("Topic", "What the finding is about.", width=20),
        Col("Reference", "File and place, e.g. business-documents/UBB_...v3.0.xlsx, sheet CBS_SIM, CREDIT_CONVERSION_FACTOR.",
            required=True, width=60),
        Col("Finding", "What it says.", required=True, width=70),
    ),
)
CHANGE_LOG = SheetSpec(
    "Change_Log",
    "Written by the tool: one row per revision. Not part of the content.",
    (
        Col("Revision", "", width=10),
        Col("Written_On", "", width=12),
        Col("Change", "", width=80),
        Col("Fingerprint", "", width=18),
    ),
)

REQUIREMENTS = DocType(
    key="requirements",
    title="Requirements analysis",
    file_suffix="_Requirements.xlsx",
    built_from="",
    sheets=(
        SheetSpec(
            "Requirements",
            "One row per requirement of the change request, quoted from it.",
            (
                Col("Req_ID", "REQ-01, REQ-02, ...", required=True, width=9),
                Col("CR_Section", "Where in the change request, e.g. '3. Mandatory measures'.", width=22),
                Col("CR_Text", "The words of the change request, quoted.", required=True, width=55),
                Col("Requirement", "The requirement restated precisely, one testable statement.", required=True, width=55),
                Col("Kind", "explicit = the CR says it; interpretation = how UBB reads it; assumption = "
                            "not in the CR, needs a business decision.",
                    choices=("explicit", "interpretation", "assumption"), required=True, width=14),
                Col("Notes", "", width=40),
            ),
            id_column="Req_ID", id_prefix="REQ-",
        ),
        SheetSpec(
            "KPIs",
            "One row per measure the change request asks for.",
            (
                Col("KPI_ID", "KPI-01, ...", required=True, width=9),
                Col("Name", "Business name.", required=True, width=26),
                Col("Definition", "What it means, for a business reader.", required=True, width=50),
                Col("Formula", "The calculation in business terms, naming Input_IDs and Rule_IDs. Never an "
                               "invented regulatory formula: write 'SUGGESTION: ...' and ask.", required=True, width=50),
                Col("Grain", "One value per what? e.g. per loan per reporting date.", required=True, width=24),
                Col("Date_Rule", "Which dates the inputs must be valid for (effective dating).", width=30),
                Col("Currency_Rule", "Reporting currency and when amounts are converted.", width=28),
                Col("Aggregation", "How it adds up to coarser levels (sector, group): sum, not additive, ...", width=26),
                Col("Rounding", "Scale and rounding step.", width=16),
                Col("Exceptions", "Missing or invalid inputs: what happens.", width=40),
                Col("Input_IDs", "Inputs it needs (Required_Data), comma separated.", required=True, width=18),
                Col("Req_IDs", "Requirements it serves, comma separated.", required=True, width=14),
                Col("Glossary_Ref", "Glossary attribute or calculation ID (e.g. AT-050, CR-002), or 'new'.", width=14),
                Col("Notes", "", width=30),
            ),
            id_column="KPI_ID", id_prefix="KPI-",
        ),
        SheetSpec(
            "Dimensions",
            "One row per reporting dimension (what results are analysed by).",
            (
                Col("Dim_ID", "DIM-01, ...", required=True, width=9),
                Col("Name", "", required=True, width=24),
                Col("Definition", "", required=True, width=50),
                Col("Key", "What identifies one member, e.g. NACE code, connected-client group reference.", width=26),
                Col("Effective_Dating", "Which version applies on a reporting date.", width=30),
                Col("Input_IDs", "Inputs it needs (Required_Data), comma separated.", required=True, width=18),
                Col("Req_IDs", "", required=True, width=14),
                Col("Glossary_Ref", "", width=14),
                Col("Notes", "", width=30),
            ),
            id_column="Dim_ID", id_prefix="DIM-",
        ),
        SheetSpec(
            "Business_Rules",
            "Rules the KPIs depend on: eligibility, valuation freshness, allocation, haircut order, caps, "
            "missing data. A rule nobody has decided yet is written 'SUGGESTION: ...' (or TODO if there is "
            "no proposal) and has an open question.",
            (
                Col("Rule_ID", "BR-01, ...", required=True, width=9),
                Col("Topic", "", width=22),
                Col("Rule", "The rule, precisely.", required=True, width=60),
                Col("Applies_To", "KPI_IDs / Dim_IDs, comma separated.", required=True, width=18),
                Col("Req_IDs", "", required=True, width=14),
                Col("Notes", "", width=30),
            ),
            id_column="Rule_ID", id_prefix="BR-",
        ),
        SheetSpec(
            "Required_Data",
            "Every business input the KPIs, dimensions and rules need. The gap analysis (ba-2) finds each one.",
            (
                Col("Input_ID", "IN-01, ...", required=True, width=9),
                Col("Business_Attribute", "Business name, e.g. Regulatory haircut.", required=True, width=28),
                Col("Definition", "", required=True, width=50),
                Col("Needed_For", "KPI_IDs / Dim_IDs / Rule_IDs, comma separated.", required=True, width=18),
                Col("Glossary_Ref", "Glossary attribute ID (AT-024) or 'new'.", width=14),
                Col("Date_Rule", "Which value counts on a reporting date.", width=30),
                Col("Notes", "", width=30),
            ),
            id_column="Input_ID", id_prefix="IN-",
        ),
        SheetSpec(
            "Glossary_Changes",
            "Glossary changes decided by this change request. The glossary itself is not changed here: "
            "/ba-3-specify-baseline-changes writes them as a new glossary version once the gap analysis is "
            "approved.",
            (
                Col("Change_ID", "GC-01, ...", required=True, width=9),
                Col("Change_Type", "", choices=("new_entity", "new_attribute", "changed_definition",
                                                "new_relationship", "new_dq_rule", "changed_dq_rule",
                                                "new_calculation", "changed_calculation"),
                    required=True, width=18),
                Col("Glossary_Ref", "The existing glossary ID it changes (EN-011, AT-050, DQ-006, CR-002); "
                                    "empty for something new.", width=14),
                Col("Entity", "Business entity.", required=True, width=20),
                Col("Name", "Attribute, rule or relationship name.", required=True, width=26),
                Col("Proposed_Text", "The proposed glossary text.", required=True, width=60),
                Col("Req_IDs", "", required=True, width=14),
                Col("Notes", "", width=30),
            ),
            id_column="Change_ID", id_prefix="GC-",
        ),
        OPEN_QUESTIONS,
        SOURCES,
    ),
)

GAP_LEVELS = ("in_core", "in_staging", "in_interface", "in_source", "not_in_source", "conflict")
GAP_ACTIONS = ("none", "mapping", "staging_change", "delivery_change", "new_delivery", "source_owner", "clarify")
# Which actions fit which level, and which location column a level must fill.
LEVEL_ACTIONS = {
    "in_core": ("none", "mapping"),
    "in_staging": ("mapping",),
    "in_interface": ("staging_change",),
    "in_source": ("delivery_change", "new_delivery"),
    "not_in_source": ("source_owner",),
    "conflict": ("clarify",),
}
LEVEL_LOCATION = {
    "in_core": ("Core_Location",),
    "in_staging": ("Staging_Location",),
    # in_interface: Staging_Location is the column staging will get (dev-1 adds it)
    "in_interface": ("Interface_Location", "Staging_Location"),
    "in_source": ("Source_Location",),
}

GAP_ANALYSIS = DocType(
    key="gap_analysis",
    title="Gap analysis and load plan",
    file_suffix="_Gap_Analysis.xlsx",
    built_from="requirements",
    sheets=(
        SheetSpec(
            "Gaps",
            "One row per required input (Required_Data of the requirements): where it is available today and "
            "what has to change.",
            (
                Col("Input_ID", "From the requirements' Required_Data.", required=True, width=9),
                Col("Business_Attribute", "", width=26),
                Col("Level", "in_core = a CORE table has it and a load fills it; in_staging = a staging table "
                             "has it, CORE does not; in_interface = the delivery agreement delivers it, staging "
                             "does not; in_source = the source system has it, the interface does not; "
                             "not_in_source = no source system has it; conflict = the documents disagree.",
                    choices=GAP_LEVELS, required=True, width=14),
                Col("Core_Location", "SCHEMA.TABLE.COLUMN in sql/.", width=34),
                Col("Staging_Location", "SCHEMA.TABLE.COLUMN in sql/; for in_interface the column staging "
                                        "will get: UBB_STAGING2.STG_<ENTITY>.ATTRIBUTE.", width=34),
                Col("Interface_Location", "Delivery agreement file, version and section, e.g. CBS_SIM v1.0 3.3 "
                                          "COLLATERAL.", width=30),
                Col("Source_Location", "SYSTEM / Entity / ATTRIBUTE from the source catalog.", width=34),
                Col("Action", "none, mapping (ba-4), staging_change (dev-1), delivery_change / new_delivery "
                              "(ba-3), source_owner (the analyst takes it to the source owner; no skill follows "
                              "it up), clarify (correct the documents first).",
                    choices=GAP_ACTIONS, required=True, width=16),
                Col("Mapping_IDs", "Load_Plan mappings that use it, comma separated.", width=24),
                Col("Responsible", "A role, never a name: business, CBS_SIM source owner, ...", width=22),
                Col("Status", "open = not decided; decided = the action is agreed; tracked = handed to the "
                              "source owner (not_in_source only). An open row blocks approval.",
                    choices=("open", "decided", "tracked"), required=True, width=10),
                Col("Notes", "", width=40),
            ),
            id_column="Input_ID", id_prefix="IN-",
        ),
        SheetSpec(
            "Load_Plan",
            "One row per mapping (one target table each) the change request needs, in load order.",
            (
                Col("Dependency_Order", "Dependency level: 1, 2, 3 ... A mapping has a higher Dependency_Order than every mapping it depends on (reads the table of); the same Dependency_Order means independent. It is the sequence in which the mappings are specified (ba-4) and their loads deployed and run.", required=True, width=7),
                Col("Mapping_ID", "M_..., one per target table.", required=True, width=30),
                Col("Target_Table", "SCHEMA.TABLE.", required=True, width=34),
                Col("Change", "new_table, new_columns (existing table), new_load (existing table without a "
                              "mapping), changed_load.",
                    choices=("new_table", "new_columns", "new_load", "changed_load"), required=True, width=14),
                Col("Grain", "One row per what?", required=True, width=30),
                Col("Purpose", "What it computes and why.", required=True, width=50),
                Col("Depends_On", "Mapping_IDs that must load first, comma separated, or empty.", width=30),
                Col("Input_IDs", "", width=20),
                Col("Req_IDs", "", required=True, width=14),
                Col("Notes", "", width=30),
            ),
            id_column="Mapping_ID", id_prefix="M_",
        ),
        OPEN_QUESTIONS,
        SOURCES,
    ),
)

DOC_TYPES = {d.key: d for d in (REQUIREMENTS, GAP_ANALYSIS)}


# ---------------------------------------------------------------------------
# The document object
# ---------------------------------------------------------------------------


def _norm(value) -> str:
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


def split_ids(text: str) -> list:
    return [p.strip().upper() for p in re.split(r"[,;\n]", text or "") if p.strip()]


@dataclass
class Document:
    doc_type: DocType
    fields: dict = field(default_factory=dict)
    rows: dict = field(default_factory=dict)  # sheet key -> [ {column: value} ]
    change_log: list = field(default_factory=list)
    path: str = ""

    def get(self, name: str) -> str:
        return self.fields.get(name, "")

    @property
    def cr_id(self) -> str:
        return self.get("CR_ID")

    @property
    def status(self) -> str:
        return self.get("Status").lower()

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def revision(self) -> int:
        try:
            return int(self.get("Revision") or 0)
        except ValueError:
            return 0

    def sheet(self, key: str) -> list:
        return self.rows.get(key, [])

    def ids(self, key: str) -> list:
        spec = next(s for s in self.doc_type.sheets if s.key == key)
        return [r.get(spec.id_column, "").upper() for r in self.sheet(key) if r.get(spec.id_column)]

    def content(self) -> dict:
        """Everything that is content: no approval fields, no tool fields."""
        data = {"document": {k: v for k, v in self.fields.items()
                             if k not in APPROVAL_FIELDS and k not in TOOL_FIELDS and v}}
        for spec in self.doc_type.sheets:
            data[spec.key] = [{k: v for k, v in r.items() if v} for r in self.sheet(spec.key)]
        return data

    def fingerprint(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        data = {"document": {name: self.get(name) for name in DOCUMENT_FIELD_NAMES}}
        for spec in self.doc_type.sheets:
            data[spec.key] = [{c: r.get(c, "") for c in spec.column_names} for r in self.sheet(spec.key)]
        return data


def from_dict(data: dict, doc_type: DocType = None) -> Document:
    """Build a Document from its JSON form. Unknown keys are an error, so a
    typo never disappears silently."""
    if not isinstance(data, dict) or not isinstance(data.get("document"), dict):
        raise ValueError("the JSON must be an object with a 'document' object")
    header = {k: _norm(v) for k, v in data["document"].items()}
    type_key = (doc_type.key if doc_type else header.get("Document_Type", "")).strip().lower()
    if type_key not in DOC_TYPES:
        raise ValueError("document.Document_Type must be one of: {0}".format(", ".join(DOC_TYPES)))
    doc_type = DOC_TYPES[type_key]
    unknown = sorted(set(header) - set(DOCUMENT_FIELD_NAMES))
    if unknown:
        raise ValueError("unknown document field(s): {0}".format(", ".join(unknown)))
    header["Document_Type"] = doc_type.key
    allowed = {s.key for s in doc_type.sheets} | {"document", "change_note"}
    extra = sorted(set(data) - allowed)
    if extra:
        raise ValueError("unknown section(s) for {0}: {1} (allowed: {2})".format(
            doc_type.key, ", ".join(extra), ", ".join(sorted(allowed - {"document"}))))
    rows = {}
    for spec in doc_type.sheets:
        items = data.get(spec.key) or []
        if not isinstance(items, list):
            raise ValueError("{0} must be a list of rows".format(spec.key))
        parsed = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise ValueError("{0} row {1} must be an object".format(spec.key, index))
            bad = sorted(set(item) - set(spec.column_names))
            if bad:
                raise ValueError("{0} row {1}: unknown column(s) {2} (columns: {3})".format(
                    spec.key, index, ", ".join(bad), ", ".join(spec.column_names)))
            parsed.append({c: _norm(item.get(c)) for c in spec.column_names})
        rows[spec.key] = parsed
    return Document(doc_type=doc_type, fields=header, rows=rows)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def document_path(cr_id: str, doc_type: DocType) -> str:
    return os.path.join(cr_folder(cr_id), cr_id + doc_type.file_suffix)


def find_document(cr_id: str, type_key: str):
    """The Document of that type for the CR, or None when it does not exist."""
    path = document_path(cr_id, DOC_TYPES[type_key])
    return read_document(path) if os.path.exists(path) else None


def list_cr_ids() -> list:
    root = cr_root()
    if not os.path.isdir(root):
        return []
    return sorted(name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name)))


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_FIELD_FONT = Font(bold=True)
_HELP_FONT = Font(italic=True, color="666666")
_WRAP = Alignment(wrap_text=True, vertical="top")
_EMPTY_ROWS = 30


def _style_header(sheet, columns) -> None:
    for index, col in enumerate(columns, start=1):
        cell = sheet.cell(row=1, column=index, value=col.name)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        sheet.column_dimensions[cell.column_letter].width = col.width
        if col.help:
            from openpyxl.comments import Comment
            cell.comment = Comment(col.help, "format")
    sheet.freeze_panes = "A2"


def _dropdown(sheet, column_index: int, choices, last_row: int) -> None:
    letter = sheet.cell(row=1, column=column_index).column_letter
    validation = DataValidation(type="list", formula1='"{0}"'.format(",".join(choices)), allow_blank=True,
                                showErrorMessage=True, error="Pick one of: {0}".format(", ".join(choices)))
    validation.add("{0}2:{0}{1}".format(letter, last_row))
    sheet.add_data_validation(validation)


def how_to(doc_type: DocType) -> list:
    lines = ["How to read and approve this {0}".format(doc_type.title.lower()), ""]
    lines += ["Document sheet: one value per field. Revision, Based_On and Document_Type are written by the tool."]
    for spec in doc_type.sheets:
        lines.append("{0} sheet: {1}".format(spec.name, spec.help))
    lines += [
        "Change_Log sheet: one row per revision, written by the tool.",
        "",
        "Hover over a column header to see what belongs in it.",
        "",
        "APPROVAL: when the content is complete, the approving person sets, on the Document sheet,",
        "Status = approved, Approved_By = their own name, Approved_On = YYYY-MM-DD.",
        "An AI assistant never does this. Any later content change drops the approval again.",
        "Check with:  python tools/change_request/cr.py validate",
    ]
    return lines


def write_document(document: Document, path: str) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Document"
    header_cols = (Col("Field", "", width=20), Col("Value", "", width=80), Col("Help", "", width=70))
    _style_header(sheet, header_cols)
    for row, spec in enumerate(DOCUMENT_FIELDS, start=2):
        sheet.cell(row=row, column=1, value=spec.name).font = _FIELD_FONT
        value_cell = sheet.cell(row=row, column=2, value=document.get(spec.name) or None)
        value_cell.alignment = _WRAP
        help_cell = sheet.cell(row=row, column=3, value=spec.help)
        help_cell.font = _HELP_FONT
        help_cell.alignment = _WRAP
        if spec.choices:
            validation = DataValidation(type="list", formula1='"{0}"'.format(",".join(spec.choices)),
                                        allow_blank=True, showErrorMessage=True)
            validation.add("B{0}".format(row))
            sheet.add_data_validation(validation)

    for spec in document.doc_type.sheets + (CHANGE_LOG,):
        sheet = workbook.create_sheet(spec.name)
        _style_header(sheet, spec.columns)
        rows = document.change_log if spec is CHANGE_LOG else document.sheet(spec.key)
        for row_index, row in enumerate(rows, start=2):
            for col_index, name in enumerate(spec.column_names, start=1):
                value = row.get(name, "")
                if name in ("Dependency_Order", "Revision") and value.isdigit():
                    value = int(value)
                cell = sheet.cell(row=row_index, column=col_index, value=value if value != "" else None)
                cell.alignment = _WRAP
        if spec is not CHANGE_LOG:
            last = len(rows) + 1 + _EMPTY_ROWS
            for index, col in enumerate(spec.columns, start=1):
                if col.choices:
                    _dropdown(sheet, index, col.choices, last)

    guide = workbook.create_sheet("How_To")
    guide.column_dimensions["A"].width = 120
    for index, line in enumerate(how_to(document.doc_type), start=1):
        cell = guide.cell(row=index, column=1, value=line)
        cell.font = Font(bold=True) if index == 1 else Font(name="Consolas")

    meta = workbook.create_sheet("_meta")
    meta.append(("Format_Version", FORMAT_VERSION))
    meta.append(("Document_Type", document.doc_type.key))
    meta.append(("Note", "Written by tools/change_request/ba_documents.py. Do not edit this sheet."))
    meta.sheet_state = "hidden"

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    workbook.save(path)


def _read_rows(sheet, spec: SheetSpec) -> list:
    rows = sheet.iter_rows(values_only=True)
    header = [_norm(c) for c in (next(rows, None) or ())]
    if spec.key == "load_plan":
        # workbooks written before the rename still have the old header
        header = ["Dependency_Order" if h == "Order" else h for h in header]
    positions = {name: header.index(name) for name in spec.column_names if name in header}
    result = []
    for row in rows:
        item = {name: _norm(row[i]) if i < len(row) else "" for name, i in positions.items()}
        for name in spec.column_names:
            item.setdefault(name, "")
        if any(item.values()):
            result.append(item)
    return result


def read_document(path: str) -> Document:
    workbook = load_workbook(path, read_only=True, data_only=True)
    names = workbook.sheetnames
    if "Document" not in names or "_meta" not in names:
        raise ValueError("{0} is not a change-request document (no Document and _meta sheets)".format(path))
    meta = {_norm(r[0]): _norm(r[1]) for r in workbook["_meta"].iter_rows(values_only=True) if r and r[0]}
    type_key = meta.get("Document_Type", "")
    if type_key not in DOC_TYPES:
        raise ValueError("{0}: unknown Document_Type '{1}'".format(path, type_key))
    doc_type = DOC_TYPES[type_key]
    fields = {}
    for row in workbook["Document"].iter_rows(min_row=2, values_only=True):
        if row and row[0]:
            fields[_norm(row[0])] = _norm(row[1] if len(row) > 1 else "")
    fields["Document_Type"] = doc_type.key
    rows = {spec.key: (_read_rows(workbook[spec.name], spec) if spec.name in names else [])
            for spec in doc_type.sheets}
    log = _read_rows(workbook[CHANGE_LOG.name], CHANGE_LOG) if CHANGE_LOG.name in names else []
    workbook.close()
    return Document(doc_type=doc_type, fields=fields, rows=rows, change_log=log, path=os.path.abspath(path))


# ---------------------------------------------------------------------------
# Approval rules - shared with delivery_agreement.py
# ---------------------------------------------------------------------------


class WriteRefused(Exception):
    pass


def approval_decision(existing, new_status: str, new_approved_by: str, new_approved_on: str,
                      new_fingerprint: str) -> tuple:
    """The approval rules every analyst document follows.

    existing: (status, approved_by, approved_on, fingerprint) of the file on
    disk, or None. Returns (status, approved_by, approved_on, message) to
    write. Raises WriteRefused when the writer is asked to record an approval.
    """
    wants_approval = new_status == "approved" or new_approved_by or new_approved_on
    unchanged = existing is not None and existing[3] == new_fingerprint
    if wants_approval:
        same = existing is not None and (existing[0], existing[1], existing[2]) == (
            new_status, new_approved_by, new_approved_on)
        if existing is not None and existing[0] == "approved" and unchanged and same:
            return new_status, new_approved_by, new_approved_on, \
                "Content unchanged; existing approval by {0} kept.".format(existing[1])
        raise WriteRefused(
            "this tool never records an approval. Set Status to draft or in_review and leave "
            "Approved_By/Approved_On empty; the approving person sets them in the document.")
    status = new_status or "draft"
    if status not in AI_WRITABLE_STATUSES:
        raise WriteRefused("Status must be one of {0}.".format(", ".join(AI_WRITABLE_STATUSES)))
    message = ""
    if existing is not None and existing[0] == "approved":
        if unchanged:
            message = "NOTE: content is unchanged but Status was set to {0}; the approval by {1} is withdrawn.".format(
                status, existing[1])
        else:
            message = ("Content changed, so the approval by {0} on {1} is dropped: Status is now {2}. "
                       "A named person must approve the new content again.".format(existing[1], existing[2], status))
    return status, "", "", message


def write_from_dict(data: dict, today: _dt.date = None) -> tuple:
    """Write a Requirements or Gap Analysis workbook from its JSON form.
    Returns (Document, [messages]). Raises ValueError / WriteRefused."""
    today = today or _dt.date.today()
    new = from_dict(data)
    if not CR_ID_PATTERN.match(new.cr_id):
        raise ValueError("document.CR_ID must look like CR-ECB-001 (upper case, hyphen separated); got "
                         "'{0}'".format(new.cr_id))
    path = document_path(new.cr_id, new.doc_type)
    new.path = path
    existing = read_document(path) if os.path.exists(path) else None

    messages = []
    if new.doc_type.built_from:
        upstream = find_document(new.cr_id, new.doc_type.built_from)
        if upstream is None or not upstream.is_approved:
            raise WriteRefused("the {0} of {1} is not approved yet; it must be approved before this "
                               "document is written (python tools/change_request/cr.py status {1})".format(
                                   DOC_TYPES[new.doc_type.built_from].title.lower(), new.cr_id))
        new.fields["Based_On"] = upstream.fingerprint()
    else:
        new.fields["Based_On"] = ""

    new_fp = new.fingerprint()
    old = None
    if existing is not None:
        old = (existing.status, existing.get("Approved_By"), existing.get("Approved_On"), existing.fingerprint())
    status, by, on, message = approval_decision(
        old, new.status, new.get("Approved_By"), new.get("Approved_On"), new_fp)
    new.fields.update({"Status": status, "Approved_By": by, "Approved_On": on})
    if message:
        messages.append(message)

    note = _norm(data.get("change_note"))
    log = list(existing.change_log) if existing is not None else []
    revision = existing.revision if existing is not None else 0
    if existing is None or existing.fingerprint() != new_fp:
        if existing is not None and not note:
            raise ValueError("the content changed: say what and why in a top-level \"change_note\" "
                             "(it goes on the Change_Log sheet)")
        revision += 1
        log.append({"Revision": str(revision), "Written_On": today.isoformat(),
                    "Change": note or "First version.", "Fingerprint": new_fp})
    new.fields["Revision"] = str(revision)
    new.change_log = log
    write_document(new, path)
    return new, messages


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def merge(self, other: "Report") -> None:
        self.errors += other.errors
        self.warnings += other.warnings


def _check_sheet_rows(document: Document, spec: SheetSpec, report: Report, where: str) -> None:
    seen = set()
    for index, row in enumerate(document.sheet(spec.key), start=1):
        label = "{0} {1} row {2}".format(where, spec.name, index)
        if spec.id_column:
            ident = row.get(spec.id_column, "").upper()
            if ident:
                label = "{0} {1} {2}".format(where, spec.name, ident)
                if spec.id_prefix and not ident.startswith(spec.id_prefix):
                    report.errors.append("{0}: {1} must start with {2}".format(label, spec.id_column, spec.id_prefix))
                if ident in seen:
                    report.errors.append("{0}: {1} is used twice".format(label, spec.id_column))
                seen.add(ident)
        for col in spec.columns:
            value = row.get(col.name, "")
            if col.required and not value:
                report.errors.append("{0}: {1} is empty".format(label, col.name))
            if value and col.choices and value not in col.choices:
                report.errors.append("{0}: {1} '{2}' is not one of {3}".format(
                    label, col.name, value, ", ".join(col.choices)))


def _refs(document: Document, key: str, column: str, allowed: set, report: Report, where: str,
          id_column: str) -> None:
    for row in document.sheet(key):
        for ref in split_ids(row.get(column, "")):
            if ref not in allowed:
                report.errors.append("{0} {1} {2}: {3} names {4}, which does not exist".format(
                    where, key, row.get(id_column, "?"), column, ref))


def _has_cycle(edges: dict) -> list:
    state = {}
    path = []

    def visit(node):
        state[node] = "busy"
        path.append(node)
        for nxt in edges.get(node, ()):
            if state.get(nxt) == "busy":
                return path[path.index(nxt):] + [nxt]
            if nxt not in state:
                found = visit(nxt)
                if found:
                    return found
        path.pop()
        state[node] = "done"
        return []

    for node in edges:
        if node not in state:
            found = visit(node)
            if found:
                return found
    return []


def validate_document(document: Document, upstream: Document = None) -> Report:
    """Check one document. `upstream` is the document it is built from (the
    requirements, for a gap analysis); without it the cross-checks are skipped."""
    report = Report()
    where = os.path.basename(document.path) if document.path else document.doc_type.key
    if not CR_ID_PATTERN.match(document.cr_id):
        report.errors.append("{0}: CR_ID '{1}' must look like CR-ECB-001".format(where, document.cr_id))
    elif document.path:
        expected = document_path(document.cr_id, document.doc_type)
        if os.path.normcase(os.path.abspath(expected)) != os.path.normcase(document.path):
            report.errors.append("{0}: a {1} of {2} belongs at {3}".format(
                where, document.doc_type.key, document.cr_id, _rel(expected)))
    if document.status not in VALID_STATUSES:
        report.errors.append("{0}: Status '{1}' is not one of {2}".format(
            where, document.get("Status"), ", ".join(VALID_STATUSES)))
    for spec in document.doc_type.sheets:
        _check_sheet_rows(document, spec, report, where)

    if document.doc_type is REQUIREMENTS:
        _validate_requirements(document, report, where)
    else:
        _validate_gap_analysis(document, upstream, report, where)

    if document.is_approved:
        if not document.get("Approved_By"):
            report.errors.append("{0}: approved but Approved_By is empty".format(where))
        if not DATE_PATTERN.match(document.get("Approved_On")):
            report.errors.append("{0}: approved but Approved_On is not a YYYY-MM-DD date".format(where))
        open_questions = [q.get("ID") for q in document.sheet("open_questions") if q.get("Status") != "decided"]
        if open_questions:
            report.errors.append("{0}: approved with open question(s) {1}".format(where, ", ".join(open_questions)))
        todo = _todo_cells(document)
        if todo:
            report.errors.append("{0}: approved but still has TODO in {1}".format(where, ", ".join(todo[:5])))
        suggestions = _suggestion_cells(document)
        if suggestions:
            report.errors.append("{0}: approved but still has an unaccepted SUGGESTION: in {1} - accept it "
                                 "(remove the prefix) or replace it".format(where, ", ".join(suggestions[:5])))
    if upstream is not None and document.doc_type.built_from:
        if document.get("Based_On") != upstream.fingerprint():
            report.errors.append(
                "{0}: built from an earlier version of {1} (Based_On {2}, now {3}). Rewrite it from the "
                "current version and have it approved again.".format(
                    where, os.path.basename(upstream.path) or upstream.doc_type.key,
                    document.get("Based_On") or "-", upstream.fingerprint()))
        if not upstream.is_approved:
            report.errors.append("{0}: {1} is no longer approved".format(
                where, os.path.basename(upstream.path) or upstream.doc_type.key))
    return report


def _todo_cells(document: Document) -> list:
    return _cells_matching(document, TODO_PATTERN)


def _suggestion_cells(document: Document) -> list:
    return _cells_matching(document, SUGGESTION_PATTERN)


def _cells_matching(document: Document, pattern) -> list:
    found = [name for name, value in document.fields.items() if pattern.search(value)]
    for spec in document.doc_type.sheets:
        for index, row in enumerate(document.sheet(spec.key), start=1):
            for name, value in row.items():
                if pattern.search(value):
                    found.append("{0} row {1} {2}".format(spec.name, index, name))
    return found


def _validate_requirements(document: Document, report: Report, where: str) -> None:
    reqs = set(document.ids("requirements"))
    kpis = set(document.ids("kpis"))
    dims = set(document.ids("dimensions"))
    rules = set(document.ids("business_rules"))
    inputs = set(document.ids("required_data"))
    _refs(document, "kpis", "Req_IDs", reqs, report, where, "KPI_ID")
    _refs(document, "kpis", "Input_IDs", inputs, report, where, "KPI_ID")
    _refs(document, "dimensions", "Req_IDs", reqs, report, where, "Dim_ID")
    _refs(document, "dimensions", "Input_IDs", inputs, report, where, "Dim_ID")
    _refs(document, "business_rules", "Req_IDs", reqs, report, where, "Rule_ID")
    _refs(document, "business_rules", "Applies_To", kpis | dims, report, where, "Rule_ID")
    _refs(document, "required_data", "Needed_For", kpis | dims | rules, report, where, "Input_ID")
    _refs(document, "glossary_changes", "Req_IDs", reqs, report, where, "Change_ID")
    used = set()
    for key in ("kpis", "dimensions", "business_rules", "glossary_changes"):
        for row in document.sheet(key):
            used.update(split_ids(row.get("Req_IDs", "")))
    for req in sorted(reqs - used):
        report.warnings.append("{0}: {1} is not served by any KPI, dimension, rule or glossary change".format(
            where, req))
    needed = set()
    for key in ("kpis", "dimensions"):
        for row in document.sheet(key):
            needed.update(split_ids(row.get("Input_IDs", "")))
    for row in document.sheet("required_data"):
        needed_for = split_ids(row.get("Needed_For", ""))
        if any(x in rules for x in needed_for):
            needed.add(row.get("Input_ID", "").upper())
    for inp in sorted(inputs - needed):
        report.warnings.append("{0}: {1} is not needed by any KPI, dimension or rule".format(where, inp))


def _validate_gap_analysis(document: Document, upstream, report: Report, where: str) -> None:
    plan_ids = set(document.ids("load_plan"))
    for row in document.sheet("gaps"):
        ident = row.get("Input_ID", "?")
        level, action, status = row.get("Level"), row.get("Action"), row.get("Status")
        if level in LEVEL_ACTIONS and action and action not in LEVEL_ACTIONS[level]:
            report.errors.append("{0} Gaps {1}: Level {2} needs Action {3}, not {4}".format(
                where, ident, level, " or ".join(LEVEL_ACTIONS[level]), action))
        for column in LEVEL_LOCATION.get(level, ()):
            if not row.get(column):
                report.errors.append("{0} Gaps {1}: Level {2} needs {3}".format(where, ident, level, column))
        if status == "tracked" and level != "not_in_source":
            report.errors.append("{0} Gaps {1}: only a not_in_source input is 'tracked' (handed to the source "
                                 "owner); this one is {2}".format(where, ident, level))
        if level == "not_in_source" and status == "decided":
            report.errors.append("{0} Gaps {1}: a not_in_source input is 'tracked' once handed to the source "
                                 "owner, or 'open'".format(where, ident))
        if document.is_approved and status == "open":
            report.errors.append("{0} Gaps {1}: approved with this row still open".format(where, ident))
        if action == "mapping" and not row.get("Mapping_IDs"):
            report.errors.append("{0} Gaps {1}: Action mapping names no Load_Plan Mapping_IDs".format(where, ident))
    _refs(document, "gaps", "Mapping_IDs", plan_ids, report, where, "Input_ID")

    edges = {}
    orders = {}
    gap_inputs = set(document.ids("gaps"))
    for row in document.sheet("load_plan"):
        ident = row.get("Mapping_ID", "").upper()
        if ident and not re.match(r"^M_[A-Z0-9_]+$", ident):
            report.errors.append("{0} Load_Plan {1}: Mapping_ID must be M_ followed by upper-case letters, "
                                 "digits and _".format(where, ident))
        if row.get("Target_Table") and not re.match(r"^[A-Z0-9_$#]+\.[A-Z0-9_$#]+$", row["Target_Table"].upper()):
            report.errors.append("{0} Load_Plan {1}: Target_Table must be SCHEMA.TABLE".format(where, ident))
        try:
            orders[ident] = int(row.get("Dependency_Order") or "")
        except ValueError:
            report.errors.append("{0} Load_Plan {1}: Dependency_Order must be a whole number".format(where, ident))
        edges[ident] = split_ids(row.get("Depends_On", ""))
        for inp in split_ids(row.get("Input_IDs", "")):
            if inp not in gap_inputs:
                report.errors.append("{0} Load_Plan {1}: Input_IDs names {2}, which has no Gaps row".format(
                    where, ident, inp))
    for ident, deps in edges.items():
        for dep in deps:
            if dep not in edges:
                report.errors.append("{0} Load_Plan {1}: Depends_On names {2}, which is not in the plan".format(
                    where, ident, dep))
            elif ident in orders and dep in orders and orders[dep] >= orders[ident]:
                report.errors.append("{0} Load_Plan {1}: depends on {2}, so its Dependency_Order must be higher".format(
                    where, ident, dep))
    cycle = _has_cycle({k: [d for d in v if d in edges] for k, v in edges.items()})
    if cycle:
        report.errors.append("{0} Load_Plan: circular dependency {1}".format(where, " -> ".join(cycle)))
    targets = {}
    for row in document.sheet("load_plan"):
        target = row.get("Target_Table", "").upper()
        if target in targets:
            report.errors.append("{0} Load_Plan: {1} and {2} both load {3}; one mapping per target table".format(
                where, targets[target], row.get("Mapping_ID"), target))
        elif target:
            targets[target] = row.get("Mapping_ID")

    if upstream is not None:
        required = set(upstream.ids("required_data"))
        reqs = set(upstream.ids("requirements"))
        for inp in sorted(gap_inputs - required):
            report.errors.append("{0} Gaps {1}: not an input of the requirements' Required_Data".format(where, inp))
        for inp in sorted(required - gap_inputs):
            report.errors.append("{0}: required input {1} has no Gaps row".format(where, inp))
        _refs(document, "load_plan", "Req_IDs", reqs, report, where, "Mapping_ID")


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
    except ValueError:
        return path
