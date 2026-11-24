--------------------------------------------------------
--  Ref Constraints for Table ANNOTATIONS_GROUP_MEMBERS$
--------------------------------------------------------

  ALTER TABLE "UBB_CORE2"."ANNOTATIONS_GROUP_MEMBERS$" ADD CONSTRAINT "FK_GROUP" FOREIGN KEY ("GROUP_ID")
	  REFERENCES "UBB_CORE2"."ANNOTATIONS_GROUPS$" ("GROUP_ID") ON DELETE CASCADE ENABLE
