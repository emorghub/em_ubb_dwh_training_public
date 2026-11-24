--------------------------------------------------------
--  DDL for Package METADATA_ANNOTATIONS
--------------------------------------------------------

  CREATE OR REPLACE EDITIONABLE PACKAGE "UBB_CORE2"."METADATA_ANNOTATIONS" authid current_user is 
          
/* Enumeration of annotation types */
 IDENTIFIER_TABLE                   constant number :=1;
 IDENTIFIER_TABLE_COLUMN            constant number :=2;
 IDENTIFIER_TABLE_PARTITION         constant number :=3;
 IDENTIFIER_TABLE_SUBPARTITION      constant number :=4;
 IDENTIFIER_VIEW                    constant number :=5;
 IDENTIFIER_VIEW_COLUMN             constant number :=6;
 IDENTIFIER_PACKAGE                 constant number :=7;
 IDENTIFIER_PACKAGE_PROCEDURE       constant number :=8;
 IDENTIFIER_PACKAGE_FUNCTION        constant number :=9;
 IDENTIFIER_PROCEDURE               constant number :=10;
 IDENTIFIER_FUNCTION                constant number :=11;
 IDENTIFIER_SCHEMA                  constant number :=12;
 IDENTIFIER_DATABASE                constant number :=13;
 IDENTIFIER_GROUP                   constant number :=14;
 IDENTIFIER_MTRLZD_VIEW             constant number :=15;
 IDENTIFIER_MTRLZD_VIEW_COLUMN      constant number :=16;
 NUM_IDENTIFIER_TYPE                constant number :=16;
 
/* Constant to identify an annotation without a value */
 NO_VALUE                         constant varchar2(20) := 'KEY WITHOUT VALUE';  

/* DESCRIPTION: Public API to add a annotation name, value pair 
 * 
 * PARAMETERS:
 *  label               (in)   annotation label to be added
 *  value               (in)   annotation label value to be added
 *  identifier_name     (in)   fully qualified identifier name
 *  identifier_type     (in)   identifier type (defaults to 'TABLE')
 *
 * USAGE:
 *  metadata_annotations.set(label, value, identifier_name, identifier_type) 
 */

procedure set(
          label In varchar2,
          value In varchar2,
          identifier_name in varchar2, 
          identifier_type In varchar2 default 'TABLE'
          );

/* DESCRIPTION: Public API to add a annotation name, value pair 
 * 
 * PARAMETERS:
 *  label               (in)   annotation label to be edited
 *  value               (in)   New annotation label value  
 *  identifier_name     (in)   fully qualified identifier name
 *  identifier_type     (in)   identifier type (defaults to 'TABLE')
 *
 * USAGE:
 *  metadata_annotations.set(label, value, identifier_name, identifier_type) 
 */

procedure edit(
          label In varchar2,
          value In varchar2,
          identifier_name in varchar2, 
          identifier_type In varchar2 default 'TABLE',
          old_value in varchar2 default NULL
          );

/* DESCRIPTION: Public API to get value for a particular annotation name
 * 
 * PARAMETERS:
 *  label               (in)   annotation label to look up
 *  identifier_name     (in)   fully qualified identifier name
 *  identifier_type     (in)   identifier type (defaults to 'TABLE')
 *
 * USAGE:
 *  metadata_annotations.get(label, identifier_name, identifier_type) 
 */

function get(
          label in varchar2,
          identifier_name in varchar2,
          identifier_type in varchar2 default 'TABLE')
return clob;

/* have retained the older one for now.
   Once we confirm the new one is all we need, we will remove it. */

/* DESCRIPTION: Public API to get JSON array of values for a particular annotation name
 * 
 * PARAMETERS:
 *  label               (in)   annotation label to look up
 *  identifier_name     (in)   fully qualified identifier name
 *  identifier_type     (in)   identifier type (defaults to 'TABLE')
 *
 * USAGE:
 *  metadata_annotations.get_json(label, identifier_name, identifier_type) 
 */
function get_json(
  label           in varchar2,
  identifier_name in varchar2,
  identifier_type in varchar2 default 'TABLE'
)
$IF DBMS_DB_VERSION.VERSION >= 21 $THEN
     return json;
$ELSE
     return clob;
$END

/* DESCRIPTION: Public API to delete an annotation
 * 
 * PARAMETERS:
 *  label               (in)   annotation label to delete
 *  identifier_name     (in)   fully qualified identifier name
 *  identifier_type     (in)   identifier type (defaults to 'TABLE')
 *
 * USAGE:
 *  metadata_annotations.get(label, identifier_name, identifier_type) 
 */

procedure delete(
          label in varchar2,
          identifier_name in varchar2,
          identifier_type in varchar2 default 'TABLE',
          value in varchar2 default NULL);
       
procedure delete_by_value_regex(
          label           in varchar2,
          identifier_name in varchar2,
          identifier_type in varchar2 default 'TABLE',
          value_pattern   in varchar2 default NULL,
          match_parameter in varchar2 default NULL);

type identifier_components_t is table of varchar2(4000) index by varchar2(100);


Type Identifier Is Record( 
       Identifier_Name Varchar2(4000),
       Identifier_Type Varchar2(4000));

Type Identifier_List Is Table Of Identifier;

type annotation is record(
     label varchar2(4000),
     value varchar2(4000),
     identifier_name varchar2(4000),
     identifier_type varchar2(4000) default 'TABLE');

/* DESCRIPTION: Public API to create a group
 * 
 * PARAMETERS:
 *  group_name              (in)   Name of the group 
 *
 * USAGE:
 *  metadata_annotations.create_group(group_name);
 */

procedure create_group(
     group_name in VARCHAR2);

/* DESCRIPTION: Public API to drop a group
 * 
 * PARAMETERS:
 *  group_name              (in)   Name of the group to drop 
 *
 * USAGE:
 *  metadata_annotations.drop_group(group_name);
 */

procedure drop_group(
     group_name in VARCHAR2);

/* DESCRIPTION: Public API to add an element to a group
 * 
 * PARAMETERS:
 *  group_name              (in)   Name of the group to modify
 *  identifier_name     (in)   fully qualified identifier name
 *  identifier_type     (in)   identifier type (defaults to 'TABLE')
 *  
 * USAGE:
 *  metadata_annotations.add_to_group(group_name, identifier_name, identifier_type );
 */


procedure add_to_group(
     group_name      in VARCHAR2,
     identifier_name in varchar2,
     identifier_type in varchar2 default 'TABLE');

/* DESCRIPTION: Public API to delete an element from a group
 * 
 * PARAMETERS:
 *  group_name              (in)   Name of the group to modify
 *  identifier_name     (in)   fully qualified identifier name
 *  identifier_type     (in)   identifier type (defaults to 'TABLE')
 *  
 * USAGE:
 *  metadata_annotations.add_to_group(group_name, identifier_name, identifier_type );
 */


procedure delete_from_group(
     group_name      in VARCHAR2,
     identifier_name in varchar2,
     identifier_type in varchar2 default 'TABLE');

function get_version return varchar2;

end metadata_annotations;
