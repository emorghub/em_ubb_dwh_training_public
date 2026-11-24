--------------------------------------------------------
--  DDL for Package Body PRVT_ANNOTATIONS_INTERNAL
--------------------------------------------------------

  CREATE OR REPLACE EDITIONABLE PACKAGE BODY "UBB_CORE2"."PRVT_ANNOTATIONS_INTERNAL" 
as

  FUNCTION get_group_id(p_group_name IN VARCHAR2)
    RETURN NUMBER
  IS
    v_group_id NUMBER;
  BEGIN

    SELECT group_id
      INTO v_group_id
      FROM annotations_groups$
    WHERE group_name = p_group_name;

    RETURN v_group_id;
    
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      
      RAISE_APPLICATION_ERROR(-20000, 'Group Name not found.');
    WHEN OTHERS THEN
        RAISE;
  END get_group_id;

/* 
 * 
 * 1. Translate_annotation_type: Translate user specified annotation type to a package defined
 *    constant 
 * 2. Dictionary_update: Insert entry to annotations catalog table
 * 
 * Notes:
 *        Provenance tracking:
 *
 *        Provenance includes 
 *           1. Tracking user who created the annotation. 
 *           2. Time of annotation
 *
 *        Annotation owner is the current user who invoked the 
 *        annotation package, so that tracks one part of the provenance
 *
 *       Concurrency control:
 *           The burden of preventing the object of hte entity being
 *           annotated from being dropped belongs to the invoker of the  
 *           package. This is because, there is nothing prventing the 
 *           drop of the object from the time of invocation to the 
 *           execution of the first statement in the PL/SQL package
 */ 
procedure set(
          v_annotation_owner      in number,
          v_annotation_name       in varchar2,
          v_annotation_value      in varchar2,
          v_annotation_type_int   in number,
          v_obj#                  in number,
          obj#_owner              in number,
          v_identifier_components in
          metadata_annotations.identifier_components_t)
as
      l_column_name     varchar2(128) := NULL;
      l_procedure_name  varchar2(128) := NULL;
      l_function_name   varchar2(128) := NULL;
      l_obj#            number        := NULL;
      l_obj_owner       number        := NULL;
      l_group_id        number        := NULL;
