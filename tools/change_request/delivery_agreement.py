"""Delivery agreements: the contract for what a source system delivers.

The approved agreements are Word documents in
``business-documents/UBB_Delivery_Agreements_Approved_v1.0/``. They are never
changed. A change request that needs a source to deliver more writes a NEW
version of the agreement into its own folder:

    change-requests/<CR_ID>/UBB_Delivery_Agreement_<SYSTEM>_v<VERSION>.docx

(v1.1 for an existing agreement, v1.0 for a source with no agreement yet).
The new version is the whole contract, not a patch: every entity and
attribute, with the added ones marked and listed in "Changes in this version".

An AI assistant never edits the Word file. It reads the current version as
JSON (``cr.py agreement-json``), changes the JSON, and ``cr.py write-agreement``
renders the document with the same styles as the version it supersedes. The
approval rules are those of every analyst document (ba_documents.py): only a
person approves, in Word, in the table of section 6 "Agreement status"; a
content change drops an approval.

This module reads both the original v1.0 layout and the layout it writes:

  Title        "Delivery Agreement - <SYSTEM>"
  Subtitle     what the system is
  version line "Version 1.0 ... Status: APPROVED"  (v1.0 only)
  1. Purpose ... paragraphs
  2. File and delivery standard: a two-column table
  3. Delivery entities and attributes: per entity a Heading 2 "3.n NAME",
     "Filename: ... | Business key: ... | Snapshot: ...", and a table
     File attribute | Expected type / precision | Business description [| Change]
  4. Delivery-level data quality: bullets
  5. Change control: paragraphs, then "Changes in this version" (a table)
  6. Agreement status: a two-column table (Status, Version, ...)

Needs python-docx (see requirements.txt). No database is involved.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field

try:
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table as _DocxTable
    from docx.text.paragraph import Paragraph as _DocxParagraph
except ImportError as exc:  # pragma: no cover - guidance path only
    raise ImportError("python-docx is required: pip install -r requirements.txt") from exc

import ba_documents
from ba_documents import CR_ID_PATTERN, DATE_PATTERN, Report, WriteRefused, approval_decision

REPO_ROOT = ba_documents.REPO_ROOT
BASELINE_ENV = "UBB_AGREEMENT_BASELINE_DIR"
FILE_PATTERN = re.compile(r"Delivery_Agreement_(?P<system>[A-Z0-9_]+?)_v(?P<major>\d+)\.(?P<minor>\d+)", re.I)
VERSION_PATTERN = re.compile(r"^\d+\.\d+$")
NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
# The staging convention: VARCHAR2 and CHAR lengths in characters.
CHAR_TYPE = re.compile(r"^(VARCHAR2|CHAR|NVARCHAR2|NCHAR)\s*\(\s*\d+\s*(CHAR)?\s*\)$", re.I)
KNOWN_TYPE = re.compile(
    r"^(VARCHAR2\(\d+ CHAR\)|CHAR\(\d+ CHAR\)|NUMBER(\(\d+(,\s*-?\d+)?\))?|DATE|TIMESTAMP(\(\d\))?)$", re.I)
# Added by the warehouse, never part of a delivered file.
TECHNICAL_COLUMNS = ("LOAD_ID", "STAGED_AT")
ATTRIBUTE_CHANGES = ("", "added", "changed")
ENTITY_CHANGES = ("", "new")
CHANGE_KINDS = ("add_attribute", "change_attribute", "new_entity")
STATUS_ROWS = ("Status", "Version", "Supersedes", "Change request", "Based on gap analysis",
               "Approved by", "Approved on")
TABLE_STYLE = "Light Shading Accent 1"


def baseline_dir() -> str:
    return os.environ.get(BASELINE_ENV) or os.path.join(REPO_ROOT, "business-documents")


@dataclass
class Attribute:
    name: str = ""
    type: str = ""
    description: str = ""
    change: str = ""  # "", added, changed


@dataclass
class Entity:
    name: str = ""
    filename: str = ""
    business_key: str = ""  # attributes joined by " + "
    snapshot: str = ""
    change: str = ""  # "", new
    attributes: list = field(default_factory=list)

    @property
    def key_columns(self) -> list:
        return [p.strip().upper() for p in re.split(r"\+|,", self.business_key) if p.strip()]

    def attribute(self, name: str):
        return next((a for a in self.attributes if a.name.upper() == name.upper()), None)


@dataclass
class Change:
    change_id: str = ""
    entity: str = ""
    attribute: str = ""
    change: str = ""  # add_attribute, change_attribute, new_entity
    reason: str = ""
    input_ids: str = ""


@dataclass
class Agreement:
    source_system: str = ""
    subtitle: str = ""
    version: str = ""
    supersedes: str = ""
    cr_id: str = ""
    status: str = ""
    approved_by: str = ""
    approved_on: str = ""
    based_on: str = ""  # fingerprint of the gap analysis it was written from (written by the tool)
    purpose: list = field(default_factory=list)
    delivery_standard: list = field(default_factory=list)  # [[topic, rule], ...]
    entities_intro: str = ""
    entities: list = field(default_factory=list)
    data_quality: list = field(default_factory=list)
    change_control: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    path: str = ""

    @property
    def is_approved(self) -> bool:
        return self.status.lower() == "approved"

    @property
    def is_baseline(self) -> bool:
        """An approved agreement that no change request wrote (business-documents)."""
        return not self.cr_id

    def entity(self, name: str):
        return next((e for e in self.entities if e.name.upper() == name.upper()), None)

    def content(self) -> dict:
        data = to_dict(self)
        for name in ("status", "approved_by", "approved_on", "path"):
            data.pop(name, None)
        return data

    def fingerprint(self) -> str:
        canonical = json.dumps(self.content(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def to_dict(agreement: Agreement) -> dict:
    data = asdict(agreement)
    data.pop("path", None)
    return data


def from_dict(data: dict) -> Agreement:
    if not isinstance(data, dict):
        raise ValueError("the JSON must be an object")
    known = {f for f in Agreement.__dataclass_fields__ if f != "path"}
    unknown = sorted(set(data) - known - {"change_note"})
    if unknown:
        raise ValueError("unknown field(s): {0} (fields: {1})".format(", ".join(unknown), ", ".join(sorted(known))))

    def text(value) -> str:
        return ba_documents._norm(value)

    def rows(items, cls, what):
        result = []
        allowed = set(cls.__dataclass_fields__)
        for index, item in enumerate(items or [], start=1):
            if not isinstance(item, dict):
                raise ValueError("{0} {1} must be an object".format(what, index))
            bad = sorted(set(item) - allowed - ({"attributes"} if cls is Entity else set()))
            if bad:
                raise ValueError("{0} {1}: unknown field(s) {2}".format(what, index, ", ".join(bad)))
            values = {k: text(v) for k, v in item.items() if k != "attributes"}
            obj = cls(**values)
            if cls is Entity:
                obj.attributes = rows(item.get("attributes"), Attribute, "entity {0} attribute".format(obj.name))
            result.append(obj)
        return result

    agreement = Agreement(**{k: text(data.get(k)) for k in (
        "source_system", "subtitle", "version", "supersedes", "cr_id", "status", "approved_by",
        "approved_on", "based_on", "entities_intro")})
    agreement.source_system = agreement.source_system.upper()
    agreement.purpose = [text(p) for p in data.get("purpose") or [] if text(p)]
    agreement.data_quality = [text(p) for p in data.get("data_quality") or [] if text(p)]
    agreement.change_control = [text(p) for p in data.get("change_control") or [] if text(p)]
    agreement.delivery_standard = [[text(r[0]), text(r[1])] for r in data.get("delivery_standard") or []
                                   if isinstance(r, (list, tuple)) and len(r) == 2]
    agreement.entities = rows(data.get("entities"), Entity, "entity")
    agreement.changes = rows(data.get("changes"), Change, "change")
    return agreement


# ---------------------------------------------------------------------------
# Reading Word
# ---------------------------------------------------------------------------


def _blocks(document):
    """Paragraphs and tables in body order."""
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield _DocxParagraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield _DocxTable(child, document)


def _cell_text(cell) -> str:
    return "\n".join(p.text for p in cell.paragraphs).strip()


def _table_rows(table) -> list:
    return [[_cell_text(c) for c in row.cells] for row in table.rows]


def _section_of(heading: str) -> str:
    text = heading.lower()
    for key, words in (("purpose", "purpose"), ("standard", "delivery standard"), ("standard", "file and"),
                       ("entities", "entities"), ("quality", "quality"), ("change", "change control"),
                       ("status", "status")):
        if words in text:
            return key
    return ""


def read_agreement(path: str) -> Agreement:
    document = docx.Document(path)
    agreement = Agreement(path=os.path.abspath(path))
    section = ""
    current = None
    for block in _blocks(document):
        if isinstance(block, _DocxTable):
            rows = _table_rows(block)
            if not rows:
                continue
            if section == "standard":
                agreement.delivery_standard += [[r[0], r[1]] for r in rows if len(r) >= 2 and r[0]]
            elif section == "entities" and current is not None:
                header = [h.lower() for h in rows[0]]
                has_change = len(header) >= 4 and "change" in header[3]
                for r in rows[1:]:
                    if r and r[0]:
                        current.attributes.append(Attribute(
                            name=r[0].strip().upper(), type=r[1].strip() if len(r) > 1 else "",
                            description=r[2].strip() if len(r) > 2 else "",
                            change=(r[3].strip().lower() if has_change and len(r) > 3 else "")))
            elif section == "change":
                for r in rows[1:]:
                    if len(r) >= 6 and r[0]:
                        agreement.changes.append(Change(*[x.strip() for x in r[:6]]))
            elif section == "status":
                values = {r[0].strip().lower(): r[1].strip() for r in rows if len(r) >= 2}
                agreement.status = values.get("status", "").lower()
                agreement.version = values.get("version", agreement.version)
                agreement.supersedes = values.get("supersedes", "")
                agreement.cr_id = values.get("change request", "")
                agreement.based_on = values.get("based on gap analysis", "")
                agreement.approved_by = values.get("approved by", "")
                agreement.approved_on = values.get("approved on", "")
            continue

        text = block.text.strip()
        style = (block.style.name if block.style is not None else "").lower()
        if style == "title":
            match = re.search(r"Delivery Agreement\s*[-–—:]\s*(\S+)", text)
            agreement.source_system = (match.group(1) if match else text).strip().upper()
            continue
        if style == "subtitle":
            agreement.subtitle = text
            continue
        if style.startswith("heading 1"):
            section = _section_of(text)
            current = None
            continue
        if style.startswith("heading 2"):
            if section == "entities":
                name = re.sub(r"^\d+(\.\d+)*\s*", "", text).strip()
                change = ""
                if re.search(r"\(new\)\s*$", name, re.I):
                    change, name = "new", re.sub(r"\s*\(new\)\s*$", "", name, flags=re.I)
                current = Entity(name=name.upper(), change=change)
                agreement.entities.append(current)
            continue
        if not text:
            continue
        if not section:
            match = re.search(r"Version\s+(\d+\.\d+)", text)
            if match and not agreement.version:
                agreement.version = match.group(1)
                if re.search(r"Status:\s*APPROVED", text, re.I):
                    agreement.status = "approved"
            continue
        if section == "purpose":
            agreement.purpose.append(text)
        elif section == "entities":
            if current is None:
                agreement.entities_intro = text
            elif text.lower().startswith("filename"):
                parts = {}
                for part in text.split("|"):
                    if ":" in part:
                        key, value = part.split(":", 1)
                        parts[key.strip().lower()] = value.strip()
                current.filename = parts.get("filename", "")
                current.business_key = parts.get("business key", "")
                current.snapshot = parts.get("snapshot", "")
        elif section == "quality":
            agreement.data_quality.append(text)
        elif section == "change":
            if not text.lower().startswith("changes in this version"):
                agreement.change_control.append(text)
    return agreement


# ---------------------------------------------------------------------------
# Writing Word
# ---------------------------------------------------------------------------

ENTITY_CLOSING = ("The stated business key is unique within each delivered business-date snapshot. The "
                  "delivery is subject to the validation and acceptance rules in section 4.")


def _paragraph(document, text: str, style: str):
    try:
        return document.add_paragraph(text, style=style)
    except KeyError:  # the template lacks the style
        return document.add_paragraph(text)


def _table(document, rows: list, header: bool):
    table = document.add_table(rows=0, cols=len(rows[0]))
    try:
        table.style = TABLE_STYLE
    except (KeyError, ValueError):
        table.style = None
    for values in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, values):
            cell.text = value
    if header:
        for cell in table.rows[0].cells:
            for run in cell.paragraphs[0].runs:
                run.bold = True
    return table


def write_agreement(agreement: Agreement, path: str, template: str) -> None:
    """Render the agreement with the styles, header and footer of `template`
    (the version it supersedes, or another agreement for a new source)."""
    document = docx.Document(template)
    body = document.element.body
    for child in list(body.iterchildren()):
        if child.tag != qn("w:sectPr"):
            body.remove(child)

    _paragraph(document, "Delivery Agreement - {0}".format(agreement.source_system), "Title")
    _paragraph(document, agreement.subtitle, "Subtitle")
    line = "Version {0}".format(agreement.version)
    if agreement.supersedes:
        line += "  •  Supersedes {0}".format(agreement.supersedes)
    if agreement.cr_id:
        line += "  •  Change request {0}".format(agreement.cr_id)
    line += "  •  Status: see section 6"
    _paragraph(document, line, "Normal")

    _paragraph(document, "1. Purpose and contractual scope", "Heading 1")
    for text in agreement.purpose:
        _paragraph(document, text, "Normal")

    _paragraph(document, "2. File and delivery standard", "Heading 1")
    if agreement.delivery_standard:
        _table(document, agreement.delivery_standard, header=False)

    _paragraph(document, "3. Delivery entities and attributes", "Heading 1")
    if agreement.entities_intro:
        _paragraph(document, agreement.entities_intro, "Normal")
    with_change = any(a.change for e in agreement.entities for a in e.attributes) or any(
        e.change for e in agreement.entities)
    for number, entity in enumerate(agreement.entities, start=1):
        title = "3.{0} {1}{2}".format(number, entity.name, " (new)" if entity.change == "new" else "")
        _paragraph(document, title, "Heading 2")
        _paragraph(document, "Filename: {0}  |  Business key: {1}  |  Snapshot: {2}".format(
            entity.filename, entity.business_key, entity.snapshot), "Normal")
        header = ["File attribute", "Expected type / precision", "Business description / clarification"]
        if with_change:
            header.append("Change")
        rows = [header]
        for attr in entity.attributes:
            row = [attr.name, attr.type, attr.description]
            if with_change:
                row.append(attr.change)
            rows.append(row)
        _table(document, rows, header=True)
        _paragraph(document, ENTITY_CLOSING, "Normal")

    _paragraph(document, "4. Delivery-level data quality and acceptance", "Heading 1")
    for text in agreement.data_quality:
        _paragraph(document, text, "List Bullet")

    _paragraph(document, "5. Change control", "Heading 1")
    for text in agreement.change_control:
        _paragraph(document, text, "Normal")
    if agreement.changes:
        _paragraph(document, "Changes in this version ({0})".format(agreement.cr_id or "baseline"), "Heading 2")
        rows = [["Change ID", "Entity", "Attribute", "Change", "Reason", "Required inputs"]]
        rows += [[c.change_id, c.entity, c.attribute, c.change, c.reason, c.input_ids] for c in agreement.changes]
        _table(document, rows, header=True)

    _paragraph(document, "6. Agreement status", "Heading 1")
    _paragraph(document, "Approval is a person's act: the approver sets Status to approved and fills Approved by "
                         "and Approved on (YYYY-MM-DD) in this table. Any later content change drops the "
                         "approval.", "Normal")
    values = {"Status": agreement.status, "Version": agreement.version, "Supersedes": agreement.supersedes,
              "Change request": agreement.cr_id, "Based on gap analysis": agreement.based_on,
              "Approved by": agreement.approved_by, "Approved on": agreement.approved_on}
    _table(document, [[name, values[name]] for name in STATUS_ROWS], header=False)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    document.save(path)


# ---------------------------------------------------------------------------
# Finding agreements
# ---------------------------------------------------------------------------


def version_key(version: str) -> tuple:
    try:
        major, minor = version.split(".")
        return int(major), int(minor)
    except ValueError:
        return (0, 0)


def file_name(system: str, version: str) -> str:
    return "UBB_Delivery_Agreement_{0}_v{1}.docx".format(system.upper(), version)


def agreement_path(cr_id: str, system: str, version: str) -> str:
    return os.path.join(ba_documents.cr_folder(cr_id), file_name(system, version))


def _docx_files(root: str) -> list:
    return sorted(p for p in glob.glob(os.path.join(root, "**", "*Delivery_Agreement*.docx"), recursive=True)
                  if not os.path.basename(p).startswith("~$"))


def baseline_agreements() -> list:
    """The approved agreements in business-documents/ (never changed by a CR)."""
    return [read_agreement(p) for p in _docx_files(baseline_dir())]


def cr_agreements(cr_id: str = None) -> list:
    """Agreement versions written by change requests (any status)."""
    root = ba_documents.cr_folder(cr_id) if cr_id else ba_documents.cr_root()
    if not os.path.isdir(root):
        return []
    return [read_agreement(p) for p in _docx_files(root)]


def current_agreements() -> dict:
    """{SYSTEM: Agreement}: per source system, the highest approved version -
    a CR's approved version wins over the baseline it supersedes."""
    best = {}
    for agreement in baseline_agreements() + cr_agreements():
        if not agreement.is_approved:
            continue
        known = best.get(agreement.source_system)
        if known is None or version_key(agreement.version) > version_key(known.version):
            best[agreement.source_system] = agreement
    return best


