--------------------------------------------------------
--  Ref Constraints for Table STG_LOAN
--------------------------------------------------------

  ALTER TABLE "UBB_STAGING2"."STG_LOAN" ADD CONSTRAINT "FK_STGL_LOAD" FOREIGN KEY ("LOAD_ID")
	  REFERENCES "UBB_CORE2"."CTRL_LOAD" ("LOAD_ID") ENABLE
