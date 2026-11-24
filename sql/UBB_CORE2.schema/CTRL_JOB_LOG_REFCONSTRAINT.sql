--------------------------------------------------------
--  Ref Constraints for Table CTRL_JOB_LOG
--------------------------------------------------------

  ALTER TABLE "UBB_CORE2"."CTRL_JOB_LOG" ADD CONSTRAINT "FK_CJL_RUN" FOREIGN KEY ("RUN_ID")
	  REFERENCES "UBB_CORE2"."CTRL_JOB_RUN" ("RUN_ID") ENABLE
