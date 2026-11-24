--------------------------------------------------------
--  DDL for View METADATA_ANNOTATIONS_GROUP_MEM
--------------------------------------------------------

  CREATE OR REPLACE FORCE EDITIONABLE VIEW "UBB_CORE2"."METADATA_ANNOTATIONS_GROUP_MEM" ("GROUP_NAME", "ANNOTATION_TYPE", "USER_NAME", "OBJECT_NAME", "OBJECT_TYPE", "COLUMN_NAME", "PROCEDURE_NAME", "FUNCTION_NAME") AS 
  select ag.group_name,
  decode(annotation_type, 1, 'TABLE', 2, 'TABLE COLUMN', 3, 'TABLE PARTITION',
              4, 'TABLE SUBPARTITION', 5, 'VIEW',
              6, 'VIEW COLUMN', 7, 'PACKAGE', 8, 'PACKAGE PROCEDURE',
              9, 'PACKAGE FUNCTION', 10, 'PROCEDURE', 11, 'FUNCTION', 12, 'SCHEMA', 13, 'DATABASE',
              15, 'MATERIALIZED VIEW', 16, 'MATERIALIZED VIEW COLUMN'),
  user_name, object_name, object_type, column_name, procedure_name, function_name
from
(
/* Should work for all types with a base object */
select agm.group_id, agm.annotation_type,
       o.owner as user_name, o.object_name, o.object_type,
       agm.column_name, agm.procedure_name, agm.function_name
from annotations_group_members$ agm,
     sys.all_objects o
where agm.obj# = o.object_id
union
/* Schema level annotations */
select agm.group_id, agm.annotation_type,
       username, null, null, null, null, NULL
from annotations_group_members$ agm,
      sys.all_users us
  where agm.annotation_type = 12
    and agm.object_owner = us.user_id /* Verify valid user */
union
/* Database level annotations */
select agm.group_id, agm.annotation_type, null, null, null, null, null, null
 from annotations_group_members$ agm
  where annotation_type = 13
) agm, annotations_groups$ ag
where agm.group_id = ag.group_id
