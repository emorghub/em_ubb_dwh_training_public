"""source_catalog.py: the source systems catalog compared with the scripts in sql/.

The tiny sql/ folder (conftest.py) has OWN.T_LOAN with LOAN_ID, PARTNER_REF,
AMOUNT and CREATED_AT. The catalog below is built per test. No database.
"""

from __future__ import annotations

import os

import pytest
from openpyxl import Workbook

import source_catalog

HEADER = ("Source System", "Source Entity", "Interface Dataset", "Attribute / File Field",
          "Business Attribute Name", "Data Type (Landing / Source)", "Business Meaning / Description",
          "In Existing Interface?", "BA Notes")
ROWS = [
    ("SYS", "Loan", "T_LOAN", "AMOUNT", "Amount", "NUMBER(20,2)", "Loan amount", "Yes - in interface", None),
    ("SYS", "Loan", "T_LOAN", "PARTNER_REF", "Partner", "VARCHAR2(80)", "Partner reference", "Yes - in interface", None),
    ("SYS", "Loan", "T_LOAN", "ALLOCATION_PRIORITY", "Priority", "NUMBER(3)",
     "Priority used if protection must be capped", "No - not in agreement", None),
    ("SYS", "Loan", "Not in current interface", "RATING", "Rating", "VARCHAR2(5)", "Loan rating",
     "No - not in agreement", None),
    ("SYS", "Loan", "T_LOAN", "VALUE_DATE", "Value date", "DATE", "Claimed delivered", "Yes - in interface", None),
    ("SYS", "Loan", "Not in current interface", "PARTNER_REF", "Partner", "VARCHAR2(80)", "Stale row",
     "No - not in agreement", None),
    ("RISK", "Assessment", "Not delivered", "PD_PCT", "Probability of default", "NUMBER(9,6)",
     "Risk model PD", "No - no interface", "Not delivered to DWH"),
]


@pytest.fixture()
def catalog_file(tmp_path, sql_dir):
    workbook = Workbook()
    readme = workbook.active
    readme.title = "README"
    readme.append(("Topic", "Description"))
    sheet = workbook.create_sheet("SYS")
    sheet.append(HEADER)
    for row in ROWS:
        sheet.append(row)
    path = tmp_path / "Catalog_Source_Systems_v1.0.xlsx"
    workbook.save(path)
    return str(path)


def by_name(path):
    attrs = source_catalog.classify(source_catalog.read_catalog(path))
    return {(a.dataset, a.attribute, a.meaning): a for a in attrs}


def status(attrs, attribute, meaning=None):
    found = [a for (d, n, m), a in attrs.items() if n == attribute and (meaning is None or m == meaning)]
    assert len(found) == 1, found
    return found[0]


def test_each_attribute_gets_a_status(catalog_file):
    attrs = by_name(catalog_file)
    assert status(attrs, "AMOUNT").status == "delivered"
    priority = status(attrs, "ALLOCATION_PRIORITY")
    assert priority.status == "interface_change" and priority.staging_table == "OWN.T_LOAN"
    assert status(attrs, "PD_PCT").status == "new_interface"


def test_an_attribute_not_in_the_interface_belongs_to_its_entitys_table(catalog_file):
    rating = status(by_name(catalog_file), "RATING")
    assert rating.dataset == "T_LOAN" and rating.status == "interface_change"


def test_a_delivered_column_staging_does_not_load_is_allowed(catalog_file):
    # An agreement may deliver columns staging does not load: not a conflict.
    value_date = status(by_name(catalog_file), "VALUE_DATE")
    assert value_date.status == "not_staged"
    assert "dev" in value_date.action or "developer" in value_date.action


def test_a_stale_duplicate_row_is_a_conflict_and_says_so(catalog_file):
    stale = status(by_name(catalog_file), "PARTNER_REF", "Stale row")
    assert stale.status == "catalog_conflict"
    assert "has the column, but the catalog says" in stale.action
    assert "lists T_LOAN.PARTNER_REF 2 times" in stale.action


def test_sql_columns_the_catalog_does_not_list(catalog_file):
    attrs = source_catalog.classify(source_catalog.read_catalog(catalog_file))
    assert source_catalog.undocumented(attrs, {"T_LOAN"}) == [("OWN.T_LOAN", "LOAN_ID"), ("OWN.T_LOAN", "CREATED_AT")]


def test_find_searches_names_and_meanings(catalog_file, capsys):
    assert source_catalog.main(["--catalog", catalog_file, "find", "capped"]) == 0
    out = capsys.readouterr().out
    assert "interface_change  OWN.T_LOAN.ALLOCATION_PRIORITY" in out
    assert "-> interface change" in out
    assert source_catalog.main(["--catalog", catalog_file, "find", "NO_SUCH_THING"]) == 1
    assert "ask the business" in capsys.readouterr().out


def test_gaps_lists_only_what_is_not_delivered(catalog_file, capsys):
    assert source_catalog.main(["--catalog", catalog_file, "gaps", "T_LOAN"]) == 0
    out = capsys.readouterr().out
    assert "6 attribute(s): 2 delivered, 0 planned, 1 not_staged, 2 interface_change, 0 new_interface, 1 catalog_conflict" in out
    assert "OWN.T_LOAN.AMOUNT" not in out
    assert "OWN.T_LOAN.LOAN_ID" in out  # in sql/, not in the catalog


def test_a_sheet_without_the_headers_is_skipped_and_none_at_all_is_an_error(tmp_path, capsys):
    workbook = Workbook()
    workbook.active.append(("Topic", "Description"))
    path = tmp_path / "empty_Source_Systems_v1.xlsx"
    workbook.save(path)
    assert source_catalog.main(["--catalog", str(path), "gaps"]) == 1
    assert "no sheet with the attribute headers" in capsys.readouterr().out


def test_the_newest_catalog_version_is_used(tmp_path, monkeypatch):
    for name in ("UBB_Source_Systems_v2.0.xlsx", "UBB_Source_Systems_v10.0.xlsx", "~$UBB_Source_Systems_v99.0.xlsx"):
        (tmp_path / name).write_bytes(b"")
    monkeypatch.delenv(source_catalog.CATALOG_ENV, raising=False)
    monkeypatch.setattr(source_catalog, "CATALOG_PATTERN", os.path.join(str(tmp_path), "*Source_Systems*.xlsx"))
    assert os.path.basename(source_catalog.default_catalog_path()) == "UBB_Source_Systems_v10.0.xlsx"
