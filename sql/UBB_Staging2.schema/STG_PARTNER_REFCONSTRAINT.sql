--------------------------------------------------------
--  Ref Constraints for Table STG_PARTNER
--------------------------------------------------------

  ALTER TABLE "UBB_STAGING2"."STG_PARTNER" ADD CONSTRAINT "FK_STGP_LOAD" FOREIGN KEY ("LOAD_ID")
	  REFERENCES "UBB_CORE2"."CTRL_LOAD" ("LOAD_ID") ENABLE
