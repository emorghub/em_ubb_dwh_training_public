--------------------------------------------------------
--  Ref Constraints for Table STG_SECURITY_COLLATERAL
--------------------------------------------------------

  ALTER TABLE "UBB_STAGING2"."STG_SECURITY_COLLATERAL" ADD CONSTRAINT "FK_STGSC_LOAD" FOREIGN KEY ("LOAD_ID")
	  REFERENCES "UBB_CORE2"."CTRL_LOAD" ("LOAD_ID") ENABLE
