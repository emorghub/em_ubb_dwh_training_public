-- Deployment handover for mapping M_COLLATERAL (specs/collateral/M_COLLATERAL.xlsx)
-- mapping fingerprint 35a96c007d483467, approved by Emil Angelov on 2026-11-27; prepared 2026-11-27 by the assistant
-- READ ONLY: this script runs no DDL, no DML, no GRANT and no COMMIT.
--
-- Preflight 1 - before the DDL of M_COLLATERAL (target UBB_CORE2.COLLATERAL_HIST, change script ddl/M_COLLATERAL.sql).
-- Run as UBB_CORE2 (the schema of the load package), after the staging script staging/STG_COLLATERAL.sql
-- is deployed and before ddl/M_COLLATERAL.sql.
-- Usage, from the package folder:   @preflight/DEPLOY_M_COLLATERAL_PREFLIGHT_1_BEFORE_DDL.sql TEST
-- The first argument is the environment, TEST or PROD. TEST also checks what the test data needs.
-- Every check prints one PASS, FAIL, WARN or INFO line; the script ends with an error when a check fails.
-- Jobs: no start_run call for this load exists in sql/ and no job is known by name, so the running-load
-- check uses the CTRL_JOB rows whose DATASET_NAME is COLLATERAL (the dataset name is decision D-DATASET, unconfirmed).
-- The only statements are SELECT queries on the data dictionary and on the tables named in the workbook.

