--------------------------------------------------------
--  DDL for Package PRVT_ANNOTATIONS_INTERNAL
--------------------------------------------------------

  CREATE OR REPLACE EDITIONABLE PACKAGE "UBB_CORE2"."PRVT_ANNOTATIONS_INTERNAL" authid definer
is 

/* 
 * Enumeration of annotation types 
 * Notes: For every annotation this is the value of the column 
 * annotation_type in the table annotations_usage$.
 *
 * Note that we are using the same values in user visible package as well as the 
 * internal helper package
 */

 IDENTIFIER_TABLE                 constant number :=1;
 IDENTIFIER_TABLE_COLUMN          constant number :=2;
 IDENTIFIER_TABLE_PARTITION       constant number :=3;
 IDENTIFIER_TABLE_SUBPARTITION    constant number :=4;
 IDENTIFIER_VIEW                  constant number :=5;
 IDENTIFIER_VIEW_COLUMN           constant number :=6;
 IDENTIFIER_PACKAGE               constant number :=7;
 IDENTIFIER_PACKAGE_PROCEDURE     constant number :=8;
 IDENTIFIER_PACKAGE_FUNCTION      constant number :=9;
 IDENTIFIER_PROCEDURE             constant number :=10;
 IDENTIFIER_FUNCTION              constant number :=11;
 IDENTIFIER_SCHEMA                constant number :=12;
 IDENTIFIER_DATABASE              constant number :=13;
 IDENTIFIER_GROUP                 constant number :=14;
 IDENTIFIER_MTRLZD_VIEW           constant number :=15; 
 IDENTIFIER_MTRLZD_VIEW_COLUMN    constant number :=16;

 NUM_IDENTIFIER_TYPE                   constant number :=16;

/* Constant to identify an annotation without a value */
 NO_VALUE                         constant varchar2(20) := 'KEY WITHOUT VALUE';

procedure set(
          v_annotation_owner      in number,
          v_annotation_name       in varchar2,
          v_annotation_value      in varchar2,
          v_annotation_type_int   In number,
          v_obj#                  in number,
          obj#_owner              in number,
          v_identifier_components in
          metadata_annotations.identifier_components_t)
;

procedure edit(
          v_annotation_owner      in number,
          v_annotation_name       in varchar2,
          v_annotation_value      in varchar2,
          v_annotation_old_value  in varchar2,
          v_annotation_type_int   In number,
          v_obj#                  in number,
          obj_owner               in number,
          v_identifier_components in
          metadata_annotations.identifier_components_t)
;

function get(
          v_annotation_owner      in number,
          v_annotation_name       in varchar2,
          v_annotation_type_int   in number,
          v_obj#                  in number,
          v_obj#_owner            in number,
          v_identifier_components in
          metadata_annotations.identifier_components_t)
return clob
;

function get_json(
  v_annotation_owner      in number,
  v_annotation_name       in varchar2,
  v_annotation_type_int   in number,
  v_obj#                  in number,
  v_obj#_owner            in number,
  v_identifier_components in metadata_annotations.identifier_components_t
)
$IF DBMS_DB_VERSION.VERSION >= 21 $THEN
  return json;
$ELSE
  return clob;
$END

procedure delete(
          v_annotation_owner      in number,
          v_annotation_name       in varchar2,
          v_annotation_value      in varchar2,
          v_annotation_type_int   In number,
          v_obj#                  in number,
          obj_owner               in number,
          v_identifier_components in
          metadata_annotations.identifier_components_t)
;

procedure delete_by_value_regex(
          v_annotation_owner      in number,
          v_annotation_name       in varchar2,
          v_value_pattern         in varchar2,
          v_match_parameter       in varchar2 default NULL,
          v_annotation_type_int   in number,
          v_obj#                  in number,
          obj_owner               in number,
          v_identifier_components in 
          metadata_annotations.identifier_components_t)
;

procedure create_group(
     v_group_name in VARCHAR2)
;

procedure drop_group(
     v_group_name in VARCHAR2)
;

procedure add_to_group(
      v_group_name            in VARCHAR2,
      v_object_id             in NUMBER,
      v_object_owner          in NUMBER,
      v_annotation_type_int   in number,
      v_identifier_components in 
      metadata_annotations.identifier_components_t);

procedure delete_from_group(
      v_group_name            in VARCHAR2,
      v_object_id             in NUMBER,
      v_object_owner          in NUMBER,
      v_annotation_type_int   in number,
      v_identifier_components in 
      metadata_annotations.identifier_components_t);

end prvt_annotations_internal;
