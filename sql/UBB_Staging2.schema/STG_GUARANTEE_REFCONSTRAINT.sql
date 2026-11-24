--------------------------------------------------------
--  Ref Constraints for Table STG_GUARANTEE
--------------------------------------------------------

  ALTER TABLE "UBB_STAGING2"."STG_GUARANTEE" ADD CONSTRAINT "FK_STGG_LOAD" FOREIGN KEY ("LOAD_ID")
	  REFERENCES "UBB_CORE2"."CTRL_LOAD" ("LOAD_ID") ENABLE
