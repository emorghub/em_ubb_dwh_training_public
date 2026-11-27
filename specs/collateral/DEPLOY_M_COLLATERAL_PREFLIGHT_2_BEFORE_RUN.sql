-- Deployment handover for mapping M_COLLATERAL (specs/collateral/M_COLLATERAL.xlsx)
-- mapping fingerprint 35a96c007d483467, approved by Emil Angelov on 2026-11-27; prepared 2026-11-27 by the assistant
-- READ ONLY: this script runs no DDL, no DML, no GRANT and no COMMIT.
--
-- Preflight 2 - after everything is deployed, before the first run of UBB_CORE2.PKG_ETL_COLLATERAL.LOAD_DAY.
-- Run as UBB_CORE2 (the schema of the load package).
-- Usage, from the package folder:   @preflight/DEPLOY_M_COLLATERAL_PREFLIGHT_2_BEFORE_RUN.sql 2026-11-30 TEST
-- The first argument is the business date P_BUSINESS_DATE of the first run, as YYYY-MM-DD, at midnight.
-- The second argument is the environment, TEST or PROD. TEST also checks the utPLSQL packages.
-- Every check prints one PASS, FAIL, WARN or INFO line; the script ends with an error when a check fails.
-- Section G repeats the guards AC-05 to AC-08 of the workbook word for word, with P_BUSINESS_DATE replaced by the
-- first argument; the load package runs the same queries and would stop with ORA-20005.
-- The statements are SELECT queries on the data dictionary and on the tables named in the workbook. The text
-- search of section D only reads ALL_SOURCE; it looks for the words that write to the target and changes nothing.

