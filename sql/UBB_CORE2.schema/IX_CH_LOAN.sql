--------------------------------------------------------
--  DDL for Index IX_CH_LOAN
--------------------------------------------------------

  CREATE INDEX "UBB_CORE2"."IX_CH_LOAN" ON "UBB_CORE2"."COLLATERAL_HIST" ("LOAN_ID", "LOAD_ID") 
  PCTFREE 10 INITRANS 2 MAXTRANS 255 COMPUTE STATISTICS 
  STORAGE(
  BUFFER_POOL DEFAULT FLASH_CACHE DEFAULT CELL_FLASH_CACHE DEFAULT)
  TABLESPACE "USERS"
