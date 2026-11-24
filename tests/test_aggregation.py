"""Aggregating loads (Group_By): workbook rules, the verifier, and the generated code.

No database: the generated SQL is checked as text. Whether it compiles and
behaves is what the generated utPLSQL tests check after deployment.

The tiny sql/ folder (conftest.py) has T_LOAN (key LOAN_ID) and T_SPLIT (key
ID, with a LOAN_ID column): joining T_SPLIT on LOAN_ID returns several rows
per loan, which is what an aggregating mapping sums.
"""

from __future__ import annotations

import datetime
import hashlib
import json

import pytest

import generate
import sqlmodel
import verify_mapping
from mapping_validation import aggregate_spans, refs_outside_aggregates, validate_mapping
from workbook_format import APPROVAL_FIELDS, mapping_from_dict, mapping_to_dict, read_mapping, write_mapping


def column(name, ctype, nullable, source_table, source_column, rule, scd_type="1"):
    return {"target_column": name, "target_type": ctype, "nullable": nullable, "source_table": source_table,
            "source_column": source_column, "transformation_rule": rule, "scd_type": scd_type,
            "business_name": name.title(), "description": "The " + name.lower() + "."}


SPLIT_JOIN = {"table": "OWN.T_SPLIT", "join_type": "left", "condition": "T_SPLIT.LOAN_ID = T_LOAN.LOAN_ID"}


def agg_mapping(fields=None, columns=None, **overrides):
    """One row per loan and date, counting and summing the loan's T_SPLIT rows."""
    data = {
        "mapping": {
            "Mapping_ID": "M_T",
            "Status": "draft",
            "Target_Table": "OWN.T_OUT",
            "Business_Key": "LOAN_ID, BUSINESS_DATE",
            "PLSQL_Proc": "OWN.PKG_T.LOAD_T",
            "Parameters": "P_DATE DATE",
            "Driving_Table": "OWN.T_LOAN",
            "Filter": "TRUNC(T_LOAN.CREATED_AT) <= P_DATE",
            "Group_By": "LOAN_ID, BUSINESS_DATE",
            "Load_Strategy": "delete_insert",
            "Reload_Predicate": "BUSINESS_DATE = P_DATE",
        },
        "columns": columns or [
            column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
            column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
            column("SPLIT_COUNT", "NUMBER(10,0)", "N", "OWN.T_SPLIT", "ID", "COUNT(T_SPLIT.ID)"),
            column("SPLIT_ID_SUM", "NUMBER(18,0)", "Y", "OWN.T_SPLIT", "ID", "SUM(T_SPLIT.ID)"),
            column("LOAN_AMOUNT", "NUMBER(20,2)", "Y", "OWN.T_LOAN", "AMOUNT", "MAX(T_LOAN.AMOUNT)"),
        ],
        "joins": [SPLIT_JOIN],
        "acceptance_criteria": [
            {"ac_id": "AC1", "description": "One row per loan and date", "check_type": "unique_key"},
            {"ac_id": "AC2", "description": "Re-run", "check_type": "rerun_idempotent"},
        ],
        "sources": [],
        "decisions": [],
    }
    data["mapping"].update(fields or {})
    data.update(overrides)
    return mapping_from_dict(data)


def errors(mapping):
    return "\n".join(validate_mapping(mapping).errors)


def warnings(mapping):
    return "\n".join(validate_mapping(mapping).warnings)


def render(mapping):
    current, pk, source = generate.existing_target(mapping)
    plan = generate.plan_changes(mapping, generate.table_columns(mapping), current, pk, source)
    return generate.render_all(mapping, plan, datetime.date(2026, 11, 17))


def verify(check, mapping, *extra):
    result = verify_mapping.Result()
    check(mapping, *extra, result)
    return result


def messages(result, level):
    return "\n".join(message for lvl, message in result.lines if lvl == level)


# ---------------------------------------------------------------------------
# Finding aggregate calls in a rule
# ---------------------------------------------------------------------------


def test_aggregate_spans_finds_nested_calls_and_tails():
    rule = "LEAST(NVL(SUM(A.X * (1 - A.H)), 0), MAX(B.Y) KEEP (DENSE_RANK LAST ORDER BY B.D))"
    calls = [rule[s:e] for s, e in aggregate_spans(rule)]
    assert calls == ["SUM(A.X * (1 - A.H))", "MAX(B.Y) KEEP (DENSE_RANK LAST ORDER BY B.D)"]
    assert refs_outside_aggregates(rule) == []


def test_analytic_calls_and_string_literals_are_not_aggregates():
    assert aggregate_spans("SUM(A.X) OVER (PARTITION BY A.K)") == []
    assert aggregate_spans("'SUM(A.X)' || A.Y") == []
    assert aggregate_spans("GREATEST(A.X, 0)") == []
    assert refs_outside_aggregates("GREATEST(MAX(A.X) - SUM(B.Y), A.Z)") == [("A", "Z")]


# ---------------------------------------------------------------------------
# Workbook rules
# ---------------------------------------------------------------------------


