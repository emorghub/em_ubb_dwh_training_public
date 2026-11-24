"""verify_mapping and the generator's change plan, against a tiny sql/ folder."""

from __future__ import annotations

import generate
import verify_mapping
from workbook_format import mapping_from_dict


def make_mapping(fields=None, **overrides):
    data = {
        "mapping": {
            "Mapping_ID": "M_T",
            "Status": "draft",
            "Target_Table": "OWN.T_OUT",
            "Business_Key": "LOAN_ID",
            "PLSQL_Proc": "OWN.PKG_T.LOAD_T",
            "Parameters": "P_DATE DATE",
            "Driving_Table": "OWN.T_LOAN",
            "Filter": "none",
            "Load_Strategy": "full",
        },
        "columns": [
            {"target_column": "LOAN_ID", "target_type": "NUMBER(18,0)", "nullable": "N", "source_table": "OWN.T_LOAN",
             "source_column": "LOAN_ID", "transformation_rule": "direct"},
            {"target_column": "AMOUNT", "target_type": "NUMBER(20,2)", "nullable": "Y", "source_table": "OWN.T_LOAN",
             "source_column": "AMOUNT", "transformation_rule": "direct"},
        ],
        "joins": [],
        "acceptance_criteria": [],
        "sources": [],
        "decisions": [],
    }
    data["mapping"].update(fields or {})
    for key, value in overrides.items():
        data[key] = value
    return mapping_from_dict(data)


def run(check, mapping, *extra):
    result = verify_mapping.Result()
    value = check(mapping, *extra, result) if extra else check(mapping, result)
    return value, result


def levels(result, level):
    return [message for lvl, message in result.lines if lvl == level]


def test_join_columns_separates_equality_from_range():
    equated, ranged = verify_mapping.join_columns(
        "P.REF = L.REF AND P.VALID_FROM <= :D AND :D < P.VALID_TO AND P.K BETWEEN L.A AND L.B", "P"
    )
    assert equated == {"REF"}
    assert ranged == {"VALID_FROM", "VALID_TO", "K"}


def test_join_columns_treats_a_literal_as_pinned():
    equated, _ranged = verify_mapping.join_columns("P.KIND = 'A' AND P.ID = L.ID", "P")
    assert equated == {"KIND", "ID"}


def test_join_on_the_full_key_cannot_multiply(sql_dir):
    mapping = make_mapping(joins=[{"table": "OWN.T_PARTNER", "join_type": "inner",
                                   "condition": "T_PARTNER.PARTNER_ID = T_LOAN.LOAN_ID AND T_PARTNER.VALID_FROM = T_LOAN.CREATED_AT"}])
    safe, result = run(verify_mapping.check_grain, mapping)
    assert safe is True
    assert levels(result, "PASS") and not levels(result, "WARN")


def test_range_join_is_flagged_as_relying_on_non_overlapping_periods(sql_dir):
    mapping = make_mapping(joins=[{"table": "OWN.T_PARTNER", "join_type": "left",
                                   "condition": "T_PARTNER.PARTNER_ID = T_LOAN.LOAN_ID AND T_PARTNER.VALID_FROM <= P_DATE"}])
    safe, result = run(verify_mapping.check_grain, mapping)
    assert safe is False
    assert "never overlap" in levels(result, "WARN")[0]


def test_join_on_a_non_key_column_may_multiply(sql_dir):
    mapping = make_mapping(joins=[{"table": "OWN.T_PARTNER", "join_type": "inner",
                                   "condition": "T_PARTNER.CBS_REF = T_LOAN.PARTNER_REF"}])
    safe, result = run(verify_mapping.check_grain, mapping)
    assert safe is False
    assert "may multiply rows" in levels(result, "WARN")[0]


def test_business_key_unique_by_construction(sql_dir):
    mapping = make_mapping()
    result = verify_mapping.Result()
    verify_mapping.check_business_key(mapping, True, result)
    assert levels(result, "PASS")


def test_missing_source_column_fails(sql_dir):
    mapping = make_mapping(columns=[
        {"target_column": "LOAN_ID", "target_type": "NUMBER(18,0)", "nullable": "N", "source_table": "OWN.T_LOAN",
         "source_column": "NO_SUCH_COLUMN", "transformation_rule": "direct"}])
    ok, result = run(verify_mapping.check_sources, mapping)
    assert ok is False
    assert "NO_SUCH_COLUMN" in levels(result, "FAIL")[0]


def test_source_with_only_a_grant_cannot_be_verified(sql_dir):
    mapping = make_mapping(fields={"Driving_Table": "STG.S_ONLY_GRANTED"})
    ok, result = run(verify_mapping.check_sources, mapping)
    assert ok is False
    assert "has no CREATE TABLE script" in levels(result, "FAIL")[0]


def test_nullable_source_into_not_null_target_warns(sql_dir):
    mapping = make_mapping(columns=[
        {"target_column": "LOAN_ID", "target_type": "NUMBER(18,0)", "nullable": "N", "source_table": "OWN.T_LOAN",
         "source_column": "LOAN_ID", "transformation_rule": "direct"},
        {"target_column": "AMOUNT", "target_type": "NUMBER(20,2)", "nullable": "N", "source_table": "OWN.T_LOAN",
         "source_column": "AMOUNT", "transformation_rule": "direct"}])
    _ok, result = run(verify_mapping.check_sources, mapping)
    assert any("allows NULL" in message for message in levels(result, "WARN"))


def test_reload_predicate_must_use_target_columns(sql_dir):
    bad = make_mapping(fields={"Load_Strategy": "delete_insert", "Reload_Predicate": "NO_SUCH = P_DATE"})
    result = verify_mapping.Result()
    verify_mapping.check_reload_predicate(bad, result)
    assert "NO_SUCH" in levels(result, "FAIL")[0]
    good = make_mapping(fields={"Load_Strategy": "delete_insert", "Reload_Predicate": "AMOUNT = P_DATE"})
    result = verify_mapping.Result()
    verify_mapping.check_reload_predicate(good, result)
    assert levels(result, "PASS")


def test_existing_target_gets_an_alter_plan_not_a_create(sql_dir):
    mapping = make_mapping(fields={"Target_Table": "OWN.T_LOAN"}, columns=[
        {"target_column": "LOAN_ID", "target_type": "NUMBER(18,0)", "nullable": "N", "source_table": "OWN.T_LOAN",
         "source_column": "LOAN_ID", "transformation_rule": "direct"},
        {"target_column": "PARTNER_REF", "target_type": "VARCHAR2(120 CHAR)", "nullable": "Y", "source_table": "OWN.T_LOAN",
         "source_column": "PARTNER_REF", "transformation_rule": "direct"},
        {"target_column": "EXTRA", "target_type": "NUMBER(5,0)", "nullable": "Y", "source_table": "EXPR",
         "source_column": "", "transformation_rule": "1"}])
    columns = generate.target_columns(mapping)
    current, pk, source = generate.existing_target(mapping)
    plan = generate.plan_changes(mapping, columns, current, pk, source)
    assert plan.table_exists
    assert [c.name for c in plan.add_columns] == ["EXTRA"]
    assert [c["name"] for c in plan.widen_columns] == ["PARTNER_REF"]
    assert "sql/ folder" in plan.compared_against


def test_new_target_gets_a_create(sql_dir):
    mapping = make_mapping()
    current, pk, source = generate.existing_target(mapping)
    plan = generate.plan_changes(mapping, generate.target_columns(mapping), current, pk, source)
    assert not plan.table_exists
