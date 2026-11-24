--------------------------------------------------------
--  Ref Constraints for Table STG_COLLATERAL
--------------------------------------------------------

  ALTER TABLE "UBB_STAGING2"."STG_COLLATERAL" ADD CONSTRAINT "FK_STGC_LOAD" FOREIGN KEY ("LOAD_ID")
	  REFERENCES "UBB_CORE2"."CTRL_LOAD" ("LOAD_ID") ENABLE