def test_a_complete_aggregating_mapping_validates(sql_dir):
    assert errors(agg_mapping()) == ""


def test_every_business_key_column_must_be_grouped(sql_dir):
    assert "Business_Key column BUSINESS_DATE is not in Group_By" in errors(agg_mapping({"Group_By": "LOAN_ID"}))


def test_group_by_names_target_columns(sql_dir):
    message = errors(agg_mapping({"Group_By": "LOAN_ID, BUSINESS_DATE, NO_SUCH"}))
    assert "Group_By column NO_SUCH is not a Target_Column" in message


def test_a_direct_column_outside_group_by_is_rejected(sql_dir):
    mapping = agg_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
        column("LOAN_AMOUNT", "NUMBER(20,2)", "Y", "OWN.T_LOAN", "AMOUNT", "direct"),
    ])
    assert "LOAN_AMOUNT) copies one source value ('direct') but is not in Group_By" in errors(mapping)
    assert "MAX(T_LOAN.AMOUNT)" in errors(mapping)


def test_a_source_column_outside_an_aggregate_is_rejected(sql_dir):
    mapping = agg_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
        column("CAPPED", "NUMBER(18,0)", "Y", "OWN.T_SPLIT", "ID", "LEAST(SUM(T_SPLIT.ID), T_LOAN.AMOUNT)"),
    ])
    assert "but T_LOAN.AMOUNT is outside one" in errors(mapping)


def test_a_wrapped_source_column_is_accepted(sql_dir):
    mapping = agg_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
        column("CAPPED", "NUMBER(18,0)", "Y", "OWN.T_SPLIT", "ID", "LEAST(SUM(T_SPLIT.ID), MAX(T_LOAN.AMOUNT))"),
        column("LOADED_AT", "TIMESTAMP", "N", "EXPR", "now", "SYSTIMESTAMP"),
    ])
    assert errors(mapping) == ""


def test_a_grouped_column_must_not_aggregate(sql_dir):
    mapping = agg_mapping({"Group_By": "LOAN_ID, BUSINESS_DATE, SPLIT_COUNT"})
    assert "SPLIT_COUNT) is in Group_By, so its rule must not use an aggregate" in errors(mapping)


def test_an_aggregate_needs_group_by(sql_dir):
    message = errors(agg_mapping({"Group_By": ""}))
    assert "SPLIT_COUNT) uses an aggregate function but Group_By is empty" in message


def test_an_aggregate_in_the_filter_is_rejected(sql_dir):
    message = errors(agg_mapping({"Filter": "SUM(T_LOAN.AMOUNT) > 0"}))
    assert "Filter uses an aggregate function" in message


def test_group_by_needs_a_source_column(sql_dir):
    mapping = agg_mapping(
        {"Group_By": "BUSINESS_DATE", "Business_Key": "BUSINESS_DATE"},
        columns=[
            column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
            column("TOTAL", "NUMBER(20,2)", "Y", "OWN.T_LOAN", "AMOUNT", "SUM(T_LOAN.AMOUNT)"),
        ],
        joins=[],
    )
    assert "Group_By needs at least one column read from a source table" in errors(mapping)


def test_an_unrounded_computed_value_warns_when_merge_compares_it(sql_dir):
    def merge_with(rule):
        return agg_mapping({"Load_Strategy": "merge", "Reload_Predicate": ""}, columns=[
            column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
            column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
            column("SHARE", "NUMBER(20,2)", "Y", "OWN.T_SPLIT", "ID", rule),
        ])

    assert "SHARE) multiplies or divides without ROUND" in warnings(merge_with("SUM(T_SPLIT.ID * 0.6)"))
    assert "ROUND" not in warnings(merge_with("ROUND(SUM(T_SPLIT.ID * 0.6), 2)"))
    assert "ROUND" not in warnings(merge_with("COUNT(*)"))
    assert "ROUND" not in warnings(agg_mapping())  # delete_insert never compares


# ---------------------------------------------------------------------------
# Fingerprint: adding Group_By must not invalidate existing approvals
# ---------------------------------------------------------------------------


def test_an_empty_group_by_leaves_the_fingerprint_as_before():
    mapping = agg_mapping({"Group_By": ""})
    data = mapping_to_dict(mapping)
    for name in APPROVAL_FIELDS + ("Group_By", "Source_Snapshot"):
        data["mapping"].pop(name)
    data.pop("item_columns")  # a sheet added later, kept out when empty
    before = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    assert mapping.fingerprint() == before


def test_a_filled_group_by_is_part_of_the_fingerprint():
    assert agg_mapping().fingerprint() != agg_mapping({"Group_By": "LOAN_ID, BUSINESS_DATE, LOAN_AMOUNT"}).fingerprint()


def test_group_by_survives_a_workbook_round_trip(tmp_path):
    path = tmp_path / "M_T.xlsx"
    write_mapping(agg_mapping(), str(path))
    assert read_mapping(str(path)).group_by == ["LOAN_ID", "BUSINESS_DATE"]


