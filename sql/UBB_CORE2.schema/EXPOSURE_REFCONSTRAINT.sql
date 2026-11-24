--------------------------------------------------------
--  Ref Constraints for Table EXPOSURE
--------------------------------------------------------

  ALTER TABLE "UBB_CORE2"."EXPOSURE" ADD CONSTRAINT "FK_EXPOSURE_LOAN" FOREIGN KEY ("LOAN_ID")
	  REFERENCES "UBB_CORE2"."LOAN" ("LOAN_ID") ENABLE
