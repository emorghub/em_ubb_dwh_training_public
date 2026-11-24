"""Item_Columns: a per-row step under an aggregating load, so a window function
(a running total) can feed an aggregate - which Oracle does not allow in one query.

The example is a priority cap: each T_SPLIT row of a loan covers only what the
rows before it (by ID, standing in for a priority) left of the loan amount.
No database: the generated SQL is checked as text.
"""

from __future__ import annotations

import datetime

import generate
import mapping_workbook
import sqlmodel
import verify_mapping
from mapping_validation import validate_mapping
from workbook_format import mapping_from_dict, read_mapping, write_mapping

PRIOR = ("NVL(SUM(T_SPLIT.ID) OVER (PARTITION BY T_SPLIT.LOAN_ID ORDER BY T_SPLIT.ID "
         "ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)")
RECOGNISED = "LEAST(T_SPLIT.ID, GREATEST(T_LOAN.AMOUNT - {0}, 0))".format(PRIOR)


def column(name, ctype, nullable, source_table, source_column, rule):
    return {"target_column": name, "target_type": ctype, "nullable": nullable, "source_table": source_table,
            "source_column": source_column, "transformation_rule": rule, "scd_type": "1",
            "business_name": name.title(), "description": "The " + name.lower() + "."}


def item(name, rule):
    return {"item_column": name, "transformation_rule": rule, "description": "The " + name.lower() + "."}


def capped_mapping(fields=None, columns=None, items=None, **overrides):
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
            "Load_Strategy": "merge",
        },
        "columns": columns or [
            column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
            column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
            column("RECOGNISED_AMT", "NUMBER(20,2)", "Y", "ITEM", "RECOGNISED", "ROUND(SUM(ITEM.RECOGNISED), 2)"),
            column("GROSS_AMT", "NUMBER(20,2)", "Y", "ITEM", "GROSS", "MAX(ITEM.GROSS)"),
        ],
        "item_columns": items if items is not None else [
            item("RECOGNISED", RECOGNISED),
            item("GROSS", "T_LOAN.AMOUNT"),
        ],
        "joins": [{"table": "OWN.T_SPLIT", "join_type": "left", "condition": "T_SPLIT.LOAN_ID = T_LOAN.LOAN_ID"}],
        "acceptance_criteria": [
            {"ac_id": "AC1", "description": "One row per loan and date", "check_type": "unique_key"},
            {"ac_id": "AC2", "description": "Re-run", "check_type": "rerun_idempotent"},
        ],
    }
    data["mapping"].update(fields or {})
    data.update(overrides)
    return mapping_from_dict(data)


def errors(mapping):
    return "\n".join(validate_mapping(mapping).errors)


def render(mapping):
    current, pk, source = generate.existing_target(mapping)
    plan = generate.plan_changes(mapping, generate.table_columns(mapping), current, pk, source)
    return generate.render_all(mapping, plan, datetime.date(2026, 11, 17))


def warns(check, mapping):
    result = verify_mapping.Result()
    check(mapping, result)
    return "\n".join(m for level, m in result.lines if level in ("WARN", "FAIL"))


# ---------------------------------------------------------------------------
# Workbook rules
# ---------------------------------------------------------------------------


def test_a_priority_cap_mapping_validates(sql_dir):
    assert errors(capped_mapping()) == ""


def test_item_columns_need_group_by(sql_dir):
    mapping = capped_mapping({"Group_By": ""}, columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
    ])
    assert "Item_Columns sheet is only used by an aggregating mapping" in errors(mapping)


def test_an_item_column_must_not_aggregate(sql_dir):
    mapping = capped_mapping(items=[item("RECOGNISED", "SUM(T_SPLIT.ID)"), item("GROSS", "T_LOAN.AMOUNT")])
    assert "RECOGNISED) uses an aggregate function" in errors(mapping)


def test_an_item_column_must_not_read_another(sql_dir):
    mapping = capped_mapping(items=[item("RECOGNISED", "ITEM.GROSS * 2"), item("GROSS", "T_LOAN.AMOUNT")])
    assert "RECOGNISED) reads another item column" in errors(mapping)


def test_an_item_rule_is_checked_against_the_sql_folder(sql_dir):
    mapping = capped_mapping(items=[item("RECOGNISED", RECOGNISED), item("GROSS", "T_LOAN.NO_SUCH")])
    assert "references T_LOAN.NO_SUCH, which does not exist in OWN.T_LOAN" in errors(mapping)


def test_an_item_column_cannot_share_a_group_by_name(sql_dir):
    mapping = capped_mapping(items=[item("LOAN_ID", "T_SPLIT.ID"), item("RECOGNISED", RECOGNISED),
                                    item("GROSS", "T_LOAN.AMOUNT")])
    assert "LOAN_ID) has the name of a Group_By column" in errors(mapping)


def test_a_target_column_outside_group_by_reads_only_item_columns(sql_dir):
    mapping = capped_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
        column("RECOGNISED_AMT", "NUMBER(20,2)", "Y", "ITEM", "RECOGNISED", "SUM(ITEM.RECOGNISED)"),
        column("GROSS_AMT", "NUMBER(20,2)", "Y", "OWN.T_LOAN", "AMOUNT", "MAX(T_LOAN.AMOUNT)"),
    ])
    assert "GROSS_AMT) reads T_LOAN directly, but with Item_Columns" in errors(mapping)


def test_unknown_item_columns_are_rejected(sql_dir):
    mapping = capped_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
        column("RECOGNISED_AMT", "NUMBER(20,2)", "Y", "ITEM", "NO_ITEM", "SUM(ITEM.NO_ITEM)"),
    ])
    message = errors(mapping)
    assert "Source_Column NO_ITEM is not on the Item_Columns sheet" in message
    assert "references ITEM.NO_ITEM, which is not on the Item_Columns sheet" in message


