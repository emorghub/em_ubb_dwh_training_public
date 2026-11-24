--------------------------------------------------------
--  Ref Constraints for Table PARTNER_HIST
--------------------------------------------------------

  ALTER TABLE "UBB_CORE2"."PARTNER_HIST" ADD CONSTRAINT "FK_PH_PARTNER" FOREIGN KEY ("PARTNER_ID")
	  REFERENCES "UBB_CORE2"."PARTNER" ("PARTNER_ID") ENABLE
  ALTER TABLE "UBB_CORE2"."PARTNER_HIST" ADD CONSTRAINT "FK_PH_LOAD" FOREIGN KEY ("LOAD_ID")
	  REFERENCES "UBB_CORE2"."CTRL_LOAD" ("LOAD_ID") ENABLE
