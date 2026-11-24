"""The scd2 load strategy: workbook rules, the fingerprint, and the generated code.

No database: the generated SQL is checked as text. Whether it compiles and
behaves is what the generated utPLSQL history tests check after deployment.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re

import pytest

import generate
import verify_mapping
from mapping_validation import validate_mapping
from workbook_format import APPROVAL_FIELDS, mapping_from_dict, mapping_to_dict


def column(name, ctype, nullable, source_column, scd_type, source_table="OWN.T_LOAN", rule="direct"):
    return {"target_column": name, "target_type": ctype, "nullable": nullable, "source_table": source_table,
            "source_column": source_column, "transformation_rule": rule, "scd_type": scd_type,
            "business_name": name.title(), "description": "The " + name.lower() + "."}


def scd2_mapping(fields=None, columns=None, **overrides):
    data = {
        "mapping": {
            "Mapping_ID": "M_T",
            "Status": "draft",
            "Target_Table": "OWN.T_OUT",
            "Table_Description": "One version of a loan.",
            "Business_Key": "LOAN_ID",
            "PLSQL_Proc": "OWN.PKG_T.LOAD_T",
            "Parameters": "P_DATE DATE",
            "Driving_Table": "OWN.T_LOAN",
            "Filter": "TRUNC(T_LOAN.CREATED_AT) <= P_DATE",
            "Load_Strategy": "scd2",
            "Source_Snapshot": "full",
            "Intent": "Loan history.",
        },
        "columns": columns or [
            column("LOAN_ID", "NUMBER(18,0)", "N", "LOAN_ID", "0"),
            column("AMOUNT", "NUMBER(20,2)", "Y", "AMOUNT", "2"),
            column("PARTNER_REF", "VARCHAR2(80 CHAR)", "Y", "PARTNER_REF", "0"),
        ],
        "joins": [],
        "acceptance_criteria": [
            {"ac_id": "AC1", "description": "Unique at every point in time", "check_type": "unique_key"},
            {"ac_id": "AC2", "description": "Re-run", "check_type": "rerun_idempotent"},
            {"ac_id": "AC3", "description": "All loaded", "check_type": "all_source_rows_loaded"},
        ],
        "sources": [],
        "decisions": [],
    }
    data["mapping"].update(fields or {})
    data.update(overrides)
    return mapping_from_dict(data)


def errors(mapping):
    return "\n".join(validate_mapping(mapping).errors)


def render(mapping):
    current, pk, source = generate.existing_target(mapping)
    plan = generate.plan_changes(mapping, generate.table_columns(mapping), current, pk, source)
    return generate.render_all(mapping, plan, datetime.date(2026, 11, 16))


# ---------------------------------------------------------------------------
# Workbook rules
# ---------------------------------------------------------------------------


def test_a_complete_scd2_mapping_validates(sql_dir):
    assert errors(scd2_mapping()) == ""


@pytest.mark.parametrize("parameters", ["P_DATE DATE; P_SYSTEM VARCHAR2(10)", "P_DATE NUMBER", "none"])
def test_scd2_needs_exactly_one_date_parameter(sql_dir, parameters):
    assert "exactly one parameter, a DATE" in errors(scd2_mapping({"Parameters": parameters}))


def test_scd2_source_must_be_read_as_of_the_date(sql_dir):
    message = errors(scd2_mapping({"Filter": "T_LOAN.AMOUNT > 0"}))
    assert "neither the Filter nor a join condition uses P_DATE" in message


def test_the_date_may_be_used_in_a_join_instead_of_the_filter(sql_dir):
    mapping = scd2_mapping(
        {"Filter": "none"},
        joins=[{"table": "OWN.T_PARTNER", "join_type": "inner",
                "condition": "T_PARTNER.CBS_REF = T_LOAN.PARTNER_REF AND T_PARTNER.VALID_FROM <= P_DATE"}],
    )
    assert "uses P_DATE" not in errors(mapping)


def test_the_date_inside_a_string_literal_does_not_count(sql_dir):
    assert "uses P_DATE" in errors(scd2_mapping({"Filter": "T_LOAN.PARTNER_REF <> 'P_DATE'"}))


@pytest.mark.parametrize("snapshot, message", [("", "needs Source_Snapshot"), ("weekly", "must be one of full, delta")])
def test_scd2_needs_a_valid_source_snapshot(sql_dir, snapshot, message):
    assert message in errors(scd2_mapping({"Source_Snapshot": snapshot}))


def test_source_snapshot_is_only_for_scd2(sql_dir):
    mapping = scd2_mapping({"Load_Strategy": "merge"}, columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "LOAN_ID", "1"),
        column("AMOUNT", "NUMBER(20,2)", "Y", "AMOUNT", "1"),
    ])
    assert "Source_Snapshot is only used by scd2" in errors(mapping)


def test_scd_type_2_needs_the_scd2_strategy(sql_dir):
    mapping = scd2_mapping({"Load_Strategy": "merge", "Source_Snapshot": ""})
    assert "SCD_Type 2 keeps history, which needs Load_Strategy scd2" in errors(mapping)


def test_scd_type_1_does_not_exist_in_an_scd2_mapping(sql_dir):
    mapping = scd2_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "LOAN_ID", "0"),
        column("AMOUNT", "NUMBER(20,2)", "Y", "AMOUNT", "2"),
        column("PARTNER_REF", "VARCHAR2(80 CHAR)", "Y", "PARTNER_REF", "1"),
    ])
    assert "PARTNER_REF) SCD_Type 1 (overwrite) does not exist in an scd2 mapping" in errors(mapping)


def test_scd2_needs_a_tracked_column(sql_dir):
    mapping = scd2_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "LOAN_ID", "0"),
        column("AMOUNT", "NUMBER(20,2)", "Y", "AMOUNT", "0"),
    ])
    assert "needs at least one tracked column" in errors(mapping)


def test_history_columns_are_not_mapped_by_hand(sql_dir):
    mapping = scd2_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "LOAN_ID", "0"),
        column("AMOUNT", "NUMBER(20,2)", "Y", "AMOUNT", "2"),
        column("VALID_FROM", "DATE", "N", "P_DATE", "0", source_table="PARAM", rule="P_DATE"),
    ])
    assert "VALID_FROM) is added by the scd2 load itself" in errors(mapping)


def test_a_tracked_parameter_column_warns(sql_dir):
    mapping = scd2_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "LOAN_ID", "0"),
        column("AMOUNT", "NUMBER(20,2)", "Y", "AMOUNT", "2"),
        column("BUSINESS_DATE", "DATE", "N", "P_DATE", "2", source_table="PARAM", rule="P_DATE"),
    ])
    assert any("every run adds a new version" in w for w in validate_mapping(mapping).warnings)


# ---------------------------------------------------------------------------
# Fingerprint: adding Source_Snapshot must not invalidate existing approvals
# ---------------------------------------------------------------------------


def test_an_empty_source_snapshot_leaves_the_fingerprint_as_before():
    mapping = scd2_mapping({"Load_Strategy": "merge", "Source_Snapshot": ""})
    data = mapping_to_dict(mapping)
    for name in APPROVAL_FIELDS + ("Source_Snapshot", "Group_By"):
        data["mapping"].pop(name)
    data.pop("item_columns")  # a sheet added later, kept out when empty
    before = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    assert mapping.fingerprint() == before


def test_a_filled_source_snapshot_is_part_of_the_fingerprint():
    full = scd2_mapping({"Source_Snapshot": "full"})
    delta = scd2_mapping({"Source_Snapshot": "delta"})
    assert full.fingerprint() != delta.fingerprint()


# ---------------------------------------------------------------------------
# Generated code
# ---------------------------------------------------------------------------


def test_scd2_table_has_history_columns_and_a_versioned_key(sql_dir):
    table = render(scd2_mapping())["table"]
    assert re.search(r"VALID_FROM +DATE NOT NULL,", table)
    assert re.search(r"VALID_TO +DATE NOT NULL,", table)
    assert re.search(r"IS_DELETED +CHAR\(1 CHAR\) NOT NULL,", table)
    assert "PRIMARY KEY (LOAN_ID, VALID_FROM)" in table
    assert "CHECK (VALID_FROM < VALID_TO)" in table
    assert "CASE WHEN VALID_TO = DATE '9999-12-31' THEN LOAN_ID END" in table


def test_scd2_writes_a_load_log_table(sql_dir):
    rendered = render(scd2_mapping())
    assert "CREATE TABLE OWN.T_OUT_LOAD_LOG" in rendered["load_log"]
    assert "load_log" in generate.output_paths(scd2_mapping(), "out")


def test_scd2_package_rewinds_and_replays(sql_dir):
    package = render(scd2_mapping())["package"]
    assert "PROCEDURE rewind(P_DATE IN DATE)" in package
    assert "PROCEDURE apply_date(P_DATE IN DATE)" in package
    assert "apply_date(l_loaded(i));" in package
    assert "SAVEPOINT SP_PKG_T;" in package and "ROLLBACK TO SAVEPOINT SP_PKG_T;" in package
    assert "DECODE(t.AMOUNT, s.AMOUNT, 0, 1) = 1" in package
    assert "DECODE(t.PARTNER_REF" not in package  # SCD_Type 0: never compared
    statements = [line.strip().upper() for line in package.splitlines() if not line.strip().startswith("--")]
    assert not any(line.startswith("COMMIT") for line in statements)


def test_full_snapshot_records_deletions_and_delta_does_not(sql_dir):
    full = render(scd2_mapping())
    delta = render(scd2_mapping({"Source_Snapshot": "delta"}))
    assert "IS_DELETED = 'Y'" in full["package"] and "a full snapshot cannot be empty" in full["package"]
    for text in (delta["package"], delta["table"]):
        assert "IS_DELETED" not in text
    assert "a full snapshot cannot be empty" not in delta["package"]


def test_scd2_tests_cover_history(sql_dir):
    rendered = render(scd2_mapping())
    tests, data = rendered["tests"], rendered["test_data"]
    for name in ("t_history_next_date", "t_history_out_of_order", "t_history_rerun_earlier_date"):
        assert "PROCEDURE {0} IS".format(name) in tests
    assert "WHERE VALID_TO = DATE '9999-12-31'" in tests  # unique_key: one current version
    assert "WHERE VALID_FROM <= P_DATE AND P_DATE < VALID_TO AND IS_DELETED = 'N'" in tests
    assert "DELETE FROM OWN.T_OUT_LOAD_LOG;" in tests
    assert "NEXT_DATE CONSTANT DATE := P_DATE + 1;" in data
    assert "PROCEDURE seed_next_date IS" in data


def test_other_strategies_are_unchanged_by_scd2(sql_dir):
    mapping = scd2_mapping({"Load_Strategy": "merge", "Source_Snapshot": "", "Filter": "none"}, columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "LOAN_ID", "1"),
        column("AMOUNT", "NUMBER(20,2)", "Y", "AMOUNT", "1"),
    ])
    rendered = render(mapping)
    assert "load_log" not in rendered
    assert "VALID_FROM" not in rendered["table"] and "PRIMARY KEY (LOAN_ID)" in rendered["table"]
    assert "rewind" not in rendered["package"] and "apply_date" not in rendered["package"]
    assert "seed_next_date" not in rendered["test_data"] and "t_history" not in rendered["tests"]


def test_an_existing_plain_table_turning_scd2_needs_a_person(sql_dir):
    mapping = scd2_mapping({"Target_Table": "OWN.T_LOAN"}, columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "LOAN_ID", "0"),
        column("AMOUNT", "NUMBER(20,2)", "Y", "AMOUNT", "2"),
    ])
    current, pk, source = generate.existing_target(mapping)
    plan = generate.plan_changes(mapping, generate.table_columns(mapping), current, pk, source)
    notes = "\n".join(plan.manual_notes)
    assert "becomes an SCD2 table" in notes
    assert "the mapping needs (LOAN_ID, VALID_FROM)" in notes


def test_verify_accepts_an_existing_scd2_table_with_the_versioned_key(sql_dir):
    mapping = scd2_mapping(
        {"Target_Table": "OWN.T_PARTNER", "Business_Key": "PARTNER_ID", "Source_Snapshot": "delta"},
        columns=[
            column("PARTNER_ID", "NUMBER(18,0)", "N", "LOAN_ID", "0"),
            column("CBS_REF", "VARCHAR2(80 CHAR)", "Y", "PARTNER_REF", "2"),
            column("PARTNER_NAME", "VARCHAR2(200 CHAR)", "N", "PARTNER_REF", "2"),
        ],
    )
    result = verify_mapping.Result()
    verify_mapping.check_target(mapping, result)
    messages = "\n".join(message for _level, message in result.lines)
    assert "primary key" not in messages
    assert "VALID_FROM is in the table script but not in the mapping" not in messages
