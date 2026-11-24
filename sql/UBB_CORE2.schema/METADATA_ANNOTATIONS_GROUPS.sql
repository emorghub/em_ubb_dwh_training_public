--------------------------------------------------------
--  DDL for View METADATA_ANNOTATIONS_GROUPS
--------------------------------------------------------

  CREATE OR REPLACE FORCE EDITIONABLE VIEW "UBB_CORE2"."METADATA_ANNOTATIONS_GROUPS" ("GROUP_NAME", "CREATION_TIME") AS 
  SELECT group_name, creation_time
FROM annotations_groups$
