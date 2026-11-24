--------------------------------------------------------
--  DDL for Package Body METADATA_ANNOTATIONS
--------------------------------------------------------

  CREATE OR REPLACE EDITIONABLE PACKAGE BODY "UBB_CORE2"."METADATA_ANNOTATIONS" 
AS

 /* package version */
 VERSION        constant varchar(12) := '1.1';
 
 type arr_number is 
         varray(PRVT_ANNOTATIONS_INTERNAL.NUM_IDENTIFIER_TYPE) of number;

 identifier_token_len arr_number := arr_number();

 M_IDEN CONSTANT NUMBER :=128; /* Maximum length of SQL identifier */

/* 
 * Opcodes for operations permitted in this pacakge. Used in privilege check 
 * 
 */
 
 OPCODE_GET     constant number := 1;
 OPCODE_SET     constant number := 2;
 OPCODE_EDIT    constant number := 3;
 OPCODE_DELETE  constant number := 4;

  PROCEDURE log(log_val IN VARCHAR2) IS
  BEGIN
   IF(FALSE) THEN
      DBMS_OUTPUT.PUT_LINE(log_val);
   END IF;
  END;

 procedure init_identifier_token_len
 as 
 begin
  identifier_token_len.extend
         (PRVT_ANNOTATIONS_INTERNAL.NUM_IDENTIFIER_TYPE);

  /* SCHEMA.TABLE */
  identifier_token_len
         (PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE) :=2; 

  /*SCHEMA.TABLE.COLUMN */
  identifier_token_len
         (PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_COLUMN) :=3; 

  /*SCHEMA.TABLE.PARTITION */
  identifier_token_len
         (PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_PARTITION) :=3; 

  /*SCHEMA.TABLE.SUBPARTITION */
  identifier_token_len
         (PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_SUBPARTITION) :=3;     

  /* SCHEMA.VIEW */
  identifier_token_len
         (PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_VIEW) :=2; 
  
  /* SCHEMA.MATERIALIZED_VIEW */
  identifier_token_len
         (PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_MTRLZD_VIEW) :=2; 

  /*SCHEMA.VIEW.COLUMN */
  identifier_token_len
         (PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_VIEW_COLUMN) :=3; 
  
   /*SCHEMA.MATERIALIZED_VIEW.COLUMN */
  identifier_token_len
         (PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_MTRLZD_VIEW_COLUMN) :=3; 

  /* SCHEMA.PACKAGE */
  identifier_token_len(PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE) :=2; 

  /*SCHEMA.PACAKGE.PROCEDURE */
  identifier_token_len(PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE_PROCEDURE) :=3; 

  /* SCHEMA.PACKAGE.FUNCTION */
  identifier_token_len(PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE_FUNCTION) :=3; 

  /*SCHEMA.PROCEDURE */
  identifier_token_len(PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PROCEDURE) :=2;
  
  /*SCHEMA.FUNCTION */
  identifier_token_len(PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_FUNCTION) :=2; 

  /*SCHEMA */
  identifier_token_len(PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_SCHEMA) :=1; 
  
  /* Identifier name should be null */
  /* The DB being annoted is the current DB */
  identifier_token_len(PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_DATABASE) :=0;

  /* GROUP */
  identifier_token_len(PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_GROUP) :=1;

 end;

 function check_user_has_access_to_obj(
         identifier_type_int   in number,
         obj#                  in number,
         obj#_owner            in number,
         curr_user_id          in number,
         curr_user_name        in varchar2,
         identifier_components in
          metadata_annotations.identifier_components_t
 )
 return boolean
 as
  privilages_needed       SYS.ODCIVARCHAR2LIST  := SYS.ODCIVARCHAR2LIST();
  privilaged_object_name  varchar2(128);
  access_count            number  := 0;
  user_has_dba_role       boolean := false;
 begin

  -- No access needed for database annotation and group level annotation
  -- TODO : group level annoations checks?
  -- FYI:
  -- For Schema
  -- We will never reach here for Schema, coz , after splitting in the previous
  -- step , we lookup all_users and we won't find it. There itself we will
  -- throw error.
  IF identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_DATABASE or
     identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_GROUP    or
     identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_SCHEMA
  THEN
    log('No check needed for database and group level annotation');
    RETURN TRUE;
  END IF;

  -- Implict Access via object ownership
  IF curr_user_id = obj#_owner THEN
    log('Current User owns the Object being annotated.');
    RETURN TRUE;
  END IF;

  -- Check if access has been granted to the user
  -- via direct grant or via a role

  IF identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE OR
     identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_COLUMN OR
     identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_VIEW OR
     identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_VIEW_COLUMN OR 
     identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_MTRLZD_VIEW OR
     identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_MTRLZD_VIEW_COLUMN 
  THEN

      privilages_needed.EXTEND(2);
      privilages_needed(1)   := 'READ'; 
      privilages_needed(2)   := 'SELECT'; 
      privilaged_object_name := identifier_components('OBJECT_NAME');

  ELSIF identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_PARTITION OR
        identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_SUBPARTITION 
  THEN

      privilages_needed.EXTEND(2);
      privilages_needed(1)   := 'READ'; 
      privilages_needed(2)   := 'SELECT'; 
      privilaged_object_name := identifier_components('TABLE');
      
  ELSIF identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE OR
        identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE_PROCEDURE OR
        identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE_FUNCTION OR
        identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PROCEDURE OR
        identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_FUNCTION 
  THEN
      privilages_needed.EXTEND(1);
      privilages_needed(1)   := 'EXECUTE'; 
      privilaged_object_name := identifier_components('OBJECT_NAME');
  END IF;

  log('Checking granted privilages ' ||
       ' curr_user_name '            || curr_user_name         ||
       ' privilaged_object_name '    || privilaged_object_name);

  -- (Even though the column name in the view all_tab_privs is table name, 
  --  it also contains privilege information for packages as well)
  SELECT COUNT(*) into access_count
  FROM SYS.ALL_TAB_PRIVS
  WHERE ( 
          GRANTEE = curr_user_name OR                                /* Access granted to the User directly */
          GRANTEE IN (SELECT GRANTED_ROLE FROM sys.user_role_privs)    /* Access granted to the User via a role */
        )
    AND TABLE_NAME   = privilaged_object_name
    AND TABLE_SCHEMA = identifier_components('SCHEMA')
    AND PRIVILEGE IN (SELECT COLUMN_VALUE FROM TABLE(privilages_needed));

  IF access_count > 0
  then
    log('User has necessary privilages');
    return TRUE;
  else 
    log('User does not have necessary privilages');
    return FALSE;
  END IF;

 end;

