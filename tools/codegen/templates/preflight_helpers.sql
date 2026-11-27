-- ===========================================================================
-- Preflight helper block. NOT a script of its own: dev-3-prepare-deployment
-- pastes the part between the two "BEGIN HELPERS" / "END HELPERS" lines,
-- unchanged, into both DEPLOY_<MAPPING_ID>_PREFLIGHT_*.sql scripts, right
-- after the DECLARE of the script and after any variables of its own (for
-- example the business date of preflight 2): PL/SQL needs every variable
-- declared before the first procedure or function, so the script's own
-- variables come BEFORE this block, never after it. The mapping's checks
-- are written after the BEGIN. Nothing here names a mapping, a table or a
-- column: those come from the workbook, never from this file.
--
-- READ ONLY: every helper only reads the data dictionary (ALL_*) or runs the
-- SELECT it is given. No DDL, no DML, no GRANT, no COMMIT.
--
-- Change this file only as a deliberate team change, and then rewrite the
-- preflight scripts of the mappings that are still to be deployed.
-- Helpers (their meaning is in references/deployment-handover.md):
--   report, cnt, str, q, check_none, table_columns, column_type,
--   valid_package, has_grant, object_state
-- ===========================================================================

-- Skeleton of a script around the helpers (the first lines up to DECLARE):
--
--   SET SERVEROUTPUT ON SIZE UNLIMITED
--   SET VERIFY OFF
--   SET DEFINE ON
--   WHENEVER SQLERROR EXIT FAILURE
--   DEFINE p_env = '&1'            -- preflight 2: DEFINE p_business_date = '&1' and p_env = '&2'
--   DECLARE
--       <the script's own variables, if any: they must come before the helpers>
--       <helpers, as below>
--   BEGIN
--       IF g_env NOT IN ('TEST', 'PROD') THEN
--           report('FAIL', 'P', 'the environment parameter is TEST or PROD', 'got ' || NVL(g_env, 'nothing'));
--           RAISE_APPLICATION_ERROR(-20999, 'preflight stopped: the environment parameter must be TEST or PROD');
--       END IF;
--       -- the mapping's checks
--       IF g_failed > 0 THEN
--           RAISE_APPLICATION_ERROR(-20999, g_failed || ' preflight check(s) failed');
--       END IF;
--       DBMS_OUTPUT.PUT_LINE('PREFLIGHT <1 or 2> OK');
--   END;
--   /

