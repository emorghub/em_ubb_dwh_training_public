-- ===========================================================================
-- GENERATED from mapping M_COLLATERAL (specs/collateral/M_COLLATERAL.xlsx)
--   by tools/codegen/generate.py on 2026-11-27
--   mapping fingerprint 35a96c007d483467, approved by Emil Angelov on 2026-11-27
-- Change the mapping workbook and regenerate - do not hand-edit this file.
-- ===========================================================================
--
-- utPLSQL tests for UBB_CORE2.COLLATERAL_HIST: one test per acceptance criterion in the
-- mapping, plus a check that the test data actually reaches the load (so no
-- test can pass just because nothing was loaded).
-- A guard test loads the good data, adds the data that breaks the guard, and
-- expects the next run to be refused with the target left unchanged.
-- Test data lives in UT_COLLATERAL_HIST_DATA (tests/UT_COLLATERAL_HIST_DATA.sql), which the
-- generator writes once and never overwrites.
-- Every test runs inside a transaction utPLSQL rolls back afterwards
-- (--%rollback(auto)); that works because the load procedure never commits.
--
-- Running this file also runs the tests (last statement). Deploy the test data
-- package (UT_COLLATERAL_HIST_DATA) first. To rerun later without redeploying:
--   EXEC ut.run('UBB_CORE2.UT_COLLATERAL_HIST');

CREATE OR REPLACE PACKAGE UBB_CORE2.UT_COLLATERAL_HIST AS
    --%suite(COLLATERAL_HIST load - mapping M_COLLATERAL)
    --%suitepath(ubb_core2)
    --%rollback(auto)

    --%beforeeach
    PROCEDURE seed;

    --%test(The test data gives the source query at least one row)
    PROCEDURE t_fixture_has_rows;

    --%test(AC-01: No collateral item occurs twice in one source load.)
    PROCEDURE t_ac_01;

    --%test(AC-02: Every collateral item of the selected source load is stored.)
    PROCEDURE t_ac_02;

    --%test(AC-03: Value, valuation currency, eligibility flag and haircut equal the delivered values.)
    PROCEDURE t_ac_03;

    --%test(AC-04: Collateral is not linked to a loan in this table.)
    PROCEDURE t_ac_04;

    --%test(AC-05: Reject a reporting date that is not at midnight.)
    PROCEDURE t_ac_05;

    --%test(AC-06: Reject a staged collateral item without currency.)
    PROCEDURE t_ac_06;

    --%test(AC-07: Reject a staged collateral item that has no identity row in UBB_CORE2.COLLATERAL.)
    PROCEDURE t_ac_07;

    --%test(AC-08: Reject a run when collateral history rows already exist for the selected source load.)
    PROCEDURE t_ac_08;
END UT_COLLATERAL_HIST;
/

