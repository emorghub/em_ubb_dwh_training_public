"""Where a mapping lives: specs/<folder>/, holding its workbook <MAPPING_ID>.xlsx
and the SQL generated from it."""

from __future__ import annotations

import os

import pytest

import generate
from mapping_validation import load_mappings, validate_mapping
from validate_spec import owning_mapping
from workbook_format import list_mapping_paths, mapping_folder_name, mapping_from_dict, mapping_path, write_mapping


def test_folder_is_the_mapping_id_without_prefix_in_lower_case():
    assert mapping_folder_name("M_LOAN_LIMIT_DAILY") == "loan_limit_daily"
    assert mapping_folder_name("CUSTOMER_ACCOUNT") == "customer_account"


@pytest.mark.parametrize("mapping_id", ["M_", ""])
def test_folder_name_cannot_be_empty(mapping_id):
    with pytest.raises(ValueError):
        mapping_folder_name(mapping_id)


def test_mapping_path_puts_the_workbook_in_its_own_folder(tmp_path):
    path = mapping_path("M_LOAN_LIMIT_DAILY", str(tmp_path))
    assert path == os.path.join(str(tmp_path), "loan_limit_daily", "M_LOAN_LIMIT_DAILY.xlsx")


def _write(spec_dir, rel_path, mapping_id):
    path = os.path.join(str(spec_dir), *rel_path.split("/"))
    mapping = mapping_from_dict({"mapping": {"Mapping_ID": mapping_id, "Status": "draft"}})
    write_mapping(mapping, path)
    return path


def test_listing_reads_mapping_folders_and_skips_lock_files(tmp_path):
    good = _write(tmp_path, "loan_limit_daily/M_LOAN_LIMIT_DAILY.xlsx", "M_LOAN_LIMIT_DAILY")
    _write(tmp_path, "loan_limit_daily/~$M_LOAN_LIMIT_DAILY.xlsx", "M_LOAN_LIMIT_DAILY")
    _write(tmp_path, "M_TOP_LEVEL.xlsx", "M_TOP_LEVEL")
    assert list_mapping_paths(str(tmp_path)) == [good]


@pytest.mark.parametrize(
    "rel_path",
    ["wrong_folder/M_LOAN_LIMIT_DAILY.xlsx", "loan_limit_daily/COPY_M_LOAN_LIMIT_DAILY.xlsx"],
)
def test_a_workbook_in_the_wrong_place_fails_validation(tmp_path, rel_path):
    _write(tmp_path, rel_path, "M_LOAN_LIMIT_DAILY")
    mappings, _report = load_mappings(str(tmp_path))
    errors = validate_mapping(mappings[0]).errors
    assert any("expected specs/loan_limit_daily/M_LOAN_LIMIT_DAILY.xlsx" in e for e in errors), errors


def test_a_workbook_in_its_own_folder_passes_the_place_check(tmp_path):
    _write(tmp_path, "loan_limit_daily/M_LOAN_LIMIT_DAILY.xlsx", "M_LOAN_LIMIT_DAILY")
    mappings, _report = load_mappings(str(tmp_path))
    assert not [e for e in validate_mapping(mappings[0]).errors if "file's place" in e]


def _approved_like(tmp_path, rel_path="limit_monitor_daily/M_LIMIT_MONITOR_DAILY.xlsx"):
    path = os.path.join(str(tmp_path), *rel_path.split("/"))
    mapping = mapping_from_dict({"mapping": {
        "Mapping_ID": "M_LIMIT_MONITOR_DAILY",
        "Target_Table": "OWN.LIMIT_MONITOR_DAILY",
        "PLSQL_Proc": "OWN.PKG_LIMIT_MONITOR.LOAD",
    }})
    mapping.path = path
    return mapping


def test_generated_code_goes_flat_into_the_mapping_folder(tmp_path):
    mapping = _approved_like(tmp_path)
    folder = generate.output_dir(mapping)
    assert folder == os.path.join(str(tmp_path), "limit_monitor_daily")
    names = {kind: os.path.relpath(p, folder) for kind, p in generate.output_paths(mapping, folder).items()}
    assert names == {
        "table": "LIMIT_MONITOR_DAILY.sql",
        "change": "M_LIMIT_MONITOR_DAILY.sql",
        "package": "PKG_LIMIT_MONITOR.sql",
        "tests": "UT_LIMIT_MONITOR_DAILY.sql",
        "test_data": "UT_LIMIT_MONITOR_DAILY_DATA.sql",
    }


def test_out_dir_overrides_the_mapping_folder(tmp_path):
    other = os.path.join(str(tmp_path), "elsewhere")
    assert generate.output_dir(_approved_like(tmp_path), other) == other


def test_two_generated_files_may_not_share_a_name(tmp_path):
    mapping = _approved_like(tmp_path)
    mapping.fields["PLSQL_Proc"] = "OWN.LIMIT_MONITOR_DAILY.LOAD"  # package named like the table
    with pytest.raises(generate.GenerationError):
        generate.output_paths(mapping, generate.output_dir(mapping))


def test_a_sql_file_belongs_to_the_mapping_in_its_folder(tmp_path):
    mine = _approved_like(tmp_path)
    other = _approved_like(tmp_path, "loan_limit_daily/M_LOAN_LIMIT_DAILY.xlsx")
    folder = os.path.join(str(tmp_path), "limit_monitor_daily")
    assert owning_mapping(os.path.join(folder, "ANY_NAME.sql"), [other, mine]) is mine
    assert owning_mapping(os.path.join(str(tmp_path), "stray", "X.sql"), [other, mine]) is None
