"""Where a change request stands, and whether the next step may start.

The analyst steps run in order, and each one starts only from approved work:

  ba-1-analyse-requirement      -> <CR>_Requirements.xlsx       (nothing before it)
  ba-2-analyse-data-gaps        -> <CR>_Gap_Analysis.xlsx       requirements approved
  ba-3-specify-baseline-changes  -> UBB_Delivery_Agreement_*.docx gap analysis approved
                                -> UBB_Credit_Risk_Business_Glossary_v*.xlsx
                                                                gap analysis approved, and the
                                                                requirements propose glossary changes
  ba-4-create-mapping-spec      -> specs/<folder>/<M_ID>.xlsx   gap analysis approved, the mapping
                                                                is in its Load_Plan, and every
                                                                agreement its inputs need approved
  dev-1-implement-staging-change -> change-requests/<CR>/staging/*.sql
                                                                gap analysis and agreements approved
  dev-2-implement-mapping       -> specs/<folder>/*.sql         the mapping approved
  dev-3-prepare-deployment      -> specs/<folder>/DEPLOY_*, deployment-packages/*.zip
                                                                the mapping approved and its code generated

"Approved" always also means "still valid and built from the current
version of the document before it" (Based_On). No database is involved.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mapping_spec"))

import ba_documents  # noqa: E402
import delivery_agreement  # noqa: E402
import glossary_version  # noqa: E402
from ba_documents import Report, split_ids  # noqa: E402
from workbook_format import mapping_path, read_mapping  # noqa: E402

STEPS = ("requirements", "gaps", "delivery", "glossary", "staging", "mapping")
SKILL_FOR_STEP = {
    "requirements": "/ba-1-analyse-requirement",
    "gaps": "/ba-2-analyse-data-gaps",
    "delivery": "/ba-3-specify-baseline-changes",
    "glossary": "/ba-3-specify-baseline-changes",
    "staging": "/dev-1-implement-staging-change",
    "mapping": "/ba-4-create-mapping-spec",
}


@dataclass
class State:
    cr_id: str
    requirements: object = None
    gap_analysis: object = None
    agreements: list = field(default_factory=list)  # this CR's agreement versions
    glossaries: list = field(default_factory=list)  # this CR's glossary versions
    reports: dict = field(default_factory=dict)  # file name -> Report

    def report_for(self, document) -> Report:
        return self.reports.get(os.path.basename(document.path), Report())

    def approved_and_valid(self, document) -> bool:
        return document is not None and document.is_approved and self.report_for(document).ok


def load(cr_id: str) -> State:
    state = State(cr_id=cr_id)
    state.requirements = ba_documents.find_document(cr_id, "requirements")
    state.gap_analysis = ba_documents.find_document(cr_id, "gap_analysis")
    state.agreements = delivery_agreement.cr_agreements(cr_id)
    state.glossaries = glossary_version.cr_glossaries(cr_id)
    if state.requirements is not None:
        state.reports[os.path.basename(state.requirements.path)] = ba_documents.validate_document(state.requirements)
    if state.gap_analysis is not None:
        state.reports[os.path.basename(state.gap_analysis.path)] = ba_documents.validate_document(
            state.gap_analysis, state.requirements)
    for agreement in state.agreements:
        state.reports[os.path.basename(agreement.path)] = delivery_agreement.validate_agreement(
            agreement, state.gap_analysis)
    for glossary in state.glossaries:
        state.reports[os.path.basename(glossary.path)] = glossary_version.validate_glossary(
            glossary, state.requirements)
    return state


def _require(document, title: str, state: State, problems: list) -> None:
    if document is None:
        problems.append("there is no {0} for {1} yet".format(title, state.cr_id))
    elif not document.is_approved:
        problems.append("the {0} ({1}) is '{2}', not approved".format(
            title, os.path.basename(document.path), document.status or "?"))
    else:
        report = state.report_for(document)
        if not report.ok:
            problems.append("the {0} is approved but not valid: {1}".format(title, report.errors[0]))


def gap_rows_for(state: State, mapping_id: str) -> list:
    """Gaps rows whose input the Load_Plan row of mapping_id uses."""
    if state.gap_analysis is None:
        return []
    plan = next((r for r in state.gap_analysis.sheet("load_plan")
                 if r.get("Mapping_ID", "").upper() == mapping_id.upper()), None)
    if plan is None:
        return []
    inputs = set(split_ids(plan.get("Input_IDs", "")))
    rows = state.gap_analysis.sheet("gaps")
    return [r for r in rows if r.get("Input_ID", "").upper() in inputs
            or mapping_id.upper() in split_ids(r.get("Mapping_IDs", ""))]


def source_system_of(row: dict) -> str:
    """SYSTEM from 'SYSTEM / Entity / ATTRIBUTE' (Source_Location)."""
    location = row.get("Source_Location", "") or row.get("Interface_Location", "")
    return location.split("/")[0].split()[0].strip().upper() if location.strip() else ""


@dataclass
class StagingRequest:
    """Columns a change request asks staging to receive, for one delivery entity."""

    agreement: object  # delivery_agreement.Agreement
    entity: object  # delivery_agreement.Entity
    attributes: set = None  # attribute names; None = every attribute (a new entity)
    origin: str = ""  # the approved document that asks for them


def staging_table_of(entity_name: str) -> str:
    return "STG_" + entity_name.upper()


def staging_requests(state: State) -> tuple:
    """(requests, problems). Staging receives only what a change request asks
    for - an agreement may deliver columns staging does not load:

    - every attribute an approved agreement version of this CR marks added or
      changed, and every attribute of an entity it marks new;
    - every in_interface row of the approved gap analysis: its
      Staging_Location (SCHEMA.STG_<ENTITY>.ATTRIBUTE) names an attribute the
      current approved agreement already delivers.
    """
    problems = []
    requests = []
    own = {}
    for agreement in state.agreements:
        if not agreement.is_approved:
            problems.append("{0} is '{1}', not approved".format(os.path.basename(agreement.path),
                                                               agreement.status or "?"))
            continue
        if not state.report_for(agreement).ok:
            problems.append("{0} is approved but not valid: {1}".format(
                os.path.basename(agreement.path), state.report_for(agreement).errors[0]))
            continue
        own[agreement.source_system] = agreement
        for entity in agreement.entities:
            if entity.change == "new":
                requests.append(StagingRequest(agreement, entity, None, agreement.path))
                continue
            names = {a.name.upper() for a in entity.attributes if a.change in ("added", "changed")}
            if names:
                requests.append(StagingRequest(agreement, entity, names, agreement.path))
    gap = state.gap_analysis
    if gap is not None and gap.is_approved and state.report_for(gap).ok:
        current = delivery_agreement.current_agreements()
        for row in gap.sheet("gaps"):
            if row.get("Level") != "in_interface":
                continue
            system = source_system_of(row)
            agreement = own.get(system) or current.get(system)
            parts = row.get("Staging_Location", "").upper().split(".")
            if agreement is None:
                problems.append("gap {0} is in_interface, but no approved delivery agreement of '{1}' was found "
                                "(Interface_Location must start with the source system)".format(
                                    row.get("Input_ID"), system or "?"))
                continue
            if len(parts) != 3:
                problems.append("gap {0}: Staging_Location must be SCHEMA.STG_<ENTITY>.ATTRIBUTE".format(
                    row.get("Input_ID")))
                continue
            entity = next((e for e in agreement.entities if staging_table_of(e.name) == parts[1]), None)
            if entity is None or entity.attribute(parts[2]) is None:
                problems.append("gap {0}: {1} v{2} delivers no {3} (the staging table {4} receives entity "
                                "{5})".format(row.get("Input_ID"), agreement.source_system, agreement.version,
                                              parts[2], parts[1], parts[1][4:]))
                continue
            requests.append(StagingRequest(agreement, entity, {parts[2]}, gap.path))
    return requests, problems


def _workbook_status(mapping_id: str) -> str:
    """Status of specs/<folder>/<mapping_id>.xlsx, '' when there is none or it cannot be read."""
    try:
        path = mapping_path(mapping_id)
        return read_mapping(path).status if os.path.exists(path) else ""
    except Exception:  # validate_spec reports an unreadable workbook
        return ""


def gate(step: str, cr_id: str, mapping_id: str = "") -> list:
    """Problems that stop `step` from starting; empty when it may start."""
    if step not in STEPS:
        return ["unknown step '{0}' (one of {1})".format(step, ", ".join(STEPS))]
    if not ba_documents.CR_ID_PATTERN.match(cr_id or ""):
        return ["'{0}' is not a change request ID like CR-ECB-001".format(cr_id)]
    state = load(cr_id)
    problems = []
    if step == "requirements":
        return problems
    _require(state.requirements, "requirements", state, problems)
    if step == "gaps":
        return problems
    _require(state.gap_analysis, "gap analysis", state, problems)
    if problems:
        return problems
    if step == "delivery":
        needed = [r for r in state.gap_analysis.sheet("gaps") if r.get("Action") in ("delivery_change", "new_delivery")]
        if not needed:
            problems.append("the gap analysis has no input with Action delivery_change or new_delivery - no "
                            "delivery agreement has to change")
        return problems
    if step == "glossary":
        if not state.requirements.sheet("glossary_changes"):
            problems.append("the requirements propose no glossary change (Glossary_Changes is empty) - no "
                            "glossary version to write")
        return problems
    if step == "staging":
        requests, more = staging_requests(state)
        problems += more
        if not requests and not more:
            problems.append("no approved delivery agreement version of {0} and no in_interface gap: no staging "
                            "change to generate".format(cr_id))
        return problems
    # mapping
    plan_ids = state.gap_analysis.ids("load_plan")
    if not mapping_id:
        problems.append("name the mapping: one of the Load_Plan's {0}".format(", ".join(plan_ids) or "(none)"))
        return problems
    if mapping_id.upper() not in plan_ids:
        problems.append("{0} is not in the Load_Plan of the gap analysis ({1}). Add it there first (ba-2), so "
                        "the plan stays the list of everything the CR loads.".format(
                            mapping_id, ", ".join(plan_ids) or "empty"))
        return problems
    current = delivery_agreement.current_agreements()
    own = {a.source_system: a for a in state.agreements}
    plan_row = next(r for r in state.gap_analysis.sheet("load_plan") if r.get("Mapping_ID", "").upper() == mapping_id.upper())
    for dependency in split_ids(plan_row.get("Depends_On", "")):
        status = _workbook_status(dependency)
        if status not in ("in_review", "approved"):
            problems.append("{0} reads the table of {1}, which has no mapping workbook yet ({2}): run "
                            "/ba-4-create-mapping-spec {3} {1} first".format(
                                mapping_id, dependency, "status " + status if status else "not started", cr_id))
    for row in gap_rows_for(state, mapping_id):
        if row.get("Action") in ("delivery_change", "new_delivery"):
            system = source_system_of(row)
            agreement = own.get(system)
            if agreement is None:
                problems.append("input {0} needs a new version of the {1} delivery agreement, which does not "
                                "exist yet (/ba-3-specify-baseline-changes)".format(row.get("Input_ID"), system or "?"))
            elif not (agreement.is_approved and state.report_for(agreement).ok):
                problems.append("input {0} needs {1}, which is '{2}'{3}".format(
                    row.get("Input_ID"), os.path.basename(agreement.path), agreement.status or "?",
                    "" if agreement.is_approved else ", not approved"))
        elif row.get("Action") == "staging_change" and source_system_of(row) not in current:
            problems.append("input {0} is delivered but no approved agreement of {1} was found".format(
                row.get("Input_ID"), source_system_of(row) or "?"))
        elif row.get("Level") == "not_in_source":
            problems.append("input {0} is not in any source system (taken to the source owner): this mapping "
                            "cannot read it until a source delivers it".format(row.get("Input_ID")))
        elif row.get("Level") == "conflict" and row.get("Status") != "decided":
            problems.append("input {0}: the documents disagree and it is not clarified".format(row.get("Input_ID")))
    return problems