SET SERVEROUTPUT ON SIZE UNLIMITED
SET VERIFY OFF
SET DEFINE ON
WHENEVER SQLERROR EXIT FAILURE
DEFINE p_business_date = '&1'
DEFINE p_env = '&2'
DECLARE
    g_date DATE;
    v_bad  VARCHAR2(4000);
    v_txt  VARCHAR2(4000);
    n      NUMBER;
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
    BEGIN
        g_date := TO_DATE('&p_business_date', 'YYYY-MM-DD');
    EXCEPTION
        WHEN OTHERS THEN
            g_date := NULL;
    END;
    IF g_date IS NULL OR g_date <> TRUNC(g_date) OR TO_CHAR(g_date, 'YYYY-MM-DD') <> '&p_business_date' THEN
        report('FAIL', 'P', 'the business date parameter is a date as YYYY-MM-DD at midnight', 'got ' || NVL('&p_business_date', 'nothing'));
        RAISE_APPLICATION_ERROR(-20999, 'preflight stopped: the business date parameter must be YYYY-MM-DD');
    END IF;

    -- A. Where am I
    report('INFO', 'A-01', 'connected to database ' || NVL(SYS_CONTEXT('USERENV', 'DB_NAME'), '?')
        || ', service ' || NVL(SYS_CONTEXT('USERENV', 'SERVICE_NAME'), '?'),
        'environment argument ' || g_env || ', business date ' || TO_CHAR(g_date, 'YYYY-MM-DD') || ': confirm both against the runbook');
    IF g_schema = 'UBB_CORE2' THEN
        report('PASS', 'A-02', 'the current schema is the schema of the load package', g_schema);
    ELSE
        report('FAIL', 'A-02', 'the current schema is the schema of the load package', 'connected as ' || g_schema || ', expected UBB_CORE2');
    END IF;

    -- B. The target as deployed: UBB_CORE2.COLLATERAL_HIST, the 14 columns of the workbook
    table_columns('B-01', 'UBB_CORE2', 'COLLATERAL_HIST',
        'COLLATERAL_ID, LOAD_ID, LOAN_ID, COLLATERAL_TYPE, COLLATERAL_STATUS, CURRENCY_CODE, MARKET_VALUE_AMT, ELIGIBLE_VALUE_AMT, VALUATION_DATE, CREATED_AT, '
        || 'VALUATION_CURRENCY_CODE, ELIGIBILITY_FLAG, ELIGIBILITY_REASON_CODE, REGULATORY_HAIRCUT_PCT');
    v_bad := NULL;
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'COLLATERAL_ID', 'NUMBER', 18, 0, NULL, 'N');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'LOAD_ID', 'NUMBER', 18, 0, NULL, 'N');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'LOAN_ID', 'NUMBER', 18, 0, NULL, 'Y');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'COLLATERAL_TYPE', 'VARCHAR2', NULL, NULL, 30, 'Y');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'COLLATERAL_STATUS', 'VARCHAR2', NULL, NULL, 20, 'Y');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'CURRENCY_CODE', 'CHAR', NULL, NULL, 3, 'N');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'MARKET_VALUE_AMT', 'NUMBER', 20, 2, NULL, 'Y');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'ELIGIBLE_VALUE_AMT', 'NUMBER', 20, 2, NULL, 'Y');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'VALUATION_DATE', 'DATE', NULL, NULL, NULL, 'Y');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'CREATED_AT', 'TIMESTAMP(6)', NULL, NULL, NULL, 'N');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'VALUATION_CURRENCY_CODE', 'VARCHAR2', NULL, NULL, 3, 'Y');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'ELIGIBILITY_FLAG', 'CHAR', NULL, NULL, 1, 'Y');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'ELIGIBILITY_REASON_CODE', 'VARCHAR2', NULL, NULL, 30, 'Y');
    column_type(v_bad, 'UBB_CORE2', 'COLLATERAL_HIST', 'REGULATORY_HAIRCUT_PCT', 'NUMBER', 9, 6, NULL, 'Y');
    IF v_bad IS NULL THEN
        report('PASS', 'B-02', 'UBB_CORE2.COLLATERAL_HIST columns have the mapped type, length or precision and nullability');
    ELSE
        report('FAIL', 'B-02', 'UBB_CORE2.COLLATERAL_HIST columns have the mapped type, length or precision and nullability', 'missing or different: ' || v_bad);
    END IF;
    v_txt := str(q'~SELECT LISTAGG(cc.COLUMN_NAME, ',') WITHIN GROUP (ORDER BY cc.POSITION) FROM ALL_CONSTRAINTS c JOIN ALL_CONS_COLUMNS cc ON cc.OWNER = c.OWNER AND cc.CONSTRAINT_NAME = c.CONSTRAINT_NAME WHERE c.OWNER = 'UBB_CORE2' AND c.TABLE_NAME = 'COLLATERAL_HIST' AND c.CONSTRAINT_TYPE = 'P'~');
    IF v_txt = 'COLLATERAL_ID,LOAD_ID' THEN
        report('PASS', 'B-03', 'the primary key of UBB_CORE2.COLLATERAL_HIST is the business key', v_txt);
    ELSE
        report('FAIL', 'B-03', 'the primary key of UBB_CORE2.COLLATERAL_HIST is the business key COLLATERAL_ID, LOAD_ID', 'found: ' || NVL(v_txt, 'nothing'));
    END IF;
    IF cnt(q'~SELECT COUNT(*) FROM ALL_COL_COMMENTS WHERE OWNER = 'UBB_CORE2' AND TABLE_NAME = 'COLLATERAL_HIST' AND COLUMN_NAME IN ('VALUATION_CURRENCY_CODE', 'ELIGIBILITY_FLAG', 'ELIGIBILITY_REASON_CODE', 'REGULATORY_HAIRCUT_PCT') AND COMMENTS IS NOT NULL~') = 4 THEN
        report('PASS', 'B-04', 'the four columns added by the change script have their column comment');
    ELSE
        report('FAIL', 'B-04', 'the four columns added by the change script have their column comment', 'comments missing');
    END IF;

    -- C. The load code
    valid_package('C-01', 'UBB_CORE2', 'PKG_ETL_COLLATERAL');
    IF cnt(q'~SELECT COUNT(*) FROM ALL_ARGUMENTS WHERE OWNER = 'UBB_CORE2' AND PACKAGE_NAME = 'PKG_ETL_COLLATERAL' AND OBJECT_NAME = 'LOAD_DAY' AND DATA_LEVEL = 0 AND ARGUMENT_NAME = 'P_BUSINESS_DATE' AND POSITION = 1 AND DATA_TYPE = 'DATE' AND IN_OUT = 'IN'~') = 1
       AND cnt(q'~SELECT COUNT(*) FROM ALL_ARGUMENTS WHERE OWNER = 'UBB_CORE2' AND PACKAGE_NAME = 'PKG_ETL_COLLATERAL' AND OBJECT_NAME = 'LOAD_DAY' AND DATA_LEVEL = 0 AND ARGUMENT_NAME IS NOT NULL~') = 1 THEN
        report('PASS', 'C-02', 'UBB_CORE2.PKG_ETL_COLLATERAL.LOAD_DAY has the one parameter P_BUSINESS_DATE IN DATE');
    ELSE
        report('FAIL', 'C-02', 'UBB_CORE2.PKG_ETL_COLLATERAL.LOAD_DAY has the one parameter P_BUSINESS_DATE IN DATE', 'signature not found or different');
    END IF;
    IF g_env = 'TEST' THEN
        valid_package('C-03', 'UBB_CORE2', 'UT_COLLATERAL_HIST');
        valid_package('C-04', 'UBB_CORE2', 'UT_COLLATERAL_HIST_DATA');
    ELSE
        report('INFO', 'C-03', 'TEST-only checks (the utPLSQL packages) skipped for ' || g_env);
    END IF;

    -- D. One writer: no other object writes to the target (text search of ALL_SOURCE, so look at any hit)
    check_none('D-01', 'no object other than PKG_ETL_COLLATERAL and the UT_ test packages writes to COLLATERAL_HIST (text search of ALL_SOURCE; look at any hit)',
        q'~SELECT DISTINCT s.OWNER, s.TYPE, s.NAME FROM ALL_SOURCE s WHERE s.TYPE IN ('PACKAGE BODY', 'PROCEDURE', 'FUNCTION', 'TRIGGER') AND NOT (s.OWNER = 'UBB_CORE2' AND (s.NAME = 'PKG_ETL_COLLATERAL' OR s.NAME LIKE 'UT\_%' ESCAPE '\')) AND NOT REGEXP_LIKE(s.TEXT, '^\s*--') AND REGEXP_LIKE(s.TEXT, '(INSERT\s+INTO|MERGE\s+INTO|UPDATE|DELETE\s+FROM|DELETE)\s+(UBB_CORE2\.)?COLLATERAL_HIST', 'i')~');

    -- E. Grants
    has_grant('E-01', 'UBB_STAGING2', 'STG_COLLATERAL', 'SELECT');

    -- F. Running loads
    check_none('F-01', 'no job run of dataset COLLATERAL is RUNNING',
        q'~SELECT r.RUN_ID FROM UBB_CORE2.CTRL_JOB_RUN r JOIN UBB_CORE2.CTRL_JOB j ON j.JOB_NAME = r.JOB_NAME WHERE r.RUN_STATUS = 'RUNNING' AND j.DATASET_NAME = 'COLLATERAL'~');
    check_none('F-02', 'no job run of dataset COLLATERAL is RUNNING for the business date',
        q'~SELECT r.RUN_ID FROM UBB_CORE2.CTRL_JOB_RUN r JOIN UBB_CORE2.CTRL_JOB j ON j.JOB_NAME = r.JOB_NAME WHERE r.RUN_STATUS = 'RUNNING' AND j.DATASET_NAME = 'COLLATERAL' AND r.BUSINESS_DATE = TO_DATE('&p_business_date','YYYY-MM-DD')~');
    n := cnt(q'~SELECT COUNT(*) FROM ALL_SCHEDULER_JOBS WHERE ENABLED = 'TRUE' AND UPPER(JOB_ACTION) LIKE '%PKG_ETL_COLLATERAL%'~');
    IF n < 0 THEN
        report('WARN', 'F-03', 'no enabled scheduler job calls PKG_ETL_COLLATERAL', 'ALL_SCHEDULER_JOBS could not be read');
    ELSIF n > 0 THEN
        report('WARN', 'F-03', 'no enabled scheduler job calls PKG_ETL_COLLATERAL', n || ' enabled job(s): resume schedules only after the first run is verified');
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

    -- G. The source load of the date and the guards of the workbook (AC-05 to AC-08)
    n := cnt(q'~SELECT COUNT(*) FROM UBB_CORE2.CTRL_LOAD WHERE SOURCE_SYSTEM = 'CBS_SIM' AND DATASET_NAME = 'COLLATERAL' AND BUSINESS_DATE = TO_DATE('&p_business_date','YYYY-MM-DD') AND LOAD_STATUS IN ('VALIDATED', 'COMPLETED')~');
    IF n = 1 THEN
        report('PASS', 'G-01', 'exactly one VALIDATED or COMPLETED CBS_SIM / COLLATERAL source load exists for the date');
    ELSE
        report('FAIL', 'G-01', 'exactly one VALIDATED or COMPLETED CBS_SIM / COLLATERAL source load exists for the date',
            CASE WHEN n = 0 THEN 'none: the load would stop with ORA-20011 (the dataset name is unconfirmed, D-DATASET)'
                 WHEN n > 1 THEN n || ' loads: the load would stop with ORA-20012'
                 ELSE 'the check could not run' END);
    END IF;
    v_txt := str(q'~SELECT LISTAGG(LOAD_ID || ':' || LOAD_STATUS, ', ') WITHIN GROUP (ORDER BY LOAD_ID) FROM UBB_CORE2.CTRL_LOAD WHERE SOURCE_SYSTEM = 'CBS_SIM' AND DATASET_NAME = 'COLLATERAL' AND BUSINESS_DATE = TO_DATE('&p_business_date','YYYY-MM-DD')~');
    report('INFO', 'G-02', 'CTRL_LOAD rows of CBS_SIM / COLLATERAL for the date (LOAD_ID:status), the source loads the guards depend on', NVL(v_txt, 'none'));
    check_none('AC-05', 'Reject a reporting date that is not at midnight.',
        q'~SELECT 1 FROM DUAL WHERE TO_DATE('&p_business_date','YYYY-MM-DD') <> TRUNC(TO_DATE('&p_business_date','YYYY-MM-DD'))~');
    check_none('AC-06', 'Reject a staged collateral item without currency.',
        q'~SELECT s.COLLATERAL_REF FROM UBB_STAGING2.STG_COLLATERAL s WHERE s.LOAD_ID = UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD('CBS_SIM', 'COLLATERAL', TO_DATE('&p_business_date','YYYY-MM-DD')) AND s.CURRENCY_CODE IS NULL~');
    check_none('AC-07', 'Reject a staged collateral item that has no identity row in UBB_CORE2.COLLATERAL.',
        q'~SELECT s.COLLATERAL_REF FROM UBB_STAGING2.STG_COLLATERAL s WHERE s.LOAD_ID = UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD('CBS_SIM', 'COLLATERAL', TO_DATE('&p_business_date','YYYY-MM-DD')) AND NOT EXISTS (SELECT 1 FROM UBB_CORE2.COLLATERAL c WHERE c.SOURCE_SYSTEM = 'CBS_SIM' AND c.COLLATERAL_REF = s.COLLATERAL_REF)~');
    check_none('AC-08', 'Reject a run when collateral history rows already exist for the selected source load.',
        q'~SELECT h.LOAD_ID FROM UBB_CORE2.COLLATERAL_HIST h WHERE h.LOAD_ID = UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD('CBS_SIM', 'COLLATERAL', TO_DATE('&p_business_date','YYYY-MM-DD')) GROUP BY h.LOAD_ID~');

    -- H. What the load of the date will do (append: a stored snapshot is never overwritten, D-RERUN)
    check_none('H-01', 'COLLATERAL_HIST has no rows yet for a source load of the date (a re-run is refused)',
        q'~SELECT h.LOAD_ID FROM UBB_CORE2.COLLATERAL_HIST h WHERE h.LOAD_ID IN (SELECT LOAD_ID FROM UBB_CORE2.CTRL_LOAD WHERE SOURCE_SYSTEM = 'CBS_SIM' AND DATASET_NAME = 'COLLATERAL' AND BUSINESS_DATE = TO_DATE('&p_business_date','YYYY-MM-DD') AND LOAD_STATUS IN ('VALIDATED', 'COMPLETED')) GROUP BY h.LOAD_ID~');
    n := cnt(q'~SELECT COUNT(*) FROM UBB_STAGING2.STG_COLLATERAL WHERE LOAD_ID IN (SELECT LOAD_ID FROM UBB_CORE2.CTRL_LOAD WHERE SOURCE_SYSTEM = 'CBS_SIM' AND DATASET_NAME = 'COLLATERAL' AND BUSINESS_DATE = TO_DATE('&p_business_date','YYYY-MM-DD') AND LOAD_STATUS IN ('VALIDATED', 'COMPLETED'))~');
    IF n < 0 THEN
        report('WARN', 'H-02', 'rows staged in STG_COLLATERAL for the selected source load', 'the count could not be read');
    ELSIF n = 0 THEN
        report('WARN', 'H-02', 'rows staged in STG_COLLATERAL for the selected source load', 'none: the load would write no row');
    ELSE
        report('INFO', 'H-02', 'rows staged in STG_COLLATERAL for the selected source load (the load stores one row per item)', n || ' row(s)');
    END IF;
    check_none('H-03', 'every staged item has a valuation currency, an eligibility flag and a haircut (a missing value is loaded as NULL and treated as not recognised, BR-03)',
        q'~SELECT s.COLLATERAL_REF FROM UBB_STAGING2.STG_COLLATERAL s WHERE s.LOAD_ID IN (SELECT LOAD_ID FROM UBB_CORE2.CTRL_LOAD WHERE SOURCE_SYSTEM = 'CBS_SIM' AND DATASET_NAME = 'COLLATERAL' AND BUSINESS_DATE = TO_DATE('&p_business_date','YYYY-MM-DD') AND LOAD_STATUS IN ('VALIDATED', 'COMPLETED')) AND (s.VALUATION_CURRENCY_CODE IS NULL OR s.ELIGIBILITY_FLAG IS NULL OR s.REGULATORY_HAIRCUT_PCT IS NULL)~', 'WARN');
    check_none('H-04', 'every staged haircut is between 0 and 100 (percentage points assumed in D-06; scale and range still to be confirmed by the source owner)',
        q'~SELECT s.COLLATERAL_REF FROM UBB_STAGING2.STG_COLLATERAL s WHERE s.LOAD_ID IN (SELECT LOAD_ID FROM UBB_CORE2.CTRL_LOAD WHERE SOURCE_SYSTEM = 'CBS_SIM' AND DATASET_NAME = 'COLLATERAL' AND BUSINESS_DATE = TO_DATE('&p_business_date','YYYY-MM-DD') AND LOAD_STATUS IN ('VALIDATED', 'COMPLETED')) AND s.REGULATORY_HAIRCUT_PCT NOT BETWEEN 0 AND 100~', 'WARN');

    IF g_failed > 0 THEN
        RAISE_APPLICATION_ERROR(-20999, g_failed || ' preflight check(s) failed');
    END IF;
    DBMS_OUTPUT.PUT_LINE('PREFLIGHT 2 OK');
END;
/
