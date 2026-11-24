"""Tables and columns an earlier mapping of a change request will create."""

from __future__ import annotations

import generate
import mapping_validation
import planned_mappings
import schema_catalog
from test_verify_mapping import make_mapping


def upstream(status="in_review"):
    return make_mapping(
        {"Mapping_ID": "M_UP", "Status": status, "Target_Table": "OWN.T_UP", "Business_Key": "LOAN_ID",
         "Driving_Table": "OWN.T_LOAN"})


def test_a_new_target_becomes_a_planned_table_with_its_columns(sql_dir):
    catalog = schema_catalog.load_catalog(str(sql_dir))
    planned_mappings._add(catalog, upstream())
    table = catalog.table("OWN.T_UP")
    assert table.planned == "mapping M_UP (in_review)"
    assert list(table.columns) == ["LOAN_ID", "AMOUNT"]
    assert table.primary_key == ["LOAN_ID"]
    assert not table.columns["LOAN_ID"].nullable


def test_only_the_missing_columns_of_an_existing_target_are_planned(sql_dir):
    catalog = schema_catalog.load_catalog(str(sql_dir))
    mapping = make_mapping({"Mapping_ID": "M_UP", "Status": "approved", "Target_Table": "OWN.T_LOAN"})
    mapping.columns[1].target_column = "NEW_COLUMN"
    planned_mappings._add(catalog, mapping)
    table = catalog.table("OWN.T_LOAN")
    assert not table.planned
    assert table.columns["NEW_COLUMN"].planned == "mapping M_UP (approved)"
    assert table.columns["NEW_COLUMN"].nullable
    assert not table.columns["LOAN_ID"].planned


def test_a_mapping_cannot_be_approved_while_the_mapping_it_reads_is_not(sql_dir, monkeypatch):
    catalog = schema_catalog.load_catalog(str(sql_dir))
    planned_mappings._add(catalog, upstream("in_review"))
    monkeypatch.setattr(schema_catalog, "table", catalog.table)
    reader = make_mapping({"Mapping_ID": "M_DOWN", "Driving_Table": "OWN.T_UP", "Target_Table": "OWN.T_DOWN"})
    for col in reader.columns:
        col.source_table = "OWN.T_UP"
    assert mapping_validation._unapproved_upstream(reader, {"T_UP": "OWN.T_UP"}) == {"M_UP": "in_review"}

    catalog = schema_catalog.load_catalog(str(sql_dir))
    planned_mappings._add(catalog, upstream("approved"))
    monkeypatch.setattr(schema_catalog, "table", catalog.table)
    assert mapping_validation._unapproved_upstream(reader, {"T_UP": "OWN.T_UP"}) == {}


def test_deployed_table_ignores_planned_tables(sql_dir):
    assert schema_catalog.deployed_table("OWN.T_UP") is None


def test_only_planned_columns_the_mapping_reads_are_prerequisites(sql_dir, monkeypatch):
    catalog = schema_catalog.load_catalog(str(sql_dir))
    adder = make_mapping({"Mapping_ID": "M_UP", "Status": "in_review", "Target_Table": "OWN.T_LOAN"})
    adder.columns[1].target_column = "NEW_COLUMN"
    planned_mappings._add(catalog, adder)
    monkeypatch.setattr(schema_catalog, "table", catalog.table)

    reader = make_mapping({"Mapping_ID": "M_DOWN", "Target_Table": "OWN.T_DOWN"})
    assert generate.planned_prerequisites(reader) == []

    reader.columns[1].source_column = "NEW_COLUMN"
    assert generate.planned_prerequisites(reader) == ["mapping M_UP (in_review)"]
