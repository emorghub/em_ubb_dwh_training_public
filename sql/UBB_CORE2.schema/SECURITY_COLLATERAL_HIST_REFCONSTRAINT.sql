--------------------------------------------------------
--  Ref Constraints for Table SECURITY_COLLATERAL_HIST
--------------------------------------------------------

  ALTER TABLE "UBB_CORE2"."SECURITY_COLLATERAL_HIST" ADD CONSTRAINT "FK_SCH_COLL_HIST" FOREIGN KEY ("COLLATERAL_ID", "LOAD_ID")
	  REFERENCES "UBB_CORE2"."COLLATERAL_HIST" ("COLLATERAL_ID", "LOAD_ID") ENABLE
