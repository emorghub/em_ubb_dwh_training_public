--------------------------------------------------------
--  DDL for Index IX_EH_LOAN
--------------------------------------------------------

  CREATE INDEX "UBB_CORE2"."IX_EH_LOAN" ON "UBB_CORE2"."EXPOSURE_HIST" ("LOAN_ID", "LOAD_ID") 
  PCTFREE 10 INITRANS 2 MAXTRANS 255 COMPUTE STATISTICS 
  STORAGE(
  BUFFER_POOL DEFAULT FLASH_CACHE DEFAULT CELL_FLASH_CACHE DEFAULT)
  TABLESPACE "USERS"
