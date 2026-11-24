"""The change-request chain: requirements -> gap analysis -> delivery agreement
-> planned staging columns -> staging DDL, with a person's approval between
the steps.

Everything runs in temporary folders: the change requests, and a copy of the
approved baseline agreements. The table scripts are the repository's real
sql/ folder (read only). Approval is simulated the way a person does it - by
editing the cells of the Excel or Word document, never through the tools.
No test needs a database.
"""

from __future__ import annotations

import copy
import json
import os
import shutil

import docx
import pytest
from openpyxl import load_workbook

import ba_documents
import cr
import delivery_agreement
import generate_staging
import glossary_version
import schema_catalog
import source_catalog
import workflow
from ba_documents import WriteRefused

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASELINE = os.path.join(ROOT, "business-documents", "UBB_Delivery_Agreements_Approved_v1.0")
GLOSSARY = os.path.join(ROOT, "business-documents", "UBB_Credit_Risk_Business_Glossary_v0.3.xlsx")
CR_ID = "CR-TST-001"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Empty change-requests folder, a copy of the baseline agreements and glossary, the real sql/."""
    crs = tmp_path / "change-requests"
    crs.mkdir()
    baseline = tmp_path / "baseline"
    shutil.copytree(BASELINE, baseline / "agreements")
    (baseline / "glossary").mkdir()
    shutil.copy(GLOSSARY, baseline / "glossary")
    monkeypatch.setenv(glossary_version.BASELINE_ENV, str(baseline / "glossary"))
    monkeypatch.setenv(ba_documents.CR_DIR_ENV, str(crs))
    monkeypatch.setenv(delivery_agreement.BASELINE_ENV, str(baseline))
    monkeypatch.setenv(schema_catalog.PLANNED_ENV, "on")
    monkeypatch.delenv(schema_catalog.SQL_DIR_ENV, raising=False)
    schema_catalog.reload()
    yield tmp_path
    schema_catalog.reload()


def requirements_json(**changes) -> dict:
    data = {
        "document": {"CR_ID": CR_ID, "Document_Type": "requirements", "Title": "Collateral test",
                     "Status": "in_review", "Source_Documents": ["business-documents/test.docx"]},
        "requirements": [
            {"Req_ID": "REQ-01", "CR_Section": "3", "CR_Text": "Eligible collateral value",
             "Requirement": "Report recognised collateral per loan and date.", "Kind": "explicit"},
        ],
        "kpis": [
            {"KPI_ID": "KPI-01", "Name": "Eligible Allocated Collateral Value", "Definition": "Recognised value",
             "Formula": "SUM(allocated value x (1 - IN-01)) capped at IN-02", "Grain": "loan, reporting date",
             "Input_IDs": "IN-01, IN-02, IN-03", "Req_IDs": "REQ-01"},
        ],
        "required_data": [
            {"Input_ID": "IN-01", "Business_Attribute": "Regulatory haircut", "Definition": "Haircut %",
             "Needed_For": "KPI-01"},
            {"Input_ID": "IN-02", "Business_Attribute": "Outstanding principal", "Definition": "Principal",
             "Needed_For": "KPI-01"},
            {"Input_ID": "IN-03", "Business_Attribute": "Probability of default", "Definition": "PD",
             "Needed_For": "KPI-01"},
        ],
        "open_questions": [
            {"ID": "Q-01", "Question": "Haircut before or after FX?", "Answer": "Before.", "Status": "decided"},
        ],
        "sources": [{"Reference": "business-documents/test.docx section 3", "Finding": "three measures"}],
    }
    data.update(changes)
    return data


def gap_json(**changes) -> dict:
    data = {
        "document": {"CR_ID": CR_ID, "Document_Type": "gap_analysis", "Title": "Gaps", "Status": "in_review"},
        "gaps": [
            {"Input_ID": "IN-01", "Business_Attribute": "Regulatory haircut", "Level": "in_source",
             "Source_Location": "CBS_SIM / Collateral / REGULATORY_HAIRCUT_PCT", "Action": "delivery_change",
             "Mapping_IDs": "M_TST_RECOGNISED", "Responsible": "CBS_SIM source owner", "Status": "decided"},
            {"Input_ID": "IN-02", "Business_Attribute": "Outstanding principal", "Level": "in_staging",
             "Staging_Location": "UBB_STAGING2.STG_LOAN.PRINCIPAL_AMT", "Action": "mapping",
             "Mapping_IDs": "M_TST_RECOGNISED", "Status": "decided"},
            {"Input_ID": "IN-03", "Business_Attribute": "Probability of default", "Level": "in_source",
             "Source_Location": "RISK_ENGINE_SIM / Credit Risk Assessment / PROBABILITY_OF_DEFAULT",
             "Action": "new_delivery", "Mapping_IDs": "M_TST_EXPOSURE", "Status": "decided"},
        ],
        "load_plan": [
            {"Dependency_Order": "1", "Mapping_ID": "M_TST_RECOGNISED", "Target_Table": "UBB_CORE2.TST_RECOGNISED",
             "Change": "new_table", "Grain": "loan, collateral, date", "Purpose": "recognised value",
             "Input_IDs": "IN-01, IN-02", "Req_IDs": "REQ-01"},
            {"Dependency_Order": "2", "Mapping_ID": "M_TST_EXPOSURE", "Target_Table": "UBB_CORE2.EXPOSURE_HIST",
             "Change": "new_load", "Grain": "loan, date", "Purpose": "sum per loan",
             "Depends_On": "M_TST_RECOGNISED", "Input_IDs": "IN-03", "Req_IDs": "REQ-01"},
        ],
    }
    data.update(changes)
    return data


def approve_xlsx(path, by="Maria Muster", on="2026-11-17"):
    """What a person does in Excel."""
    workbook = load_workbook(path)
    sheet = workbook["Document"]
    for row in sheet.iter_rows(min_row=2):
        if row[0].value == "Status":
            row[1].value = "approved"
        elif row[0].value == "Approved_By":
            row[1].value = by
        elif row[0].value == "Approved_On":
            row[1].value = on
    workbook.save(path)


def approve_docx(path, by="Peter Owner", on="2026-11-18"):
    """What a person does in Word: the table of section 6."""
    document = docx.Document(path)
    table = document.tables[-1]
    for row in table.rows:
        name = row.cells[0].text.strip().lower()
        if name == "status":
            row.cells[1].text = "approved"
        elif name == "approved by":
            row.cells[1].text = by
        elif name == "approved on":
            row.cells[1].text = on
    document.save(path)


def write_approved_requirements():
    document, _ = ba_documents.write_from_dict(requirements_json())
    approve_xlsx(document.path)
    return document.path


def write_approved_gaps():
    write_approved_requirements()
    document, _ = ba_documents.write_from_dict(gap_json())
    approve_xlsx(document.path)
    return document.path


def cbs_v11() -> dict:
    """CBS_SIM v1.1: the baseline plus a haircut on COLLATERAL."""
    data = delivery_agreement.to_dict(delivery_agreement.latest_any_status("CBS_SIM"))
    data.update({"version": "1.1", "supersedes": "1.0", "cr_id": CR_ID, "status": "in_review",
                 "approved_by": "", "approved_on": ""})
    collateral = next(e for e in data["entities"] if e["name"] == "COLLATERAL")
    collateral["attributes"].append({"name": "REGULATORY_HAIRCUT_PCT", "type": "NUMBER(9,6)",
                                     "description": "Haircut percentage", "change": "added"})
    data["changes"] = [{"change_id": "DAC-01", "entity": "COLLATERAL", "attribute": "REGULATORY_HAIRCUT_PCT",
                        "change": "add_attribute", "reason": "CR haircut rule", "input_ids": "IN-01"}]
    return data


def risk_v10() -> dict:
    data = copy.deepcopy(delivery_agreement.to_dict(delivery_agreement.latest_any_status("FX_SIM")))
    data.update({"source_system": "RISK_ENGINE_SIM", "subtitle": "Risk engine", "version": "1.0",
                 "supersedes": "", "cr_id": CR_ID, "status": "draft", "approved_by": "", "approved_on": ""})
    data["entities"] = [{
        "name": "CREDIT_RISK_ASSESSMENT", "filename": "RISK_ENGINE_SIM_CREDIT_RISK_ASSESSMENT_YYYYMMDD.csv",
        "business_key": "ASSESSMENT_REF", "snapshot": "daily full", "change": "new",
        "attributes": [
            {"name": "ASSESSMENT_REF", "type": "VARCHAR2(80 CHAR)", "description": "Assessment id"},
            {"name": "LOAN_REF", "type": "VARCHAR2(80 CHAR)", "description": "Loan"},
            {"name": "PROBABILITY_OF_DEFAULT", "type": "NUMBER(9,6)", "description": "PD"},
        ],
    }]
    data["changes"] = [{"change_id": "DAC-01", "entity": "CREDIT_RISK_ASSESSMENT", "change": "new_entity",
                        "reason": "new interface for PD", "input_ids": "IN-03"}]
    return data


# ---------------------------------------------------------------------------
# Requirements and gap analysis workbooks
# ---------------------------------------------------------------------------


def test_requirements_round_trip_revision_and_change_log(env):
    document, _ = ba_documents.write_from_dict(requirements_json())
    assert os.path.basename(document.path) == CR_ID + "_Requirements.xlsx"
    again = ba_documents.read_document(document.path)
    assert again.fingerprint() == document.fingerprint()
    assert again.status == "in_review" and again.revision == 1
    assert again.change_log[0]["Change"] == "First version."
    assert ba_documents.validate_document(again).ok

    ba_documents.write_from_dict(requirements_json())  # unchanged: no new revision
    assert ba_documents.read_document(document.path).revision == 1

    changed = requirements_json()
    changed["requirements"][0]["Notes"] = "clarified"
    with pytest.raises(ValueError, match="change_note"):
        ba_documents.write_from_dict(changed)
    changed["change_note"] = "Clarified REQ-01."
    ba_documents.write_from_dict(changed)
    again = ba_documents.read_document(document.path)
    assert again.revision == 2 and [r["Change"] for r in again.change_log][-1] == "Clarified REQ-01."


def test_the_writer_never_records_an_approval(env):
    data = requirements_json()
    data["document"]["Status"] = "approved"
    with pytest.raises(WriteRefused):
        ba_documents.write_from_dict(data)
    data = requirements_json()
    data["document"]["Approved_By"] = "Claude"
    with pytest.raises(WriteRefused):
        ba_documents.write_from_dict(data)


def test_a_content_change_drops_the_approval(env):
    path = write_approved_requirements()
    approved = ba_documents.read_document(path)
    assert approved.is_approved and ba_documents.validate_document(approved).ok

    keep = approved.to_dict()  # rewriting the approved content as it is keeps the approval
    _document, messages = ba_documents.write_from_dict(keep)
    assert ba_documents.read_document(path).is_approved and "kept" in messages[0]

    changed = requirements_json(change_note="Added a note.")
    changed["kpis"][0]["Notes"] = "new note"
    _document, messages = ba_documents.write_from_dict(changed)
    again = ba_documents.read_document(path)
    assert again.status == "in_review" and not again.get("Approved_By")
    assert "dropped" in messages[0]


def test_requirements_references_must_resolve(env):
    data = requirements_json()
    data["kpis"][0]["Input_IDs"] = "IN-01, IN-99"
    data["required_data"][0]["Needed_For"] = "KPI-07"
    document, _ = ba_documents.write_from_dict(data)
    errors = " ".join(ba_documents.validate_document(document).errors)
    assert "IN-99" in errors and "KPI-07" in errors


def test_approval_needs_a_name_a_date_and_no_open_question(env):
    data = requirements_json()
    data["open_questions"][0]["Status"] = "open"
    document, _ = ba_documents.write_from_dict(data)
    approve_xlsx(document.path, by="", on="17.11.2026")
    errors = " ".join(ba_documents.validate_document(ba_documents.read_document(document.path)).errors)
    assert "Approved_By is empty" in errors and "YYYY-MM-DD" in errors and "Q-01" in errors


def test_an_unaccepted_suggestion_blocks_approval(env):
    data = requirements_json()
    data["kpis"][0]["Notes"] = "SUGGESTION: net of haircut - confirm with the business"
    document, _ = ba_documents.write_from_dict(data)
    approve_xlsx(document.path, by="A. Analyst", on="2026-11-17")
    errors = " ".join(ba_documents.validate_document(ba_documents.read_document(document.path)).errors)
    assert "unaccepted SUGGESTION" in errors and "KPIs row 1 Notes" in errors

    data["kpis"][0]["Notes"] = "net of haircut"  # accepted: prefix removed
    data["change_note"] = "Accepted the suggestion."
    document, _ = ba_documents.write_from_dict(data)
    approve_xlsx(document.path, by="A. Analyst", on="2026-11-17")
    assert ba_documents.validate_document(ba_documents.read_document(document.path)).ok


def test_gap_analysis_waits_for_approved_requirements(env):
    ba_documents.write_from_dict(requirements_json())
    with pytest.raises(WriteRefused, match="not approved"):
        ba_documents.write_from_dict(gap_json())


def test_gap_analysis_checks_levels_plan_and_inputs(env):
    write_approved_requirements()
    data = gap_json()
    data["gaps"][1]["Action"] = "delivery_change"  # in_staging needs mapping
    data["gaps"] = data["gaps"][:2]  # IN-03 has no row
    data["load_plan"][0]["Depends_On"] = "M_TST_EXPOSURE"  # cycle
    document, _ = ba_documents.write_from_dict(data)
    requirements = ba_documents.find_document(CR_ID, "requirements")
    errors = " ".join(ba_documents.validate_document(document, requirements).errors)
    assert "in_staging needs Action mapping" in errors
    assert "IN-03 has no Gaps row" in errors
    assert "circular dependency" in errors


def test_a_changed_requirements_document_invalidates_the_gap_analysis(env):
    write_approved_gaps()
    changed = requirements_json(change_note="New requirement.")
    changed["requirements"].append({"Req_ID": "REQ-02", "CR_Text": "x", "Requirement": "y", "Kind": "assumption"})
    changed["kpis"][0]["Req_IDs"] = "REQ-01, REQ-02"
    document, _ = ba_documents.write_from_dict(changed)
    approve_xlsx(document.path)
    problems = workflow.gate("delivery", CR_ID)
    assert any("earlier version" in p for p in problems)


# ---------------------------------------------------------------------------
# Delivery agreements
# ---------------------------------------------------------------------------


def test_baseline_agreements_are_read_as_approved(env):
    found = {a.source_system: a for a in delivery_agreement.baseline_agreements()}
    assert set(found) == {"CBS_SIM", "CRM_SIM", "FX_SIM"}
    cbs = found["CBS_SIM"]
    assert cbs.is_approved and cbs.version == "1.0" and cbs.is_baseline
    assert [e.name for e in cbs.entities][:3] == ["LOAN", "LIMIT", "COLLATERAL"]
    assert cbs.entity("LOAN_COLLATERAL_REL").key_columns == ["LOAN_REF", "COLLATERAL_REF"]
    for agreement in found.values():
        assert delivery_agreement.validate_agreement(agreement).ok


def test_a_new_agreement_version_round_trips_and_needs_approved_gaps(env):
    with pytest.raises(WriteRefused):
        delivery_agreement.write_from_dict(cbs_v11())
    write_approved_gaps()
    agreement, path, _ = delivery_agreement.write_from_dict(cbs_v11())
    assert os.path.basename(path) == "UBB_Delivery_Agreement_CBS_SIM_v1.1.docx"
    assert os.path.dirname(path) == ba_documents.cr_folder(CR_ID)
    again = delivery_agreement.read_agreement(path)
    assert again.fingerprint() == agreement.fingerprint()
    assert again.entity("COLLATERAL").attribute("REGULATORY_HAIRCUT_PCT").change == "added"
    assert again.status == "in_review"
    gap = ba_documents.find_document(CR_ID, "gap_analysis")
    assert delivery_agreement.validate_agreement(again, gap).ok


def test_a_baseline_version_is_never_overwritten(env):
    write_approved_gaps()
    data = cbs_v11()
    data["version"] = "1.0"
    with pytest.raises(WriteRefused, match="approved baseline"):
        delivery_agreement.write_from_dict(data)


def test_an_added_attribute_must_be_listed_and_typed_like_staging(env):
    write_approved_gaps()
    data = cbs_v11()
    data["changes"] = [{"change_id": "DAC-01", "entity": "LOAN", "attribute": "LOAN_REF",
                        "change": "change_attribute", "reason": "x", "input_ids": "IN-01"}]
    data["entities"][0]["attributes"].append({"name": "CCF", "type": "VARCHAR2(8)", "description": "x",
                                              "change": "added"})
    agreement, _path, _ = delivery_agreement.write_from_dict(data)
    errors = " ".join(delivery_agreement.validate_agreement(agreement).errors)
    assert "REGULATORY_HAIRCUT_PCT: marked added but has no row in changes" in errors
    assert "VARCHAR2(80 CHAR)" in errors


def test_the_writer_never_records_an_agreement_approval(env):
    write_approved_gaps()
    data = cbs_v11()
    data["status"] = "approved"
    with pytest.raises(WriteRefused):
        delivery_agreement.write_from_dict(data)


# ---------------------------------------------------------------------------
# Gates, planned staging, staging DDL
# ---------------------------------------------------------------------------


def test_mapping_gate_waits_for_the_agreements_its_inputs_need(env):
    write_approved_gaps()
    problems = workflow.gate("mapping", CR_ID, "M_TST_RECOGNISED")
    assert any("does not exist yet" in p for p in problems)
    assert workflow.gate("mapping", CR_ID, "M_NOT_PLANNED")[0].startswith("M_NOT_PLANNED is not in the Load_Plan")

    _agreement, path, _ = delivery_agreement.write_from_dict(cbs_v11())
    assert any("not approved" in p for p in workflow.gate("mapping", CR_ID, "M_TST_RECOGNISED"))
    approve_docx(path)
    assert workflow.gate("mapping", CR_ID, "M_TST_RECOGNISED") == []


def test_an_approved_agreement_plans_staging_columns(env):
    write_approved_gaps()
    _agreement, path, _ = delivery_agreement.write_from_dict(cbs_v11())
    schema_catalog.reload()
    assert "REGULATORY_HAIRCUT_PCT" not in schema_catalog.table("UBB_STAGING2.STG_COLLATERAL").columns

    approve_docx(path)
    schema_catalog.reload()
    column = schema_catalog.table("UBB_STAGING2.STG_COLLATERAL").columns["REGULATORY_HAIRCUT_PCT"]
    assert column.planned.endswith("UBB_Delivery_Agreement_CBS_SIM_v1.1.docx")
    assert column.type == "NUMBER(9,6)" and column.nullable
    # the plain sql/ folder is unchanged
    assert "REGULATORY_HAIRCUT_PCT" not in schema_catalog.load_catalog().table(
        "UBB_STAGING2.STG_COLLATERAL").columns

    attributes = source_catalog.classify([source_catalog.Attribute(
        system="CBS_SIM", entity="Collateral", dataset="STG_COLLATERAL", attribute="REGULATORY_HAIRCUT_PCT",
        business_name="", type="NUMBER(9,6)", meaning="", in_interface=False, notes="", sheet="CBS_SIM")])
    assert attributes[0].status == "planned"


def test_staging_ddl_is_generated_from_approved_agreements_only(env, capsys):
    write_approved_gaps()
    _a, cbs_path, _ = delivery_agreement.write_from_dict(cbs_v11())
    _a, risk_path, _ = delivery_agreement.write_from_dict(risk_v10())
    assert generate_staging.main([CR_ID]) == 1
    assert "not approved" in capsys.readouterr().out

    approve_docx(cbs_path)
    approve_docx(risk_path)
    assert generate_staging.main([CR_ID]) == 0
    folder = generate_staging.output_dir(CR_ID)
    assert sorted(os.listdir(folder)) == ["STG_COLLATERAL.sql", "STG_CREDIT_RISK_ASSESSMENT.sql"]

    alter = open(os.path.join(folder, "STG_COLLATERAL.sql"), encoding="utf-8").read()
    assert "ALTER TABLE UBB_STAGING2.STG_COLLATERAL ADD (" in alter
    assert "REGULATORY_HAIRCUT_PCT NUMBER(9,6)" in alter
    assert "approved by Peter Owner on 2026-11-18" in alter

    create = open(os.path.join(folder, "STG_CREDIT_RISK_ASSESSMENT.sql"), encoding="utf-8").read()
    assert "CREATE TABLE UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT (" in create
    assert "PRIMARY KEY (LOAD_ID, ASSESSMENT_REF)" in create
    assert "ASSESSMENT_REF         VARCHAR2(80 CHAR) NOT NULL" in create
    assert "REFERENCES UBB_CORE2.CTRL_LOAD (LOAD_ID)" in create
    assert "GRANT SELECT ON UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT TO UBB_CORE2;" in create

    assert generate_staging.main([CR_ID, "--check"]) == 0
    with open(os.path.join(folder, "STG_OLD.sql"), "w") as handle:
        handle.write("-- left over")
    assert generate_staging.main([CR_ID, "--check"]) == 1


def test_status_trace_and_validate_commands(env, capsys):
    write_approved_gaps()
    assert cr.main(["validate", CR_ID]) == 0
    assert cr.main(["status", CR_ID]) == 0
    out = capsys.readouterr().out
    assert "M_TST_RECOGNISED" in out and "/ba-3-specify-baseline-changes" in out
    assert cr.main(["trace", CR_ID, "--xlsx"]) == 0
    out = capsys.readouterr().out
    assert "REQ-01 | KPI-01 | IN-01" in out
    assert os.path.exists(os.path.join(ba_documents.cr_folder(CR_ID), CR_ID + "_Traceability.xlsx"))
    assert cr.main(["gate", "staging", CR_ID]) == 1


def test_schema_prints_valid_json(env, capsys):
    for kind in ("requirements", "gap_analysis", "agreement"):
        assert cr.main(["schema", kind]) == 0
        text = capsys.readouterr().out
        json.loads(text[:text.rindex("}") + 1])


# ---------------------------------------------------------------------------
# An agreement may deliver more than staging loads: staging gets only what a
# change request asks for
# ---------------------------------------------------------------------------


def _baseline_fx_with_rate_source(env):
    """Make the copied FX_SIM v1.0 baseline deliver RATE_SOURCE, which staging does not load."""
    path = os.path.join(str(env), "baseline", "agreements", "UBB_Delivery_Agreement_FX_SIM_v1.0_Approved.docx")
    fx = delivery_agreement.read_agreement(path)
    fx.entities[0].attributes.append(delivery_agreement.Attribute("RATE_SOURCE", "VARCHAR2(40 CHAR)",
                                                                  "Fixing source"))
    delivery_agreement.write_agreement(fx, path, path)
    assert delivery_agreement.read_agreement(path).is_baseline


def test_a_delivered_column_nobody_asks_for_stays_out_of_staging(env):
    _baseline_fx_with_rate_source(env)
    schema_catalog.reload()
    assert "RATE_SOURCE" not in schema_catalog.table("UBB_STAGING2.STG_FX_RATE").columns

    write_approved_gaps()
    data = cbs_v11()
    collateral = next(e for e in data["entities"] if e["name"] == "COLLATERAL")
    collateral["attributes"].append({"name": "LIEN_RANK", "type": "NUMBER(3)", "description": "Delivered, "
                                     "not loaded"})  # not marked added: not asked for
    _a, path, _ = delivery_agreement.write_from_dict(data)
    approve_docx(path)
    schema_catalog.reload()
    columns = schema_catalog.table("UBB_STAGING2.STG_COLLATERAL").columns
    assert "REGULATORY_HAIRCUT_PCT" in columns and "LIEN_RANK" not in columns
    assert generate_staging.main([CR_ID]) == 0
    text = open(os.path.join(generate_staging.output_dir(CR_ID), "STG_COLLATERAL.sql"), encoding="utf-8").read()
    assert "REGULATORY_HAIRCUT_PCT" in text and "LIEN_RANK" not in text
    assert not os.path.exists(os.path.join(generate_staging.output_dir(CR_ID), "STG_FX_RATE.sql"))


def test_an_in_interface_gap_brings_exactly_its_column_into_staging(env):
    _baseline_fx_with_rate_source(env)
    requirements = requirements_json()
    requirements["required_data"].append({"Input_ID": "IN-04", "Business_Attribute": "FX fixing source",
                                          "Definition": "x", "Needed_For": "KPI-01"})
    requirements["kpis"][0]["Input_IDs"] += ", IN-04"
    document, _ = ba_documents.write_from_dict(requirements)
    approve_xlsx(document.path)
    gaps = gap_json()
    gaps["gaps"] = gaps["gaps"][1:2] + [{
        "Input_ID": "IN-01", "Level": "in_staging", "Staging_Location": "UBB_STAGING2.STG_LOAN.PRINCIPAL_AMT",
        "Action": "mapping", "Mapping_IDs": "M_TST_RECOGNISED", "Status": "decided"}, {
        "Input_ID": "IN-03", "Level": "not_in_source", "Action": "source_owner", "Status": "tracked"}, {
        "Input_ID": "IN-04", "Level": "in_interface", "Interface_Location": "FX_SIM v1.0 3.1 FX_RATE",
        "Action": "staging_change", "Mapping_IDs": "M_TST_RECOGNISED", "Status": "decided"}]
    document, _ = ba_documents.write_from_dict(gaps)
    errors = " ".join(ba_documents.validate_document(document, ba_documents.find_document(CR_ID, "requirements")).errors)
    assert "in_interface needs Staging_Location" in errors

    gaps["gaps"][-1]["Staging_Location"] = "UBB_STAGING2.STG_FX_RATE.RATE_SOURCE"
    gaps["change_note"] = "Named the staging column."
    document, _ = ba_documents.write_from_dict(gaps)
    approve_xlsx(document.path)
    assert workflow.gate("staging", CR_ID) == []
    schema_catalog.reload()
    column = schema_catalog.table("UBB_STAGING2.STG_FX_RATE").columns["RATE_SOURCE"]
    assert column.planned.endswith("_Gap_Analysis.xlsx")
    assert generate_staging.main([CR_ID]) == 0
    folder = generate_staging.output_dir(CR_ID)
    assert os.listdir(folder) == ["STG_FX_RATE.sql"]
    text = open(os.path.join(folder, "STG_FX_RATE.sql"), encoding="utf-8").read()
    assert "RATE_SOURCE VARCHAR2(40 CHAR)" in text and "approved by (approved baseline)" in text


# ---------------------------------------------------------------------------
# Glossary versions: decided in step 1, written in step 3 after the gap analysis
# ---------------------------------------------------------------------------

GLOSSARY_CHANGES = [
    {"Change_ID": "GC-01", "Change_Type": "new_attribute", "Entity": "Collateral (EN-004)",
     "Name": "Regulatory Haircut", "Proposed_Text": "Approved haircut on a collateral valuation.",
     "Req_IDs": "REQ-01"},
    {"Change_ID": "GC-02", "Change_Type": "changed_definition", "Glossary_Ref": "AT-049",
     "Entity": "Credit Exposure (EN-011)", "Name": "Exposure Amount",
     "Proposed_Text": "Gross exposure per loan and reporting date.", "Req_IDs": "REQ-01"},
]


def write_approved_gaps_with_glossary_changes():
    document, _ = ba_documents.write_from_dict(requirements_json(glossary_changes=GLOSSARY_CHANGES))
    approve_xlsx(document.path)
    document, _ = ba_documents.write_from_dict(gap_json())
    approve_xlsx(document.path)


def glossary_v04() -> dict:
    """v0.4: the baseline with GC-01 added and GC-02 applied to AT-049."""
    baseline = glossary_version.newest_baseline()
    data = glossary_version.to_dict(glossary_version.Glossary(
        version="0.4", supersedes=baseline.version, cr_id=CR_ID, status="in_review",
        sheets=baseline.sheets, about=baseline.about))
    attributes = data["sheets"]["Business Attributes"]["rows"]
    attributes.append({"Attribute ID": "AT-053", "Entity ID": "EN-004", "Business Attribute": "Regulatory Haircut",
                       "Business Definition": "Approved haircut on a collateral valuation.",
                       "Business Data Type": "Percentage", "Definition Status": "Proposed - CR-TST-001",
                       "Business Key Role": "Non-key attribute", "Change": "added", "Change_ID": "GC-01"})
    exposure = next(r for r in attributes if r["Attribute ID"] == "AT-049")
    exposure.update({"Business Definition": "Gross exposure per loan and reporting date.",
                     "Change": "changed", "Change_ID": "GC-02"})
    return data


def _errors(glossary) -> str:
    requirements = ba_documents.find_document(CR_ID, "requirements")
    return " ".join(glossary_version.validate_glossary(glossary, requirements).errors)


def test_glossary_change_types_match_the_requirements_choices():
    sheet = next(s for s in ba_documents.REQUIREMENTS.sheets if s.key == "glossary_changes")
    choices = next(c.choices for c in sheet.columns if c.name == "Change_Type")
    assert set(glossary_version.CHANGE_TYPES) == set(choices)


def test_the_glossary_version_waits_for_an_approved_gap_analysis(env):
    document, _ = ba_documents.write_from_dict(requirements_json(glossary_changes=GLOSSARY_CHANGES))
    approve_xlsx(document.path)
    assert workflow.gate("glossary", CR_ID)
    with pytest.raises(WriteRefused, match="gap analysis"):
        glossary_version.write_from_dict(glossary_v04())

    ba_documents.write_from_dict(gap_json())  # written, but not approved yet
    assert any("gap analysis" in p for p in workflow.gate("glossary", CR_ID))
    approve_xlsx(ba_documents.find_document(CR_ID, "gap_analysis").path)
    assert workflow.gate("glossary", CR_ID) == []


def test_no_glossary_change_means_no_glossary_step(env):
    write_approved_gaps()
    assert any("no glossary change" in p for p in workflow.gate("glossary", CR_ID))


def test_a_glossary_version_round_trips_and_leaves_the_baseline_alone(env):
    write_approved_gaps_with_glossary_changes()
    start = glossary_version.starting_point(CR_ID)  # no version yet: the baseline, as the next version
    assert (start.version, start.supersedes, start.status) == ("0.4", "0.3", "in_review")
    assert not start.marked_rows()
    baseline = os.path.join(os.environ[glossary_version.BASELINE_ENV], os.path.basename(GLOSSARY))
    with open(baseline, "rb") as handle:
        before = handle.read()
    glossary, path, _ = glossary_version.write_from_dict(glossary_v04())
    assert os.path.basename(path) == "UBB_Credit_Risk_Business_Glossary_v0.4.xlsx"
    assert os.path.dirname(path) == ba_documents.cr_folder(CR_ID)
    with open(baseline, "rb") as handle:
        assert handle.read() == before

    again = glossary_version.read_glossary(path)
    assert again.fingerprint() == glossary.fingerprint() and again.status == "in_review"
    assert _errors(again) == ""
    changes = load_workbook(path)[glossary_version.CHANGES_SHEET]
    listed = [[c.value for c in row] for row in changes.iter_rows(min_row=2)]
    assert ["GC-01", "Business Attributes", "AT-053", "added", "Regulatory Haircut", None] in listed
    assert any(r[0] == "GC-02" and "Business Definition was:" in r[5] for r in listed)

    with pytest.raises(WriteRefused, match="baseline"):
        glossary_version.write_from_dict(dict(glossary_v04(), version="0.3"))


def test_every_row_of_a_glossary_version_is_checked_against_the_requirements(env):
    write_approved_gaps_with_glossary_changes()
    data = glossary_v04()
    attributes = data["sheets"]["Business Attributes"]["rows"]
    attributes[-1].update({"Change": "", "Change_ID": ""})  # GC-01 not applied, AT-053 not marked
    next(r for r in attributes if r["Attribute ID"] == "AT-001")["Business Definition"] = "silently edited"
    data["sheets"]["Entities"]["rows"].pop()  # an entry removed
    glossary, _, _ = glossary_version.write_from_dict(data)
    errors = _errors(glossary)
    assert "GC-01 of the requirements is not applied" in errors
    assert "AT-001: differs from the superseded version but is not marked changed" in errors
    assert "EN-011: removed" in errors

    data = glossary_v04()
    data["sheets"]["Business Attributes"]["rows"][-1]["Change_ID"] = "GC-99"
    glossary, _, _ = glossary_version.write_from_dict(data)
    assert "GC-99 is not on the Glossary_Changes sheet" in _errors(glossary)


def test_the_writer_never_records_a_glossary_approval_and_a_change_drops_it(env):
    write_approved_gaps_with_glossary_changes()
    with pytest.raises(WriteRefused):
        glossary_version.write_from_dict(dict(glossary_v04(), status="approved"))
    _, path, _ = glossary_version.write_from_dict(glossary_v04())
    approve_xlsx(path, by="Gloria Owner")
    approved = glossary_version.read_glossary(path)
    assert approved.status == "approved" and _errors(approved) == ""
    assert workflow.load(CR_ID).approved_and_valid(approved)

    changed = glossary_v04()
    changed["sheets"]["Business Attributes"]["rows"][-1]["Business Data Type"] = "Rate"
    _, _, messages = glossary_version.write_from_dict(changed)
    assert glossary_version.read_glossary(path).status == "in_review" and "dropped" in messages[0]


def test_changed_requirements_make_the_glossary_version_stale(env, capsys):
    write_approved_gaps_with_glossary_changes()
    _, path, _ = glossary_version.write_from_dict(glossary_v04())
    assert cr.main(["validate", CR_ID]) == 0

    changes = copy.deepcopy(GLOSSARY_CHANGES)
    changes[0]["Proposed_Text"] = "Haircut, after a gap analysis finding."
    document, _ = ba_documents.write_from_dict(requirements_json(glossary_changes=changes,
                                                                 change_note="Gap finding changed GC-01."))
    approve_xlsx(document.path)
    assert "earlier version of the requirements" in _errors(glossary_version.read_glossary(path))
    capsys.readouterr()
    assert cr.main(["status", CR_ID]) == 0
    assert "3 glossary" in capsys.readouterr().out
    assert cr.main(["validate", CR_ID]) == 1
