--------------------------------------------------------
--  DDL for View METADATA_PREBUILT_ANNOTATIONS
--------------------------------------------------------

  CREATE OR REPLACE FORCE EDITIONABLE VIEW "UBB_CORE2"."METADATA_PREBUILT_ANNOTATIONS" ("ANNOTATION_NAME", "DESCRIPTION", "CATEGORY") AS 
  select "ANNOTATION_NAME","DESCRIPTION","CATEGORY" from annotations_prebuilt$