/* 
 * Checks if the current user has the privileges to annnotate
 *  Check 1 - See if the User is the owner or has access to the
 *            object being annotated.
 *  Check 2 - (TBD) is the owner of the annotation? Needed?
 *            Issue, Only one user can be annotation owner,
 *            but multiple users can have access to the object.
 */ 
function check_annotation_privilege(
         identifier_type_int   in number,
         identifier_components in identifier_components_t,
         opcode                in number,
         obj#                  in number,
         obj#_owner            in number,
         user_id               in number,
         user_name             in varchar2)
return boolean
as 
  has_privilege boolean := TRUE;
begin
  has_privilege := check_user_has_access_to_obj(identifier_type_int,
                                  obj#,
                                  obj#_owner,
                                  user_id,
                                  user_name,
                                  identifier_components);

  return has_privilege;
end;

procedure split_identifier_name_tokens(
    identifier_name              IN  VARCHAR2,
    identifier_name_split_pieces OUT SYS.ODCIVARCHAR2LIST,  
    split_successful             OUT BOOLEAN
) IS
    pos1_identifier_piece  VARCHAR2(128);
    pos2_identifier_piece  VARCHAR2(128);
    pos3_identifier_piece  VARCHAR2(128);

    identifier_piece_count  PLS_INTEGER := 0;

    dummy_param_1  VARCHAR2(4000);
    v_nextpos      BINARY_INTEGER;