def test_a_group_by_column_reads_the_source_not_an_item(sql_dir):
    mapping = capped_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "ITEM", "GROSS", "ITEM.GROSS"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
        column("RECOGNISED_AMT", "NUMBER(20,2)", "Y", "ITEM", "RECOGNISED", "SUM(ITEM.RECOGNISED)"),
    ])
    assert "LOAN_ID) is in Group_By, so it reads the source tables directly, never ITEM" in errors(mapping)


def test_an_aggregate_of_an_item_needs_no_source_column_wrapper(sql_dir):
    # ITEM.RECOGNISED outside an aggregate is still caught by the Group_By rule.
    mapping = capped_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
        column("RECOGNISED_AMT", "NUMBER(20,2)", "Y", "ITEM", "RECOGNISED", "ITEM.RECOGNISED + 0"),
    ])
    assert "but ITEM.RECOGNISED is outside one" in errors(mapping)


# ---------------------------------------------------------------------------
# Workbook file and fingerprint
# ---------------------------------------------------------------------------


def test_item_columns_survive_a_workbook_round_trip(tmp_path):
    path = tmp_path / "M_T.xlsx"
    write_mapping(capped_mapping(), str(path))
    back = read_mapping(str(path))
    assert back.item_names == ["RECOGNISED", "GROSS"]
    assert back.fingerprint() == capped_mapping().fingerprint()
    assert "## Item_Columns (2)" in mapping_workbook.render_text(back)


def test_the_item_sheet_is_part_of_the_fingerprint_only_when_filled():
    assert capped_mapping().fingerprint() != capped_mapping(items=[item("GROSS", "T_LOAN.AMOUNT")]).fingerprint()
    assert "Item_Columns" not in mapping_workbook.render_text(capped_mapping(items=[]))


# ---------------------------------------------------------------------------
# Generated code
# ---------------------------------------------------------------------------


def test_the_source_query_has_a_per_row_step_under_the_grouping(sql_dir):
    query = sqlmodel.source_query(capped_mapping())
    lines = [line.strip() for line in query.splitlines()]
    assert lines[0].startswith("SELECT ITEM.LOAN_ID")
    assert "P_DATE" in lines[1] and "AS BUSINESS_DATE" in lines[1]  # a parameter stays outside
    assert "FROM (" in lines
    assert any(line.startswith("SELECT T_LOAN.LOAN_ID") and line.endswith("AS LOAN_ID,") for line in lines)
    assert "OVER (PARTITION BY T_SPLIT.LOAN_ID ORDER BY T_SPLIT.ID" in query
    assert "WHERE TRUNC(T_LOAN.CREATED_AT) <= P_DATE" in query
    assert lines[-2] == ") ITEM" and lines[-1] == "GROUP BY ITEM.LOAN_ID"
    # the aggregate is in the outer SELECT, the window function in the inner one
    assert query.index("SUM(ITEM.RECOGNISED)") < query.index("FROM (") < query.index("OVER (")


def test_the_inner_step_is_indented_under_the_outer_query(sql_dir):
    query = sqlmodel.source_query(capped_mapping())
    inner = query[query.index("FROM (") + len("FROM ("):query.index(") ITEM")]
    assert all(line.startswith("    ") for line in inner.strip("\n").splitlines())


def test_every_generated_artifact_uses_the_two_level_query(sql_dir):
    rendered = render(capped_mapping())
    assert ") ITEM" in rendered["package"] and "GROUP BY ITEM.LOAN_ID" in rendered["package"]
    assert ") ITEM" in rendered["tests"]  # t_fixture_has_rows reads the same query
    data = rendered["test_data"]
    assert "whose order matters to the Item_Columns (RECOGNISED, GROSS)" in data
    assert "AMOUNT" in data  # the item rules' source columns are seeded


def test_a_mapping_without_items_keeps_its_single_query(sql_dir):
    mapping = capped_mapping(items=[], columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
        column("SPLIT_COUNT", "NUMBER(10,0)", "N", "OWN.T_SPLIT", "ID", "COUNT(T_SPLIT.ID)"),
    ])
    query = sqlmodel.source_query(mapping)
    assert "ITEM" not in query and query.rstrip().endswith("GROUP BY T_LOAN.LOAN_ID")


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------


def test_summing_an_item_that_reads_the_driving_table_warns(sql_dir):
    mapping = capped_mapping(columns=[
        column("LOAN_ID", "NUMBER(18,0)", "N", "OWN.T_LOAN", "LOAN_ID", "direct"),
        column("BUSINESS_DATE", "DATE", "N", "PARAM", "P_DATE", "P_DATE"),
        column("RECOGNISED_AMT", "NUMBER(20,2)", "Y", "ITEM", "RECOGNISED", "SUM(ITEM.RECOGNISED)"),
        column("GROSS_AMT", "NUMBER(20,2)", "Y", "ITEM", "GROSS", "SUM(ITEM.GROSS)"),
    ])
    warned = warns(verify_mapping.check_grain, mapping)
    assert "GROSS_AMT: SUM(ITEM.GROSS) adds up T_LOAN" in warned
    assert "RECOGNISED_AMT" not in warned


def test_item_rules_are_checked_as_source_columns(sql_dir):
    mapping = capped_mapping(items=[item("RECOGNISED", RECOGNISED), item("GROSS", "T_LOAN.NO_SUCH")])
    assert "T_LOAN.NO_SUCH does not exist in OWN.T_LOAN" in warns(verify_mapping.check_sources, mapping)
