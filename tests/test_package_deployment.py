"""The deployment package (tools/codegen/package_deployment.py): a zip that
deploys the same way from Windows and from Linux.

No database and no generated code are needed: the tests pack small items.
"""

from __future__ import annotations

import datetime
import zipfile

import pytest

import package_deployment as pkg
from workbook_format import mapping_from_dict


def make_mapping(proc_schema="UBB_CORE2", driving="UBB_STAGING2.STG_LOAN", joins=("UBB_CORE2.CTRL_LOAD",)):
    return mapping_from_dict({
        "mapping": {
            "Mapping_ID": "M_T",
            "Status": "approved",
            "Approved_By": "A Person",
            "Approved_On": "2026-11-21",
            "Source_Ref": "CR-X-001 Load_Plan M_T",
            "Target_Table": "UBB_CORE2.T_OUT",
            "PLSQL_Proc": proc_schema + ".PKG_T.LOAD_T",
            "Parameters": "P_DATE DATE",
            "Driving_Table": driving,
        },
        "joins": [{"table": table, "join_type": "inner", "condition": "1 = 1"} for table in joins],
    })


def items():
    return [
        pkg.Item("RUNBOOK.md", b"# runbook\n", "runbook"),
        pkg.Item("code/PKG_T.sql", b"CREATE OR REPLACE PACKAGE X;\n", "package"),
        pkg.Item("test/UT_T.sql", b"-- tests\n", "tests", ("TEST",), "test environment only"),
    ]


def test_text_gets_lf_endings_and_loses_a_byte_order_mark():
    assert pkg.clean_text(b"\xef\xbb\xbfBEGIN\r\n  NULL;\r\nEND;\r\n") == b"BEGIN\n  NULL;\nEND;\n"


def test_grants_cover_only_source_tables_of_another_schema_and_split_the_test_grant():
    found = pkg.grants_items(make_mapping())
    by_name = {item.arc: item.data.decode() for item in found}
    assert set(by_name) == {"grants/grants_select.sql", "grants/grants_test_only_insert.sql"}
    assert "GRANT SELECT ON UBB_STAGING2.STG_LOAN TO UBB_CORE2;" in by_name["grants/grants_select.sql"]
    assert "UBB_CORE2.CTRL_LOAD" not in "".join(by_name.values())
    assert "INSERT" not in by_name["grants/grants_select.sql"].replace("-- ", "")
    assert [item.environments for item in found] == [("TEST", "PROD"), ("TEST",)]


def test_no_grant_files_when_every_source_is_in_the_package_schema():
    assert pkg.grants_items(make_mapping(driving="UBB_CORE2.LOAN")) == []


def test_files_are_placed_by_role_with_the_runbook_at_the_top(tmp_path, monkeypatch):
    monkeypatch.setattr(pkg, "REPO_ROOT", str(tmp_path))
    folder = tmp_path / "specs" / "x"
    folder.mkdir(parents=True)
    (folder / "DEPLOY_M_T_RUNBOOK.md").write_text("# runbook\n")
    (folder / "M_T.sql").write_text("ALTER TABLE X ADD (Y NUMBER);\n")
    assert pkg._file_item(str(folder / "DEPLOY_M_T_RUNBOOK.md"), "runbook").arc == "RUNBOOK.md"
    item = pkg._file_item(str(folder / "M_T.sql"), "table_change")
    assert (item.arc, item.source) == ("ddl/M_T.sql", "specs/x/M_T.sql")


def test_zip_is_sound_portable_and_lists_everything_it_holds(tmp_path):
    out = str(tmp_path / "p.zip")
    pkg.build_zip(make_mapping(), items(), ["M_UP (in_review)"], out, today=datetime.date(2026, 11, 21))
    assert pkg.verify_zip(out) == []
    with zipfile.ZipFile(out) as archive:
        names = archive.namelist()
        assert pkg.package_root(names) == "M_T"
        assert all("\\" not in n and not n.startswith("/") for n in names)
        assert {"M_T/" + n for n in pkg.META_FILES} <= set(names)
        assert "M_T/RUNBOOK.md" in names and "M_T/README.txt" in names
        assert max(n.count("/") for n in names) <= 2  # the mapping folder, one folder, the file
        assert archive.getinfo("M_T/verify.sh").external_attr >> 16 == 0o755
        assert all(i.date_time == pkg.FIXED_TIME for i in archive.infolist())
        sums = pkg.read_sums(archive)
        assert set(sums) == {n[len("M_T/"):] for n in names} - {"SHA256SUMS"}
        readme = archive.read("M_T/README.txt").decode()
        assert "code/PKG_T.sql" in readme and "tests (TEST only)" in readme
        assert b"M_UP (in_review)" in archive.read("M_T/MANIFEST.json")