BEGIN

    log('Attempting to split identifier name: ' || identifier_name);

    split_successful             := TRUE;
    identifier_name_split_pieces := SYS.ODCIVARCHAR2LIST();

    IF(identifier_name IS NULL) THEN
     RETURN ;
    END IF;

    BEGIN

      DBMS_UTILITY.NAME_TOKENIZE(identifier_name, 
                                 pos1_identifier_piece, 
                                 pos2_identifier_piece, 
                                 pos3_identifier_piece, 
                                 dummy_param_1, v_nextpos);

    EXCEPTION
        WHEN OTHERS THEN
          split_successful := FALSE;
          log('Error occurred during NAME_TOKENIZE: ' || SQLERRM);
          RETURN;
    END;

   /* Catch Unparsed Trailing Characters (e.g., spaces)
    * NAME_TOKENIZE stops parsing when it hits an invalid character like a space.
    * 'nextpos' returns the index of the LAST valid character successfully parsed.
    * By checking SUBSTR starting at (nextpos + 1), we isolate any leftover 
    * garbage text. If anything remains (other than trailing spaces), it's invalid.
    */    
    IF TRIM(SUBSTR(identifier_name, v_nextpos + 1)) IS NOT NULL THEN
          RAISE_APPLICATION_ERROR(
              -20001, 
              'Invalid Identifier Name: ''' || identifier_name || '''. ' ||
              'Name contains spaces or invalid characters. If spaces are required, enclose the specific identifier in double quotes.'
          );
    END IF;

    IF pos1_identifier_piece IS NOT NULL 
    THEN
       identifier_name_split_pieces.EXTEND;
       identifier_piece_count := identifier_piece_count + 1;
       identifier_name_split_pieces(identifier_piece_count) := pos1_identifier_piece;
       log('Identifier at POS 1 ' || pos1_identifier_piece);
    END IF;

    IF pos2_identifier_piece IS NOT NULL
    THEN
       identifier_name_split_pieces.EXTEND;
       identifier_piece_count := identifier_piece_count + 1;
       identifier_name_split_pieces(identifier_piece_count) := pos2_identifier_piece;
       log('Identifier at POS 2 ' || pos2_identifier_piece);
    END IF;

    IF pos3_identifier_piece IS NOT NULL
    THEN
       identifier_name_split_pieces.EXTEND;
       identifier_piece_count := identifier_piece_count + 1;
       identifier_name_split_pieces(identifier_piece_count) := pos3_identifier_piece;
       log('Identifier at POS 3 ' || pos3_identifier_piece);
    END IF;

END; 

/* 
 *Procedure to assign the split identifier name tokens to the 
 * identifier components based on the identifier type
 * Ex: Say the identifier type is TABLE and the tokens are SCOTT and EMP
 * This procedure assigns SCOTT as the schema name and EMP as the table name
 * Assumes that the caller has passed the correct number of tokens 
 */
procedure assign_identifier_components(
    identifier_type_int in number,
    identifier_name_split_tokens in SYS.ODCIVARCHAR2LIST,
    identifier_components in out identifier_components_t)
as
    default_schema varchar2(128);
begin
   
  default_schema := sys_context('USERENV','CURRENT_SCHEMA');
  
  case (identifier_type_int)

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_SCHEMA then
      if identifier_name_split_tokens.count < 1 
          or identifier_name_split_tokens(1) is null then
        --raise_application_error(-20001, 'To annotate a Schema, Schema name required');
        identifier_components('SCHEMA') := default_schema;
      else
        identifier_components('SCHEMA') := identifier_name_split_tokens(1);
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE then
      if identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA') := identifier_name_split_tokens(1);
        identifier_components('TABLE')  := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME') := identifier_name_split_tokens(2);
      elsif identifier_name_split_tokens.count = 1 then
        identifier_components('SCHEMA') := default_schema;
        identifier_components('TABLE')  := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME') := identifier_name_split_tokens(1);
      else
        raise_application_error(-20002, 'Invalid tokens for TABLE type');
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_COLUMN then
      if identifier_name_split_tokens.count = 3 then
        identifier_components('SCHEMA')      := identifier_name_split_tokens(1);
        identifier_components('TABLE')       := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME') := identifier_name_split_tokens(2);
        identifier_components('COLUMN_NAME') := identifier_name_split_tokens(3);
      elsif identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA')      := default_schema;
        identifier_components('TABLE')       := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME') := identifier_name_split_tokens(1);
        identifier_components('COLUMN_NAME') := identifier_name_split_tokens(2);
      else
        raise_application_error(-20003, 'Invalid tokens for TABLE_COLUMN type');
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_PARTITION then
      if identifier_name_split_tokens.count = 3 then
        identifier_components('SCHEMA')        := identifier_name_split_tokens(1);
        identifier_components('TABLE')         := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME')   := identifier_name_split_tokens(3);
        identifier_components('PARTITION_NAME'):= identifier_name_split_tokens(3);
      elsif identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA')        := default_schema;
        identifier_components('TABLE')         := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME')   := identifier_name_split_tokens(2);
        identifier_components('PARTITION_NAME'):= identifier_name_split_tokens(2);
      else
        raise_application_error(-20004, 'Invalid tokens for TABLE_PARTITION type');
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_SUBPARTITION then
      if identifier_name_split_tokens.count = 3 then
        identifier_components('SCHEMA')           := identifier_name_split_tokens(1);
        identifier_components('TABLE')            := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME')      := identifier_name_split_tokens(3);
        identifier_components('SUBPARTITION_NAME'):= identifier_name_split_tokens(3);
      elsif identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA')           := default_schema;
        identifier_components('TABLE')            := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME')      := identifier_name_split_tokens(2);
        identifier_components('SUBPARTITION_NAME'):= identifier_name_split_tokens(2);
      else
        raise_application_error(-20005, 'Invalid tokens for TABLE_SUBPARTITION type');
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_VIEW then
      if identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA')      := identifier_name_split_tokens(1);
        identifier_components('VIEW')        := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME') := identifier_name_split_tokens(2);
      elsif identifier_name_split_tokens.count = 1 then
        identifier_components('SCHEMA')      := default_schema;
        identifier_components('VIEW')        := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME') := identifier_name_split_tokens(1);
      else
        raise_application_error(-20006, 'Invalid tokens for VIEW type');
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_VIEW_COLUMN then
      if identifier_name_split_tokens.count = 3 then
        identifier_components('SCHEMA')      := identifier_name_split_tokens(1);
        identifier_components('VIEW')        := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME') := identifier_name_split_tokens(2);
        identifier_components('COLUMN_NAME') := identifier_name_split_tokens(3);
      elsif identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA')      := default_schema;
        identifier_components('VIEW')        := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME') := identifier_name_split_tokens(1);
        identifier_components('COLUMN_NAME') := identifier_name_split_tokens(2);
      else
        raise_application_error(-20007, 'Invalid tokens for VIEW_COLUMN type');
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE then
      if identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA')       := identifier_name_split_tokens(1);
        identifier_components('PACKAGE_NAME') := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME')  := identifier_name_split_tokens(2);
      elsif identifier_name_split_tokens.count = 1 then
        identifier_components('SCHEMA')       := default_schema;
        identifier_components('PACKAGE_NAME') := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME')  := identifier_name_split_tokens(1);
      else
        raise_application_error(-20008, 'Invalid tokens for PACKAGE type');
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE_PROCEDURE then
      if identifier_name_split_tokens.count = 3 then
        identifier_components('SCHEMA')         := identifier_name_split_tokens(1);
        identifier_components('PACKAGE_NAME')   := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME')    := identifier_name_split_tokens(2);
        identifier_components('PROCEDURE_NAME') := identifier_name_split_tokens(3);
      elsif identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA')         := default_schema;
        identifier_components('PACKAGE_NAME')   := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME')    := identifier_name_split_tokens(1);
        identifier_components('PROCEDURE_NAME') := identifier_name_split_tokens(2);
      else
        raise_application_error(-20009, 'Invalid tokens for PACKAGE_PROCEDURE type');
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE_FUNCTION then
      if identifier_name_split_tokens.count = 3 then
        identifier_components('SCHEMA')         := identifier_name_split_tokens(1);
        identifier_components('PACKAGE_NAME')   := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME')    := identifier_name_split_tokens(2);
        identifier_components('FUNCTION_NAME')  := identifier_name_split_tokens(3);
      elsif identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA')         := default_schema;
        identifier_components('PACKAGE_NAME')   := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME')    := identifier_name_split_tokens(1);
        identifier_components('FUNCTION_NAME')  := identifier_name_split_tokens(2);
      else
        raise_application_error(-20010, 'Invalid tokens for PACKAGE_FUNCTION type');
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PROCEDURE then
      if identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA')         := identifier_name_split_tokens(1);
        identifier_components('PROCEDURE_NAME') := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME')    := identifier_name_split_tokens(2);
      elsif identifier_name_split_tokens.count = 1 then
        identifier_components('SCHEMA')         := default_schema;
        identifier_components('PROCEDURE_NAME') := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME')    := identifier_name_split_tokens(1);
      else
        raise_application_error(-20011, 'Invalid tokens for PROCEDURE type');
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_FUNCTION then
      if identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA')         := identifier_name_split_tokens(1);
        identifier_components('FUNCTION_NAME')  := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME')    := identifier_name_split_tokens(2);
      elsif identifier_name_split_tokens.count = 1 then
        identifier_components('SCHEMA')         := default_schema;
        identifier_components('FUNCTION_NAME')  := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME')    := identifier_name_split_tokens(1);
      else
        raise_application_error(-20012, 'Invalid tokens for FUNCTION type');
      end if;

    /* Nothing to extract for DB Type. As its the current DB being annotated */
    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_DATABASE then
      if identifier_name_split_tokens.count > 0 then
        raise_application_error(-20013, 'Invalid tokens for DATABASE type');
      end if;
    
    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_MTRLZD_VIEW then
      if identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA')      := identifier_name_split_tokens(1);
        identifier_components('MATERIALIZED_VIEW')  := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME') := identifier_name_split_tokens(2);
      elsif identifier_name_split_tokens.count = 1 then
        identifier_components('SCHEMA')      := default_schema;
        identifier_components('MATERIALIZED_VIEW') := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME') := identifier_name_split_tokens(1);
      else
        raise_application_error(-20014, 'Invalid tokens for MATERIALIZED VIEW type');
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_MTRLZD_VIEW_COLUMN then
      if identifier_name_split_tokens.count = 3 then
        identifier_components('SCHEMA')      := identifier_name_split_tokens(1);
        identifier_components('MATERIALIZED_VIEW') := identifier_name_split_tokens(2);
        identifier_components('OBJECT_NAME') := identifier_name_split_tokens(2);
        identifier_components('COLUMN_NAME') := identifier_name_split_tokens(3);
      elsif identifier_name_split_tokens.count = 2 then
        identifier_components('SCHEMA')      := default_schema;
        identifier_components('MATERIALIZED_VIEW') := identifier_name_split_tokens(1);
        identifier_components('OBJECT_NAME') := identifier_name_split_tokens(1);
        identifier_components('COLUMN_NAME') := identifier_name_split_tokens(2);
      else
        raise_application_error(-20015, 'Invalid tokens for MATERIALIZED_VIEW_COLUMN type');
      end if;

    when PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_GROUP then
      if identifier_name_split_tokens.count = 1 then
        identifier_components('GROUP_NAME')      := identifier_name_split_tokens(1);
        
      else
        raise_application_error(-20015, 'Invalid tokens for MATERIALIZED_VIEW_COLUMN type');
      end if;

    else
      raise_application_error(-20000, 'Invalid identifier type');

  end case;
end;

/* 
 * Procedure to split the identifier name to 
 * <owner,object_name, subobject_name, annotation_targer>
 */

procedure split_identifier_name(
           identifier_type_int in number,
           identifier_name in varchar2,
           identifier_components in out identifier_components_t)

as 
v_delimiter varchar2(1) := '.';
v_delimiter_pos number;
split_successful boolean;
identifier_name_split_tokens  SYS.ODCIVARCHAR2LIST;
expected_len number;

begin
 
 split_identifier_name_tokens(identifier_name,
                              identifier_name_split_tokens,
                              split_successful);

 if (split_successful = FALSE) then
   raise_application_error(-20000, 'Invalid identifier_name : Parsing Failed');
 end if;

 expected_len := identifier_token_len(identifier_type_int);
 
 if    identifier_name_split_tokens.COUNT = expected_len 
    OR identifier_name_split_tokens.COUNT = expected_len - 1 then
      NULL;
 else
   raise_application_error(-20000,
    'Invalid identifier_name : Len mismatch. ' ||
    'Actual : ' || identifier_name_split_tokens.COUNT ||
    ' Expected : (' || (expected_len - 1) || ' or ' || expected_len || ')');
 end if;

 FOR i IN 1 .. identifier_name_split_tokens.COUNT LOOP
    log('Position ' || i || ': ' ||
                         identifier_name_split_tokens(i));
 END LOOP; 

 assign_identifier_components(
         identifier_type_int,
         identifier_name_split_tokens,
         identifier_components);
end;


PROCEDURE check_package_proc_func_exists(
                            p_package_name IN VARCHAR2, 
                            p_procedure_or_function_name IN VARCHAR2) 
IS
  v_count NUMBER;
BEGIN

   /* ALL_PROCEDURES has both procedures and functions */

    SELECT COUNT(*)
      INTO v_count
      FROM SYS.ALL_PROCEDURES
     WHERE OBJECT_TYPE = 'PACKAGE'
       AND OBJECT_NAME = p_package_name
       AND PROCEDURE_NAME = p_procedure_or_function_name;

    IF v_count = 0 THEN
      RAISE_APPLICATION_ERROR(-20002, ' ' || p_procedure_or_function_name || ' does not exist in package ' || p_package_name);
    END IF;
END check_package_proc_func_exists;


PROCEDURE check_view_table_colum_exists(
                            p_view_or_table_name IN VARCHAR2, 
                            p_column_name IN VARCHAR2) 
IS
  v_count NUMBER;
BEGIN

   /* ALL_TAB_COLUMNS has both table and view columns */

    SELECT COUNT(*)
      INTO v_count
      FROM SYS.ALL_TAB_COLUMNS
     WHERE TABLE_NAME = p_view_or_table_name
       AND COLUMN_NAME = p_column_name;

    IF v_count = 0 THEN
      RAISE_APPLICATION_ERROR(-20005, 'Column ' || p_column_name || ' does not exist in ' || p_view_or_table_name);
    END IF;

END check_view_table_colum_exists;

PROCEDURE validate_non_object_existance(
                            v_object_name IN VARCHAR2,
                            identifier_type_int IN NUMBER,
                            identifier_components IN identifier_components_t)
IS
BEGIN

  IF identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE_PROCEDURE
  THEN
    check_package_proc_func_exists(
          v_object_name,
          identifier_components('PROCEDURE_NAME'));
  ELSIF identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE_FUNCTION THEN
    check_package_proc_func_exists(
          v_object_name,
          identifier_components('FUNCTION_NAME'));
  ELSIF identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_COLUMN OR
        identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_VIEW_COLUMN OR
        identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_MTRLZD_VIEW_COLUMN
  THEN
    check_view_table_colum_exists(
          v_object_name,
          identifier_components('COLUMN_NAME'));
  END IF;

END validate_non_object_existance;

/* 
 * 1. Sanitize_arguments: 
 *     a. Ensure identifier_type passed is allowed
 *     b. If an annotation already exists, for the same label throw an 
 *        error
 * 
 * 2. Complete the annotation set operation using the database internal 
 *    package
 * 
 */
procedure sanitize_and_get_internal_rep
          (identifier_name       in  varchar2,
           identifier_type       in  varchar2,
           identifier_type_int   out number,
           base_obj_id           out number,  
           base_obj_owner_id     out number,
           identifier_components out identifier_components_t)    
as
   current_user                varchar2(M_IDEN);
   current_user_id             number;
   is_authorized               boolean := FALSE;
   identifier_type_has_baseobj boolean := FALSE;
   object_type_base_obj        varchar2(128);
   v_owner                     varchar2(128);
   v_object_name               varchar2(128);
   v_subobject_name            varchar2(128);
   base_obj_owner_name         varchar2(128);
   idx                         VARCHAR2(100);
begin

identifier_components := identifier_components_t();
/*  1. Sanitize_arguments: 
 *     a. Ensure identifier_type passed is allowed. 
 *     b. Ensure size of annotation_name and annotation_value due to 
 *        exceed limits.
 */

 CASE (identifier_type)
     when 'TABLE' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'TABLE';
     when 'TABLE COLUMN' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_COLUMN;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'TABLE';
     when 'TABLE PARTITION' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_PARTITION;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'TABLE PARTITION';        
     when 'TABLE SUBPARTITION' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_SUBPARTITION;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'TABLE SUBPARTITION';              
     when 'VIEW' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_VIEW;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'VIEW';
     when 'VIEW COLUMN' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_VIEW_COLUMN;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'VIEW';        
     when 'MATERIALIZED VIEW' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_MTRLZD_VIEW;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'MATERIALIZED VIEW';
     when 'MATERIALIZED VIEW COLUMN' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_MTRLZD_VIEW_COLUMN;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'MATERIALIZED VIEW';        
     when 'PACKAGE' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'PACKAGE';
     when 'PACKAGE PROCEDURE' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE_PROCEDURE;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'PACKAGE';
     when 'PACKAGE FUNCTION' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PACKAGE_FUNCTION;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'PACKAGE';
     when 'PROCEDURE' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_PROCEDURE;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'PROCEDURE';
     when 'FUNCTION' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_FUNCTION;
        identifier_type_has_baseobj := TRUE;
        object_type_base_obj := 'FUNCTION';
     when 'SCHEMA' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_SCHEMA;
        identifier_type_has_baseobj := FALSE;
     when 'DATABASE' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_DATABASE;
        identifier_type_has_baseobj := FALSE;
     when 'GROUP' then
        identifier_type_int := PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_GROUP;
        identifier_type_has_baseobj := FALSE;
     else 
        raise_application_error(-20000, 'Invalid annotation type');   
 END CASE;

  log ('Identifier internal type ' || identifier_type_int);


 /* 
  * 3. If authorized, add the annotation
  *    a. Get current user
  *    b. Get obj# from arguments
  */

  current_user := SYS_CONTEXT('USERENV', 'CURRENT_USER');
  select user_id into current_user_id
    from sys.all_users
   where username = current_user;
 
  split_identifier_name(identifier_type_int,
                        identifier_name,
                        identifier_components);

  idx := identifier_components.FIRST;
  WHILE idx IS NOT NULL LOOP
    log(idx || ' = ' || identifier_components(idx));
    idx := identifier_components.NEXT(idx);
  END LOOP;

  log('Current user: ' || current_user || '; Id ' 
                       || current_user_id);

 
  if(identifier_type_has_baseobj) then 

    BEGIN

      IF(identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_PARTITION OR
        identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_SUBPARTITION)
      THEN

        v_owner          := identifier_components('SCHEMA');
        v_object_name    := identifier_components('TABLE');

        IF (identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_TABLE_PARTITION) THEN
          v_subobject_name := identifier_components('PARTITION_NAME');
        ELSE
          v_subobject_name := identifier_components('SUBPARTITION_NAME');
        END IF;
    

        select object_id, OWNER into 
              base_obj_id, base_obj_owner_name
          from sys.all_objects 
        where object_name    = v_object_name
          and subobject_name = v_subobject_name
          and owner          = v_owner
          and object_type    = object_type_base_obj; 

        select user_id into base_obj_owner_id
        from   sys.all_users
        where username = base_obj_owner_name;

        log(' v_owner '              || v_owner              || 
            ' v_object_name '        || v_object_name        ||
            ' v_subobject_name '     || v_subobject_name     || 
            ' object_type_base_obj ' || object_type_base_obj ||
            ' base_obj_owner_id '    || base_obj_owner_id);

      ELSE

        v_owner       := identifier_components('SCHEMA');
        v_object_name := identifier_components('OBJECT_NAME');

        /* v_object_name,  v_owner will already be upper case
           as they are extracted from indentifer name which will be
           uppercased at the begining itself */
        select object_id, OWNER into 
              base_obj_id, base_obj_owner_name
          from sys.all_objects 
        where object_name = v_object_name
          and owner       = v_owner
          and object_type        = object_type_base_obj;

        select user_id into base_obj_owner_id
        from   sys.all_users
        where username = base_obj_owner_name;        

        validate_non_object_existance(v_object_name,
                                      identifier_type_int,
                                      identifier_components);   

        log(' v_owner: '             || v_owner              || 
            ' v_object_name '        || v_object_name        ||
            ' v_subobject_name '     || v_subobject_name     ||
            ' object_type_base_obj ' || object_type_base_obj ||
            ' base_obj_owner_id '    || base_obj_owner_id);

      END IF;
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
          raise_application_error(-20003, 
                                  'Object does not exist or insufficient privileges');
    END;    
  ELSE

   IF identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_SCHEMA
     THEN

      BEGIN
         v_owner       := identifier_components('SCHEMA');
         base_obj_id   := -1;

         select user_id into base_obj_owner_id
         from   sys.all_users
         where username = v_owner;

         log(' v_owner: '              || v_owner               || 
             ' base_obj_owner_id '     || base_obj_owner_id     ||
             ' base_obj_id '           || base_obj_id );

      EXCEPTION
          WHEN NO_DATA_FOUND THEN
                    raise_application_error(-20003, 
                                            'Specified User does not exist or insufficient privileges');
      END; 
     ELSIF identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_DATABASE OR
           identifier_type_int = PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_GROUP
     THEN

         base_obj_id       := -1;
         base_obj_owner_id := -1;

     END IF;

  end if;

end;

PROCEDURE check_null_and_len_for_label (
                label              IN  VARCHAR2
) IS
BEGIN

  IF label is NULL THEN
    RAISE_APPLICATION_ERROR(-20001, 'Label is mandatory and cannot be null');
  END IF;

  IF LENGTH(label) > 1024 THEN
      RAISE_APPLICATION_ERROR(-20001, 'Label length exceeds 1024 characters limit');
  END IF;

END;

PROCEDURE check_len_for_value (
                value              IN  VARCHAR2
) IS
BEGIN

  IF value IS NOT NULL AND LENGTH(value) > 4000 THEN
      RAISE_APPLICATION_ERROR(-20001, 'Value length exceeds 4000 characters limit');
  END IF;

END;

PROCEDURE check_null_for_identifier(
              identifier_type_in    IN  varchar2,
              identifier_type_out   OUT varchar2,
              identifier_name_in    IN  VARCHAR2) IS
BEGIN

  /* Identifier_type won't be null as it defaults to Table in the caller */
  identifier_type_out := UPPER(identifier_type_in);

  /* For DATABASE, identifier name will be NULL,
     For SCHEMA,   identifier name can be NULL */
  IF identifier_type_out = 'DATABASE' OR identifier_type_out = 'SCHEMA'
  THEN
      NULL;
  ELSE
    IF identifier_name_in is NULL
    THEN
      RAISE_APPLICATION_ERROR(-20001, 'Identifier Name is mandatory and cannot be null ');
    END IF;
  END IF;

END check_null_for_identifier;

PROCEDURE chk_null_annotation_operation(
                  identifier_type_in    IN  varchar2,
                  identifier_type_out   OUT varchar2,
                  identifier_name_in    IN  VARCHAR2,
                  label                 IN  VARCHAR2,
                  value                 IN  VARCHAR2)
 IS
BEGIN
  check_null_and_len_for_label(label);
  check_len_for_value(value);
  check_null_for_identifier(identifier_type_in,
                            identifier_type_out,
                            identifier_name_in);

END;

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
Procedure set(
          label            in  varchar2,
          value            in  varchar2,
          identifier_name  In Varchar2,
          identifier_type  in varchar2)
as 
   current_user            varchar2(M_IDEN);
   current_user_id         number;
   is_authorized           boolean := FALSE;
   identifier_type_int     number; 
   obj#                    number;  /* Object number of the annotated object */
   obj#_owner              number;  /* OwnerID of the Object being annotated */
   v_owner                 varchar2(128);
   v_object_name           varchar2(128);
   identifier_components   identifier_components_t;
   object_type_base_obj    varchar2(128);
   opcode                  number;
   has_privilege           boolean   := FALSE;
   identifier_type_upper   varchar2(M_IDEN);
begin
   
   chk_null_annotation_operation(identifier_type,
                                 identifier_type_upper ,
                                 identifier_name,
                                 label,
                                 value);

    /*
     
      STEPS:
        1. For each annotation <name, value> pair:
        2. call set() procedure 
     
     */ 
    sanitize_and_get_internal_rep(
             identifier_name,
             identifier_type_upper,
             identifier_type_int,
             obj#,
             obj#_owner,
             identifier_components);

    /* get user information */
    current_user := SYS_CONTEXT('USERENV', 'CURRENT_USER');
    select user_id into current_user_id
      from sys.all_users
     where username = current_user;
    
    /* privilege check */    
    opcode := OPCODE_SET; 
    has_privilege := check_annotation_privilege(identifier_type_int,
                                                identifier_components,
                                                opcode, 
                                                obj#,
                                                obj#_owner,
                                                current_user_id,
                                                current_user);
  
    if (has_privilege <> TRUE) then
      raise_application_error(-20000, 'Insufficient privileges');   
    end if;

   /*
    * Deal with Schema and Database types which do not have obj#
    */
    begin 
      prvt_annotations_internal.set(
            current_user_id,
            label,
            value,
            identifier_type_int,
            obj#,
            obj#_owner,
            identifier_components); 
    exception
      when DUP_VAL_ON_INDEX THEN
        raise_application_error(-20000, 'Annotation already exists. Use edit' 
            || ' procedure to replace value') ;
    end;

end;

/* DESCRIPTION: Public API to modify the value of a particular annotation name
 * 
 * PARAMETERS:
 *  label               (in)   annotation label to be modified
 *  identifier_name     (in)   fully qualified identifier name
 *  identifier_type     (in)   identifier type (defaults to 'TABLE')
 *
 * USAGE:
 *  metadata_annotations.edit(label, identifier_name, identifier_type) 
 */
procedure edit(
          label In varchar2,
          value In varchar2,
          identifier_name in varchar2, 
          identifier_type In varchar2 default 'TABLE',
          old_value in varchar2 default NULL
          )
as
   current_user            varchar2(M_IDEN);
   current_user_id         number;
   is_authorized           boolean := FALSE;
   identifier_type_int     number; 
   obj#                    number;  /* Object number of the annotated object */
   obj#_owner              number;  /* OwnerID of the Object being annotated */
   v_owner                 varchar2(128);
   v_object_name           varchar2(128);
   identifier_components   identifier_components_t;
   object_type_base_obj    varchar2(128);
   opcode                  number;
   has_privilege           boolean   := FALSE;
   identifier_type_upper   varchar2(M_IDEN);
begin

   chk_null_annotation_operation(identifier_type,
                                 identifier_type_upper,
                                 identifier_name,
                                 label,
                                 value);      

     sanitize_and_get_internal_rep(
             identifier_name,
             identifier_type_upper,
             identifier_type_int,
             obj#, 
             obj#_owner,
             identifier_components);
 
  
    /* get user information */
    current_user := SYS_CONTEXT('USERENV', 'CURRENT_USER');
    select user_id into current_user_id
      from sys.all_users
     where username = current_user;
    
    /* privilege check */    
    opcode := OPCODE_EDIT;
    has_privilege := check_annotation_privilege(identifier_type_int,
                                                identifier_components,
                                                opcode,
                                                obj#,
                                                obj#_owner,
                                                current_user_id,
                                                current_user);

    if (has_privilege) then  
      prvt_annotations_internal.edit(
           current_user_id,
           label,
           value,
           old_value,
           identifier_type_int,
           obj#,
           obj#_owner,
           identifier_components); 
  else
    raise_application_error(-20000, 'Insufficient privileges');   
  end if;

end;

/* DESCRIPTION: Public API to get value for a particular annotation name
 * 
 * PARAMETERS:
 *  label               (in)   annotation label to be looked up
 *  identifier_name     (in)   fully qualified identifier name
 *  identifier_type     (in)   identifier type (defaults to 'TABLE')
 *
 * USAGE:
 *  metadata_annotations.get(label, identifier_name, identifier_type) 
 */
function  get(
          label in varchar2,
          identifier_name in varchar2,
          identifier_type in varchar2  default 'TABLE')
return clob
as 
   current_user            varchar2(M_IDEN);
   current_user_id         number;
   is_authorized           boolean := FALSE;
   identifier_type_int     number; 
   obj#                    number;  /* Object number of the annotated object */
   obj#_owner              number;  /* OwnerID of the Object being annotated */
   v_owner                 varchar2(128);
   v_object_name           varchar2(128);
   identifier_components   identifier_components_t;
   object_type_base_obj    varchar2(128);
   v_annotation_clob       clob := NULL;
   opcode                  number;
   has_privilege           boolean   := FALSE;
   identifier_type_upper   varchar2(M_IDEN);
begin

   chk_null_annotation_operation(identifier_type,
                                 identifier_type_upper,
                                 identifier_name,
                                 label,
                                 NULL);

  sanitize_and_get_internal_rep(
           identifier_name,
           identifier_type_upper,
           identifier_type_int,
           obj#, 
           obj#_owner,
           identifier_components);
  
  /* get user information */
  current_user := SYS_CONTEXT('USERENV', 'CURRENT_USER');
  select user_id into current_user_id
    from sys.all_users
   where username = current_user;
  
  /* privilege check */    
  opcode := OPCODE_GET; 
  has_privilege := check_annotation_privilege(identifier_type_int,
                                              identifier_components,
                                              opcode,
                                              obj#,
                                              obj#_owner,
                                              current_user_id,
                                              current_user);

  if (has_privilege) then  
    v_annotation_clob :=  prvt_annotations_internal.get(
                                 current_user_id,
                                 label,
                                 identifier_type_int,
                                 obj#,
                                 obj#_owner,
                                 identifier_components);
  else
    raise_application_error(-20000, 'Insufficient privileges');   
  end if;

  return v_annotation_clob;

end;

function get_json(
  label           in varchar2,
  identifier_name in varchar2,
  identifier_type in varchar2 default 'TABLE'
)
$IF DBMS_DB_VERSION.VERSION >= 21 $THEN
  return json
$ELSE
  return clob
$END
as
  current_user          varchar2(M_IDEN);
  current_user_id       number;
  identifier_type_int   number;
  obj#                  number;
  obj#_owner            number;
  identifier_components identifier_components_t;
  opcode                number;
  has_privilege         boolean := FALSE;
  identifier_type_upper varchar2(M_IDEN);
begin
  -- Validate inputs (aligned with existing get)
  chk_null_annotation_operation(identifier_type,
                                identifier_type_upper,
                                identifier_name,
                                label,
                                NULL);

  -- Resolve to internal representation
  sanitize_and_get_internal_rep(
       identifier_name,
       identifier_type_upper,
       identifier_type_int,
       obj#,
       obj#_owner,
       identifier_components);

  -- Privilege check
  current_user := SYS_CONTEXT('USERENV', 'CURRENT_USER');
  select user_id into current_user_id
    from sys.all_users
   where username = current_user;

  opcode := OPCODE_GET;
  has_privilege := check_annotation_privilege(identifier_type_int,
                                              identifier_components,
                                              opcode,
                                              obj#,
                                              obj#_owner,
                                              current_user_id,
                                              current_user);

  if not has_privilege then
    raise_application_error(-20000, 'Insufficient privileges');
  end if;

  -- Delegate to internal JSON implementation
  return prvt_annotations_internal.get_json(
                 current_user_id,
                 label,
                 identifier_type_int,
                 obj#,
                 obj#_owner,
                 identifier_components);

end get_json;

/* DESCRIPTION: Public API to delete a specified annotation 
 * 
 * PARAMETERS:
 *  label               (in)   annotation label to be deleted
 *  identifier_name     (in)   fully qualified identifier name
 *  identifier_type     (in)   identifier type (defaults to 'TABLE')
 *
 * USAGE:
 *  metadata_annotations.delete(label, identifier_name, identifier_type) 
 */
procedure delete(
          label in varchar2,
          identifier_name in varchar2,
          identifier_type in varchar2 default 'TABLE',
          value in varchar2 default NULL)
as
  current_user            varchar2(M_IDEN);
  current_user_id         number;
  obj#                    number;
  obj_owner               number;
  identifier_type_int     number;
  identifier_components   identifier_components_t;
  opcode                  number;
  has_privilege           boolean   := FALSE;
  identifier_type_upper   varchar2(M_IDEN);
begin
    
   chk_null_annotation_operation(identifier_type,
                                 identifier_type_upper,
                                 identifier_name,
                                 label,
                                 value);

    sanitize_and_get_internal_rep(
           identifier_name,
           identifier_type_upper,
           identifier_type_int,
           obj#, 
           obj_owner,
           identifier_components);
 
    /* get user information */
    current_user := SYS_CONTEXT('USERENV', 'CURRENT_USER');
    select user_id into current_user_id
       from sys.all_users
       where username = current_user;
    
    /* privilege check */    
    opcode := OPCODE_DELETE; 
    has_privilege := check_annotation_privilege(identifier_type_int,
                                                identifier_components,
                                                opcode,
                                                obj#,
                                                obj_owner,
                                                current_user_id,
                                                current_user);

    if(has_privilege) then
        prvt_annotations_internal.delete(
        current_user_id,
        label,
        value,
        identifier_type_int,
        obj#,
        obj_owner,
        identifier_components
        );
    else
        raise_application_error(-20000, 'Insufficient privileges');   
    end if;
end;

procedure delete_by_value_regex(
  label            in varchar2,
  identifier_name  in varchar2,
  identifier_type  in varchar2 default 'TABLE',
  value_pattern    in varchar2,
  match_parameter  in varchar2 default NULL)
as
  current_user          varchar2(M_IDEN);
  current_user_id       number;
  obj#                  number;
  obj_owner             number;
  identifier_type_int   number;
  identifier_components identifier_components_t;
  opcode                number;
  has_privilege         boolean := FALSE;
  identifier_type_upper varchar2(M_IDEN);
begin
  -- Basic validation and identifier checks
  chk_null_annotation_operation(identifier_type,
                                identifier_type_upper,
                                identifier_name,
                                label,
                                value_pattern);

  if value_pattern is null then
    raise_application_error(-20001, 'Regex pattern is mandatory');
  end if;

  -- Resolve to internal representation
  sanitize_and_get_internal_rep(
       identifier_name,
       identifier_type_upper,
       identifier_type_int,
       obj#,
       obj_owner,
       identifier_components);

  -- Privilege check, same as delete
  current_user := SYS_CONTEXT('USERENV', 'CURRENT_USER');
  select user_id into current_user_id
    from sys.all_users
   where username = current_user;

  opcode := OPCODE_DELETE;
  has_privilege := check_annotation_privilege(identifier_type_int,
                                              identifier_components,
                                              opcode,
                                              obj#,
                                              obj_owner,
                                              current_user_id,
                                              current_user);

  if not has_privilege then
    raise_application_error(-20000, 'Insufficient privileges');
  end if;

  -- Call internal implementation
  prvt_annotations_internal.delete_by_value_regex(
      current_user_id,
      label,
      value_pattern,
      match_parameter,
      identifier_type_int,
      obj#,
      obj_owner,
      identifier_components);
end delete_by_value_regex;

procedure chk_null_and_format_grp_name(
            group_name_in  IN  VARCHAR2,
            group_name_out OUT VARCHAR2)
AS
  identifier_components identifier_components_t;
BEGIN

  IF group_name_in is NULL THEN
    RAISE_APPLICATION_ERROR(-20001, 'Group Name is mandatory and cannot be null');
  END IF;

  identifier_components := identifier_components_t();

  BEGIN
    split_identifier_name(PRVT_ANNOTATIONS_INTERNAL.IDENTIFIER_GROUP,
                          group_name_in,
                          identifier_components);

    IF (NOT identifier_components.EXISTS('GROUP_NAME')) OR
       identifier_components('GROUP_NAME') IS NULL THEN
      RAISE_APPLICATION_ERROR(-20001, 'Invalid Group Name');
    END IF;

    group_name_out := identifier_components('GROUP_NAME');

  EXCEPTION
    WHEN OTHERS THEN
      RAISE_APPLICATION_ERROR(-20001, 'Invalid Group Name');
  END;

END chk_null_and_format_grp_name;

 procedure chk_null_group_operation(
              group_name              IN  VARCHAR2,
              group_name_formatted    OUT VARCHAR2,
              identifier_type         IN  varchar2,
              identifier_type_upper   OUT varchar2,
              identifier_name         IN  VARCHAR2)
  AS
  BEGIN

    chk_null_and_format_grp_name(group_name,
                                         group_name_formatted);

    check_null_for_identifier(identifier_type, 
                                  identifier_type_upper,
                                  identifier_name);

  END chk_null_group_operation;


  procedure create_group(group_name in VARCHAR2)
  as 
    group_name_formatted varchar2(M_IDEN);
  begin

    chk_null_and_format_grp_name(group_name, 
                                         group_name_formatted);

    prvt_annotations_internal.create_group(group_name_formatted);

  end;

  procedure drop_group(group_name in VARCHAR2)
  as 
    group_name_formatted varchar2(M_IDEN);
  begin

    chk_null_and_format_grp_name(group_name, 
                                         group_name_formatted);

    prvt_annotations_internal.drop_group(group_name_formatted);

  end;

procedure add_to_group(group_name in VARCHAR2,
                       identifier_name in varchar2,
                       identifier_type in varchar2 default 'TABLE')
as 
  current_user            varchar2(M_IDEN);
  current_user_id         number;
  obj#                    number;
  obj_owner               number;
  identifier_type_int     number;
  identifier_components   identifier_components_t;
  opcode                  number;
  has_privilege           boolean   := FALSE;
  identifier_type_upper   varchar2(M_IDEN);
  group_name_formatted    varchar2(M_IDEN);
begin

  chk_null_group_operation(group_name,
                           group_name_formatted,
                           identifier_type, 
                           identifier_type_upper,
                           identifier_name);

  sanitize_and_get_internal_rep(
       identifier_name,
       identifier_type_upper,
       identifier_type_int,
       obj#, 
       obj_owner,
       identifier_components);

  /* get user information */
  current_user := SYS_CONTEXT('USERENV', 'CURRENT_USER');
  select user_id into current_user_id
     from sys.all_users
     where username = current_user;
    
  /* privilege check */    
  opcode := OPCODE_SET; 
  has_privilege := check_annotation_privilege(identifier_type_int,
                                              identifier_components,
                                              opcode,
                                              obj#,
                                              obj_owner,
                                              current_user_id,
                                              current_user);

  if(has_privilege) then
    prvt_annotations_internal.add_to_group(group_name_formatted,
                                           obj#,
                                           obj_owner,
                                           identifier_type_int,
                                           identifier_components);
  else
    raise_application_error(-20000, 'Insufficient privileges');   
  end if;

end;

procedure delete_from_group(group_name      in VARCHAR2,
                            identifier_name in varchar2,
                            identifier_type in varchar2 default 'TABLE')
as 
  current_user            varchar2(M_IDEN);
  current_user_id         number;
  obj#                    number;
  obj_owner               number;
  identifier_type_int     number;
  identifier_components   identifier_components_t;
  opcode                  number;
  has_privilege           boolean   := FALSE;
  identifier_type_upper   varchar2(M_IDEN);
  group_name_formatted    varchar2(M_IDEN);
begin

  chk_null_group_operation(group_name,
                           group_name_formatted,
                           identifier_type,
                           identifier_type_upper,
                           identifier_name);

  sanitize_and_get_internal_rep(
       identifier_name,
       identifier_type_upper,
       identifier_type_int,
       obj#, 
       obj_owner,
       identifier_components);

  /* get user information */
  current_user := SYS_CONTEXT('USERENV', 'CURRENT_USER');
  select user_id into current_user_id
     from sys.all_users
     where username = current_user; 

  /* privilege check */    
  opcode := OPCODE_SET; 
  has_privilege := check_annotation_privilege(identifier_type_int,
                                              identifier_components,
                                              opcode,
                                              obj#,
                                              obj_owner,
                                              current_user_id,
                                              current_user);

  if(has_privilege) then
    prvt_annotations_internal.delete_from_group(group_name_formatted,
                                                obj#,
                                                obj_owner,
                                                identifier_type_int,
                                                identifier_components);
  else
    raise_application_error(-20000, 'Insufficient privileges');   
  end if;

end;

function get_version 
  return varchar2
is
begin
  return VERSION;
end get_version;

/* Initialization */
begin
 init_identifier_token_len;

end metadata_annotations;