CREATE OR REPLACE PACKAGE BODY UBB_CORE2.UT_COLLATERAL_HIST AS

    -- The parameter values the load runs with, taken from the test data package
    -- so Check_SQL from the mapping can use them by name.
    P_BUSINESS_DATE CONSTANT DATE := UBB_CORE2.UT_COLLATERAL_HIST_DATA.P_BUSINESS_DATE;

    PROCEDURE seed IS
    BEGIN
        UBB_CORE2.UT_COLLATERAL_HIST_DATA.seed;
    END seed;

    PROCEDURE run_load IS
    BEGIN
        UBB_CORE2.PKG_ETL_COLLATERAL.LOAD_DAY(P_BUSINESS_DATE => P_BUSINESS_DATE);
    END run_load;

    -- Row count and a content hash of the whole target, to compare two states of it.
    PROCEDURE measure(o_rows OUT INTEGER, o_hash OUT NUMBER) IS
    BEGIN
        SELECT COUNT(*), NVL(SUM(NVL(ORA_HASH(COLLATERAL_ID), 0) + NVL(ORA_HASH(LOAD_ID), 0) + NVL(ORA_HASH(COLLATERAL_TYPE), 0) + NVL(ORA_HASH(COLLATERAL_STATUS), 0) + NVL(ORA_HASH(CURRENCY_CODE), 0) + NVL(ORA_HASH(MARKET_VALUE_AMT), 0) + NVL(ORA_HASH(ELIGIBLE_VALUE_AMT), 0) + NVL(ORA_HASH(VALUATION_DATE), 0) + NVL(ORA_HASH(VALUATION_CURRENCY_CODE), 0) + NVL(ORA_HASH(ELIGIBILITY_FLAG), 0) + NVL(ORA_HASH(ELIGIBILITY_REASON_CODE), 0) + NVL(ORA_HASH(REGULATORY_HAIRCUT_PCT), 0)), 0)
          INTO o_rows, o_hash
          FROM UBB_CORE2.COLLATERAL_HIST;
    END measure;

    PROCEDURE t_fixture_has_rows IS
        l_rows INTEGER;
    BEGIN
        SELECT COUNT(*) INTO l_rows FROM (
            SELECT COLLATERAL.COLLATERAL_ID               AS COLLATERAL_ID,
                   STG_COLLATERAL.LOAD_ID                 AS LOAD_ID,
                   NULL                                   AS LOAN_ID,
                   STG_COLLATERAL.COLLATERAL_TYPE         AS COLLATERAL_TYPE,
                   STG_COLLATERAL.COLLATERAL_STATUS       AS COLLATERAL_STATUS,
                   STG_COLLATERAL.CURRENCY_CODE           AS CURRENCY_CODE,
                   STG_COLLATERAL.MARKET_VALUE_AMT        AS MARKET_VALUE_AMT,
                   STG_COLLATERAL.ELIGIBLE_VALUE_AMT      AS ELIGIBLE_VALUE_AMT,
                   STG_COLLATERAL.VALUATION_DATE          AS VALUATION_DATE,
                   SYSTIMESTAMP                           AS CREATED_AT,
                   STG_COLLATERAL.VALUATION_CURRENCY_CODE AS VALUATION_CURRENCY_CODE,
                   STG_COLLATERAL.ELIGIBILITY_FLAG        AS ELIGIBILITY_FLAG,
                   STG_COLLATERAL.ELIGIBILITY_REASON_CODE AS ELIGIBILITY_REASON_CODE,
                   STG_COLLATERAL.REGULATORY_HAIRCUT_PCT  AS REGULATORY_HAIRCUT_PCT
            FROM UBB_STAGING2.STG_COLLATERAL STG_COLLATERAL
            JOIN UBB_CORE2.COLLATERAL COLLATERAL
              ON COLLATERAL.SOURCE_SYSTEM = 'CBS_SIM' AND COLLATERAL.COLLATERAL_REF = STG_COLLATERAL.COLLATERAL_REF
            WHERE STG_COLLATERAL.LOAD_ID = "UBB_CORE2"."PKG_ETL_CONTROL"."FIND_SOURCE_LOAD"('CBS_SIM', 'COLLATERAL', P_BUSINESS_DATE)
        );
        ut.expect(l_rows, 'source rows produced by the test data').to_be_greater_than(0);
    END t_fixture_has_rows;

    -- AC-01 (unique_key): No collateral item occurs twice in one source load.
    PROCEDURE t_ac_01 IS
        l_duplicates INTEGER;
    BEGIN
        run_load;
        SELECT COUNT(*) INTO l_duplicates FROM (
            SELECT COLLATERAL_ID, LOAD_ID
            FROM UBB_CORE2.COLLATERAL_HIST
            GROUP BY COLLATERAL_ID, LOAD_ID
            HAVING COUNT(*) > 1
        );
        ut.expect(l_duplicates, 'business keys that occur more than once').to_equal(0);
    END t_ac_01;

    -- AC-02 (all_source_rows_loaded): Every collateral item of the selected source load is stored.
    PROCEDURE t_ac_02 IS
        l_missing INTEGER;
    BEGIN
        run_load;
        SELECT COUNT(*) INTO l_missing FROM (
            SELECT COLLATERAL_ID, LOAD_ID FROM (
                SELECT COLLATERAL.COLLATERAL_ID               AS COLLATERAL_ID,
                       STG_COLLATERAL.LOAD_ID                 AS LOAD_ID,
                       NULL                                   AS LOAN_ID,
                       STG_COLLATERAL.COLLATERAL_TYPE         AS COLLATERAL_TYPE,
                       STG_COLLATERAL.COLLATERAL_STATUS       AS COLLATERAL_STATUS,
                       STG_COLLATERAL.CURRENCY_CODE           AS CURRENCY_CODE,
                       STG_COLLATERAL.MARKET_VALUE_AMT        AS MARKET_VALUE_AMT,
                       STG_COLLATERAL.ELIGIBLE_VALUE_AMT      AS ELIGIBLE_VALUE_AMT,
                       STG_COLLATERAL.VALUATION_DATE          AS VALUATION_DATE,
                       SYSTIMESTAMP                           AS CREATED_AT,
                       STG_COLLATERAL.VALUATION_CURRENCY_CODE AS VALUATION_CURRENCY_CODE,
                       STG_COLLATERAL.ELIGIBILITY_FLAG        AS ELIGIBILITY_FLAG,
                       STG_COLLATERAL.ELIGIBILITY_REASON_CODE AS ELIGIBILITY_REASON_CODE,
                       STG_COLLATERAL.REGULATORY_HAIRCUT_PCT  AS REGULATORY_HAIRCUT_PCT
                FROM UBB_STAGING2.STG_COLLATERAL STG_COLLATERAL
                JOIN UBB_CORE2.COLLATERAL COLLATERAL
                  ON COLLATERAL.SOURCE_SYSTEM = 'CBS_SIM' AND COLLATERAL.COLLATERAL_REF = STG_COLLATERAL.COLLATERAL_REF
                WHERE STG_COLLATERAL.LOAD_ID = "UBB_CORE2"."PKG_ETL_CONTROL"."FIND_SOURCE_LOAD"('CBS_SIM', 'COLLATERAL', P_BUSINESS_DATE)
            )
            MINUS
            SELECT COLLATERAL_ID, LOAD_ID FROM UBB_CORE2.COLLATERAL_HIST
        );
        ut.expect(l_missing, 'source rows that did not reach the target').to_equal(0);
    END t_ac_02;

    -- AC-03 (zero_rows): Value, valuation currency, eligibility flag and haircut equal the delivered values.
    PROCEDURE t_ac_03 IS
        l_violations INTEGER;
    BEGIN
        run_load;
        SELECT COUNT(*) INTO l_violations FROM (
            SELECT s.COLLATERAL_REF FROM UBB_STAGING2.STG_COLLATERAL s JOIN UBB_CORE2.COLLATERAL c ON c.SOURCE_SYSTEM = 'CBS_SIM' AND c.COLLATERAL_REF = s.COLLATERAL_REF JOIN UBB_CORE2.COLLATERAL_HIST h ON h.COLLATERAL_ID = c.COLLATERAL_ID AND h.LOAD_ID = s.LOAD_ID WHERE s.LOAD_ID = UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD('CBS_SIM', 'COLLATERAL', P_BUSINESS_DATE) AND (DECODE(h.MARKET_VALUE_AMT, s.MARKET_VALUE_AMT, 0, 1) = 1 OR DECODE(h.VALUATION_CURRENCY_CODE, s.VALUATION_CURRENCY_CODE, 0, 1) = 1 OR DECODE(h.ELIGIBILITY_FLAG, s.ELIGIBILITY_FLAG, 0, 1) = 1 OR DECODE(h.REGULATORY_HAIRCUT_PCT, s.REGULATORY_HAIRCUT_PCT, 0, 1) = 1)
        );
        ut.expect(l_violations, 'rows that break AC-03').to_equal(0);
    END t_ac_03;

    -- AC-04 (zero_rows): Collateral is not linked to a loan in this table.
    PROCEDURE t_ac_04 IS
        l_violations INTEGER;
    BEGIN
        run_load;
        SELECT COUNT(*) INTO l_violations FROM (
            SELECT h.COLLATERAL_ID FROM UBB_CORE2.COLLATERAL_HIST h WHERE h.LOAD_ID = UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD('CBS_SIM', 'COLLATERAL', P_BUSINESS_DATE) AND h.LOAN_ID IS NOT NULL
        );
        ut.expect(l_violations, 'rows that break AC-04').to_equal(0);
    END t_ac_04;

    -- AC-05 (guard): Reject a reporting date that is not at midnight.
    PROCEDURE t_ac_05 IS
        l_rows_before INTEGER;
        l_hash_before NUMBER;
        l_rows_after  INTEGER;
        l_hash_after  NUMBER;
        l_refused     BOOLEAN := FALSE;
    BEGIN
        run_load;  -- a good run first, so "unchanged" below means something
        measure(l_rows_before, l_hash_before);
        UBB_CORE2.UT_COLLATERAL_HIST_DATA.seed_ac_05;  -- source rows that break AC-05
        BEGIN
            run_load;
        EXCEPTION
            WHEN UBB_CORE2.PKG_ETL_COLLATERAL.e_guard_failed THEN
                l_refused := TRUE;
        END;
        measure(l_rows_after, l_hash_after);
        ut.expect(l_refused, 'the load refused the source (ORA-20005)').to_be_true();
        ut.expect(l_rows_after, 'rows after the refused run (no partial snapshot)').to_equal(l_rows_before);
        ut.expect(l_hash_after, 'content after the refused run (no partial snapshot)').to_equal(l_hash_before);
    END t_ac_05;

    -- AC-06 (guard): Reject a staged collateral item without currency.
    PROCEDURE t_ac_06 IS
        l_rows_before INTEGER;
        l_hash_before NUMBER;
        l_rows_after  INTEGER;
        l_hash_after  NUMBER;
        l_refused     BOOLEAN := FALSE;
    BEGIN
        run_load;  -- a good run first, so "unchanged" below means something
        measure(l_rows_before, l_hash_before);
        UBB_CORE2.UT_COLLATERAL_HIST_DATA.seed_ac_06;  -- source rows that break AC-06
        BEGIN
            run_load;
        EXCEPTION
            WHEN UBB_CORE2.PKG_ETL_COLLATERAL.e_guard_failed THEN
                l_refused := TRUE;
        END;
        measure(l_rows_after, l_hash_after);
        ut.expect(l_refused, 'the load refused the source (ORA-20005)').to_be_true();
        ut.expect(l_rows_after, 'rows after the refused run (no partial snapshot)').to_equal(l_rows_before);
        ut.expect(l_hash_after, 'content after the refused run (no partial snapshot)').to_equal(l_hash_before);
    END t_ac_06;

    -- AC-07 (guard): Reject a staged collateral item that has no identity row in UBB_CORE2.COLLATERAL.
    PROCEDURE t_ac_07 IS
        l_rows_before INTEGER;
        l_hash_before NUMBER;
        l_rows_after  INTEGER;
        l_hash_after  NUMBER;
        l_refused     BOOLEAN := FALSE;
    BEGIN
        run_load;  -- a good run first, so "unchanged" below means something
        measure(l_rows_before, l_hash_before);
        UBB_CORE2.UT_COLLATERAL_HIST_DATA.seed_ac_07;  -- source rows that break AC-07
        BEGIN
            run_load;
        EXCEPTION
            WHEN UBB_CORE2.PKG_ETL_COLLATERAL.e_guard_failed THEN
                l_refused := TRUE;
        END;
        measure(l_rows_after, l_hash_after);
        ut.expect(l_refused, 'the load refused the source (ORA-20005)').to_be_true();
        ut.expect(l_rows_after, 'rows after the refused run (no partial snapshot)').to_equal(l_rows_before);
        ut.expect(l_hash_after, 'content after the refused run (no partial snapshot)').to_equal(l_hash_before);
    END t_ac_07;

    -- AC-08 (guard): Reject a run when collateral history rows already exist for the selected source load.
    PROCEDURE t_ac_08 IS
        l_rows_before INTEGER;
        l_hash_before NUMBER;
        l_rows_after  INTEGER;
        l_hash_after  NUMBER;
        l_refused     BOOLEAN := FALSE;
    BEGIN
        run_load;  -- a good run first, so "unchanged" below means something
        measure(l_rows_before, l_hash_before);
        UBB_CORE2.UT_COLLATERAL_HIST_DATA.seed_ac_08;  -- source rows that break AC-08
        BEGIN
            run_load;
        EXCEPTION
            WHEN UBB_CORE2.PKG_ETL_COLLATERAL.e_guard_failed THEN
                l_refused := TRUE;
        END;
        measure(l_rows_after, l_hash_after);
        ut.expect(l_refused, 'the load refused the source (ORA-20005)').to_be_true();
        ut.expect(l_rows_after, 'rows after the refused run (no partial snapshot)').to_equal(l_rows_before);
        ut.expect(l_hash_after, 'content after the refused run (no partial snapshot)').to_equal(l_hash_before);
    END t_ac_08;

END UT_COLLATERAL_HIST;
/

-- Run the tests just deployed. Run this file as a script (SQL Developer F5,
-- SQLcl or SQL*Plus) so the report is printed; it needs the data package, the
-- load package and the target table to be deployed already.
SET SERVEROUTPUT ON SIZE UNLIMITED
BEGIN
    ut.run('UBB_CORE2.UT_COLLATERAL_HIST');
END;
/
