"""Business glossary versions: what a change request changes in the glossary.

The approved glossary is the workbook
``business-documents/UBB_Credit_Risk_Business_Glossary_v<VERSION>.xlsx``. It is
never changed. A change request decides its glossary changes in step 1 (the
Glossary_Changes sheet of the requirements) and writes them, in step 3, as a
NEW version of the glossary into its own folder:

    change-requests/<CR_ID>/UBB_Credit_Risk_Business_Glossary_v<VERSION>.xlsx

It is written only once the gap analysis is approved, so that every finding
of step 2 that changed a meaning has gone back into the requirements first.
The new version is the whole glossary, not a patch: every sheet and row of
the version it supersedes, with each added or changed row marked in a
``Change`` column and tied to the requirements' change (``Change_ID`` =
GC-..), and a ``Changes_In_This_Version`` sheet listing them.

An AI assistant never edits the workbook. It reads the current version as
JSON (``cr.py glossary-json``), changes the JSON, and ``cr.py write-glossary``
renders it. The approval rules are those of every analyst document
(ba_documents.py): only the glossary owner approves, in Excel, on the
Document sheet; a content change drops an approval. ``Based_On`` records the
requirements it was written from: when they change, this version must be
rewritten and approved again.

Needs openpyxl (see requirements.txt). No database is involved.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
from dataclasses import dataclass, field

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

import ba_documents
from ba_documents import (CR_ID_PATTERN, DATE_PATTERN, SUGGESTION_PATTERN, TODO_PATTERN, Report, WriteRefused,
                          approval_decision, split_ids)

REPO_ROOT = ba_documents.REPO_ROOT
BASELINE_ENV = "UBB_GLOSSARY_BASELINE_DIR"
FILE_PREFIX = "UBB_Credit_Risk_Business_Glossary"
FILE_PATTERN = re.compile(r"Business_Glossary_v(?P<major>\d+)\.(?P<minor>\d+)\.xlsx$", re.I)
VERSION_PATTERN = re.compile(r"^\d+\.\d+$")

# The glossary's content sheets; the first column of each is its ID (EN-001, AT-001, ...).
DATA_SHEETS = ("Entities", "Business Attributes", "Relationships", "Business DQ Rules", "Business Calculations")
# The column that names an entry, for the Changes_In_This_Version sheet.
NAME_COLUMN = {"Entities": "Business Entity", "Business Attributes": "Business Attribute",
               "Relationships": "Business Relationship", "Business DQ Rules": "Rule Name",
               "Business Calculations": "Business Measure / KPI"}
ABOUT_SHEET = "About"
CHANGE_COL = "Change"
CHANGE_ID_COL = "Change_ID"
ROW_CHANGES = ("", "added", "changed")
CHANGES_SHEET = "Changes_In_This_Version"
DOCUMENT_SHEET = "Document"
META_SHEET = "_meta"
DOCUMENT_TYPE = "glossary_version"

# The requirements' Glossary_Changes Change_Type -> the glossary sheet it lands on
# (None: any sheet) and the row marking it needs.
CHANGE_TYPES = {
    "new_entity": ("Entities", "added"),
    "new_attribute": ("Business Attributes", "added"),
    "changed_definition": (None, "changed"),
    "new_relationship": ("Relationships", "added"),
    "new_dq_rule": ("Business DQ Rules", "added"),
    "changed_dq_rule": ("Business DQ Rules", "changed"),
    "new_calculation": ("Business Calculations", "added"),
    "changed_calculation": ("Business Calculations", "changed"),
}

DOCUMENT_FIELDS = (
    ("CR_ID", "The change request that writes this version."),
    ("Version", "This version, e.g. 0.4."),
    ("Supersedes", "The approved version it replaces, e.g. 0.3."),
    ("Status", "draft -> in_review -> approved. Only the glossary owner sets approved."),
    ("Approved_By", "Name of the person who approved it. Never filled in by an AI."),
    ("Approved_On", "Approval date, YYYY-MM-DD."),
    ("Based_On", "Written by the tool: fingerprint of the requirements whose Glossary_Changes this version "
                 "applies. When they change, this version must be rewritten and approved again."),
)

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_ROW_FILL = {"added": PatternFill("solid", fgColor="E2EFDA"), "changed": PatternFill("solid", fgColor="FFF2CC")}
_WRAP = Alignment(wrap_text=True, vertical="top")


def baseline_dir() -> str:
    return os.environ.get(BASELINE_ENV) or os.path.join(REPO_ROOT, "business-documents")


# ---------------------------------------------------------------------------
# The glossary object
# ---------------------------------------------------------------------------


@dataclass
class Sheet:
    columns: list = field(default_factory=list)  # the glossary's own columns, without Change / Change_ID
    rows: list = field(default_factory=list)  # [ {column: value, "Change": .., "Change_ID": ..} ]

    @property
    def id_column(self) -> str:
        return self.columns[0] if self.columns else ""

    def row(self, row_id: str):
        return next((r for r in self.rows if r.get(self.id_column, "").upper() == row_id.upper()), None)


@dataclass
class Glossary:
    version: str = ""
    supersedes: str = ""
    cr_id: str = ""  # empty for an approved baseline in business-documents/
    status: str = ""
    approved_by: str = ""
    approved_on: str = ""
    based_on: str = ""
    sheets: dict = field(default_factory=dict)  # sheet name -> Sheet
    about: list = field(default_factory=list)  # [[topic, explanation]]
    path: str = ""

    @property
    def is_baseline(self) -> bool:
        return not self.cr_id

    @property
    def is_approved(self) -> bool:
        return self.is_baseline or self.status.lower() == "approved"

    def marked_rows(self) -> list:
        """(sheet name, row) for every added or changed row."""
        return [(name, row) for name in DATA_SHEETS for row in self.sheets.get(name, Sheet()).rows
                if row.get(CHANGE_COL)]

    def content(self) -> dict:
        """Everything that is content: no approval fields, no Based_On."""
        return {"version": self.version, "supersedes": self.supersedes, "cr_id": self.cr_id,
                "sheets": {n: {"columns": s.columns, "rows": s.rows} for n, s in self.sheets.items()},
                "about": self.about}

    def fingerprint(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def to_dict(glossary: Glossary) -> dict:
    data = {"version": glossary.version, "supersedes": glossary.supersedes, "cr_id": glossary.cr_id,
            "status": glossary.status, "approved_by": glossary.approved_by, "approved_on": glossary.approved_on,
            "based_on": glossary.based_on, "sheets": {}, "about": glossary.about}
    for name, sheet in glossary.sheets.items():
        rows = [dict({c: r.get(c, "") for c in sheet.columns},
                     **{CHANGE_COL: r.get(CHANGE_COL, ""), CHANGE_ID_COL: r.get(CHANGE_ID_COL, "")})
                for r in sheet.rows]
        data["sheets"][name] = {"columns": list(sheet.columns), "rows": rows}
    return data


def from_dict(data: dict) -> Glossary:
    """Build a Glossary from its JSON form. Unknown keys are an error."""
    if not isinstance(data, dict):
        raise ValueError("the JSON must be an object")
    allowed = {"version", "supersedes", "cr_id", "status", "approved_by", "approved_on", "based_on",
               "sheets", "about"}
    extra = sorted(set(data) - allowed)
    if extra:
        raise ValueError("unknown key(s): {0} (allowed: {1})".format(", ".join(extra), ", ".join(sorted(allowed))))
    norm = ba_documents._norm
    glossary = Glossary(**{k: norm(data.get(k)) for k in ("version", "supersedes", "cr_id", "status",
                                                          "approved_by", "approved_on", "based_on")})
    sheets = data.get("sheets") or {}
    if not isinstance(sheets, dict):
        raise ValueError("sheets must be an object: sheet name -> {columns, rows}")
    unknown = sorted(set(sheets) - set(DATA_SHEETS))
    if unknown:
        raise ValueError("unknown sheet(s): {0} (the glossary has {1})".format(", ".join(unknown),
                                                                             ", ".join(DATA_SHEETS)))
    for name in DATA_SHEETS:
        if name not in sheets:
            continue
        columns = [norm(c) for c in sheets[name].get("columns") or []]
        rows = []
        for index, item in enumerate(sheets[name].get("rows") or [], start=1):
            if not isinstance(item, dict):
                raise ValueError("{0} row {1} must be an object".format(name, index))
            bad = sorted(set(item) - set(columns) - {CHANGE_COL, CHANGE_ID_COL})
            if bad:
                raise ValueError("{0} row {1}: unknown column(s) {2} (columns: {3})".format(
                    name, index, ", ".join(bad), ", ".join(columns)))
            rows.append({c: norm(item.get(c)) for c in columns + [CHANGE_COL, CHANGE_ID_COL]})
        glossary.sheets[name] = Sheet(columns=columns, rows=rows)
    glossary.about = [[norm(v) for v in pair] for pair in data.get("about") or []]
    return glossary


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------


def _version_from_name(path: str) -> str:
    match = FILE_PATTERN.search(os.path.basename(path))
    return "{0}.{1}".format(match.group("major"), match.group("minor")) if match else ""


def read_glossary(path: str) -> Glossary:
    """A baseline glossary (no Document sheet) or a version a change request wrote."""
    norm = ba_documents._norm
    workbook = load_workbook(path, read_only=True, data_only=True)
    names = workbook.sheetnames
    glossary = Glossary(version=_version_from_name(path), path=os.path.abspath(path))
    if DOCUMENT_SHEET in names:
        fields = {norm(r[0]): norm(r[1] if len(r) > 1 else "")
                  for r in workbook[DOCUMENT_SHEET].iter_rows(min_row=2, values_only=True) if r and r[0]}
        glossary.cr_id = fields.get("CR_ID", "")
        glossary.version = fields.get("Version", "") or glossary.version
        glossary.supersedes = fields.get("Supersedes", "")
        glossary.status = fields.get("Status", "").lower()
        glossary.approved_by = fields.get("Approved_By", "")
        glossary.approved_on = fields.get("Approved_On", "")
        glossary.based_on = fields.get("Based_On", "")
    for name in DATA_SHEETS:
        if name not in names:
            continue
        rows = workbook[name].iter_rows(values_only=True)
        header = [norm(c) for c in (next(rows, None) or ())]
        while header and not header[-1]:
            header.pop()
        columns = [c for c in header if c not in (CHANGE_COL, CHANGE_ID_COL)]
        sheet = Sheet(columns=columns)
        for values in rows:
            item = {c: norm(values[i]) if i < len(values) else "" for i, c in enumerate(header)}
            if any(item.values()):
                item.setdefault(CHANGE_COL, "")
                item.setdefault(CHANGE_ID_COL, "")
                sheet.rows.append(item)
        glossary.sheets[name] = sheet
    if ABOUT_SHEET in names:
        rows = list(workbook[ABOUT_SHEET].iter_rows(values_only=True))
        glossary.about = [[norm(r[0]), norm(r[1] if len(r) > 1 else "")] for r in rows if r and any(r)]
    workbook.close()
    return glossary


def _header(sheet, names: list, widths: dict) -> None:
    for index, name in enumerate(names, start=1):
        cell = sheet.cell(row=1, column=index, value=name)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        sheet.column_dimensions[cell.column_letter].width = widths.get(name, 30)
    sheet.freeze_panes = "A2"


def change_rows(glossary: Glossary, superseded: Glossary = None) -> list:
    """The rows of the Changes_In_This_Version sheet."""
    result = []
    for name, row in glossary.marked_rows():
        sheet = glossary.sheets[name]
        before = superseded.sheets.get(name, Sheet()).row(row.get(sheet.id_column, "")) if superseded else None
        what = ""
        if row.get(CHANGE_COL) == "changed" and before is not None:
            what = "\n".join("{0} was: {1}".format(c, before.get(c, "")) for c in sheet.columns
                             if before.get(c, "") != row.get(c, ""))
        label = NAME_COLUMN.get(name) if NAME_COLUMN.get(name) in sheet.columns else \
            (sheet.columns[1] if len(sheet.columns) > 1 else "")
        result.append([row.get(CHANGE_ID_COL, ""), name, row.get(sheet.id_column, ""), row.get(CHANGE_COL, ""),
                       row.get(label, ""), what])
    return result


def write_glossary(glossary: Glossary, path: str, superseded: Glossary = None) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = DOCUMENT_SHEET
    _header(sheet, ["Field", "Value", "Help"], {"Field": 16, "Value": 40, "Help": 90})
    values = {"CR_ID": glossary.cr_id, "Version": glossary.version, "Supersedes": glossary.supersedes,
              "Status": glossary.status, "Approved_By": glossary.approved_by,
              "Approved_On": glossary.approved_on, "Based_On": glossary.based_on}
    for row, (name, help_text) in enumerate(DOCUMENT_FIELDS, start=2):
        sheet.cell(row=row, column=1, value=name).font = Font(bold=True)
        sheet.cell(row=row, column=2, value=values[name] or None)
        cell = sheet.cell(row=row, column=3, value=help_text)
        cell.font = Font(italic=True, color="666666")
        cell.alignment = _WRAP
        if name == "Status":
            validation = DataValidation(type="list", formula1='"{0}"'.format(",".join(ba_documents.VALID_STATUSES)),
                                        allow_blank=True, showErrorMessage=True)
            validation.add("B{0}".format(row))
            sheet.add_data_validation(validation)
    note = len(DOCUMENT_FIELDS) + 3
    sheet.cell(row=note, column=1, value="Approval").font = Font(bold=True)
    sheet.cell(row=note, column=2, value=(
        "The glossary owner reviews every row marked added or changed (see {0}), then sets Status = approved, "
        "Approved_By = their own name, Approved_On = YYYY-MM-DD. An AI assistant never does this; a later "
        "content change drops the approval. Check with: python tools/change_request/cr.py validate".format(
            CHANGES_SHEET))).alignment = _WRAP

    for name in DATA_SHEETS:
        if name not in glossary.sheets:
            continue
        data = glossary.sheets[name]
        out = workbook.create_sheet(name)
        columns = list(data.columns) + [CHANGE_COL, CHANGE_ID_COL]
        _header(out, columns, {CHANGE_COL: 10, CHANGE_ID_COL: 12, data.id_column: 12})
        for row_index, row in enumerate(data.rows, start=2):
            fill = _ROW_FILL.get(row.get(CHANGE_COL, ""))
            for col_index, column in enumerate(columns, start=1):
                cell = out.cell(row=row_index, column=col_index, value=row.get(column, "") or None)
                cell.alignment = _WRAP
                if fill is not None:
                    cell.fill = fill

    changes = workbook.create_sheet(CHANGES_SHEET)
    columns = ["Change_ID", "Sheet", "ID", "Change", "Name", "Before"]
    _header(changes, columns, {"Change_ID": 12, "Sheet": 22, "ID": 10, "Change": 10, "Name": 36, "Before": 80})
    for row_index, values_row in enumerate(change_rows(glossary, superseded), start=2):
        for col_index, value in enumerate(values_row, start=1):
            changes.cell(row=row_index, column=col_index, value=value or None).alignment = _WRAP

    about = workbook.create_sheet(ABOUT_SHEET)
    about.column_dimensions["A"].width = 24
    about.column_dimensions["B"].width = 100
    for row_index, pair in enumerate(glossary.about, start=1):
        for col_index, value in enumerate(pair[:2], start=1):
            cell = about.cell(row=row_index, column=col_index, value=value or None)
            cell.alignment = _WRAP
            if row_index == 1:
                cell.fill = _HEADER_FILL
                cell.font = _HEADER_FONT

    meta = workbook.create_sheet(META_SHEET)
    meta.append(("Document_Type", DOCUMENT_TYPE))
    meta.append(("Note", "Written by tools/change_request/glossary_version.py. Do not edit this sheet."))
    meta.sheet_state = "hidden"
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    workbook.save(path)


# ---------------------------------------------------------------------------
# Finding versions
# ---------------------------------------------------------------------------


def version_key(version: str) -> tuple:
    try:
        major, minor = version.split(".")
        return int(major), int(minor)
    except ValueError:
        return (0, 0)


def next_version(version: str) -> str:
    major, minor = version_key(version)
    return "{0}.{1}".format(major, minor + 1)


def file_name(version: str) -> str:
    return "{0}_v{1}.xlsx".format(FILE_PREFIX, version)


def glossary_path(cr_id: str, version: str) -> str:
    return os.path.join(ba_documents.cr_folder(cr_id), file_name(version))


def _files(root: str) -> list:
    return sorted(p for p in glob.glob(os.path.join(root, "**", "*Business_Glossary_v*.xlsx"), recursive=True)
                  if not os.path.basename(p).startswith("~$"))


def baseline_glossaries() -> list:
    """The approved glossary versions in business-documents/ (never changed by a CR)."""
    return [read_glossary(p) for p in _files(baseline_dir())]


def newest_baseline() -> Glossary:
    found = baseline_glossaries()
    return max(found, key=lambda g: version_key(g.version)) if found else None


def cr_glossaries(cr_id: str = None) -> list:
    """Glossary versions written by change requests (any status)."""
    root = ba_documents.cr_folder(cr_id) if cr_id else ba_documents.cr_root()
    if not os.path.isdir(root):
        return []
    return [read_glossary(p) for p in _files(root)]


def starting_point(cr_id: str) -> Glossary:
    """What ba-3 edits: this CR's own newest version if it has one, else the
    newest baseline prepared as the next version (no row marked yet)."""
    own = cr_glossaries(cr_id)
    if own:
        return max(own, key=lambda g: version_key(g.version))
    baseline = newest_baseline()
    if baseline is None:
        return None
    return Glossary(version=next_version(baseline.version), supersedes=baseline.version, cr_id=cr_id,
                    status="in_review", sheets=baseline.sheets, about=baseline.about)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_glossary(glossary: Glossary, requirements=None) -> Report:
    """A CR's glossary version against the version it supersedes and the
    Glossary_Changes of the requirements it applies."""
    report = Report()
    where = os.path.basename(glossary.path) if glossary.path else "glossary v{0}".format(glossary.version)
    if glossary.is_baseline:
        return report
    if not CR_ID_PATTERN.match(glossary.cr_id):
        report.errors.append("{0}: CR_ID '{1}' must look like CR-ECB-001".format(where, glossary.cr_id))
    if not VERSION_PATTERN.match(glossary.version):
        report.errors.append("{0}: Version '{1}' must look like 0.4".format(where, glossary.version))
    if glossary.status not in ba_documents.VALID_STATUSES:
        report.errors.append("{0}: Status '{1}' is not one of {2}".format(
            where, glossary.status, ", ".join(ba_documents.VALID_STATUSES)))
    superseded = next((g for g in baseline_glossaries() if g.version == glossary.supersedes), None)
    if superseded is None:
        report.errors.append("{0}: Supersedes '{1}' is not an approved glossary version in {2}".format(
            where, glossary.supersedes, _rel(baseline_dir())))
    elif version_key(glossary.version) <= version_key(superseded.version):
        report.errors.append("{0}: version {1} must be higher than the version it supersedes ({2})".format(
            where, glossary.version, superseded.version))

    for name in DATA_SHEETS:
        sheet = glossary.sheets.get(name)
        if sheet is None:
            report.errors.append("{0}: sheet {1} is missing - a new version is the whole glossary".format(where, name))
            continue
        _check_sheet(name, sheet, superseded.sheets.get(name) if superseded else None, report, where)
    marked = glossary.marked_rows()
    if not marked:
        report.errors.append("{0}: no row is marked added or changed - a new version must change something".format(
            where))

    if requirements is not None:
        _check_against_requirements(glossary, requirements, report, where)

    if glossary.status == "approved":
        if not glossary.approved_by:
            report.errors.append("{0}: approved but Approved_By is empty".format(where))
        if not DATE_PATTERN.match(glossary.approved_on):
            report.errors.append("{0}: approved but Approved_On is not a YYYY-MM-DD date".format(where))
        text = json.dumps(glossary.content(), ensure_ascii=False)
        if TODO_PATTERN.search(text) or SUGGESTION_PATTERN.search(text):
            report.errors.append("{0}: approved but still has TODO or SUGGESTION: text - a glossary entry is "
                                 "complete before it is approved".format(where))
    return report


def _check_sheet(name: str, sheet: Sheet, before: Sheet, report: Report, where: str) -> None:
    label = "{0} {1}".format(where, name)
    if before is not None and sheet.columns != before.columns:
        report.errors.append("{0}: columns must stay those of the version it supersedes ({1})".format(
            label, ", ".join(before.columns)))
        return
    seen = set()
    for index, row in enumerate(sheet.rows, start=1):
        row_id = row.get(sheet.id_column, "")
        at = "{0} {1}".format(label, row_id or "row {0}".format(index))
        if not row_id:
            report.errors.append("{0}: {1} is empty".format(at, sheet.id_column))
            continue
        if row_id.upper() in seen:
            report.errors.append("{0}: listed twice".format(at))
        seen.add(row_id.upper())
        change, change_ids = row.get(CHANGE_COL, ""), row.get(CHANGE_ID_COL, "")
        if change not in ROW_CHANGES:
            report.errors.append("{0}: Change '{1}' must be empty, added or changed".format(at, change))
            continue
        if change and not change_ids:
            report.errors.append("{0}: marked {1} but has no Change_ID (the GC-.. of the requirements)".format(
                at, change))
        if change_ids and not change:
            report.errors.append("{0}: has Change_ID {1} but is not marked added or changed".format(at, change_ids))
        if before is None:
            continue
        old = before.row(row_id)
        if change == "added" and old is not None:
            report.errors.append("{0}: marked added but the superseded version has it - mark it changed".format(at))
        elif change == "changed" and old is None:
            report.errors.append("{0}: marked changed but the superseded version does not have it - mark it "
                                 "added".format(at))
        elif old is not None and _same(sheet, row, old) and change == "changed":
            report.errors.append("{0}: marked changed but equal to the superseded version".format(at))
        elif old is not None and not _same(sheet, row, old) and not change:
            report.errors.append("{0}: differs from the superseded version but is not marked changed".format(at))
    if before is not None:
        for old in before.rows:
            if sheet.row(old.get(before.id_column, "")) is None:
                report.errors.append("{0} {1}: removed - a new version keeps every entry (retire one through its "
                                     "Definition Status instead)".format(label, old.get(before.id_column)))


def _same(sheet: Sheet, row: dict, old: dict) -> bool:
    return all(row.get(c, "") == old.get(c, "") for c in sheet.columns)


def _check_against_requirements(glossary: Glossary, requirements, report: Report, where: str) -> None:
    proposed = {r.get("Change_ID", "").upper(): r for r in requirements.sheet("glossary_changes")
                if r.get("Change_ID")}
    applied = set()
    for name, row in glossary.marked_rows():
        sheet = glossary.sheets[name]
        row_id = row.get(sheet.id_column, "")
        for change_id in split_ids(row.get(CHANGE_ID_COL, "")):
            at = "{0} {1} {2}".format(where, name, row_id)
            gc = proposed.get(change_id)
            if gc is None:
                report.errors.append("{0}: Change_ID {1} is not on the Glossary_Changes sheet of the requirements "
                                     "- a glossary change is decided in /ba-1-analyse-requirement".format(
                                         at, change_id))
                continue
            applied.add(change_id)
            target, marking = CHANGE_TYPES.get(gc.get("Change_Type", ""), (None, ""))
            if target is not None and target != name:
                report.errors.append("{0}: {1} is a {2}, which belongs on the {3} sheet".format(
                    at, change_id, gc.get("Change_Type"), target))
            if marking and row.get(CHANGE_COL) != marking:
                report.errors.append("{0}: {1} is a {2}, so the row must be marked {3}".format(
                    at, change_id, gc.get("Change_Type"), marking))
            refs = split_ids(gc.get("Glossary_Ref", ""))
            if marking == "changed" and refs and row_id.upper() not in refs:
                report.errors.append("{0}: {1} changes {2}, not {3}".format(
                    at, change_id, ", ".join(refs), row_id))
    for change_id in proposed:
        if change_id not in applied:
            report.errors.append("{0}: {1} of the requirements is not applied to any row".format(where, change_id))
    if glossary.based_on != requirements.fingerprint():
        report.errors.append(
            "{0}: written from an earlier version of the requirements (based on {1}, now {2}). "
            "Rewrite it and have it approved again.".format(where, glossary.based_on or "-",
                                                            requirements.fingerprint()))


# ---------------------------------------------------------------------------
# Writing from JSON, with the approval rules
# ---------------------------------------------------------------------------


def write_from_dict(data: dict) -> tuple:
    """Write a new glossary version into its change request's folder.
    Returns (Glossary, path, [messages]). Raises ValueError / WriteRefused."""
    new = from_dict(data)
    if not CR_ID_PATTERN.match(new.cr_id):
        raise ValueError("cr_id must name the change request, e.g. CR-ECB-001")
    if not VERSION_PATTERN.match(new.version):
        raise ValueError("version must look like 0.4")
    requirements = ba_documents.find_document(new.cr_id, "requirements")
    gap = ba_documents.find_document(new.cr_id, "gap_analysis")
    if requirements is None or not requirements.is_approved:
        raise WriteRefused("the requirements of {0} are not approved; the glossary changes are decided "
                           "there first".format(new.cr_id))
    if gap is None or not gap.is_approved or not ba_documents.validate_document(gap, requirements).ok:
        raise WriteRefused("the gap analysis of {0} is not approved and valid for the current requirements; "
                           "the glossary version is written only after step 2, so that no finding can still "
                           "change a meaning".format(new.cr_id))
    if not requirements.sheet("glossary_changes"):
        raise WriteRefused("the requirements of {0} propose no glossary change".format(new.cr_id))
    new.based_on = requirements.fingerprint()

    baseline = newest_baseline()
    if baseline is None:
        raise WriteRefused("no glossary in {0} to supersede".format(_rel(baseline_dir())))
    if version_key(new.version) <= version_key(baseline.version):
        raise WriteRefused("v{0} is an approved baseline in {1}; a change is a new, higher version (e.g. {2})".format(
            baseline.version, _rel(baseline_dir()), next_version(baseline.version)))
    if new.supersedes != baseline.version:
        raise ValueError("supersedes must be {0}, the approved version this one replaces".format(baseline.version))

    path = glossary_path(new.cr_id, new.version)
    new.path = path
    existing = read_glossary(path) if os.path.exists(path) else None
    old = None
    if existing is not None:
        old = (existing.status, existing.approved_by, existing.approved_on, existing.fingerprint())
    status, by, on, message = approval_decision(old, new.status, new.approved_by, new.approved_on,
                                                new.fingerprint())
    new.status, new.approved_by, new.approved_on = status, by, on
    messages = [message] if message else []
    others = [g for g in cr_glossaries() if g.cr_id and g.cr_id != new.cr_id]
    for other in others:
        messages.append("NOTE: {0} also writes glossary v{1}; the glossary owner must merge the two.".format(
            other.cr_id, other.version))
    write_glossary(new, path, baseline)
    return new, path, messages


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
    except ValueError:
        return path
