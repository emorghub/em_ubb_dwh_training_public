--------------------------------------------------------
--  Ref Constraints for Table REAL_ESTATE_HIST
--------------------------------------------------------

  ALTER TABLE "UBB_CORE2"."REAL_ESTATE_HIST" ADD CONSTRAINT "FK_REH_COLL_HIST" FOREIGN KEY ("COLLATERAL_ID", "LOAD_ID")
	  REFERENCES "UBB_CORE2"."COLLATERAL_HIST" ("COLLATERAL_ID", "LOAD_ID") ENABLE
