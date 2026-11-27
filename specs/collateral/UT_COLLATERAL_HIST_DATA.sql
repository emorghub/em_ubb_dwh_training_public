-- ===========================================================================
-- Test data for UT_COLLATERAL_HIST (mapping M_COLLATERAL).
-- Written ONCE by tools/codegen/generate.py on 2026-11-27 as a starting
-- point, then owned by the developer: regenerating the tests never overwrites
-- this file. All placeholders have been replaced with realistic values.
--
-- Needs (run by a user who may grant on the staging schema):
--   GRANT INSERT ON UBB_STAGING2.STG_COLLATERAL TO UBB_CORE2;
--   GRANT INSERT ON UBB_CORE2.COLLATERAL TO UBB_CORE2;
-- Everything seed inserts is rolled back after each test by utPLSQL.
-- ===========================================================================

CREATE OR REPLACE PACKAGE UBB_CORE2.UT_COLLATERAL_HIST_DATA AS
    -- The parameter values every test runs the load with. Pick values no real
    -- staging data uses, so the tests do not depend on what happens to be loaded.
    P_BUSINESS_DATE CONSTANT DATE := DATE '2000-01-01';

    -- Test source loads, registered in CTRL_LOAD by seed. C_LOAD_ID is the one
    -- the load selects for P_BUSINESS_DATE; C_OTHER_LOAD_ID belongs to the next
    -- day and must be left out. IDs far above the CTRL_LOAD sequence.
    C_LOAD_ID       CONSTANT NUMBER := 999000001;
    C_OTHER_LOAD_ID CONSTANT NUMBER := 999000002;

    PROCEDURE seed;

    -- Source rows that break guard AC-05. Only its test inserts them, after seed.
    PROCEDURE seed_ac_05;

    -- Source rows that break guard AC-06. Only its test inserts them, after seed.
    PROCEDURE seed_ac_06;

    -- Source rows that break guard AC-07. Only its test inserts them, after seed.
    PROCEDURE seed_ac_07;

    -- Source rows that break guard AC-08. Only its test inserts them, after seed.
    PROCEDURE seed_ac_08;
END UT_COLLATERAL_HIST_DATA;
/