def latest_any_status(system: str) -> Agreement:
    """The highest version of an agreement for the system, approved or not."""
    found = [a for a in baseline_agreements() + cr_agreements() if a.source_system == system.upper()]
    return max(found, key=lambda a: version_key(a.version)) if found else None


def default_template(system: str) -> str:
    """The styles to render with: the system's own baseline, else any baseline."""
    files = _docx_files(baseline_dir())
    own = [p for p in files if FILE_PATTERN.search(os.path.basename(p))
           and FILE_PATTERN.search(os.path.basename(p)).group("system").upper() == system.upper()]
    chosen = own or files
    if not chosen:
        raise WriteRefused("no delivery agreement in {0} to take the Word styles from".format(baseline_dir()))
    return chosen[-1]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_agreement(agreement: Agreement, gap_analysis=None) -> Report:
    report = Report()
    where = os.path.basename(agreement.path) if agreement.path else "agreement {0}".format(agreement.source_system)
    if not NAME_PATTERN.match(agreement.source_system or ""):
        report.errors.append("{0}: source_system '{1}' must be upper case, e.g. CBS_SIM".format(
            where, agreement.source_system))
    if not VERSION_PATTERN.match(agreement.version):
        report.errors.append("{0}: version '{1}' must look like 1.1".format(where, agreement.version))
    if agreement.supersedes:
        if not VERSION_PATTERN.match(agreement.supersedes):
            report.errors.append("{0}: supersedes '{1}' must look like 1.0".format(where, agreement.supersedes))
        elif version_key(agreement.supersedes) >= version_key(agreement.version):
            report.errors.append("{0}: version {1} must be higher than the version it supersedes ({2})".format(
                where, agreement.version, agreement.supersedes))
    if not agreement.is_baseline:
        if not CR_ID_PATTERN.match(agreement.cr_id):
            report.errors.append("{0}: cr_id '{1}' must look like CR-ECB-001".format(where, agreement.cr_id))
        if agreement.status not in ba_documents.VALID_STATUSES:
            report.errors.append("{0}: status '{1}' is not one of {2}".format(
                where, agreement.status, ", ".join(ba_documents.VALID_STATUSES)))
    if not agreement.entities:
        report.errors.append("{0}: no delivery entity".format(where))

    seen_entities = set()
    for entity in agreement.entities:
        label = "{0} {1}".format(where, entity.name or "?")
        if not NAME_PATTERN.match(entity.name):
            report.errors.append("{0}: entity name must be upper case letters, digits and _".format(label))
        if entity.name in seen_entities:
            report.errors.append("{0}: entity listed twice".format(label))
        seen_entities.add(entity.name)
        if entity.change not in ENTITY_CHANGES:
            report.errors.append("{0}: change '{1}' must be empty or 'new'".format(label, entity.change))
        for name, value in (("filename", entity.filename), ("business key", entity.business_key),
                            ("snapshot", entity.snapshot)):
            if not value:
                report.errors.append("{0}: {1} is empty".format(label, name))
        seen = set()
        for attr in entity.attributes:
            if attr.name in seen:
                report.errors.append("{0}.{1}: listed twice".format(label, attr.name))
            seen.add(attr.name)
            if not NAME_PATTERN.match(attr.name):
                report.errors.append("{0}.{1}: attribute name must be upper case letters, digits and _".format(
                    label, attr.name))
            if attr.name in TECHNICAL_COLUMNS:
                report.errors.append("{0}.{1}: added by the warehouse, never part of the delivered file".format(
                    label, attr.name))
            if not KNOWN_TYPE.match(attr.type.strip()):
                hint = (" - write lengths in characters, e.g. VARCHAR2(80 CHAR), as staging does"
                        if CHAR_TYPE.match(attr.type.strip()) else "")
                report.errors.append("{0}.{1}: type '{2}' is not an Oracle type the staging tables use{3}".format(
                    label, attr.name, attr.type, hint))
            if not attr.description:
                report.errors.append("{0}.{1}: description is empty".format(label, attr.name))
            if attr.change not in ATTRIBUTE_CHANGES:
                report.errors.append("{0}.{1}: change '{2}' must be empty, added or changed".format(
                    label, attr.name, attr.change))
        for key in entity.key_columns:
            if key not in seen:
                report.errors.append("{0}: business key {1} is not an attribute of the entity".format(label, key))

    if not agreement.is_baseline:
        listed = {(c.entity.upper(), c.attribute.upper()) for c in agreement.changes}
        listed_entities = {c.entity.upper() for c in agreement.changes if c.change == "new_entity"}
        for entity in agreement.entities:
            if entity.change == "new" and entity.name not in listed_entities:
                report.errors.append("{0} {1}: a new entity needs a new_entity row in changes".format(
                    where, entity.name))
            for attr in entity.attributes:
                if attr.change and entity.change != "new" and (entity.name, attr.name) not in listed:
                    report.errors.append("{0} {1}.{2}: marked {3} but has no row in changes".format(
                        where, entity.name, attr.name, attr.change))
        for change in agreement.changes:
            label = "{0} change {1}".format(where, change.change_id or "?")
            if change.change not in CHANGE_KINDS:
                report.errors.append("{0}: change '{1}' is not one of {2}".format(
                    label, change.change, ", ".join(CHANGE_KINDS)))
            entity = agreement.entity(change.entity)
            if entity is None:
                report.errors.append("{0}: entity {1} is not in the agreement".format(label, change.entity))
            elif change.change != "new_entity" and entity.attribute(change.attribute) is None:
                report.errors.append("{0}: {1}.{2} is not in the agreement".format(
                    label, change.entity, change.attribute))
            if not change.reason:
                report.errors.append("{0}: reason is empty".format(label))
        if not agreement.changes:
            report.errors.append("{0}: a new version must list its changes".format(where))
        if gap_analysis is not None:
            inputs = set(gap_analysis.ids("gaps"))
            for change in agreement.changes:
                for ref in ba_documents.split_ids(change.input_ids):
                    if ref not in inputs:
                        report.errors.append("{0} change {1}: required input {2} is not in the gap analysis".format(
                            where, change.change_id, ref))
            if agreement.based_on != gap_analysis.fingerprint():
                report.errors.append(
                    "{0}: written from an earlier version of the gap analysis (based on {1}, now {2}). "
                    "Rewrite it and have it approved again.".format(
                        where, agreement.based_on or "-", gap_analysis.fingerprint()))
        if agreement.is_approved:
            if not agreement.approved_by:
                report.errors.append("{0}: approved but Approved by is empty".format(where))
            if not DATE_PATTERN.match(agreement.approved_on):
                report.errors.append("{0}: approved but Approved on is not a YYYY-MM-DD date".format(where))
            if ba_documents.TODO_PATTERN.search(json.dumps(agreement.content(), ensure_ascii=False)):
                report.errors.append("{0}: approved but still has TODO text - a contract is complete "
                                     "before it is approved".format(where))
    return report


