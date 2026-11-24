"""Shared test setup: make the tools importable and give tests a tiny sql/ folder.

No test needs a database. The tests that need table scripts build a small
``*.schema`` folder in a temporary directory and point the catalog at it.
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for sub in ("tools/mapping_spec", "tools/codegen", "tools/change_request", "tools/data_flow"):
    sys.path.insert(0, os.path.join(ROOT, sub))

import schema_catalog  # noqa: E402


@pytest.fixture(autouse=True)
def no_change_requests(tmp_path_factory, monkeypatch):
    """Tests never see the repository's own change-requests/ folder, and the
    catalog shows no planned staging columns unless a test asks for them."""
    monkeypatch.setenv("UBB_CR_DIR", str(tmp_path_factory.mktemp("no_change_requests")))
    monkeypatch.setenv(schema_catalog.PLANNED_ENV, "off")
    schema_catalog.reload()
    yield
    schema_catalog.reload()

LOAN_SCRIPT = '''--------------------------------------------------------
--  DDL for Table T_LOAN
--------------------------------------------------------

  CREATE TABLE "OWN"."T_LOAN"
   (	"LOAN_ID" NUMBER(18,0) NOT NULL ENABLE,
	"PARTNER_REF" VARCHAR2(80 CHAR),
	"AMOUNT" NUMBER(20,2),
	"CREATED_AT" TIMESTAMP (6) DEFAULT SYSTIMESTAMP NOT NULL ENABLE,
	 CONSTRAINT "CK_T_LOAN" CHECK (AMOUNT >= 0) ENABLE,
	 CONSTRAINT "PK_T_LOAN" PRIMARY KEY ("LOAN_ID")
  USING INDEX PCTFREE 10 STORAGE(INITIAL 65536 NEXT 1048576)
  TABLESPACE "USERS"  ENABLE
   ) SEGMENT CREATION DEFERRED
  PARTITION BY LIST ("LOAN_ID") AUTOMATIC
 (PARTITION "P_0"  VALUES (0) SEGMENT CREATION DEFERRED)

   COMMENT ON TABLE "OWN"."T_LOAN"  IS 'Loans; it''s a test table.'
'''

PARTNER_SCRIPT = '''  CREATE TABLE "OWN"."T_PARTNER"
   (	"PARTNER_ID" NUMBER(18,0) NOT NULL ENABLE,
	"VALID_FROM" DATE NOT NULL ENABLE,
	"VALID_TO" DATE DEFAULT DATE '9999-12-31' NOT NULL ENABLE,
	"CBS_REF" VARCHAR2(80 CHAR),
	"PARTNER_NAME" VARCHAR2(200 CHAR) NOT NULL ENABLE,
	 CONSTRAINT "PK_T_PARTNER" PRIMARY KEY ("PARTNER_ID", "VALID_FROM")
  USING INDEX TABLESPACE "USERS"  ENABLE,
	 CONSTRAINT "UQ_T_PARTNER_REF" UNIQUE ("CBS_REF", "VALID_FROM")
  USING INDEX TABLESPACE "USERS"  ENABLE
   )
'''

# A table whose constraints and NOT NULLs live in separate files, as in the real export.
SPLIT_TABLE = '''  CREATE TABLE "OWN"."T_SPLIT"
   (	"ID" NUMBER(10,0),
	"LOAN_ID" NUMBER(18,0)
   )
'''
SPLIT_CONSTRAINTS = '''--  Constraints for Table T_SPLIT
  ALTER TABLE "OWN"."T_SPLIT" MODIFY ("ID" NOT NULL ENABLE)
  ALTER TABLE "OWN"."T_SPLIT" ADD CONSTRAINT "PK_T_SPLIT" PRIMARY KEY ("ID")
  USING INDEX TABLESPACE "USERS"  ENABLE
--  Ref Constraints for Table T_SPLIT
  ALTER TABLE "OWN"."T_SPLIT" ADD CONSTRAINT "FK_T_SPLIT_LOAN" FOREIGN KEY ("LOAN_ID")
	  REFERENCES "OWN"."T_LOAN" ("LOAN_ID") ENABLE
'''

GRANT_ONLY = 'GRANT SELECT ON "STG"."S_ONLY_GRANTED" TO "OWN"\n'


@pytest.fixture()
def sql_dir(tmp_path, monkeypatch):
    """A tiny sql/ folder with two schema folders; the catalog is pointed at it."""
    own = tmp_path / "OWN.schema"
    stg = tmp_path / "STG.schema"
    own.mkdir()
    stg.mkdir()
    (own / "T_LOAN.sql").write_text(LOAN_SCRIPT, encoding="utf-8")
    (own / "T_PARTNER.sql").write_text(PARTNER_SCRIPT, encoding="utf-8")
    (own / "T_SPLIT.sql").write_text(SPLIT_TABLE, encoding="utf-8")
    (own / "T_SPLIT_CONSTRAINT.sql").write_text(SPLIT_CONSTRAINTS, encoding="utf-8")
    (stg / "S_ONLY_GRANTED.sql").write_text(GRANT_ONLY, encoding="utf-8")
    monkeypatch.setenv(schema_catalog.SQL_DIR_ENV, str(tmp_path))
    schema_catalog.reload()
    yield tmp_path
    schema_catalog.reload()