CREATE OR REPLACE PACKAGE BODY UBB_CORE2.UT_COLLATERAL_HIST_DATA AS

    PROCEDURE seed IS
    BEGIN
        -- Cases the data covers:
        --   * Two source loads in CTRL_LOAD: C_LOAD_ID (the one FIND_SOURCE_LOAD finds
        --     for P_BUSINESS_DATE) and C_OTHER_LOAD_ID (next day, outside the Filter).
        --   * UT_COL_001: complete item, all four new columns filled. Its CURRENCY_CODE
        --     differs from VALUATION_CURRENCY_CODE, and its market value from its eligible
        --     value, so a mix-up of columns is caught by AC-03.
        --   * UT_COL_002: no valuation, no haircut, not eligible - loaded as NULL, not rejected.
        --   * UT_COL_003: in the other load, with an identity row - must NOT be loaded.
        --   * A staged item without identity row is the data of guard AC-07 (seed_ac_07).
        --   * AC-04 needs no extra row: no row may get a LOAN_ID.
        --   * No row here breaks a guard; the rows that do are in the seed_ procedures below.

        INSERT INTO UBB_CORE2.CTRL_LOAD (LOAD_ID, SOURCE_SYSTEM, DATASET_NAME, BUSINESS_DATE, LOAD_STATUS)
        VALUES (C_LOAD_ID, 'CBS_SIM', 'COLLATERAL', P_BUSINESS_DATE, 'COMPLETED');
        INSERT INTO UBB_CORE2.CTRL_LOAD (LOAD_ID, SOURCE_SYSTEM, DATASET_NAME, BUSINESS_DATE, LOAD_STATUS)
        VALUES (C_OTHER_LOAD_ID, 'CBS_SIM', 'COLLATERAL', P_BUSINESS_DATE + 1, 'COMPLETED');

        -- UBB_CORE2.COLLATERAL - inner join: identity rows, SOURCE_SYSTEM must be 'CBS_SIM'
        INSERT INTO UBB_CORE2.COLLATERAL (COLLATERAL_ID, SOURCE_SYSTEM, COLLATERAL_REF)
        VALUES (999000001, 'CBS_SIM', 'UT_COL_001');
        INSERT INTO UBB_CORE2.COLLATERAL (COLLATERAL_ID, SOURCE_SYSTEM, COLLATERAL_REF)
        VALUES (999000002, 'CBS_SIM', 'UT_COL_002');
        INSERT INTO UBB_CORE2.COLLATERAL (COLLATERAL_ID, SOURCE_SYSTEM, COLLATERAL_REF)
        VALUES (999000003, 'CBS_SIM', 'UT_COL_003');

        -- UBB_STAGING2.STG_COLLATERAL - driving table: each row of C_LOAD_ID becomes one target row
        INSERT INTO UBB_STAGING2.STG_COLLATERAL (
            LOAD_ID, COLLATERAL_REF, COLLATERAL_TYPE, COLLATERAL_STATUS, CURRENCY_CODE,
            MARKET_VALUE_AMT, ELIGIBLE_VALUE_AMT, VALUATION_DATE,
            VALUATION_CURRENCY_CODE, ELIGIBILITY_FLAG, ELIGIBILITY_REASON_CODE, REGULATORY_HAIRCUT_PCT
        ) VALUES (
            C_LOAD_ID, 'UT_COL_001', 'REAL_ESTATE', 'ACTIVE', 'CHF',
            250000.00, 212500.00, P_BUSINESS_DATE - 1,
            'EUR', 'Y', 'ELIGIBLE', 15.000000
        );
        INSERT INTO UBB_STAGING2.STG_COLLATERAL (
            LOAD_ID, COLLATERAL_REF, COLLATERAL_TYPE, COLLATERAL_STATUS, CURRENCY_CODE,
            MARKET_VALUE_AMT, ELIGIBLE_VALUE_AMT, VALUATION_DATE,
            VALUATION_CURRENCY_CODE, ELIGIBILITY_FLAG, ELIGIBILITY_REASON_CODE, REGULATORY_HAIRCUT_PCT
        ) VALUES (
            C_LOAD_ID, 'UT_COL_002', 'GUARANTEE', 'ACTIVE', 'EUR',
            NULL, NULL, NULL,
            NULL, 'N', 'NOT_ELIGIBLE', NULL
        );

        -- Outside the Filter: another source load
        INSERT INTO UBB_STAGING2.STG_COLLATERAL (
            LOAD_ID, COLLATERAL_REF, COLLATERAL_TYPE, COLLATERAL_STATUS, CURRENCY_CODE,
            MARKET_VALUE_AMT, ELIGIBLE_VALUE_AMT, VALUATION_DATE,
            VALUATION_CURRENCY_CODE, ELIGIBILITY_FLAG, ELIGIBILITY_REASON_CODE, REGULATORY_HAIRCUT_PCT
        ) VALUES (
            C_OTHER_LOAD_ID, 'UT_COL_003', 'CASH', 'ACTIVE', 'EUR',
            10000.00, 10000.00, P_BUSINESS_DATE,
            'EUR', 'Y', 'ELIGIBLE', 0
        );
    END seed;

    PROCEDURE seed_ac_05 IS
    BEGIN
        -- AC-05 looks only at the parameter P_BUSINESS_DATE, never at data, and the
        -- test runs the load with the constant above, which is at midnight (seed must
        -- pass every guard). No rows can break this guard; the refusal in t_ac_05
        -- comes from AC-08, because the first run already stored the snapshot.
        NULL;
    END seed_ac_05;

    PROCEDURE seed_ac_06 IS
    BEGIN
        -- A staged item without currency (its identity row exists, so only AC-06 fires).
        INSERT INTO UBB_CORE2.COLLATERAL (COLLATERAL_ID, SOURCE_SYSTEM, COLLATERAL_REF)
        VALUES (999000004, 'CBS_SIM', 'UT_COL_004');
        INSERT INTO UBB_STAGING2.STG_COLLATERAL (
            LOAD_ID, COLLATERAL_REF, COLLATERAL_TYPE, COLLATERAL_STATUS, CURRENCY_CODE,
            MARKET_VALUE_AMT, ELIGIBLE_VALUE_AMT, VALUATION_DATE,
            VALUATION_CURRENCY_CODE, ELIGIBILITY_FLAG, ELIGIBILITY_REASON_CODE, REGULATORY_HAIRCUT_PCT
        ) VALUES (
            C_LOAD_ID, 'UT_COL_004', 'CASH', 'ACTIVE', NULL,
            5000.00, 5000.00, P_BUSINESS_DATE - 1,
            'EUR', 'Y', 'ELIGIBLE', 0
        );
    END seed_ac_06;

    PROCEDURE seed_ac_07 IS
    BEGIN
        -- A staged item with currency but without an identity row in UBB_CORE2.COLLATERAL.
        INSERT INTO UBB_STAGING2.STG_COLLATERAL (
            LOAD_ID, COLLATERAL_REF, COLLATERAL_TYPE, COLLATERAL_STATUS, CURRENCY_CODE,
            MARKET_VALUE_AMT, ELIGIBLE_VALUE_AMT, VALUATION_DATE,
            VALUATION_CURRENCY_CODE, ELIGIBILITY_FLAG, ELIGIBILITY_REASON_CODE, REGULATORY_HAIRCUT_PCT
        ) VALUES (
            C_LOAD_ID, 'UT_COL_005', 'CASH', 'ACTIVE', 'EUR',
            7500.00, 7500.00, P_BUSINESS_DATE - 1,
            'EUR', 'Y', 'ELIGIBLE', 0
        );
    END seed_ac_07;

    PROCEDURE seed_ac_08 IS
    BEGIN
        -- Nothing to add: the test loads the good data first, and that run stores
        -- COLLATERAL_HIST rows for C_LOAD_ID, which is exactly what AC-08 refuses.
        NULL;
    END seed_ac_08;

END UT_COLLATERAL_HIST_DATA;
/