# ---------------------------------------------------------------------------
# Generated code
# ---------------------------------------------------------------------------


def test_source_query_groups_by_the_source_expressions(sql_dir):
    query = sqlmodel.source_query(agg_mapping())
    assert query.rstrip().endswith("GROUP BY T_LOAN.LOAN_ID")  # P_DATE is the same on every row: not grouped
    assert "LEFT JOIN OWN.T_SPLIT T_SPLIT" in query
    assert query.index("WHERE") < query.index("GROUP BY")


def test_a_plain_mapping_has_no_group_by(sql_dir):
    mapping = agg_mapping({"Group_By": ""}, columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
    ], joins=[])
    assert "GROUP BY" not in sqlmodel.source_query(mapping)


def test_every_generated_artifact_uses_the_grouped_query(sql_dir):
    mapping = agg_mapping({"Load_Strategy": "merge", "Reload_Predicate": ""})
    rendered = render(mapping)
    package, tests = rendered["package"], rendered["tests"]
    assert "USING (" in package and "GROUP BY T_LOAN.LOAN_ID" in package
    assert "summed into one row per\n--     (LOAN_ID, BUSINESS_DATE)" in package
    assert "GROUP BY T_LOAN.LOAN_ID" in tests  # t_fixture_has_rows reads the same query


def test_test_data_asks_for_two_rows_summed_into_one(sql_dir):
    data = render(agg_mapping())["test_data"]
    assert "must become ONE target row whose aggregates cover both" in data
    assert "summed into one target row per (LOAN_ID, BUSINESS_DATE)" in data


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


def test_a_join_that_returns_several_rows_is_expected_when_aggregating(sql_dir):
    result = verify(verify_mapping.check_grain, agg_mapping())
    assert "join to T_SPLIT may return several rows per driving row" in messages(result, "INFO")
    assert messages(result, "WARN") == ""


def test_the_same_join_is_a_warning_when_not_aggregating(sql_dir):
    mapping = agg_mapping({"Group_By": ""}, columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
    ])
    assert "join to T_SPLIT may multiply rows" in messages(verify(verify_mapping.check_grain, mapping), "WARN")


def test_two_joins_that_return_several_rows_warn_of_double_counting(sql_dir):
    mapping = agg_mapping(joins=[
        SPLIT_JOIN,
        {"table": "OWN.T_PARTNER", "join_type": "left", "condition": "T_PARTNER.CBS_REF = T_LOAN.PARTNER_REF"},
    ])
    assert "double counting: the joins to T_SPLIT, T_PARTNER" in messages(
        verify(verify_mapping.check_grain, mapping), "WARN")


def test_summing_a_driving_column_over_a_join_that_returns_several_rows_warns(sql_dir):
    mapping = agg_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
        column("LOAN_AMOUNT", "NUMBER(20,2)", "Y", "OWN.T_LOAN", "AMOUNT", "SUM(T_LOAN.AMOUNT)"),
        column("SPLIT_ID_SUM", "NUMBER(18,0)", "Y", "OWN.T_SPLIT", "ID", "SUM(T_SPLIT.ID)"),
    ])
    warned = messages(verify(verify_mapping.check_grain, mapping), "WARN")
    assert "LOAN_AMOUNT: SUM(T_LOAN.AMOUNT) adds up T_LOAN" in warned
    assert "SPLIT_ID_SUM" not in warned


def test_a_business_key_equal_to_group_by_is_unique_by_construction(sql_dir):
    result = verify(verify_mapping.check_business_key, agg_mapping(), False)
    assert "is exactly Group_By" in messages(result, "PASS")


def test_grouping_by_more_than_the_key_is_reported(sql_dir):
    mapping = agg_mapping({"Group_By": "LOAN_ID, BUSINESS_DATE, LOAN_AMOUNT"}, columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
        column("LOAN_AMOUNT", "NUMBER(20,2)", "Y", "OWN.T_LOAN", "AMOUNT", "direct"),
        column("SPLIT_COUNT", "NUMBER(10,0)", "N", "OWN.T_SPLIT", "ID", "COUNT(T_SPLIT.ID)"),
    ])
    assert errors(mapping) == ""
    result = verify(verify_mapping.check_business_key, mapping, False)
    assert "Group_By also holds LOAN_AMOUNT" in messages(result, "INFO")


@pytest.mark.parametrize("strategy", ["full", "append", "merge"])
def test_aggregation_works_with_other_strategies(sql_dir, strategy):
    mapping = agg_mapping({"Load_Strategy": strategy, "Reload_Predicate": ""}, acceptance_criteria=[
        {"ac_id": "AC1", "description": "One row per loan and date", "check_type": "unique_key"},
        {"ac_id": "AC2", "description": "All loaded", "check_type": "all_source_rows_loaded"},
    ])
    assert errors(mapping) == ""
    assert "GROUP BY T_LOAN.LOAN_ID" in render(mapping)["package"]
