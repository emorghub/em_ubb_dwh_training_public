--------------------------------------------------------
--  DDL for Index UQ_EXPOSURE_BK
--------------------------------------------------------

  CREATE UNIQUE INDEX "UBB_CORE2"."UQ_EXPOSURE_BK" ON "UBB_CORE2"."EXPOSURE" ("SOURCE_SYSTEM", "EXPOSURE_REF") 
  PCTFREE 10 INITRANS 2 MAXTRANS 255 
  TABLESPACE "USERS"
