"""All-or-nothing loads and guards (Check_Type guard).

* Every generated load sets its own savepoint and rolls back to it on any
  error, so a failed run never leaves a partial snapshot - whatever the caller
  does with the exception.
* A guard's Check_SQL finds source rows that must stop the run. The package
  checks every guard before writing anything and raises ORA-20005; the tests
  feed it such rows and expect the target unchanged.
* The package raises and never logs; the caller logs (templates/README.md).

No database: the generated SQL is checked as text.
"""

from __future__ import annotations

import datetime
import re

import pytest

import generate
from mapping_validation import validate_mapping
from workbook_format import VALID_LOAD_STRATEGIES, mapping_from_dict

GUARD = {
    "ac_id": "AC9",
    "description": "A loan without an amount stops the run - it's not loaded half",
    "check_type": "guard",
    "check_sql": "SELECT 1 FROM OWN.T_LOAN L\nWHERE TRUNC(L.CREATED_AT) <= P_DATE AND L.AMOUNT IS NULL",
}


def column(name, ctype, nullable, source_column, scd_type="1", source_table="OWN.T_LOAN", rule="direct"):
    return {"target_column": name, "target_type": ctype, "nullable": nullable, "source_table": source_table,
            "source_column": source_column, "transformation_rule": rule, "scd_type": scd_type,
            "business_name": name.title(), "description": "The " + name.lower() + "."}


def make_mapping(strategy="full", guards=(GUARD,)):
    fields = {
        "Mapping_ID": "M_T",
        "Status": "draft",
        "Target_Table": "OWN.T_OUT",
        "Business_Key": "LOAN_ID",
        "PLSQL_Proc": "OWN.PKG_T.LOAD_T",
        "Parameters": "P_DATE DATE",
        "Driving_Table": "OWN.T_LOAN",
        "Filter": "TRUNC(T_LOAN.CREATED_AT) <= P_DATE",
        "Load_Strategy": strategy,
    }
    scd_type = "1"
    if strategy == "delete_insert":
        fields["Reload_Predicate"] = "LOAN_ID > 0"
    if strategy == "scd2":
        fields["Source_Snapshot"] = "full"
        scd_type = "2"
    criteria = [{"ac_id": "AC1", "description": "Unique", "check_type": "unique_key"}] + [dict(g) for g in guards]
    return mapping_from_dict({
        "mapping": fields,
        "columns": [
            column("LOAN_ID", "NUMBER(18,0)", "N", "LOAN_ID", "0" if strategy == "scd2" else "1"),
            column("AMOUNT", "NUMBER(20,2)", "Y", "AMOUNT", scd_type),
        ],
        "acceptance_criteria": criteria,
    })


def render(mapping):
    current, pk, source = generate.existing_target(mapping)
    plan = generate.plan_changes(mapping, generate.table_columns(mapping), current, pk, source)
    return generate.render_all(mapping, plan, datetime.date(2026, 11, 17))


def code_lines(sql):
    return [line.strip().upper() for line in sql.splitlines() if line.strip() and not line.strip().startswith("--")]


# ---------------------------------------------------------------------------
# All or nothing (every strategy)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", VALID_LOAD_STRATEGIES)
def test_every_load_rolls_back_to_its_own_savepoint_and_never_commits(sql_dir, strategy):
    package = render(make_mapping(strategy, guards=()))["package"]
    lines = code_lines(package)
    assert "SAVEPOINT SP_PKG_T;" in lines
    assert "ROLLBACK TO SAVEPOINT SP_PKG_T;" in lines
    assert lines.index("SAVEPOINT SP_PKG_T;") < next(i for i, l in enumerate(lines) if l.startswith("DBMS_APPLICATION_INFO"))
    assert not any(line.startswith("COMMIT") for line in lines)
    assert not any(line.startswith("ROLLBACK") and "TO SAVEPOINT" not in line for line in lines)
    assert "never a partial snapshot" in package


# ---------------------------------------------------------------------------
# Workbook rules
# ---------------------------------------------------------------------------


def test_a_guard_validates(sql_dir):
    assert validate_mapping(make_mapping()).errors == []


def test_a_guard_needs_check_sql(sql_dir):
    mapping = make_mapping(guards=[dict(GUARD, check_sql="")])
    assert any("(guard) needs Check_SQL" in e for e in validate_mapping(mapping).errors)


# ---------------------------------------------------------------------------
# Generated package
# ---------------------------------------------------------------------------


def test_the_package_checks_every_guard_before_writing(sql_dir):
    package = render(make_mapping("full"))["package"]
    assert "e_guard_failed EXCEPTION;" in package and "PRAGMA EXCEPTION_INIT(e_guard_failed, -20005);" in package
    assert "PROCEDURE check_guards(P_DATE IN DATE) IS" in package
    assert "WHERE TRUNC(L.CREATED_AT) <= P_DATE AND L.AMOUNT IS NULL" in package
    assert "RAISE_APPLICATION_ERROR(-20005, 'LOAD_T: guard AC9 found '" in package
    assert "'P_DATE=' || TO_CHAR(P_DATE, 'YYYY-MM-DD')" in package
    assert "it''s not loaded half" in package  # quotes in the description are escaped
    body = package[package.index("PROCEDURE LOAD_T"):]
    assert body.index("check_guards(P_DATE);") < body.index("DELETE FROM OWN.T_OUT;")


def test_without_guards_the_package_has_no_guard_code(sql_dir):
    rendered = render(make_mapping("merge", guards=()))
    assert "check_guards" not in rendered["package"] and "e_guard_failed" not in rendered["package"]
    assert "e_guard_failed" not in rendered["tests"] and "seed_ac" not in rendered["test_data"]


def test_scd2_checks_every_date_it_loads_or_replays_before_rewinding(sql_dir):
    package = render(make_mapping("scd2"))["package"]
    body = package[package.index("PROCEDURE LOAD_T"):]
    assert "check_guards(P_DATE);" in body and "check_guards(l_loaded(i));" in body
    assert body.index("check_guards(l_loaded(i));") < body.index("rewind(P_DATE);")


@pytest.mark.parametrize("parameters, expected", [
    ("P_RUN NUMBER", "'P_RUN=' || TO_CHAR(P_RUN)"),
    ("P_SYSTEM VARCHAR2(10)", "'P_SYSTEM=' || P_SYSTEM"),
])
def test_the_error_message_names_the_parameter_values(sql_dir, parameters, expected):
    mapping = make_mapping()
    mapping.fields["Parameters"] = parameters
    mapping.fields["Filter"] = "none"
    assert expected in render(mapping)["package"]


# ---------------------------------------------------------------------------
# Generated tests and test data
# ---------------------------------------------------------------------------


def test_a_guard_test_expects_a_refused_run_and_an_unchanged_target(sql_dir):
    rendered = render(make_mapping("full"))
    tests, data = rendered["tests"], rendered["test_data"]
    assert "PROCEDURE t_ac9 IS" in tests
    assert "OWN.UT_T_OUT_DATA.seed_ac9;" in tests
    assert "WHEN OWN.PKG_T.e_guard_failed THEN" in tests
    assert "PROCEDURE measure(o_rows OUT INTEGER, o_hash OUT NUMBER) IS" in tests
    assert "rows after the refused run (no partial snapshot)" in tests
    assert "PROCEDURE seed_ac9;" in data and "PROCEDURE seed_ac9 IS" in data
    seed_body = data[data.index("PROCEDURE seed_ac9 IS"):]
    assert "TODO: insert source rows that break AC9" in seed_body  # generate.py --check refuses until done
    assert "seed's data must pass every guard" in data