def test_packages_of_different_mappings_unpack_into_one_directory_without_clashes(tmp_path):
    made = []
    for mapping_id in ("M_A", "M_B"):
        mapping = make_mapping()
        mapping.fields["Mapping_ID"] = mapping_id
        out = str(tmp_path / (mapping_id + ".zip"))
        pkg.build_zip(mapping, items(), [], out, today=datetime.date(2026, 11, 21))
        made.append(out)
    seen = set()
    for out in made:
        with zipfile.ZipFile(out) as archive:
            names = set(archive.namelist())
        assert not names & seen
        seen |= names
    assert {n.split("/")[0] for n in seen} == {"M_A", "M_B"}


def test_same_inputs_give_the_same_zip(tmp_path):
    first, second = str(tmp_path / "a.zip"), str(tmp_path / "b.zip")
    for path in (first, second):
        pkg.build_zip(make_mapping(), items(), [], path, today=datetime.date(2026, 11, 21))
    with open(first, "rb") as a, open(second, "rb") as b:
        assert a.read() == b.read()


def test_a_changed_file_is_found_by_the_package_check(tmp_path):
    out = str(tmp_path / "p.zip")
    pkg.build_zip(make_mapping(), items(), [], out, today=datetime.date(2026, 11, 21))
    tampered = str(tmp_path / "t.zip")
    with zipfile.ZipFile(out) as src, zipfile.ZipFile(tampered, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            dst.writestr(info, data + b"-- tampered\n" if info.filename == "M_T/code/PKG_T.sql" else data)
    assert pkg.verify_zip(tampered) == ["checksum mismatch: code/PKG_T.sql"]


def test_a_package_deeper_than_one_folder_or_outside_one_top_folder_is_refused(tmp_path):
    deep = str(tmp_path / "d.zip")
    with zipfile.ZipFile(deep, "w") as archive:
        archive.writestr("M_T/a/b/c.sql", b"x")
        archive.writestr("M_T/SHA256SUMS", b"")
    assert any("more than one folder level" in p for p in pkg.verify_zip(deep))
    loose = str(tmp_path / "l.zip")
    with zipfile.ZipFile(loose, "w") as archive:
        archive.writestr("README.txt", b"x")
        archive.writestr("M_T/SHA256SUMS", b"")
    assert pkg.verify_zip(loose) == ["the entries are not all inside one top folder"]


def test_an_unsafe_entry_name_is_refused(tmp_path):
    out = str(tmp_path / "u.zip")
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("M_T/..\\evil.sql", b"x")
        archive.writestr("M_T/SHA256SUMS", b"")
    assert any(p.startswith("unsafe entry name") for p in pkg.verify_zip(out))


def test_a_file_outside_the_repository_cannot_be_packed(tmp_path):
    outside = tmp_path / "x.sql"
    outside.write_text("SELECT 1 FROM DUAL;\n")
    with pytest.raises(pkg.PackageError):
        pkg._arc(str(outside))


def test_a_preflight_script_must_carry_the_helper_block_unchanged():
    block = pkg.helper_block()
    script = "DECLARE\r\n" + block.replace("\n", "\r\n") + "\r\nBEGIN\r\nNULL;\r\nEND;\r\n"
    assert pkg.has_helper_block(script)
    assert not pkg.has_helper_block(script.replace("RETURN -1;", "RETURN 0;"))
    assert not pkg.has_helper_block("DECLARE\nBEGIN\nNULL;\nEND;\n")


def test_every_helper_of_the_handover_doc_is_in_the_helper_block():
    import re
    import os
    from workbook_format import REPO_ROOT
    doc = open(os.path.join(REPO_ROOT, ".github", "skills", "dev-3-prepare-deployment", "references",
                            "deployment-handover.md"), encoding="utf-8").read()
    documented = set()
    for row in re.findall(r"^\| (`\w+\(.*?) \| ", doc, re.M):
        documented.update(re.findall(r"`(\w+)\(", row))
    defined = set(re.findall(r"^    (?:PROCEDURE|FUNCTION) (\w+)", pkg.helper_block(), re.M))
    assert documented and documented == defined
