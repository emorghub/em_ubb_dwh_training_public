--------------------------------------------------------
--  Ref Constraints for Table STG_LIMIT
--------------------------------------------------------

  ALTER TABLE "UBB_STAGING2"."STG_LIMIT" ADD CONSTRAINT "FK_STGLIM_LOAD" FOREIGN KEY ("LOAD_ID")
	  REFERENCES "UBB_CORE2"."CTRL_LOAD" ("LOAD_ID") ENABLE
