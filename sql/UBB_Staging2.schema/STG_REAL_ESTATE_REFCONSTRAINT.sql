--------------------------------------------------------
--  Ref Constraints for Table STG_REAL_ESTATE
--------------------------------------------------------

  ALTER TABLE "UBB_STAGING2"."STG_REAL_ESTATE" ADD CONSTRAINT "FK_STGRE_LOAD" FOREIGN KEY ("LOAD_ID")
	  REFERENCES "UBB_CORE2"."CTRL_LOAD" ("LOAD_ID") ENABLE