-- BEGIN HELPERS
    g_failed PLS_INTEGER := 0;
    g_schema CONSTANT VARCHAR2(128) := SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA');
    g_env    CONSTANT VARCHAR2(30)  := UPPER('&p_env');

    PROCEDURE report(p_level VARCHAR2, p_id VARCHAR2, p_text VARCHAR2, p_detail VARCHAR2 DEFAULT NULL) IS
    BEGIN
        IF p_level = 'FAIL' THEN
            g_failed := g_failed + 1;
        END IF;
        DBMS_OUTPUT.PUT_LINE(RPAD(p_level, 5) || RPAD(p_id, 6) || p_text
            || CASE WHEN p_detail IS NOT NULL THEN ' - ' || p_detail END);
    END report;

    -- Number a query returns; -1 when the query itself fails (a missing object is a FAIL, not a crash).
    FUNCTION cnt(p_sql VARCHAR2) RETURN NUMBER IS
        n NUMBER;
    BEGIN
        EXECUTE IMMEDIATE p_sql INTO n;
        RETURN n;
    EXCEPTION
        WHEN OTHERS THEN
            RETURN -1;
    END cnt;

    -- String a query returns; NULL when the query returns nothing or fails.
    FUNCTION str(p_sql VARCHAR2) RETURN VARCHAR2 IS
        s VARCHAR2(4000);
    BEGIN
        EXECUTE IMMEDIATE p_sql INTO s;
        RETURN s;
    EXCEPTION
        WHEN OTHERS THEN
            RETURN NULL;
    END str;

    -- A string as a quoted literal for the dynamic SQL.
    FUNCTION q(p_value VARCHAR2) RETURN VARCHAR2 IS
    BEGIN
        RETURN '''' || REPLACE(p_value, '''', '''''') || '''';
    END q;

    -- p_sql returns the offending rows: none is a PASS; p_level is FAIL or WARN.
    PROCEDURE check_none(p_id VARCHAR2, p_text VARCHAR2, p_sql VARCHAR2, p_level VARCHAR2 DEFAULT 'FAIL') IS
        n NUMBER := cnt('SELECT COUNT(*) FROM (' || p_sql || ')');
    BEGIN
        IF n = 0 THEN
            report('PASS', p_id, p_text);
        ELSIF n < 0 THEN
            report(p_level, p_id, p_text, 'the check could not run');
        ELSE
            report(p_level, p_id, p_text, n || ' row(s) found');
        END IF;
    END check_none;

    -- The table exists and has every column in the comma list.
    PROCEDURE table_columns(p_id VARCHAR2, p_owner VARCHAR2, p_table VARCHAR2, p_cols VARCHAR2) IS
        v_missing VARCHAR2(4000);
        v_pos     PLS_INTEGER := 1;
        v_next    PLS_INTEGER;
        v_col     VARCHAR2(128);
    BEGIN
        IF cnt('SELECT COUNT(*) FROM ALL_TABLES WHERE OWNER = ' || q(p_owner) || ' AND TABLE_NAME = ' || q(p_table)) <> 1 THEN
            report('FAIL', p_id, p_owner || '.' || p_table || ' exists', 'table not found or not visible to ' || g_schema);
            RETURN;
        END IF;
        LOOP
            v_next := INSTR(p_cols, ',', v_pos);
            v_col  := TRIM(CASE WHEN v_next = 0 THEN SUBSTR(p_cols, v_pos) ELSE SUBSTR(p_cols, v_pos, v_next - v_pos) END);
            IF cnt('SELECT COUNT(*) FROM ALL_TAB_COLUMNS WHERE OWNER = ' || q(p_owner) || ' AND TABLE_NAME = ' || q(p_table)
                   || ' AND COLUMN_NAME = ' || q(v_col)) <> 1 THEN
                v_missing := v_missing || CASE WHEN v_missing IS NOT NULL THEN ', ' END || v_col;
            END IF;
            EXIT WHEN v_next = 0;
            v_pos := v_next + 1;
        END LOOP;
        IF v_missing IS NULL THEN
            report('PASS', p_id, p_owner || '.' || p_table || ' exists with the columns read or written');
        ELSE
            report('FAIL', p_id, p_owner || '.' || p_table || ' has the columns read or written', 'missing: ' || v_missing);
        END IF;
    END table_columns;

    -- One column of a table with its mapped type; a mismatch is added to p_bad (report it once afterwards).
    PROCEDURE column_type(p_bad IN OUT VARCHAR2, p_owner VARCHAR2, p_table VARCHAR2, p_col VARCHAR2,
                          p_type VARCHAR2, p_prec NUMBER, p_scale NUMBER, p_len NUMBER, p_null VARCHAR2) IS
        v_sql VARCHAR2(4000) := 'SELECT COUNT(*) FROM ALL_TAB_COLUMNS WHERE OWNER = ' || q(p_owner)
            || ' AND TABLE_NAME = ' || q(p_table) || ' AND COLUMN_NAME = ' || q(p_col)
            || ' AND DATA_TYPE = ' || q(p_type) || ' AND NULLABLE = ' || q(p_null);
    BEGIN
        IF p_prec IS NOT NULL THEN v_sql := v_sql || ' AND DATA_PRECISION = ' || p_prec; END IF;
        IF p_scale IS NOT NULL THEN v_sql := v_sql || ' AND DATA_SCALE = ' || p_scale; END IF;
        IF p_len IS NOT NULL THEN v_sql := v_sql || ' AND CHAR_LENGTH = ' || p_len; END IF;
        IF cnt(v_sql) <> 1 THEN
            p_bad := p_bad || CASE WHEN p_bad IS NOT NULL THEN ', ' END || p_col;
        END IF;
    END column_type;

    -- Specification and body are VALID, with no compile errors.
    PROCEDURE valid_package(p_id VARCHAR2, p_owner VARCHAR2, p_name VARCHAR2) IS
        v_bad VARCHAR2(4000);
    BEGIN
        IF cnt('SELECT COUNT(*) FROM ALL_OBJECTS WHERE OWNER = ' || q(p_owner) || ' AND OBJECT_NAME = ' || q(p_name)
               || ' AND OBJECT_TYPE = ''PACKAGE'' AND STATUS = ''VALID''') <> 1 THEN
            v_bad := 'specification ' || NVL(str('SELECT STATUS FROM ALL_OBJECTS WHERE OWNER = ' || q(p_owner)
                || ' AND OBJECT_NAME = ' || q(p_name) || ' AND OBJECT_TYPE = ''PACKAGE'''), 'not found');
        END IF;
        IF cnt('SELECT COUNT(*) FROM ALL_OBJECTS WHERE OWNER = ' || q(p_owner) || ' AND OBJECT_NAME = ' || q(p_name)
               || ' AND OBJECT_TYPE = ''PACKAGE BODY'' AND STATUS = ''VALID''') <> 1 THEN
            v_bad := v_bad || CASE WHEN v_bad IS NOT NULL THEN '; ' END || 'body ' || NVL(str('SELECT STATUS FROM ALL_OBJECTS WHERE OWNER = '
                || q(p_owner) || ' AND OBJECT_NAME = ' || q(p_name) || ' AND OBJECT_TYPE = ''PACKAGE BODY'''), 'not found');
        END IF;
        IF cnt('SELECT COUNT(*) FROM ALL_ERRORS WHERE OWNER = ' || q(p_owner) || ' AND NAME = ' || q(p_name)
               || ' AND ATTRIBUTE = ''ERROR''') <> 0 THEN
            v_bad := v_bad || CASE WHEN v_bad IS NOT NULL THEN '; ' END || 'compile errors in ALL_ERRORS';
        END IF;
        IF v_bad IS NULL THEN
            report('PASS', p_id, p_owner || '.' || p_name || ' specification and body are VALID, no compile errors');
        ELSE
            report('FAIL', p_id, p_owner || '.' || p_name || ' specification and body are VALID, no compile errors', v_bad);
        END IF;
    END valid_package;

    -- A direct grant to the current schema; a grant through a role does not count for a definer-rights package.
    PROCEDURE has_grant(p_id VARCHAR2, p_owner VARCHAR2, p_table VARCHAR2, p_priv VARCHAR2) IS
    BEGIN
        IF cnt('SELECT COUNT(*) FROM ALL_TAB_PRIVS WHERE GRANTEE = ' || q(g_schema) || ' AND TABLE_SCHEMA = ' || q(p_owner)
               || ' AND TABLE_NAME = ' || q(p_table) || ' AND PRIVILEGE = ' || q(p_priv)) >= 1 THEN
            report('PASS', p_id, p_priv || ' on ' || p_owner || '.' || p_table || ' is granted directly to ' || g_schema);
        ELSE
            report('FAIL', p_id, p_priv || ' on ' || p_owner || '.' || p_table || ' is granted directly to ' || g_schema,
                   'not found (a grant through a role does not count for a definer-rights package)');
        END IF;
    END has_grant;

    -- Preflight 1 only: status and last DDL time of an object, for the rollback notes.
    PROCEDURE object_state(p_id VARCHAR2, p_owner VARCHAR2, p_name VARCHAR2, p_type VARCHAR2) IS
        v_state VARCHAR2(4000) := str('SELECT STATUS || '', last DDL '' || TO_CHAR(LAST_DDL_TIME, ''YYYY-MM-DD HH24:MI:SS'') FROM ALL_OBJECTS WHERE OWNER = '
            || q(p_owner) || ' AND OBJECT_NAME = ' || q(p_name) || ' AND OBJECT_TYPE = ' || q(p_type));
    BEGIN
        IF v_state IS NULL THEN
            report('INFO', p_id, p_type || ' ' || p_owner || '.' || p_name || ' does not exist yet');
        ELSIF v_state LIKE 'VALID%' THEN
            report('INFO', p_id, p_type || ' ' || p_owner || '.' || p_name || ' (rollback state)', v_state);
        ELSE
            report('WARN', p_id, p_type || ' ' || p_owner || '.' || p_name || ' is not valid (rollback state)', v_state);
        END IF;
    END object_state;
-- END HELPERS
