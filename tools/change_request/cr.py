"""Change requests: write, read, check and trace the analyst's documents.

A change request (CR) lives in change-requests/<CR_ID>/. The analyst skills
write its documents through this tool - never by editing Excel or Word
directly - and the developer skills check them before generating code.

Commands
--------
read <file>                         Any .docx or .xlsx as plain text (the change request, the
                                    glossary, the S2T baseline, the source catalog, an agreement).
schema <requirements|gap_analysis|agreement>
                                    The JSON shape `write` / `write-agreement` accept, with help.
write <file.json>                   Write <CR>_Requirements.xlsx or <CR>_Gap_Analysis.xlsx.
show <CR_ID> <requirements|gap_analysis> [--json]
                                    A workbook as text, or as the JSON `write` accepts.
agreement-json <SYSTEM | file.docx> The current version of a delivery agreement as JSON: the
                                    starting point of a new version.
write-agreement <file.json>         Write change-requests/<CR>/UBB_Delivery_Agreement_<SYS>_v<V>.docx.
glossary-json <CR_ID>               The glossary version the CR edits as JSON: its own version if it
                                    has one, else the newest baseline prepared as the next version.
write-glossary <file.json>          Write change-requests/<CR>/UBB_Credit_Risk_Business_Glossary_v<V>.xlsx
                                    from the approved requirements' Glossary_Changes.
validate [CR_ID]                    Check every document of one CR (or of all). Exit 1 on a problem.
status [CR_ID]                      Where each CR stands, and the next step.
gate <step> <CR_ID> [MAPPING_ID]    Exit 0 when the step may start; else say why. Steps:
                                    requirements, gaps, delivery, glossary, staging, mapping.
trace <CR_ID> [--xlsx]              The traceability matrix: requirement -> KPI -> input -> gap ->
                                    agreement change -> mapping -> acceptance criteria.
                                    --xlsx also writes change-requests/<CR>/<CR>_Traceability.xlsx.

Approval rules (the same for every analyst document): the tool never records
an approval; a named person sets it in Excel or Word; a content change drops
it. No command connects to a database.

    python tools/change_request/cr.py read business-documents/UBB_CR_ECB_001_Collateral_Adjusted_Credit_Risk_v2.0.docx
    python tools/change_request/cr.py write .work/CR-ECB-001_requirements.json
    python tools/change_request/cr.py status CR-ECB-001
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mapping_spec"))

import ba_documents  # noqa: E402
import delivery_agreement  # noqa: E402
import glossary_version  # noqa: E402
import workflow  # noqa: E402
from ba_documents import DOC_TYPES, DOCUMENT_FIELDS, Report, WriteRefused, split_ids  # noqa: E402

REPO_ROOT = ba_documents.REPO_ROOT


def _rel(path: str) -> str:
    try:
        return os.path.relpath(os.path.abspath(path), REPO_ROOT).replace(os.sep, "/")
    except ValueError:
        return path


def _load_json(path: str) -> dict:
    raw = sys.stdin.read() if path == "-" else open(path, "r", encoding="utf-8").read()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# read: any Word or Excel file as text
# ---------------------------------------------------------------------------


def docx_text(path: str) -> str:
    import docx
    from delivery_agreement import _blocks, _table_rows
    from docx.table import Table

    document = docx.Document(path)
    lines = []
    for block in _blocks(document):
        if isinstance(block, Table):
            for row in _table_rows(block):
                lines.append(" | ".join(cell.replace("\n", " / ") for cell in row))
            lines.append("")
            continue
        text = block.text.strip()
        if not text:
            continue
        style = block.style.name if block.style is not None else ""
        if style.lower().startswith("heading") or style.lower() in ("title", "subtitle"):
            level = {"title": "#", "subtitle": "##"}.get(style.lower())
            if level is None:
                digits = re.findall(r"\d", style)
                level = "#" * (int(digits[0]) + 1 if digits else 2)
            lines.append("")
            lines.append("{0} {1}".format(level, text))
        elif "list" in style.lower():
            lines.append("- " + text)
        else:
            lines.append(text)
    return "\n".join(lines).strip() + "\n"


def xlsx_text(path: str, sheet: str = None) -> str:
    from openpyxl import load_workbook

    # read_only: also opens workbooks whose Excel tables openpyxl would reject
    workbook = load_workbook(path, read_only=True, data_only=True)
    lines = []
    for ws in workbook.worksheets:
        if sheet and ws.title.lower() != sheet.lower():
            continue
        if ws.sheet_state != "visible":
            continue
        lines.append("=== sheet: {0}".format(ws.title))
        for row in ws.iter_rows(values_only=True):
            values = ["" if v is None else ba_documents._norm(v).replace("\n", " / ") for v in row]
            while values and values[-1] == "":
                values.pop()
            if values:
                lines.append(" | ".join(values))
        lines.append("")
    workbook.close()
    return "\n".join(lines)


def cmd_read(args) -> int:
    path = args.file
    if not os.path.exists(path):
        print("ERROR: no file at {0}".format(path))
        return 1
    if path.lower().endswith(".docx"):
        print(docx_text(path))
    elif path.lower().endswith((".xlsx", ".xlsm")):
        print(xlsx_text(path, args.sheet))
    else:
        print("ERROR: read handles .docx and .xlsx; read other files directly")
        return 1
    return 0


# ---------------------------------------------------------------------------
# schema / write / show for the workbooks
# ---------------------------------------------------------------------------


def cmd_schema(args) -> int:
    if args.type == "agreement":
        example = {
            "source_system": "<SYSTEM, e.g. CBS_SIM>",
            "subtitle": "<what the system is>",
            "version": "<the new version, e.g. 1.1; 1.0 for a source with no agreement yet>",
            "supersedes": "<the approved version it replaces, e.g. 1.0; empty for a new source>",
            "cr_id": "<CR-ECB-001>",
            "status": "draft | in_review  (never approved - a person does that in Word)",
            "approved_by": "", "approved_on": "",
            "based_on": "(written by the tool: the gap analysis fingerprint)",
            "purpose": ["<paragraph>"],
            "delivery_standard": [["<topic>", "<rule>"]],
            "entities_intro": "<paragraph>",
            "entities": [{
                "name": "<ENTITY, arrives in UBB_STAGING2.STG_<ENTITY>>",
                "filename": "<SYSTEM>_<ENTITY>_YYYYMMDD.csv",
                "business_key": "<ATTR or ATTR_A + ATTR_B>",
                "snapshot": "daily full",
                "change": "'' | new",
                "attributes": [{"name": "<ATTRIBUTE>", "type": "VARCHAR2(80 CHAR) | CHAR(3 CHAR) | NUMBER(20,2) | "
                                "DATE | TIMESTAMP(6)", "description": "<business meaning>",
                                "change": "'' | added | changed"}],
            }],
            "data_quality": ["<rule>"],
            "change_control": ["<paragraph>"],
            "changes": [{"change_id": "DAC-01", "entity": "<ENTITY>", "attribute": "<ATTRIBUTE, empty for "
                         "new_entity>", "change": "add_attribute | change_attribute | new_entity",
                         "reason": "<why, for the source owner>", "input_ids": "<IN-.. from the gap analysis>"}],
            "change_note": "<what changed and why, when rewriting>",
        }
        print(json.dumps(example, indent=2, ensure_ascii=False))
        print("\nStart from the current version: python tools/change_request/cr.py agreement-json <SYSTEM>")
        print("Keep every existing entity and attribute; mark additions with change 'added' and list each "
              "in 'changes'.")
        return 0
    doc_type = DOC_TYPES[args.type]
    example = {"document": {f.name: "<{0}>".format(f.help) for f in DOCUMENT_FIELDS}}
    example["document"]["Document_Type"] = doc_type.key
    example["document"]["Status"] = "draft | in_review  (never approved - a person does that in Excel)"
    for name in ("Approved_By", "Approved_On", "Revision", "Based_On", "Owner"):
        example["document"][name] = ""
    for spec in doc_type.sheets:
        example[spec.key] = [{c.name: "<{0}>".format(c.help or c.name) + (
            "  one of: " + ", ".join(c.choices) if c.choices else "") for c in spec.columns}]
    example["change_note"] = "<what changed and why - required when rewriting an existing document>"
    print(json.dumps(example, indent=2, ensure_ascii=False))
    print("\nOne row per item, IDs as shown (REQ-01, KPI-01, IN-01, ...). Multi-value cells: comma separated.")
    return 0


def cmd_write(args) -> int:
    try:
        document, messages = ba_documents.write_from_dict(_load_json(args.json_file))
    except (ValueError, json.JSONDecodeError, WriteRefused) as exc:
        print("ERROR: {0}".format(exc))
        return 1
    for message in messages:
        print(message)
    print("wrote {0} (status: {1}, revision {2}, fingerprint {3})".format(
        _rel(document.path), document.status, document.revision, document.fingerprint()))
    upstream = None
    if document.doc_type.built_from:
        upstream = ba_documents.find_document(document.cr_id, document.doc_type.built_from)
    _print_report(ba_documents.validate_document(ba_documents.read_document(document.path), upstream))
    return 0


def _print_report(report: Report) -> None:
    for warning in report.warnings:
        print("  WARN  " + warning)
    for error in report.errors:
        print("  FAIL  " + error)
    if report.ok:
        print("  OK    valid{0}".format(" ({0} warning(s))".format(len(report.warnings)) if report.warnings else ""))


def cmd_show(args) -> int:
    document = ba_documents.find_document(args.cr_id, args.type)
    if document is None:
        print("ERROR: no {0} for {1}".format(args.type, args.cr_id))
        return 1
    if args.json:
        print(json.dumps(document.to_dict(), indent=2, ensure_ascii=False))
        return 0
    print(xlsx_text(document.path))
    print("fingerprint: {0}".format(document.fingerprint()))
    return 0


# ---------------------------------------------------------------------------
# agreements
# ---------------------------------------------------------------------------


def cmd_agreement_json(args) -> int:
    if args.source.lower().endswith(".docx"):
        agreement = delivery_agreement.read_agreement(args.source)
    else:
        agreement = delivery_agreement.latest_any_status(args.source)
        if agreement is None:
            print("ERROR: no delivery agreement for {0}. A new source starts from "
                  "`cr.py schema agreement`.".format(args.source.upper()))
            return 1
    print(json.dumps(delivery_agreement.to_dict(agreement), indent=2, ensure_ascii=False))
    print("(from {0}, version {1}, {2})".format(_rel(agreement.path), agreement.version,
                                               agreement.status or "status unknown"), file=sys.stderr)
    return 0


def cmd_write_agreement(args) -> int:
    try:
        agreement, path, messages = delivery_agreement.write_from_dict(_load_json(args.json_file), args.template)
    except (ValueError, json.JSONDecodeError, WriteRefused) as exc:
        print("ERROR: {0}".format(exc))
        return 1
    for message in messages:
        print(message)
    written = delivery_agreement.read_agreement(path)
    print("wrote {0} (status: {1}, fingerprint {2})".format(_rel(path), written.status, written.fingerprint()))
    gap = ba_documents.find_document(written.cr_id, "gap_analysis")
    _print_report(delivery_agreement.validate_agreement(written, gap))
    return 0


# ---------------------------------------------------------------------------
# glossary versions
# ---------------------------------------------------------------------------


def cmd_glossary_json(args) -> int:
    glossary = glossary_version.starting_point(args.cr_id)
    if glossary is None:
        print("ERROR: no glossary in {0}".format(_rel(glossary_version.baseline_dir())))
        return 1
    print(json.dumps(glossary_version.to_dict(glossary), indent=2, ensure_ascii=False))
    origin = _rel(glossary.path) if glossary.path else "the baseline v{0}, as v{1}".format(
        glossary.supersedes, glossary.version)
    print("(from {0}, {1})".format(origin, glossary.status or "status unknown"), file=sys.stderr)
    return 0


def cmd_write_glossary(args) -> int:
    try:
        glossary, path, messages = glossary_version.write_from_dict(_load_json(args.json_file))
    except (ValueError, json.JSONDecodeError, WriteRefused) as exc:
        print("ERROR: {0}".format(exc))
        return 1
    for message in messages:
        print(message)
    written = glossary_version.read_glossary(path)
    print("wrote {0} (status: {1}, fingerprint {2})".format(_rel(path), written.status, written.fingerprint()))
    requirements = ba_documents.find_document(written.cr_id, "requirements")
    _print_report(glossary_version.validate_glossary(written, requirements))
    return 0


# ---------------------------------------------------------------------------
# validate / status / gate
# ---------------------------------------------------------------------------


def _cr_ids(arg: str) -> list:
    return [arg] if arg else ba_documents.list_cr_ids()


def cmd_validate(args) -> int:
    total = Report()
    ids = _cr_ids(args.cr_id)
    for cr_id in ids:
        state = workflow.load(cr_id)
        for name, report in sorted(state.reports.items()):
            print("{0}/{1}".format(cr_id, name))
            _print_report(report)
            total.merge(report)
    if not ids:
        print("No change requests yet (change-requests/ is empty).")
    if total.ok:
        print("OK: {0} change request(s) valid.".format(len(ids)))
        return 0
    print("\n{0} problem(s) found.".format(len(total.errors)))
    return 1


def _doc_line(label: str, document, state) -> str:
    if document is None:
        return "  {0:16} -".format(label)
    report = state.report_for(document)
    approval = ""
    if document.is_approved:
        approval = " by {0} on {1}".format(document.get("Approved_By") or "?", document.get("Approved_On") or "?")
    return "  {0:16} {1}  {2}{3}  rev {4}  {5}".format(
        label, os.path.basename(document.path), document.status or "?", approval, document.revision,
        "OK" if report.ok else "FAIL: " + report.errors[0])


def _mapping_state(mapping_id: str) -> str:
    try:
        from workbook_format import mapping_path, read_mapping
    except ImportError:  # pragma: no cover
        return "?"
    path = mapping_path(mapping_id)
    if not os.path.exists(path):
        return "not started"
    mapping = read_mapping(path)
    state = mapping.status or "?"
    if mapping.is_approved:
        state += " by {0}".format(mapping.get("Approved_By"))
    generated = [p for p in os.listdir(os.path.dirname(path)) if p.lower().endswith(".sql")]
    return "{0}{1}  ({2})".format(state, ", code generated" if generated else "", _rel(path))


def cmd_status(args) -> int:
    ids = _cr_ids(args.cr_id)
    if not ids:
        print("No change requests yet. Start one with /ba-1-analyse-requirement.")
        return 0
    for cr_id in ids:
        state = workflow.load(cr_id)
        print("{0}  ({1})".format(cr_id, _rel(ba_documents.cr_folder(cr_id))))
        print(_doc_line("1 requirements", state.requirements, state))
        print(_doc_line("2 gap analysis", state.gap_analysis, state))
        if state.agreements:
            for agreement in state.agreements:
                report = state.report_for(agreement)
                approval = " by {0} on {1}".format(agreement.approved_by, agreement.approved_on) \
                    if agreement.is_approved else ""
                print("  {0:16} {1}  {2}{3}  {4}".format(
                    "3 agreement", os.path.basename(agreement.path), agreement.status or "?", approval,
                    "OK" if report.ok else "FAIL: " + report.errors[0]))
        else:
            print("  {0:16} -".format("3 agreement"))
        for glossary in state.glossaries:
            report = state.report_for(glossary)
            approval = " by {0} on {1}".format(glossary.approved_by, glossary.approved_on)                 if glossary.status == "approved" else ""
            print("  {0:16} {1}  {2}{3}  {4}".format(
                "3 glossary", os.path.basename(glossary.path), glossary.status or "?", approval,
                "OK" if report.ok else "FAIL: " + report.errors[0]))
        if not state.glossaries:
            proposed = state.requirements is not None and state.requirements.sheet("glossary_changes")
            print("  {0:16} {1}".format("3 glossary", "-" if proposed else "- (no glossary change proposed)"))
        staging = os.path.join(ba_documents.cr_folder(cr_id), "staging")
        files = sorted(os.listdir(staging)) if os.path.isdir(staging) else []
        print("  {0:16} {1}".format("dev-1 staging", ", ".join(files) if files else "-"))
        if state.gap_analysis is not None:
            rows = sorted(state.gap_analysis.sheet("load_plan"), key=lambda r: int(r.get("Dependency_Order") or 0)
                          if (r.get("Dependency_Order") or "").isdigit() else 0)
            print("  4 mappings (Load_Plan):" if rows else "  4 mappings       - (empty Load_Plan)")
            for row in rows:
                print("      {0:>2}. {1:32} {2:36} {3}".format(row.get("Dependency_Order"), row.get("Mapping_ID"),
                                                            row.get("Target_Table"),
                                                            _mapping_state(row.get("Mapping_ID", ""))))
            tracked = [r for r in state.gap_analysis.sheet("gaps") if r.get("Level") == "not_in_source"]
            for row in tracked:
                print("  with the source owner: {0} {1} ({2}, {3})".format(
                    row.get("Input_ID"), row.get("Business_Attribute"), row.get("Responsible") or "?",
                    row.get("Status")))
        print("  next: " + _next_step(state))
        print()
    return 0


def _next_step(state) -> str:
    cr_id = state.cr_id
    if state.requirements is None or not state.approved_and_valid(state.requirements):
        what = "finish and approve" if state.requirements is not None else "write"
        return "{0} the requirements: /ba-1-analyse-requirement {1}".format(what, cr_id)
    if state.gap_analysis is None or not state.approved_and_valid(state.gap_analysis):
        what = "finish and approve" if state.gap_analysis is not None else "write"
        return "{0} the gap analysis: /ba-2-analyse-data-gaps {1}".format(what, cr_id)
    needs_agreement = any(r.get("Action") in ("delivery_change", "new_delivery")
                          for r in state.gap_analysis.sheet("gaps"))
    if needs_agreement and (not state.agreements or not all(state.approved_and_valid(a) for a in state.agreements)):
        return "write and approve the delivery agreement changes: /ba-3-specify-baseline-changes {0}".format(cr_id)
    needs_glossary = bool(state.requirements.sheet("glossary_changes"))
    glossary_done = state.glossaries and all(state.approved_and_valid(g) for g in state.glossaries)
    open_mappings = [r.get("Mapping_ID") for r in sorted(
                         state.gap_analysis.sheet("load_plan"),
                         key=lambda r: int(r.get("Dependency_Order") or 0) if (r.get("Dependency_Order") or "").isdigit() else 0)
                     if not _mapping_state(r.get("Mapping_ID", "")).startswith("approved")]
    steps = []
    if needs_glossary and not glossary_done:
        steps.append("analyst: write and have the glossary version approved: /ba-3-specify-baseline-changes "
                     "{0}".format(cr_id))
    if not workflow.gate("staging", cr_id):
        steps.append("developer: /dev-1-implement-staging-change {0}".format(cr_id))
    if open_mappings:
        steps.append("analyst: /ba-4-create-mapping-spec {0} {1} (in Load_Plan order; without a mapping ID it "
                     "drafts every mapping not started, in order)".format(cr_id, open_mappings[0]))
    else:
        steps.append("developer: /dev-2-implement-mapping <MAPPING_ID> for each mapping, in Load_Plan order, "
                     "then /dev-3-prepare-deployment <MAPPING_ID>")
    return "; ".join(steps)


def cmd_gate(args) -> int:
    problems = workflow.gate(args.step, args.cr_id, args.mapping_id or "")
    if not problems:
        print("OK: {0} may start for {1}{2}.".format(args.step, args.cr_id,
                                                     " / " + args.mapping_id if args.mapping_id else ""))
        return 0
    print("NOT YET: {0} for {1} cannot start:".format(args.step, args.cr_id))
    for problem in problems:
        print("  - " + problem)
    return 1


# ---------------------------------------------------------------------------
# trace
# ---------------------------------------------------------------------------

TRACE_HEADERS = ("Req_ID", "Requirement", "Served_By", "Input_ID", "Business_Attribute", "Level", "Action",
                 "Agreement_Change", "Mapping_IDs", "Mapping_Status", "Acceptance_Criteria")


def trace_rows(cr_id: str) -> list:
    state = workflow.load(cr_id)
    req_doc, gap_doc = state.requirements, state.gap_analysis
    if req_doc is None:
        return []
    served = {}
    inputs_of = {}
    for key, id_col in (("kpis", "KPI_ID"), ("dimensions", "Dim_ID"), ("business_rules", "Rule_ID")):
        for row in req_doc.sheet(key):
            ident = row.get(id_col, "").upper()
            for req in split_ids(row.get("Req_IDs", "")):
                served.setdefault(req, []).append(ident)
            inputs_of[ident] = split_ids(row.get("Input_IDs", ""))
    for row in req_doc.sheet("required_data"):
        for user in split_ids(row.get("Needed_For", "")):
            inputs_of.setdefault(user, [])
            if row.get("Input_ID", "").upper() not in inputs_of[user]:
                inputs_of[user].append(row.get("Input_ID", "").upper())
    names = {r.get("Input_ID", "").upper(): r.get("Business_Attribute", "") for r in req_doc.sheet("required_data")}
    gaps = {r.get("Input_ID", "").upper(): r for r in (gap_doc.sheet("gaps") if gap_doc else [])}
    plan = gap_doc.sheet("load_plan") if gap_doc else []
    changes = {}
    for agreement in state.agreements:
        for change in agreement.changes:
            for inp in split_ids(change.input_ids):
                changes.setdefault(inp, []).append("{0} v{1} {2}".format(
                    agreement.source_system, agreement.version, change.change_id))

    def criteria(mapping_id: str, req: str, inp: str) -> str:
        try:
            from workbook_format import mapping_path, read_mapping
        except ImportError:  # pragma: no cover
            return ""
        path = mapping_path(mapping_id)
        if not os.path.exists(path):
            return ""
        found = []
        for criterion in read_mapping(path).criteria:
            text = " ".join((criterion.description, criterion.notes)).upper()
            if re.search(r"\b{0}\b".format(re.escape(req)), text) or re.search(r"\b{0}\b".format(re.escape(inp)), text):
                found.append("{0}.{1}".format(mapping_id, criterion.ac_id))
        return ", ".join(found)

    rows = []
    for req in req_doc.sheet("requirements"):
        req_id = req.get("Req_ID", "").upper()
        users = served.get(req_id, [])
        inputs = []
        for user in users:
            for inp in inputs_of.get(user, []):
                if inp not in inputs:
                    inputs.append(inp)
        if not inputs:
            rows.append({"Req_ID": req_id, "Requirement": req.get("Requirement", ""),
                         "Served_By": ", ".join(users) or "(nothing)"})
            continue
        for inp in inputs:
            gap = gaps.get(inp, {})
            mappings = [r.get("Mapping_ID") for r in plan
                        if inp in split_ids(r.get("Input_IDs", "")) or r.get("Mapping_ID", "").upper()
                        in split_ids(gap.get("Mapping_IDs", ""))]
            rows.append({
                "Req_ID": req_id, "Requirement": req.get("Requirement", ""),
                "Served_By": ", ".join(u for u in users if inp in inputs_of.get(u, [])),
                "Input_ID": inp, "Business_Attribute": names.get(inp, ""),
                "Level": gap.get("Level", "(no gap row)"), "Action": gap.get("Action", ""),
                "Agreement_Change": ", ".join(changes.get(inp, [])),
                "Mapping_IDs": ", ".join(mappings),
                "Mapping_Status": "; ".join("{0}: {1}".format(m, _mapping_state(m).split("  (")[0]) for m in mappings),
                "Acceptance_Criteria": ", ".join(c for c in (criteria(m, req_id, inp) for m in mappings) if c),
            })
    return rows


def cmd_trace(args) -> int:
    rows = trace_rows(args.cr_id)
    if not rows:
        print("No approved-or-draft requirements for {0} yet.".format(args.cr_id))
        return 1
    for row in rows:
        print(" | ".join(row.get(h, "") or "-" for h in TRACE_HEADERS if h != "Requirement"))
    gaps_in_trace = [r for r in rows if not r.get("Acceptance_Criteria") and r.get("Input_ID")]
    print("\n{0} trace row(s); {1} without an acceptance criterion naming the requirement or input.".format(
        len(rows), len(gaps_in_trace)))
    if args.xlsx:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Traceability"
        sheet.append(TRACE_HEADERS)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
        for row in rows:
            sheet.append([row.get(h, "") for h in TRACE_HEADERS])
        for column, width in zip("ABCDEFGHIJK", (9, 50, 18, 9, 26, 14, 16, 28, 30, 40, 40)):
            sheet.column_dimensions[column].width = width
        for line in sheet.iter_rows(min_row=2):
            for cell in line:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        sheet.freeze_panes = "A2"
        note = workbook.create_sheet("About")
        note.append(("Generated by python tools/change_request/cr.py trace {0} --xlsx from the documents in "
                     "change-requests/{0}/ and the mapping workbooks. Do not edit: regenerate.".format(args.cr_id),))
        path = os.path.join(ba_documents.cr_folder(args.cr_id), "{0}_Traceability.xlsx".format(args.cr_id))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        workbook.save(path)
        print("wrote {0}".format(_rel(path)))
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("read", help="a .docx or .xlsx as text")
    p.add_argument("file")
    p.add_argument("--sheet", help="only this sheet of a workbook")
    p = sub.add_parser("schema", help="the JSON shape of a document")
    p.add_argument("type", choices=("requirements", "gap_analysis", "agreement"))
    p = sub.add_parser("write", help="write a requirements or gap analysis workbook from JSON")
    p.add_argument("json_file")
    p = sub.add_parser("show", help="a workbook as text or JSON")
    p.add_argument("cr_id")
    p.add_argument("type", choices=tuple(DOC_TYPES))
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("agreement-json", help="a delivery agreement as JSON")
    p.add_argument("source", help="source system (newest version) or a .docx path")
    p = sub.add_parser("write-agreement", help="write a new delivery agreement version from JSON")
    p.add_argument("json_file")
    p.add_argument("--template", help="the .docx whose styles to use (default: the system's baseline)")
    p = sub.add_parser("glossary-json", help="the glossary version a change request edits, as JSON")
    p.add_argument("cr_id")
    p = sub.add_parser("write-glossary", help="write a new glossary version from JSON")
    p.add_argument("json_file")
    p = sub.add_parser("validate", help="check the documents of one or every change request")
    p.add_argument("cr_id", nargs="?")
    p = sub.add_parser("status", help="where each change request stands")
    p.add_argument("cr_id", nargs="?")
    p = sub.add_parser("gate", help="may a step start?")
    p.add_argument("step", choices=workflow.STEPS)
    p.add_argument("cr_id")
    p.add_argument("mapping_id", nargs="?")
    p = sub.add_parser("trace", help="the traceability matrix")
    p.add_argument("cr_id")
    p.add_argument("--xlsx", action="store_true")
    args = parser.parse_args(argv)
    handlers = {
        "read": cmd_read, "schema": cmd_schema, "write": cmd_write, "show": cmd_show,
        "agreement-json": cmd_agreement_json, "write-agreement": cmd_write_agreement,
        "glossary-json": cmd_glossary_json, "write-glossary": cmd_write_glossary,
        "validate": cmd_validate, "status": cmd_status, "gate": cmd_gate, "trace": cmd_trace,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