# ---------------------------------------------------------------------------
# Writing from JSON, with the approval rules
# ---------------------------------------------------------------------------


def write_from_dict(data: dict, template: str = None) -> tuple:
    """Write a new agreement version into its change request's folder.
    Returns (Agreement, path, [messages])."""
    new = from_dict(data)
    if not CR_ID_PATTERN.match(new.cr_id):
        raise ValueError("cr_id must name the change request, e.g. CR-ECB-001")
    if not VERSION_PATTERN.match(new.version):
        raise ValueError("version must look like 1.1")
    gap = ba_documents.find_document(new.cr_id, "gap_analysis")
    if gap is None or not gap.is_approved:
        raise WriteRefused("the gap analysis of {0} is not approved; delivery agreement changes are written "
                           "from an approved gap analysis".format(new.cr_id))
    new.based_on = gap.fingerprint()

    previous = latest_any_status(new.source_system)
    baseline = [a for a in baseline_agreements() if a.source_system == new.source_system]
    if baseline:
        newest = max(baseline, key=lambda a: version_key(a.version))
        if version_key(new.version) <= version_key(newest.version):
            raise WriteRefused("{0} v{1} is an approved baseline in {2}; a change is a new, higher version "
                               "(e.g. {3})".format(new.source_system, newest.version, _rel(baseline_dir()),
                                                   _next(newest.version)))
        if new.supersedes != newest.version:
            raise ValueError("supersedes must be {0}, the approved version this one replaces".format(newest.version))

    path = agreement_path(new.cr_id, new.source_system, new.version)
    new.path = path
    existing = read_agreement(path) if os.path.exists(path) else None
    old = None
    if existing is not None:
        old = (existing.status, existing.approved_by, existing.approved_on, existing.fingerprint())
    status, by, on, message = approval_decision(old, new.status, new.approved_by, new.approved_on,
                                                new.fingerprint())
    new.status, new.approved_by, new.approved_on = status, by, on
    messages = [message] if message else []
    if previous is not None and previous.path != path and previous.cr_id and previous.cr_id != new.cr_id:
        messages.append("NOTE: {0} also has a version {1} from {2}; check the two do not conflict.".format(
            new.source_system, previous.version, previous.cr_id))
    write_agreement(new, path, template or default_template(new.source_system))
    return new, path, messages


def _next(version: str) -> str:
    major, minor = version_key(version)
    return "{0}.{1}".format(major, minor + 1)


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
    except ValueError:
        return path
