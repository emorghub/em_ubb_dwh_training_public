--------------------------------------------------------
--  DDL for Package PKG_ETL_LIMIT
--------------------------------------------------------

  CREATE OR REPLACE EDITIONABLE PACKAGE "UBB_CORE2"."PKG_ETL_LIMIT" AUTHID DEFINER AS
  PROCEDURE load_day(p_business_date IN DATE);
END PKG_ETL_LIMIT;
