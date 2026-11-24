--------------------------------------------------------
--  Ref Constraints for Table STG_LOAN_COLLATERAL_REL
--------------------------------------------------------

  ALTER TABLE "UBB_STAGING2"."STG_LOAN_COLLATERAL_REL" ADD CONSTRAINT "FK_STGLCR_LOAD" FOREIGN KEY ("LOAD_ID")
	  REFERENCES "UBB_CORE2"."CTRL_LOAD" ("LOAD_ID") ENABLE