SET SERVEROUTPUT ON SIZE UNLIMITED
SET VERIFY OFF
SET DEFINE ON
WHENEVER SQLERROR EXIT FAILURE
DEFINE p_env = '&1'
DECLARE
    v_bad VARCHAR2(4000);
    v_txt VARCHAR2(4000);
    n     NUMBER;
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
BEGIN
    IF g_env NOT IN ('TEST', 'PROD') THEN
        report('FAIL', 'P', 'the environment parameter is TEST or PROD', 'got ' || NVL(g_env, 'nothing'));
        RAISE_APPLICATION_ERROR(-20999, 'preflight stopped: the environment parameter must be TEST or PROD');
    END IF;

    -- A. Where am I
    report('INFO', 'A-01', 'connected to database ' || NVL(SYS_CONTEXT('USERENV', 'DB_NAME'), '?')
        || ', service ' || NVL(SYS_CONTEXT('USERENV', 'SERVICE_NAME'), '?'), 'environment argument ' || g_env || ': confirm it is the target of the runbook');
    IF g_schema = 'UBB_CORE2' THEN
        report('PASS', 'A-02', 'the current schema is the schema of the load package', g_schema);
    ELSE
        report('FAIL', 'A-02', 'the current schema is the schema of the load package', 'connected as ' || g_schema || ', expected UBB_CORE2');
    END IF;

    -- B. Earlier mappings of CR-ECB-001 and the baseline objects this load reads
    report('INFO', 'B-01', 'earlier mappings of CR-ECB-001 that must be deployed first', 'none: M_COLLATERAL is Load_Plan order 1 and its Depends_On is empty');
    table_columns('B-02', 'UBB_CORE2', 'CTRL_LOAD', 'LOAD_ID, SOURCE_SYSTEM, DATASET_NAME, BUSINESS_DATE, LOAD_STATUS');
    valid_package('B-03', 'UBB_CORE2', 'PKG_ETL_CONTROL');
    IF cnt(q'~SELECT COUNT(*) FROM ALL_PROCEDURES WHERE OWNER = 'UBB_CORE2' AND OBJECT_NAME = 'PKG_ETL_CONTROL' AND PROCEDURE_NAME = 'FIND_SOURCE_LOAD'~') = 1 THEN
        report('PASS', 'B-04', 'UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD exists');
    ELSE
        report('FAIL', 'B-04', 'UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD exists', 'not found');
    END IF;
    table_columns('B-05', 'UBB_CORE2', 'COLLATERAL', 'COLLATERAL_ID, SOURCE_SYSTEM, COLLATERAL_REF');
    v_txt := str(q'~SELECT LISTAGG(cc.COLUMN_NAME, ',') WITHIN GROUP (ORDER BY cc.POSITION) FROM ALL_CONSTRAINTS c JOIN ALL_CONS_COLUMNS cc ON cc.OWNER = c.OWNER AND cc.CONSTRAINT_NAME = c.CONSTRAINT_NAME WHERE c.OWNER = 'UBB_CORE2' AND c.TABLE_NAME = 'COLLATERAL' AND c.CONSTRAINT_NAME = 'UQ_COLLATERAL_BK' AND c.CONSTRAINT_TYPE = 'U'~');
    IF v_txt = 'SOURCE_SYSTEM,COLLATERAL_REF' THEN
        report('PASS', 'B-06', 'UBB_CORE2.COLLATERAL has the unique key UQ_COLLATERAL_BK, so the join of the load cannot multiply rows', v_txt);
    ELSE
        report('FAIL', 'B-06', 'UBB_CORE2.COLLATERAL has the unique key UQ_COLLATERAL_BK on SOURCE_SYSTEM, COLLATERAL_REF', 'found: ' || NVL(v_txt, 'nothing'));
    END IF;
    n := cnt(q'~SELECT COUNT(*) FROM UBB_CORE2.COLLATERAL WHERE SOURCE_SYSTEM = 'CBS_SIM'~');
    IF n < 0 THEN
        report('FAIL', 'B-07', 'identity rows of UBB_CORE2.COLLATERAL for CBS_SIM can be read', 'the check could not run');
    ELSIF n = 0 THEN
        report('WARN', 'B-07', 'identity rows of UBB_CORE2.COLLATERAL for CBS_SIM', 'none: no loader in the repository creates them (D-05), so guard AC-07 stops every run until they exist');
    ELSE
        report('INFO', 'B-07', 'identity rows of UBB_CORE2.COLLATERAL for CBS_SIM', n || ' row(s)');
    END IF;
    v_txt := str(q'~SELECT LISTAGG(DATASET_NAME, ', ') WITHIN GROUP (ORDER BY DATASET_NAME) FROM (SELECT DISTINCT DATASET_NAME FROM UBB_CORE2.CTRL_LOAD WHERE SOURCE_SYSTEM = 'CBS_SIM')~');
    report('INFO', 'B-08', 'dataset names registered in CTRL_LOAD for CBS_SIM (D-DATASET: the load selects COLLATERAL)', NVL(v_txt, 'none'));
    n := cnt(q'~SELECT COUNT(*) FROM UBB_CORE2.CTRL_LOAD WHERE SOURCE_SYSTEM = 'CBS_SIM' AND DATASET_NAME = 'COLLATERAL'~');
    IF n = 0 THEN
        report('WARN', 'B-09', 'CTRL_LOAD rows for CBS_SIM / COLLATERAL', 'none yet: the dataset name is unconfirmed (D-DATASET) and no source load can be selected before one exists');
    ELSIF n < 0 THEN
        report('FAIL', 'B-09', 'CTRL_LOAD rows for CBS_SIM / COLLATERAL can be read', 'the check could not run');
    ELSE
        report('INFO', 'B-09', 'CTRL_LOAD rows for CBS_SIM / COLLATERAL', n || ' row(s)');
    END IF;

    -- C. What this mapping reads: UBB_STAGING2.STG_COLLATERAL, including the four columns planned by CBS_SIM v1.1
    table_columns('C-01', 'UBB_STAGING2', 'STG_COLLATERAL',
        'LOAD_ID, COLLATERAL_REF, COLLATERAL_TYPE, COLLATERAL_STATUS, CURRENCY_CODE, MARKET_VALUE_AMT, ELIGIBLE_VALUE_AMT, VALUATION_DATE, '
        || 'VALUATION_CURRENCY_CODE, ELIGIBILITY_FLAG, ELIGIBILITY_REASON_CODE, REGULATORY_HAIRCUT_PCT');
    v_bad := NULL;
    column_type(v_bad, 'UBB_STAGING2', 'STG_COLLATERAL', 'LOAD_ID', 'NUMBER', 18, 0, NULL, 'N');
    column_type(v_bad, 'UBB_STAGING2', 'STG_COLLATERAL', 'COLLATERAL_REF', 'VARCHAR2', NULL, NULL, 80, 'N');
    column_type(v_bad, 'UBB_STAGING2', 'STG_COLLATERAL', 'COLLATERAL_TYPE', 'VARCHAR2', NULL, NULL, 30, 'Y');
    column_type(v_bad, 'UBB_STAGING2', 'STG_COLLATERAL', 'COLLATERAL_STATUS', 'VARCHAR2', NULL, NULL, 20, 'Y');
    column_type(v_bad, 'UBB_STAGING2', 'STG_COLLATERAL', 'CURRENCY_CODE', 'CHAR', NULL, NULL, 3, 'Y');
    column_type(v_bad, 'UBB_STAGING2', 'STG_COLLATERAL', 'MARKET_VALUE_AMT', 'NUMBER', 20, 2, NULL, 'Y');
    column_type(v_bad, 'UBB_STAGING2', 'STG_COLLATERAL', 'ELIGIBLE_VALUE_AMT', 'NUMBER', 20, 2, NULL, 'Y');
    column_type(v_bad, 'UBB_STAGING2', 'STG_COLLATERAL', 'VALUATION_DATE', 'DATE', NULL, NULL, NULL, 'Y');
    column_type(v_bad, 'UBB_STAGING2', 'STG_COLLATERAL', 'VALUATION_CURRENCY_CODE', 'VARCHAR2', NULL, NULL, 3, 'Y');
    column_type(v_bad, 'UBB_STAGING2', 'STG_COLLATERAL', 'ELIGIBILITY_FLAG', 'CHAR', NULL, NULL, 1, 'Y');
    column_type(v_bad, 'UBB_STAGING2', 'STG_COLLATERAL', 'ELIGIBILITY_REASON_CODE', 'VARCHAR2', NULL, NULL, 30, 'Y');
    column_type(v_bad, 'UBB_STAGING2', 'STG_COLLATERAL', 'REGULATORY_HAIRCUT_PCT', 'NUMBER', 9, 6, NULL, 'Y');
    IF v_bad IS NULL THEN
        report('PASS', 'C-02', 'UBB_STAGING2.STG_COLLATERAL columns have the types the target copies (staging script deployed)');
    ELSE
        report('FAIL', 'C-02', 'UBB_STAGING2.STG_COLLATERAL columns have the types the target copies', 'missing or different: ' || v_bad
            || ' - the four planned columns come from staging/STG_COLLATERAL.sql, which must be deployed first');
    END IF;

    -- D. The target UBB_CORE2.COLLATERAL_HIST exists; the change script adds four columns
    table_columns('D-01', 'UBB_CORE2', 'COLLATERAL_HIST',
        'COLLATERAL_ID, LOAD_ID, LOAN_ID, COLLATERAL_TYPE, COLLATERAL_STATUS, CURRENCY_CODE, MARKET_VALUE_AMT, ELIGIBLE_VALUE_AMT, VALUATION_DATE, CREATED_AT');
    FOR r IN (SELECT 'VALUATION_CURRENCY_CODE' AS col FROM DUAL UNION ALL SELECT 'ELIGIBILITY_FLAG' FROM DUAL
              UNION ALL SELECT 'ELIGIBILITY_REASON_CODE' FROM DUAL UNION ALL SELECT 'REGULATORY_HAIRCUT_PCT' FROM DUAL) LOOP
        n := cnt('SELECT COUNT(*) FROM ALL_TAB_COLUMNS WHERE OWNER = ''UBB_CORE2'' AND TABLE_NAME = ''COLLATERAL_HIST'' AND COLUMN_NAME = ' || q(r.col));
        IF n = 0 THEN
            report('PASS', 'D-02', 'UBB_CORE2.COLLATERAL_HIST.' || r.col || ' is not there yet (the change script adds it)');
        ELSIF n < 0 THEN
            report('FAIL', 'D-02', 'UBB_CORE2.COLLATERAL_HIST.' || r.col || ' can be checked', 'the check could not run');
        ELSE
            report('WARN', 'D-02', 'UBB_CORE2.COLLATERAL_HIST.' || r.col || ' already exists', 'change script already applied: do not run ddl/M_COLLATERAL.sql again');
        END IF;
    END LOOP;
    n := cnt(q'~SELECT COUNT(*) FROM UBB_CORE2.COLLATERAL_HIST~');
    IF n < 0 THEN
        report('WARN', 'D-03', 'rows already stored in UBB_CORE2.COLLATERAL_HIST', 'the count could not be read');
    ELSE
        report('INFO', 'D-03', 'rows already stored in UBB_CORE2.COLLATERAL_HIST (they stay; the new columns are NULL for them)', n || ' row(s)');
    END IF;

    -- E. Grants (direct grants; a definer-rights package does not use roles)
    has_grant('E-01', 'UBB_STAGING2', 'STG_COLLATERAL', 'SELECT');
    IF g_env = 'TEST' THEN
        has_grant('E-02', 'UBB_STAGING2', 'STG_COLLATERAL', 'INSERT');
        IF cnt(q'~SELECT COUNT(*) FROM ALL_OBJECTS WHERE OBJECT_NAME = 'UT' AND OBJECT_TYPE = 'PACKAGE' AND STATUS = 'VALID'~') >= 1 THEN
            report('PASS', 'E-03', 'the utPLSQL package UT is installed and valid');
        ELSE
            report('FAIL', 'E-03', 'the utPLSQL package UT is installed and valid', 'not found: the tests cannot run');
        END IF;
    ELSE
        report('INFO', 'E-02', 'TEST-only checks (INSERT grant for the test data, utPLSQL) skipped for ' || g_env);
    END IF;

    -- F. Running loads
    v_txt := str(q'~SELECT LISTAGG(JOB_NAME, ', ') WITHIN GROUP (ORDER BY JOB_NAME) FROM UBB_CORE2.CTRL_JOB WHERE DATASET_NAME = 'COLLATERAL'~');
    report('INFO', 'F-01', 'jobs registered in CTRL_JOB for dataset COLLATERAL', NVL(v_txt, 'none (the scheduler job is an open item of the runbook)'));
    check_none('F-02', 'no job run of dataset COLLATERAL is RUNNING',
        q'~SELECT r.RUN_ID FROM UBB_CORE2.CTRL_JOB_RUN r JOIN UBB_CORE2.CTRL_JOB j ON j.JOB_NAME = r.JOB_NAME WHERE r.RUN_STATUS = 'RUNNING' AND j.DATASET_NAME = 'COLLATERAL'~');
    n := cnt(q'~SELECT COUNT(*) FROM ALL_SCHEDULER_JOBS WHERE ENABLED = 'TRUE' AND UPPER(JOB_ACTION) LIKE '%PKG_ETL_COLLATERAL%'~');
    IF n < 0 THEN
        report('WARN', 'F-03', 'no enabled scheduler job calls PKG_ETL_COLLATERAL', 'ALL_SCHEDULER_JOBS could not be read');
    ELSIF n > 0 THEN
        report('WARN', 'F-03', 'no enabled scheduler job calls PKG_ETL_COLLATERAL', n || ' enabled job(s): the runbook pauses the schedule');
    ELSE
        report('PASS', 'F-03', 'no enabled scheduler job calls PKG_ETL_COLLATERAL');
    END IF;
    n := cnt(q'~SELECT COUNT(*) FROM V$SESSION WHERE MODULE = 'PKG_ETL_COLLATERAL'~');
    IF n < 0 THEN
        report('WARN', 'F-04', 'no session runs PKG_ETL_COLLATERAL', 'V$SESSION is not readable by ' || g_schema);
    ELSIF n > 0 THEN
        report('FAIL', 'F-04', 'no session runs PKG_ETL_COLLATERAL', n || ' session(s) have MODULE PKG_ETL_COLLATERAL');
    ELSE
        report('PASS', 'F-04', 'no session runs PKG_ETL_COLLATERAL');
    END IF;

    -- G. Rollback state: what exists now (the package and the table are replaced or altered by the runbook)
    object_state('G-01', 'UBB_CORE2', 'PKG_ETL_COLLATERAL', 'PACKAGE');
    object_state('G-02', 'UBB_CORE2', 'PKG_ETL_COLLATERAL', 'PACKAGE BODY');
    object_state('G-03', 'UBB_CORE2', 'COLLATERAL_HIST', 'TABLE');
    n := cnt('SELECT COUNT(*) FROM ALL_OBJECTS WHERE OWNER = ' || q(g_schema) || ' AND STATUS = ''INVALID''');
    IF n < 0 THEN
        report('WARN', 'G-04', 'no invalid object in ' || g_schema, 'the check could not run');
    ELSIF n > 0 THEN
        report('WARN', 'G-04', 'no invalid object in ' || g_schema, n || ' invalid object(s): note them before deploying');
    ELSE
        report('PASS', 'G-04', 'no invalid object in ' || g_schema);
    END IF;

    IF g_failed > 0 THEN
        RAISE_APPLICATION_ERROR(-20999, g_failed || ' preflight check(s) failed');
    END IF;
    DBMS_OUTPUT.PUT_LINE('PREFLIGHT 1 OK');
END;
/
