--------------------------------------------------------
--  DDL for View METADATA_ANNOTATIONS_USAGE
--------------------------------------------------------

  CREATE OR REPLACE FORCE EDITIONABLE VIEW "UBB_CORE2"."METADATA_ANNOTATIONS_USAGE" ("ANNOTATION_TYPE", "USER_NAME", "OBJECT_NAME", "OBJECT_TYPE", "COLUMN_NAME", "PROCEDURE_NAME", "FUNCTION_NAME", "GROUP_NAME", "ANNOTATION_NAME", "ANNOTATION_VALUE") AS 
  select decode(annotation_type, 1, 'TABLE', 2, 'TABLE COLUMN', 3, 'TABLE PARTITION',
              4, 'TABLE SUBPARTITION', 5, 'VIEW',
              6, 'VIEW COLUMN', 7, 'PACKAGE', 8, 'PACKAGE PROCEDURE',
              9, 'PACKAGE FUNCTION', 10, 'PROCEDURE', 11, 'FUNCTION', 12, 'SCHEMA', 13, 'DATABASE',
              14, 'GROUP', 15, 'MATERIALIZED VIEW', 16, 'MATERIALIZED VIEW COLUMN'),
  user_name, object_name, object_type, column_name, procedure_name, function_name, group_name,
  annotation_name, annotation_value
from
(
/* Should work for all types with a base object */
select annotation_type, o.owner as user_name, o.object_name, o.object_type,
  au.column_name, procedure_name, function_name, null as group_name,
  au.annotation_name as annotation_name,
  au.annotation_value as annotation_value
from annotations_usage$ au,
     sys.all_objects o
where au.obj# = o.object_id
union
/* Schema level annotations */
select annotation_type, username, null, null, null, null, null, null,
       annotation_name, annotation_value
 from annotations_usage$ au,
      sys.all_users us
  where annotation_type = 12
    and au.object_owner = us.user_id /* Verify valid user */
union
/* Database level annotations */
select annotation_type, null, null, null, null, null, null, null,
       annotation_name, annotation_value
 from annotations_usage$
  where annotation_type = 13
union
/* Group level annotations */
select annotation_type, null, null, null, null, null, null,
       ag.group_name as group_name,
       au.annotation_name, au.annotation_value
 from annotations_usage$ au, annotations_groups$ ag
  where au.annotation_type = 14 and
        au.group_id = ag.group_id
)
