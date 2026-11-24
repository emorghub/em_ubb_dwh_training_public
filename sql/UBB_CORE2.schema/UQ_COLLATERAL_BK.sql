--------------------------------------------------------
--  DDL for Index UQ_COLLATERAL_BK
--------------------------------------------------------

  CREATE UNIQUE INDEX "UBB_CORE2"."UQ_COLLATERAL_BK" ON "UBB_CORE2"."COLLATERAL" ("SOURCE_SYSTEM", "COLLATERAL_REF") 
  PCTFREE 10 INITRANS 2 MAXTRANS 255 
  TABLESPACE "USERS"
