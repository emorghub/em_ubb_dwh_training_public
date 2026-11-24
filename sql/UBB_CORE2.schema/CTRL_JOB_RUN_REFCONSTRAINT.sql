--------------------------------------------------------
--  Ref Constraints for Table CTRL_JOB_RUN
--------------------------------------------------------

  ALTER TABLE "UBB_CORE2"."CTRL_JOB_RUN" ADD CONSTRAINT "FK_CJR_JOB" FOREIGN KEY ("JOB_NAME")
	  REFERENCES "UBB_CORE2"."CTRL_JOB" ("JOB_NAME") ENABLE
  ALTER TABLE "UBB_CORE2"."CTRL_JOB_RUN" ADD CONSTRAINT "FK_CJR_LOAD" FOREIGN KEY ("SOURCE_LOAD_ID")
	  REFERENCES "UBB_CORE2"."CTRL_LOAD" ("LOAD_ID") ENABLE
