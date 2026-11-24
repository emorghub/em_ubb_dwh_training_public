--------------------------------------------------------
--  Ref Constraints for Table STG_FX_RATE
--------------------------------------------------------

  ALTER TABLE "UBB_STAGING2"."STG_FX_RATE" ADD CONSTRAINT "FK_STGFX_LOAD" FOREIGN KEY ("LOAD_ID")
	  REFERENCES "UBB_CORE2"."CTRL_LOAD" ("LOAD_ID") ENABLE