begin

   -- Handle database-level (no identifier components / null obj#)
   IF (v_identifier_components IS NULL OR v_identifier_components.COUNT = 0) THEN
      -- Only allow this when type is database-level
      IF v_annotation_type_int != IDENTIFIER_DATABASE THEN
         raise_application_error(
           -20002,
           'Only database-level annotations can have NULL identifier components'
         );
      END IF;

      l_obj#      := v_obj#;          --  ( will be -1 for IDENTIFIER_DATABASE)
      l_obj_owner := obj#_owner;      --  ( will be -1 for IDENTIFIER_DATABASE)

   ELSE
      -- Extract from identifier components
      IF v_identifier_components.EXISTS('COLUMN_NAME') THEN
          l_column_name := v_identifier_components('COLUMN_NAME');
      END IF;

      IF v_identifier_components.EXISTS('PROCEDURE_NAME') THEN
          l_procedure_name := v_identifier_components('PROCEDURE_NAME');
      END IF;

      IF v_identifier_components.EXISTS('FUNCTION_NAME') THEN
          l_function_name := v_identifier_components('FUNCTION_NAME');
      END IF;

      IF v_identifier_components.EXISTS('GROUP_NAME') THEN
          l_group_id := get_group_id(v_identifier_components('GROUP_NAME'));
      END IF;

      l_obj#      := v_obj#;
      l_obj_owner := obj#_owner;
   END IF;

   /* Dictionary update with DDL-like semantics */
   COMMIT;

   INSERT INTO annotations_usage$
           (annotation_owner,
            annotation_name,
            annotation_value,
            annotation_type,
            creation_time,
            obj#,
            object_owner,
            column_name,
            procedure_name,
            function_name,
            group_id)
   VALUES (v_annotation_owner,
           v_annotation_name,
           v_annotation_value,
           v_annotation_type_int,
           SYSTIMESTAMP,
           l_obj#,
           l_obj_owner,
           l_column_name,
           l_procedure_name,
           l_function_name,
           l_group_id);

   COMMIT;

exception
   WHEN DUP_VAL_ON_INDEX THEN
       raise_application_error(-20000,
         'Annotation already exists. Use edit procedure to replace value');
   WHEN others THEN
       raise;
end;

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
as 
  v_rows_updated number;
  l_group_id number;
begin
   commit;   
      
      CASE 
        /* 
         * Identifier_type represents an object
         */ 
        when v_annotation_type_int in ( IDENTIFIER_TABLE,
                                        IDENTIFIER_TABLE_PARTITION, 
                                        IDENTIFIER_TABLE_SUBPARTITION,
                                        IDENTIFIER_VIEW,
                                        IDENTIFIER_PACKAGE, 
                                        IDENTIFIER_PROCEDURE,
                                        IDENTIFIER_FUNCTION,
                                        IDENTIFIER_MTRLZD_VIEW) 
        then

        /* There are 2 possibilities. 
         *  1. The user wants to replace a specific key,value pair
         *  2. The user wants to replace all values with a specific 
         *     key. This is the case when v_annotation_old_Value is NULL
         */   

         /* 
          * Case 1: User wants to replace a specific annotation value 
          *         The old annotation value could be NULL which is 
          *         is indicated by v_annotation_old_value = NO_VALUE
          */

            if (v_annotation_old_value is not null) then
              update annotations_usage$   
                 set annotation_value = v_annotation_value
               where annotation_type = v_annotation_type_int
                 and obj# = v_obj#
                 and object_owner = obj_owner
                 and annotation_owner = v_annotation_owner
                 and annotation_name = v_annotation_name
                 and ( (v_annotation_old_value = NO_VALUE and
                      annotation_value is null)
                     or 
                     annotation_value = v_annotation_old_value); 

               v_rows_updated := SQL%ROWCOUNT;
            end if;

        /*
         * Case 2: User wants to replace all values for a key
         *         with just one value  
         */
          if (v_annotation_old_value is null) then
            delete from annotations_usage$
             where annotation_type = v_annotation_type_int
                 and obj# = v_obj#
                 and object_owner = obj_owner
                 and annotation_owner = v_annotation_owner
                 and annotation_name = v_annotation_name; 

            v_rows_updated := SQL%ROWCOUNT;

            if (v_rows_updated > 0) then
               prvt_annotations_internal.set(v_annotation_owner,
                                             v_annotation_name,
                                             v_annotation_value,
                                             v_annotation_type_int,
                                             v_obj#,
                                             obj_owner,
                                             v_identifier_components
                                             );
            end if;

          end if;
           
   
       /* 
        * The next few identifier types have a parent object
        */
         
        when v_annotation_type_int in (IDENTIFIER_TABLE_COLUMN, 
                                       IDENTIFIER_VIEW_COLUMN, 
                                       IDENTIFIER_MTRLZD_VIEW_COLUMN) 
        then 

         /* 
          * Case 1: User wants to replace a specific annotation value 
          *         The old annotation value could be NULL which is 
          *         is indicated by v_annotation_old_value = NO_VALUE
          */

          if (v_annotation_old_value is not null) then
            update annotations_usage$   
            set annotation_value = v_annotation_value
             where annotation_type = v_annotation_type_int
               and obj# = v_obj#
               and object_owner = obj_owner
               and annotation_owner = v_annotation_owner
               and annotation_name = v_annotation_name
               and column_name = v_identifier_components('COLUMN_NAME')
               and ( (v_annotation_old_value = NO_VALUE and
                      annotation_value is null)
                     or 
                     annotation_value = v_annotation_old_value);
            v_rows_updated := SQL%ROWCOUNT;   
          end if;


         /* Case 2: User wants to replace all values for a key
          *         with just one value  
          */
          if (v_annotation_old_value is null) then
            delete from annotations_usage$
             where annotation_type = v_annotation_type_int
                 and obj# = v_obj#
                 and object_owner = obj_owner
                 and annotation_owner = v_annotation_owner
                 and annotation_name = v_annotation_name 
                 and column_name = v_identifier_components('COLUMN_NAME');

            v_rows_updated := SQL%ROWCOUNT;

            if (v_rows_updated > 0) then
               prvt_annotations_internal.set(v_annotation_owner,
                                             v_annotation_name,
                                             v_annotation_value,
                                             v_annotation_type_int,
                                             v_obj#,
                                             obj_owner,
                                             v_identifier_components
                                             );
            end if;
 
         end if;

        when v_annotation_type_int in (IDENTIFIER_PACKAGE_FUNCTION)
        then

         /* Case 1: User wants to replace a specific annotation value 
          *         The old annotation value could be NULL which is 
          *         is indicated by v_annotation_old_value = NO_VALUE
          */
          if (v_annotation_old_value is not null) then 
            update annotations_usage$   
            set annotation_value = v_annotation_value
             where annotation_type = v_annotation_type_int
               and obj# = v_obj#
               and object_owner = obj_owner
               and annotation_owner = v_annotation_owner
               and annotation_name = v_annotation_name
               and function_name = v_identifier_components('FUNCTION_NAME')
               and ( (v_annotation_old_value = NO_VALUE and
                      annotation_value is null)
                     or 
                     annotation_value = v_annotation_old_value);
             v_rows_updated := SQL%ROWCOUNT;
          end if;
 /*
         * Case 2: User wants to replace all values for a key
         *         with just one value  
         */
          if (v_annotation_old_value is null) then
            delete from annotations_usage$
             where annotation_type = v_annotation_type_int
                 and obj# = v_obj#
                 and object_owner = obj_owner
                 and annotation_owner = v_annotation_owner
                 and annotation_name = v_annotation_name
                 and function_name = v_identifier_components('FUNCTION_NAME');

            v_rows_updated := SQL%ROWCOUNT;

            if (v_rows_updated > 0) then
               prvt_annotations_internal.set(v_annotation_owner,
                                             v_annotation_name,
                                             v_annotation_value,
                                             v_annotation_type_int,
                                             v_obj#,
                                             obj_owner,
                                             v_identifier_components
                                             );
            end if;

          end if;
         
        when v_annotation_type_int in (IDENTIFIER_PACKAGE_PROCEDURE)
        then

         /* 
          * Case 1: User wants to replace a specific annotation value 
          *         The old annotation value could be NULL which is 
          *         is indicated by v_annotation_old_value = NO_VALUE
          */

          if (v_annotation_old_value is not null) then

            update annotations_usage$   
            set annotation_value = v_annotation_value
             where annotation_type = v_annotation_type_int
               and obj# = v_obj#
               and object_owner = obj_owner
               and annotation_owner = v_annotation_owner
               and annotation_name = v_annotation_name
               and procedure_name = v_identifier_components('PROCEDURE_NAME')
                and ( (v_annotation_old_value = NO_VALUE and
                      annotation_value is null)
                     or 
                     annotation_value = v_annotation_old_value);

            v_rows_updated := SQL%ROWCOUNT;
          end if;

        /*
         * Case 2: User wants to replace all values for a key
         *         with just one value  
         */
          if (v_annotation_old_value is null) then
            delete from annotations_usage$
             where annotation_type = v_annotation_type_int
                 and obj# = v_obj#
                 and object_owner = obj_owner
                 and annotation_owner = v_annotation_owner
                 and annotation_name = v_annotation_name
                 and procedure_name = v_identifier_components('PROCEDURE_NAME');

             v_rows_updated := SQL%ROWCOUNT;

            if (v_rows_updated > 0) then
               prvt_annotations_internal.set(v_annotation_owner,
                                             v_annotation_name,
                                             v_annotation_value,
                                             v_annotation_type_int,
                                             v_obj#,
                                             obj_owner,
                                             v_identifier_components
                                             );
            end if;

          end if;
         /* The next few identifier types do not have a parent object */


        when v_annotation_type_int in (IDENTIFIER_SCHEMA)
        then

         /* 
          * Case 1: User wants to replace a specific annotation value 
          *         The old annotation value could be NULL which is 
          *         is indicated by v_annotation_old_value = NO_VALUE
          */

          if (v_annotation_old_value is not null) then

            update annotations_usage$   
             set annotation_value = v_annotation_value 
              where annotation_type = v_annotation_type_int
               and annotation_owner = v_annotation_owner
               and annotation_name = v_annotation_name
               and obj# = -1
               and object_owner = obj_owner
               and ( (v_annotation_old_value = NO_VALUE and
                      annotation_value is null)
                     or 
                     annotation_value = v_annotation_old_value); 
            v_rows_updated := SQL%ROWCOUNT;
         end if;


        /*
         * Case 2: User wants to replace all values for a key
         *         with just one value  
         */
          if (v_annotation_old_value is null) then
            delete from annotations_usage$
             where annotation_type = v_annotation_type_int
                 and annotation_owner = v_annotation_owner
                 and annotation_name = v_annotation_name
                 and obj# = -1
                 and object_owner = obj_owner;
             v_rows_updated := SQL%ROWCOUNT;

            if (v_rows_updated > 0) then
               prvt_annotations_internal.set(v_annotation_owner,
                                             v_annotation_name,
                                             v_annotation_value,
                                             v_annotation_type_int,
                                             v_obj#,
                                             obj_owner,
                                             v_identifier_components
                                             );
            end if;

          end if;

        when v_annotation_type_int in (IDENTIFIER_DATABASE)
        then
         /* 
          * Case 1: User wants to replace a specific annotation value 
          *         The old annotation value could be NULL which is 
          *         is indicated by v_annotation_old_value = NO_VALUE
          */

            if (v_annotation_old_value is not null) then
              update annotations_usage$   
               set annotation_value = v_annotation_value
              where annotation_type = v_annotation_type_int
               and annotation_owner = v_annotation_owner
               and annotation_name = v_annotation_name
               and obj# = -1
               and object_owner = -1
               and ( (v_annotation_old_value = NO_VALUE and
                      annotation_value is null)
                     or 
                     annotation_value = v_annotation_old_value); 

             v_rows_updated := SQL%ROWCOUNT;
           end if;

        /*
         * Case 2: User wants to replace all values for a key
         *         with just one value  
         */
          if (v_annotation_old_value is null) then
            delete from annotations_usage$
             where annotation_type = v_annotation_type_int
                 and annotation_owner = v_annotation_owner
                 and annotation_name = v_annotation_name
                 and obj# = -1
                and object_owner = -1;

            v_rows_updated := SQL%ROWCOUNT;

            if (v_rows_updated > 0) then
               prvt_annotations_internal.set(v_annotation_owner,
                                             v_annotation_name,
                                             v_annotation_value,
                                             v_annotation_type_int,
                                             v_obj#,
                                             obj_owner,
                                             v_identifier_components
                                             );
            end if;

          end if;
           
        when v_annotation_type_int in (IDENTIFIER_GROUP) 
        then
          
            l_group_id := get_group_id(v_identifier_components('GROUP_NAME'));
         /* 
          * Case 1: User wants to replace a specific annotation value 
          *         The old annotation value could be NULL which is 
          *         is indicated by v_annotation_old_value = NO_VALUE
          */

            if (v_annotation_old_value is not null) then

            update annotations_usage$   
            set annotation_value = v_annotation_value
             where annotation_type = v_annotation_type_int
               and annotation_owner = v_annotation_owner
               and annotation_name = v_annotation_name
               and obj# = -1
               and object_owner = -1
               and group_id = l_group_id
               and ( (v_annotation_old_value = NO_VALUE and
                      annotation_value is null)
                     or 
                     annotation_value = v_annotation_old_value); 
            v_rows_updated := SQL%ROWCOUNT;
           end if;

        /*
         * Case 2: User wants to replace all values for a key
         *         with just one value  
         */
          if (v_annotation_old_value is null) then
            delete from annotations_usage$
             where annotation_type = v_annotation_type_int
                 and annotation_owner = v_annotation_owner
                 and annotation_name = v_annotation_name 
                 and obj# = -1
                 and object_owner = -1
                 and group_id = l_group_id;
            v_rows_updated := SQL%ROWCOUNT;

            if (v_rows_updated > 0) then
               prvt_annotations_internal.set(v_annotation_owner,
                                             v_annotation_name,
                                             v_annotation_value,
                                             v_annotation_type_int,
                                             v_obj#,
                                             obj_owner,
                                             v_identifier_components
                                             );
            end if;

          end if;

      else

        raise_application_error(-20000, 'invalid identifier type');   

      END CASE;


   commit;

   if(v_rows_updated = 0) then
      raise_application_error(-20000, 'Annotation does not exist. Use set ' 
            || 'procedure to add annotation') ;
   end if;
end;

/* internal implementation of get annotation */
function get(
          v_annotation_owner      in number,
          v_annotation_name       in varchar2,
          v_annotation_type_int   in number,
          v_obj#                  in number,
          v_obj#_owner            in number,
          v_identifier_components in
          metadata_annotations.identifier_components_t)
return clob
as 
v_annotations_clob  clob  := NULL;
l_group_id number := NULL;
begin

  begin

    case  
      /* 
       * Identifier_type represents an object
       */ 
      when v_annotation_type_int in ( IDENTIFIER_TABLE,
                                      IDENTIFIER_TABLE_PARTITION, 
                                      IDENTIFIER_TABLE_SUBPARTITION,
                                      IDENTIFIER_VIEW,
                                      IDENTIFIER_PACKAGE, 
                                      IDENTIFIER_PROCEDURE,
                                      IDENTIFIER_FUNCTION,
                                      IDENTIFIER_MTRLZD_VIEW) 
      then
        select to_clob(annotation_value) into v_annotations_clob
        from annotations_usage$ 
         where annotation_type = v_annotation_type_int
           and obj# = v_obj#
           and object_owner = v_obj#_owner
           and annotation_owner = v_annotation_owner
           and annotation_name = v_annotation_name;
     
     /* 
      * The next few identifier types have a parent object
      */
      when v_annotation_type_int in (IDENTIFIER_TABLE_COLUMN, 
                                     IDENTIFIER_VIEW_COLUMN, 
                                     IDENTIFIER_MTRLZD_VIEW_COLUMN) 
      then 
        select to_clob(annotation_value) into v_annotations_clob
        from annotations_usage$ 
         where annotation_type = v_annotation_type_int
           and obj# = v_obj#
           and object_owner = v_obj#_owner
           and annotation_owner = v_annotation_owner
           and annotation_name = v_annotation_name
           and column_name = v_identifier_components('COLUMN_NAME');
      
      when v_annotation_type_int in (IDENTIFIER_PACKAGE_FUNCTION)
      then
        select to_clob(annotation_value) into v_annotations_clob
        from annotations_usage$ 
         where annotation_type = v_annotation_type_int
           and obj# = v_obj#
           and object_owner = v_obj#_owner
           and annotation_owner = v_annotation_owner
           and annotation_name = v_annotation_name
           and function_name = v_identifier_components('FUNCTION_NAME');
      
      when v_annotation_type_int in (IDENTIFIER_PACKAGE_PROCEDURE)
      then
        select to_clob(annotation_value) into v_annotations_clob
        from annotations_usage$ 
         where annotation_type = v_annotation_type_int
           and obj# = v_obj#
           and object_owner = v_obj#_owner
           and annotation_owner = v_annotation_owner
           and annotation_name = v_annotation_name
           and procedure_name = v_identifier_components('PROCEDURE_NAME');
      
      when v_annotation_type_int in (IDENTIFIER_SCHEMA)
      then
        select to_clob(annotation_value) into v_annotations_clob
        from annotations_usage$ 
         where annotation_type = v_annotation_type_int
           and obj# = -1
           and object_owner = v_obj#_owner
           and annotation_owner = v_annotation_owner
           and annotation_name = v_annotation_name;
      
      when v_annotation_type_int in (IDENTIFIER_DATABASE)
      then
        select to_clob(annotation_value) into v_annotations_clob
        from annotations_usage$ 
         where annotation_type = v_annotation_type_int
           and obj# = -1
           and object_owner = -1
           and annotation_owner = v_annotation_owner
           and annotation_name = v_annotation_name;
      
      when v_annotation_type_int in (IDENTIFIER_GROUP) 
      then

        l_group_id := get_group_id(v_identifier_components('GROUP_NAME'));

        select to_clob(annotation_value) into v_annotations_clob
        from annotations_usage$ 
         where annotation_type = v_annotation_type_int
           and obj# = -1
           and object_owner = -1
           and annotation_owner = v_annotation_owner
           and annotation_name = v_annotation_name
           and group_id = l_group_id;
           
      else
        raise_application_error(-20000, 'invalid identifier type');   
    end case;

  exception
    when NO_DATA_FOUND then
      raise_application_error(-20001, 'Annotation name not found');
    when others then 
      raise;
  end;
 
  return v_annotations_clob;
    
end;

function get_json(
  v_annotation_owner      in number,
  v_annotation_name       in varchar2,
  v_annotation_type_int   in number,
  v_obj#                  in number,
  v_obj#_owner            in number,
  v_identifier_components in metadata_annotations.identifier_components_t
)
$IF DBMS_DB_VERSION.VERSION >= 21 $THEN
  return json
$ELSE
  return clob
$END
as
  $IF DBMS_DB_VERSION.VERSION >= 21 $THEN
    v_annotations_json json;
  $ELSE
    v_annotations_json clob;
  $END
  l_group_id         number := NULL;
begin
  case
    /* Object-scoped types */
    when v_annotation_type_int in (
         IDENTIFIER_TABLE,
         IDENTIFIER_TABLE_PARTITION,
         IDENTIFIER_TABLE_SUBPARTITION,
         IDENTIFIER_VIEW,
         IDENTIFIER_PACKAGE,
         IDENTIFIER_PROCEDURE,
         IDENTIFIER_FUNCTION,
         IDENTIFIER_MTRLZD_VIEW )
    then
      select JSON_ARRAYAGG(annotation_value ORDER BY creation_time, annotation_value
        $IF DBMS_DB_VERSION.VERSION >= 21 $THEN
          RETURNING JSON
        $ELSE
          RETURNING CLOB
        $END)
        into v_annotations_json
        from annotations_usage$
       where annotation_type   = v_annotation_type_int
         and obj#             = v_obj#
         and object_owner     = v_obj#_owner
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name;

    /* Child identifiers with parent object */
    when v_annotation_type_int in (
         IDENTIFIER_TABLE_COLUMN,
         IDENTIFIER_VIEW_COLUMN,
         IDENTIFIER_MTRLZD_VIEW_COLUMN )
    then
      select JSON_ARRAYAGG(annotation_value ORDER BY creation_time, annotation_value
        $IF DBMS_DB_VERSION.VERSION >= 21 $THEN
          RETURNING JSON
        $ELSE
          RETURNING CLOB
        $END)
        into v_annotations_json
        from annotations_usage$
       where annotation_type   = v_annotation_type_int
         and obj#             = v_obj#
         and object_owner     = v_obj#_owner
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name
         and column_name      = v_identifier_components('COLUMN_NAME');

    when v_annotation_type_int = IDENTIFIER_PACKAGE_FUNCTION
    then
      select JSON_ARRAYAGG(annotation_value ORDER BY creation_time, annotation_value
        $IF DBMS_DB_VERSION.VERSION >= 21 $THEN
          RETURNING JSON
        $ELSE
          RETURNING CLOB
        $END)
        into v_annotations_json
        from annotations_usage$
       where annotation_type   = v_annotation_type_int
         and obj#             = v_obj#
         and object_owner     = v_obj#_owner
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name
         and function_name    = v_identifier_components('FUNCTION_NAME');

    when v_annotation_type_int = IDENTIFIER_PACKAGE_PROCEDURE
    then
      select JSON_ARRAYAGG(annotation_value ORDER BY creation_time, annotation_value
        $IF DBMS_DB_VERSION.VERSION >= 21 $THEN
          RETURNING JSON
        $ELSE
          RETURNING CLOB
        $END)
        into v_annotations_json
        from annotations_usage$
       where annotation_type   = v_annotation_type_int
         and obj#             = v_obj#
         and object_owner     = v_obj#_owner
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name
         and procedure_name   = v_identifier_components('PROCEDURE_NAME');

    /* Types without a concrete object */
    when v_annotation_type_int = IDENTIFIER_SCHEMA
    then
      select JSON_ARRAYAGG(annotation_value ORDER BY creation_time, annotation_value
        $IF DBMS_DB_VERSION.VERSION >= 21 $THEN
          RETURNING JSON
        $ELSE
          RETURNING CLOB
        $END)
        into v_annotations_json
        from annotations_usage$
       where annotation_type   = v_annotation_type_int
         and obj#             = -1
         and object_owner     = v_obj#_owner
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name;

    when v_annotation_type_int = IDENTIFIER_DATABASE
    then
      select JSON_ARRAYAGG(annotation_value ORDER BY creation_time, annotation_value
        $IF DBMS_DB_VERSION.VERSION >= 21 $THEN
          RETURNING JSON
        $ELSE
          RETURNING CLOB
        $END)
        into v_annotations_json
        from annotations_usage$
       where annotation_type   = v_annotation_type_int
         and obj#             = -1
         and object_owner     = -1
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name;

    when v_annotation_type_int = IDENTIFIER_GROUP
    then
      l_group_id := get_group_id(v_identifier_components('GROUP_NAME'));

      select JSON_ARRAYAGG(annotation_value ORDER BY creation_time, annotation_value
        $IF DBMS_DB_VERSION.VERSION >= 21 $THEN
          RETURNING JSON
        $ELSE
          RETURNING CLOB
        $END)
        into v_annotations_json
        from annotations_usage$
       where annotation_type   = v_annotation_type_int
         and obj#             = -1
         and object_owner     = -1
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name
         and group_id         = l_group_id;

    else
      raise_application_error(-20000, 'invalid identifier type');
  end case;

  -- Preserve error semantics consistent with existing GET (raise on no data)
  if v_annotations_json is null then
    raise_application_error(-20001, 'Annotation name not found');
  end if;

  return v_annotations_json;
end get_json;

procedure delete(
          v_annotation_owner      in number,
          v_annotation_name       in varchar2,
          v_annotation_value      in varchar2,
          v_annotation_type_int   In number,
          v_obj#                  in number,
          obj_owner               in number,
          v_identifier_components in
          metadata_annotations.identifier_components_t)

as 
   v_rows_deleted number;
   l_group_id       number;
begin

  commit;
     /* Use different queries for various identifier types. The code would be more 
      * compact if we constructed there clause for different identifier types
      * and issued a dynamic SQL after constructing the delete statement. However,
      * this longer version is more readable, even if verbose.
      */
     CASE
        /* 
         * Identifier_type represents an object
         */ 
        when v_annotation_type_int in ( IDENTIFIER_TABLE,
                                        IDENTIFIER_TABLE_PARTITION, 
                                        IDENTIFIER_TABLE_SUBPARTITION,
                                        IDENTIFIER_VIEW,
                                        IDENTIFIER_PACKAGE, 
                                        IDENTIFIER_PROCEDURE,
                                        IDENTIFIER_FUNCTION,
                                        IDENTIFIER_MTRLZD_VIEW) 
        then

       /*
        *  We allow multiple values per key now. This presents the following 
        *  possibilities
        *  1. Delete all annotations for a key  
        *  2. Delete a specific key,value pair
        *  3. Delete annotation with a null value. Note that there may be other 
        *     values associated with this  
        */

              delete annotations_usage$  
               where annotation_type = v_annotation_type_int
                 and obj# = v_obj#
                 and object_owner = obj_owner
                 and annotation_owner = v_annotation_owner
                 and annotation_name = v_annotation_name
                 and (v_annotation_value is null 
                      or annotation_value = v_annotation_value
                      or (v_annotation_value = NO_VALUE 
                          and annotation_value is null)) ;

        /* 
        * The next few identifier types have a parent object
        */
         
        when v_annotation_type_int in (IDENTIFIER_TABLE_COLUMN, 
                                       IDENTIFIER_VIEW_COLUMN, 
                                       IDENTIFIER_MTRLZD_VIEW_COLUMN) 
        then 

            delete annotations_usage$  
             where annotation_type = v_annotation_type_int
               and obj# = v_obj#
               and object_owner = obj_owner
               and annotation_owner = v_annotation_owner
               and annotation_name = v_annotation_name
               and column_name = v_identifier_components('COLUMN_NAME')
               and (v_annotation_value is null 
                      or annotation_value = v_annotation_value
                      or (v_annotation_value = NO_VALUE 
                          and annotation_value is null)) ;
 
        when v_annotation_type_int in (IDENTIFIER_PACKAGE_FUNCTION)
        then

            delete annotations_usage$  
             where annotation_type = v_annotation_type_int
               and obj# = v_obj#
               and object_owner = obj_owner
               and annotation_owner = v_annotation_owner
               and annotation_name = v_annotation_name
               and function_name = v_identifier_components('FUNCTION_NAME')
               and (v_annotation_value is null 
                      or annotation_value = v_annotation_value
                      or (v_annotation_value = NO_VALUE 
                          and annotation_value is null));

        when v_annotation_type_int in (IDENTIFIER_PACKAGE_PROCEDURE)
        then

            delete annotations_usage$  
             where annotation_type = v_annotation_type_int
               and obj# = v_obj#
               and object_owner = obj_owner
               and annotation_owner = v_annotation_owner
               and annotation_name = v_annotation_name
               and procedure_name = v_identifier_components('PROCEDURE_NAME')
               and (v_annotation_value is null 
                      or annotation_value = v_annotation_value
                      or (v_annotation_value = NO_VALUE 
                          and annotation_value is null));

         /* The next few identifier types do not have a parent object */


        when v_annotation_type_int in (IDENTIFIER_SCHEMA)
        then

           delete annotations_usage$  
             where annotation_type = v_annotation_type_int
               and annotation_owner = v_annotation_owner
               and annotation_name = v_annotation_name
               and obj# = -1
               and object_owner = obj_owner
               and (v_annotation_value is null 
                      or annotation_value = v_annotation_value
                      or (v_annotation_value = NO_VALUE 
                          and annotation_value is null));

        when v_annotation_type_int in (IDENTIFIER_DATABASE)
        then

            delete annotations_usage$  
             where annotation_type = v_annotation_type_int
               and annotation_owner = v_annotation_owner
               and annotation_name = v_annotation_name
               and obj# = -1
               and object_owner = -1
               and (v_annotation_value is null 
                      or annotation_value = v_annotation_value
                      or (v_annotation_value = NO_VALUE 
                          and annotation_value is null));
   
        when v_annotation_type_int in (IDENTIFIER_GROUP) 
        then

            l_group_id := get_group_id(v_identifier_components('GROUP_NAME'));

            delete annotations_usage$  
             where annotation_type = v_annotation_type_int
               and annotation_owner = v_annotation_owner
               and annotation_name = v_annotation_name
               and obj# = -1
               and object_owner = -1
               and group_id = l_group_id
               and (v_annotation_value is null 
                      or annotation_value = v_annotation_value
                      or (v_annotation_value = NO_VALUE 
                          and annotation_value is null));

      else

        raise_application_error(-20000, 'invalid identifier type');   

      END CASE;

   v_rows_deleted := SQL%ROWCOUNT;

   commit;

   if(v_rows_deleted = 0) then
      raise_application_error(-20000, 'Annotation does not exist.' 
            || ' Nothing to delete') ;
   end if;

end;


procedure create_group(v_group_name in VARCHAR2)
as 
  v_group_id NUMBER;
begin

  SELECT group_id_seq.NEXTVAL INTO v_group_id FROM SYS.DUAL;

  commit;

  INSERT INTO annotations_groups$ (group_id, group_name, creation_time)
  VALUES (v_group_id, v_group_name, SYSTIMESTAMP);

  commit;

  EXCEPTION
    WHEN DUP_VAL_ON_INDEX THEN
      RAISE_APPLICATION_ERROR(-20000, 'Group Name already exists.');

end;

procedure drop_group(v_group_name in VARCHAR2)
as 
begin

  commit;

  DELETE FROM annotations_groups$ WHERE group_name = v_group_name;

  IF SQL%ROWCOUNT = 0 THEN
    RAISE_APPLICATION_ERROR(-20000, 'Group Name not found.');
  END IF;

  commit;

end;

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
as
  v_rows_deleted number;
  l_group_id     number;
begin
  commit;

  case
    /* Object-scoped types */
    when v_annotation_type_int in (
         IDENTIFIER_TABLE,
         IDENTIFIER_TABLE_PARTITION,
         IDENTIFIER_TABLE_SUBPARTITION,
         IDENTIFIER_VIEW,
         IDENTIFIER_PACKAGE,
         IDENTIFIER_PROCEDURE,
         IDENTIFIER_FUNCTION,
         IDENTIFIER_MTRLZD_VIEW )
    then
      delete annotations_usage$
       where annotation_type   = v_annotation_type_int
         and obj#             = v_obj#
         and object_owner     = obj_owner
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name
         and annotation_value is not null
         and REGEXP_LIKE(annotation_value,
                         v_value_pattern,
                         v_match_parameter);

    /* Child identifiers with parent object */
    when v_annotation_type_int in (
         IDENTIFIER_TABLE_COLUMN,
         IDENTIFIER_VIEW_COLUMN,
         IDENTIFIER_MTRLZD_VIEW_COLUMN )
    then
      delete annotations_usage$
       where annotation_type   = v_annotation_type_int
         and obj#             = v_obj#
         and object_owner     = obj_owner
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name
         and column_name      = v_identifier_components('COLUMN_NAME')
         and annotation_value is not null
         and REGEXP_LIKE(annotation_value,
                         v_value_pattern,
                         v_match_parameter);

    when v_annotation_type_int = IDENTIFIER_PACKAGE_FUNCTION
    then
      delete annotations_usage$
       where annotation_type   = v_annotation_type_int
         and obj#             = v_obj#
         and object_owner     = obj_owner
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name
         and function_name    = v_identifier_components('FUNCTION_NAME')
         and annotation_value is not null
         and REGEXP_LIKE(annotation_value,
                         v_value_pattern,
                         v_match_parameter);

    when v_annotation_type_int = IDENTIFIER_PACKAGE_PROCEDURE
    then
      delete annotations_usage$
       where annotation_type   = v_annotation_type_int
         and obj#             = v_obj#
         and object_owner     = obj_owner
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name
         and procedure_name   = v_identifier_components('PROCEDURE_NAME')
         and annotation_value is not null
         and REGEXP_LIKE(annotation_value,
                         v_value_pattern,
                         v_match_parameter);

    /* Types without a concrete object */
    when v_annotation_type_int = IDENTIFIER_SCHEMA
    then
      delete annotations_usage$
       where annotation_type   = v_annotation_type_int
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name
         and obj#             = -1
         and object_owner     = obj_owner
         and annotation_value is not null
         and REGEXP_LIKE(annotation_value,
                         v_value_pattern,
                         v_match_parameter);

    when v_annotation_type_int = IDENTIFIER_DATABASE
    then
      delete annotations_usage$
       where annotation_type   = v_annotation_type_int
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name
         and obj#             = -1
         and object_owner     = -1
         and annotation_value is not null
         and REGEXP_LIKE(annotation_value,
                         v_value_pattern,
                         v_match_parameter);

    when v_annotation_type_int = IDENTIFIER_GROUP
    then
      l_group_id := get_group_id(
                      v_identifier_components('GROUP_NAME'));
      delete annotations_usage$
       where annotation_type   = v_annotation_type_int
         and annotation_owner = v_annotation_owner
         and annotation_name  = v_annotation_name
         and obj#             = -1
         and object_owner     = -1
         and group_id         = l_group_id
         and annotation_value is not null
         and REGEXP_LIKE(annotation_value,
                         v_value_pattern,
                         v_match_parameter);

    else
      raise_application_error(-20000, 'invalid identifier type');
  end case;

  v_rows_deleted := SQL%ROWCOUNT;

  commit;

  if v_rows_deleted = 0 then
    raise_application_error(
      -20000,
      'Annotation does not exist. Nothing to delete');
  end if;
end delete_by_value_regex;

procedure add_to_group(
      v_group_name            in VARCHAR2,
      v_object_id             in NUMBER,
      v_object_owner          in NUMBER,
      v_annotation_type_int   in number,
      v_identifier_components in 
      metadata_annotations.identifier_components_t)
as 
  l_group_id        NUMBER;
  l_column_name     varchar2(128) := NULL;
  l_procedure_name  varchar2(128) := NULL;
  l_function_name   varchar2(128) := NULL;
begin

  BEGIN

    SELECT group_id into l_group_id 
    from annotations_groups$ 
    where group_name = v_group_name;

  EXCEPTION

    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(-20001, 'Group does not exist.');

  END;

  IF v_identifier_components.EXISTS('COLUMN_NAME') THEN
      l_column_name := v_identifier_components('COLUMN_NAME');
  END IF;

  IF v_identifier_components.EXISTS('PROCEDURE_NAME') THEN
      l_procedure_name := v_identifier_components('PROCEDURE_NAME');
  END IF;

  IF v_identifier_components.EXISTS('FUNCTION_NAME') THEN
      l_function_name := v_identifier_components('FUNCTION_NAME');
  END IF;

  commit;

  INSERT INTO annotations_group_members$ 
        (group_id, obj#, object_owner, annotation_type, 
        column_name, function_name, procedure_name)
  VALUES (l_group_id, v_object_id, v_object_owner, v_annotation_type_int,
          l_column_name, l_function_name, l_procedure_name);

  commit;

exception

  WHEN DUP_VAL_ON_INDEX THEN
    RAISE_APPLICATION_ERROR(-20004, 'Object already added to group.');

  WHEN OTHERS THEN
      IF SQLCODE = -2291 THEN /* Parent Key (Group Id) doesn't exit */
          RAISE_APPLICATION_ERROR(-20001, 'Group does not exist');
      ELSE
          RAISE_APPLICATION_ERROR(-20002, 'Error adding member: ' || SQLERRM);
      END IF;

end;

procedure delete_from_group(
      v_group_name            in VARCHAR2,
      v_object_id             in NUMBER,
      v_object_owner          in NUMBER,
      v_annotation_type_int   in number,
      v_identifier_components in 
      metadata_annotations.identifier_components_t)
as 
  v_group_id NUMBER;
  v_rows_deleted number;
begin

  BEGIN

    SELECT group_id into v_group_id 
    from annotations_groups$ 
    where group_name = v_group_name;

  EXCEPTION

    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(-20001, 'Group does not exist.');

  END;

  commit;

   /* Use different queries for various identifier types. The code would be more 
    * compact if we constructed there clause for different identifier types
    * and issued a dynamic SQL after constructing the delete statement. However,
    * this longer version is more readable, even if verbose.
    */
   CASE
      /* 
       * Identifier_type represents an object
       */ 
      when v_annotation_type_int in ( IDENTIFIER_TABLE,
                                      IDENTIFIER_TABLE_PARTITION, 
                                      IDENTIFIER_TABLE_SUBPARTITION,
                                      IDENTIFIER_VIEW,
                                      IDENTIFIER_PACKAGE, 
                                      IDENTIFIER_PROCEDURE,
                                      IDENTIFIER_FUNCTION,
                                      IDENTIFIER_MTRLZD_VIEW) 
      then
          delete annotations_group_members$  
           where group_id = v_group_id
             and annotation_type = v_annotation_type_int
             and obj# = v_object_id
             and object_owner = v_object_owner;

     /* 
      * The next few identifier types have a parent object
      */
       
      when v_annotation_type_int in (IDENTIFIER_TABLE_COLUMN, 
                                     IDENTIFIER_VIEW_COLUMN, 
                                     IDENTIFIER_MTRLZD_VIEW_COLUMN) 
      then 

          delete annotations_group_members$  
           where group_id = v_group_id
             and annotation_type = v_annotation_type_int
             and obj# = v_object_id
             and object_owner = v_object_owner
             and column_name = v_identifier_components('COLUMN_NAME');

      when v_annotation_type_int in (IDENTIFIER_PACKAGE_FUNCTION)
      then

          delete annotations_group_members$  
           where group_id = v_group_id
             and annotation_type = v_annotation_type_int
             and obj# = v_object_id
             and object_owner = v_object_owner
             and function_name = v_identifier_components('FUNCTION_NAME');

      when v_annotation_type_int in (IDENTIFIER_PACKAGE_PROCEDURE)
      then

          delete annotations_group_members$  
           where group_id = v_group_id
             and annotation_type = v_annotation_type_int
             and obj# = v_object_id
             and object_owner = v_object_owner
             and procedure_name = v_identifier_components('PROCEDURE_NAME');

       /* The next few identifier types do not have a parent object */


      when v_annotation_type_int in (IDENTIFIER_SCHEMA)
      then

     
          delete annotations_group_members$  
           where group_id = v_group_id
             and annotation_type = v_annotation_type_int
             and obj# = -1
             and object_owner = v_object_owner;

      when v_annotation_type_int in (IDENTIFIER_DATABASE)
      then

          delete annotations_group_members$  
           where group_id = v_group_id
             and annotation_type = v_annotation_type_int
             and obj# = -1
             and object_owner = -1;
 

    else

      raise_application_error(-20000, 'invalid identifier type');   

    END CASE;

 v_rows_deleted := SQL%ROWCOUNT;

 commit;

 if(v_rows_deleted = 0) then
    raise_application_error(-20000, 'Object Not found in Group') ;
 end if;

end;

end prvt_annotations_internal;
