"""The catalog reads the table scripts in sql/ and never touches a database."""

from __future__ import annotations

import os

import schema_catalog


def test_reads_columns_types_nullability_and_defaults(sql_dir):
    loan = schema_catalog.table("OWN.T_LOAN")
    assert list(loan.columns) == ["LOAN_ID", "PARTNER_REF", "AMOUNT", "CREATED_AT"]
    assert loan.columns["LOAN_ID"].type == "NUMBER(18,0)"
    assert loan.columns["PARTNER_REF"].type == "VARCHAR2(80 CHAR)"
    assert loan.columns["CREATED_AT"].type == "TIMESTAMP(6)"  # "TIMESTAMP (6)" is normalised
    assert loan.columns["LOAN_ID"].nullable is False
    assert loan.columns["AMOUNT"].nullable is True
    assert loan.columns["CREATED_AT"].default == "SYSTIMESTAMP"


def test_reads_keys_checks_and_comments(sql_dir):
    loan = schema_catalog.table("OWN.T_LOAN")
    assert loan.primary_key == ["LOAN_ID"]
    assert loan.checks == {"CK_T_LOAN": "AMOUNT >= 0"}
    assert loan.comment == "Loans; it's a test table."
    partner = schema_catalog.table("OWN.T_PARTNER")
    assert partner.primary_key == ["PARTNER_ID", "VALID_FROM"]
    assert partner.unique_keys == {"UQ_T_PARTNER_REF": ["CBS_REF", "VALID_FROM"]}
    assert partner.columns["VALID_TO"].default == "DATE '9999-12-31'"
    assert partner.unique_column_sets() == [["PARTNER_ID", "VALID_FROM"], ["CBS_REF", "VALID_FROM"]]


def test_reads_constraints_kept_in_separate_files(sql_dir):
    split = schema_catalog.table("OWN.T_SPLIT")
    assert split.primary_key == ["ID"]
    assert split.columns["ID"].nullable is False
    fk = split.foreign_keys["FK_T_SPLIT_LOAN"]
    assert (fk.columns, fk.ref_table, fk.ref_columns) == (["LOAN_ID"], "T_LOAN", ["LOAN_ID"])


def test_table_states(sql_dir):
    assert schema_catalog.table_state("OWN.T_LOAN") == "ok"
    assert schema_catalog.table_state("STG.S_ONLY_GRANTED") == "no_ddl"
    assert schema_catalog.table_state("OWN.NOPE") == "unknown"
    assert schema_catalog.columns_of("STG.S_ONLY_GRANTED") is None
    assert schema_catalog.columns_of("own.t_loan")["AMOUNT"] == "NUMBER(20,2)"
    assert schema_catalog.schemas() == {"OWN", "STG"}


def test_real_core_export_is_readable():
    """Smoke test on the repository's own sql/ folder."""
    real = schema_catalog.load_catalog(os.path.join(schema_catalog.REPO_ROOT, "sql"))
    loan_hist = real.table("UBB_CORE2.LOAN_HIST")
    assert loan_hist is not None and loan_hist.has_ddl
    assert loan_hist.primary_key == ["LOAN_ID", "LOAD_ID"]
    assert loan_hist.columns["PRINCIPAL_AMT"].type == "NUMBER(20,2)"
    assert loan_hist.foreign_keys["FK_LH_PARTNER"].ref_table == "PARTNER"
    partner_hist = real.table("UBB_CORE2.PARTNER_HIST")
    assert partner_hist.primary_key == ["PARTNER_ID", "VALID_FROM"]


def test_command_line_lists_tables_and_flags_unknown_columns(sql_dir, capsys):
    assert schema_catalog.main([]) == 0
    out = capsys.readouterr().out
    assert "OWN (3 tables)" in out and "T_LOAN" in out
    assert "S_ONLY_GRANTED  (no CREATE TABLE script: columns unknown)" in out


def test_command_line_describes_one_table(sql_dir, capsys):
    assert schema_catalog.main(["own.t_loan"]) == 0
    out = capsys.readouterr().out
    assert "primary key: LOAN_ID" in out and "check CK_T_LOAN: AMOUNT >= 0" in out
    assert schema_catalog.main(["OWN.NOPE"]) == 1
