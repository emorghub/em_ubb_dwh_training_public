"""package_usage: which procedures read or write a table, from package scripts only."""

from __future__ import annotations

import package_usage
import verify_mapping
from workbook_format import mapping_from_dict

LOAD_BODY = '''--------------------------------------------------------
--  DDL for Package Body PKG_T
--------------------------------------------------------

  CREATE OR REPLACE EDITIONABLE PACKAGE BODY "OWN"."PKG_T" AS
  PROCEDURE load_day(p_date IN DATE) IS
    v_n NUMBER;
  BEGIN
    -- writes OWN.T_COMMENTED only in this comment
    log('loading OWN.T_IN_STRING now');
    SELECT COUNT(*) INTO v_n FROM STG.S_SRC s WHERE s.D = p_date;
    DELETE FROM OWN.T_OUT WHERE D = p_date;
    INSERT INTO "OWN"."T_OUT" (ID)
    SELECT s.ID FROM STG.S_SRC s JOIN T_LOAN l ON l.ID = s.ID;
    MERGE INTO OWN.T_LOAN t USING (SELECT ID FROM STG.S_SRC) s ON (t.ID = s.ID)
    WHEN MATCHED THEN UPDATE SET t.X = 1;
  END load_day;

  PROCEDURE fix IS
  BEGIN
    UPDATE T_LOAN SET X = 0;
    INSERT ALL INTO OWN.T_A (ID) VALUES (1) INTO OWN.T_B (ID) VALUES (2) SELECT * FROM DUAL;
    EXECUTE IMMEDIATE 'TRUNCATE TABLE OWN.T_OUT';
  END fix;
END PKG_T;
'''

# Another owner: a bare T_LOAN here is STG.T_LOAN, not OWN.T_LOAN.
OTHER_BODY = '''CREATE OR REPLACE PACKAGE BODY "STG"."PKG_S" AS
  PROCEDURE p IS BEGIN
    DELETE T_LOAN;
    SELECT 1 INTO x FROM OWN.T_OUT;
  END p;
END PKG_S;
'''

PACKAGE_SPEC = '''CREATE OR REPLACE PACKAGE "OWN"."PKG_T" AS
  PROCEDURE load_day(p_date IN DATE);
END PKG_T;
'''


def write_packages(sql_dir):
    (sql_dir / "OWN.schema" / "PKG_T.sql").write_text(PACKAGE_SPEC, encoding="utf-8")
    (sql_dir / "OWN.schema" / "PKG_T_1.sql").write_text(LOAD_BODY, encoding="utf-8")
    (sql_dir / "STG.schema" / "PKG_S_1.sql").write_text(OTHER_BODY, encoding="utf-8")


def summary(table):
    return sorted({(u.where, u.access, u.verb) for u in package_usage.find_usages([table])[table]})


def test_only_package_bodies_are_read(sql_dir):
    write_packages(sql_dir)
    assert sorted(b.qualified for b in package_usage.load_package_bodies()) == ["OWN.PKG_T", "STG.PKG_S"]


def test_writes_and_reads_are_told_apart_per_procedure(sql_dir):
    write_packages(sql_dir)
    assert summary("OWN.T_OUT") == [
        ("OWN.PKG_T.LOAD_DAY", "write", "DELETE"),
        ("OWN.PKG_T.LOAD_DAY", "write", "INSERT"),
        ("STG.PKG_S.P", "read", ""),
    ]
    assert summary("STG.S_SRC") == [("OWN.PKG_T.LOAD_DAY", "read", "")]


def test_bare_name_resolves_to_the_package_owner_only(sql_dir):
    write_packages(sql_dir)
    assert summary("OWN.T_LOAN") == [
        ("OWN.PKG_T.FIX", "write", "UPDATE"),
        ("OWN.PKG_T.LOAD_DAY", "read", ""),
        ("OWN.PKG_T.LOAD_DAY", "write", "MERGE"),
    ]
    assert summary("STG.T_LOAN") == [("STG.PKG_S.P", "write", "DELETE")]


def test_multi_table_insert_targets_are_writes(sql_dir):
    write_packages(sql_dir)
    assert summary("OWN.T_A") == [("OWN.PKG_T.FIX", "write", "INSERT")]
    assert summary("OWN.T_B") == [("OWN.PKG_T.FIX", "write", "INSERT")]


def test_comments_and_strings_are_not_references(sql_dir):
    write_packages(sql_dir)
    assert summary("OWN.T_COMMENTED") == []
    assert summary("OWN.T_IN_STRING") == []


def test_line_numbers_point_at_the_statement(sql_dir):
    write_packages(sql_dir)
    lines = {u.line for u in package_usage.find_usages(["OWN.T_OUT"])["OWN.T_OUT"] if u.verb == "INSERT"}
    assert lines == {LOAD_BODY.splitlines().index('    INSERT INTO "OWN"."T_OUT" (ID)') + 1}


def test_dynamic_sql_is_listed_not_analysed(sql_dir):
    write_packages(sql_dir)
    assert [where for where, _path, _line in package_usage.dynamic_sql()] == ["OWN.PKG_T.FIX"]


def test_verify_warns_when_another_package_writes_the_target(sql_dir):
    write_packages(sql_dir)

    def warnings(proc):
        mapping = mapping_from_dict({"mapping": {"Mapping_ID": "M_T", "Target_Table": "OWN.T_OUT", "PLSQL_Proc": proc}})
        result = verify_mapping.Result()
        verify_mapping.check_other_writers(mapping, result)
        return [message for level, message in result.lines if level == "WARN"]

    assert len(warnings("OWN.PKG_NEW.LOAD")) == 1
    assert "OWN.PKG_T.LOAD_DAY" in warnings("OWN.PKG_NEW.LOAD")[0]
    assert warnings("OWN.PKG_T.LOAD_DAY") == []
