-- ===========================================================================
-- GENERATED from mapping M_COLLATERAL (specs/collateral/M_COLLATERAL.xlsx)
--   by tools/codegen/generate.py on 2026-11-27
--   mapping fingerprint 35a96c007d483467, approved by Emil Angelov on 2026-11-27
-- Change the mapping workbook and regenerate - do not hand-edit this file.
-- ===========================================================================
--
-- Load package for UBB_CORE2.COLLATERAL_HIST.
-- Conventions (see tools/codegen/templates/README.md to change them):
--   * No COMMIT inside the procedure: the caller owns the transaction (the
--     scheduler job or the developer's session commits after the call). That is also
--     what lets the utPLSQL tests roll back everything a test did.
--   * All or nothing: the procedure sets its own savepoint first and, on any
--     error, rolls back to it (never the caller's earlier work) and re-raises.
--     A failed run leaves COLLATERAL_HIST exactly as it was - never a partial snapshot.
--   * Every parameter is mandatory; a NULL raises ORA-20001.
--   * Load strategy: append - every run only inserts; re-running the same parameters fails on the primary key
--   * Guards (AC-05, AC-06, AC-07, AC-08): checked before anything is written; one
--     that finds source rows stops the run with ORA-20005.
--   * Errors are raised, not logged here: the caller logs them (for example
--     with PKG_ETL_CONTROL.fail_run) - see tools/codegen/templates/README.md.

CREATE OR REPLACE PACKAGE UBB_CORE2.PKG_ETL_COLLATERAL AUTHID DEFINER AS
    -- Mapping M_COLLATERAL (fingerprint 35a96c007d483467)
    -- Load the daily collateral snapshot with valuation, currency of the valuation, eligibility and regulatory haircut, so collateral can be recognised as protection 

    -- Raised (ORA-20005) when a guard finds source rows; nothing was written.
    e_guard_failed EXCEPTION;
    PRAGMA EXCEPTION_INIT(e_guard_failed, -20005);

    PROCEDURE LOAD_DAY (
        P_BUSINESS_DATE IN DATE
    );
END PKG_ETL_COLLATERAL;
/

CREATE OR REPLACE PACKAGE BODY UBB_CORE2.PKG_ETL_COLLATERAL AS

    -- The mapping's guards: source rows that must stop the run. Checked before
    -- anything is written, so a refused run changes nothing.
    PROCEDURE check_guards(P_BUSINESS_DATE IN DATE) IS
        l_violations INTEGER;
    BEGIN
        -- AC-05: Reject a reporting date that is not at midnight.
        SELECT COUNT(*) INTO l_violations FROM (
            SELECT 1 FROM DUAL WHERE P_BUSINESS_DATE <> TRUNC(P_BUSINESS_DATE)
        );
        IF l_violations > 0 THEN
            RAISE_APPLICATION_ERROR(-20005, 'LOAD_DAY: guard AC-05 found '
                || l_violations || ' row(s) for ' || 'P_BUSINESS_DATE=' || TO_CHAR(P_BUSINESS_DATE, 'YYYY-MM-DD')
                || ' - Reject a reporting date that is not at midnight.');
        END IF;
        -- AC-06: Reject a staged collateral item without currency.
        SELECT COUNT(*) INTO l_violations FROM (
            SELECT s.COLLATERAL_REF FROM UBB_STAGING2.STG_COLLATERAL s WHERE s.LOAD_ID = UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD('CBS_SIM', 'COLLATERAL', P_BUSINESS_DATE) AND s.CURRENCY_CODE IS NULL
        );
        IF l_violations > 0 THEN
            RAISE_APPLICATION_ERROR(-20005, 'LOAD_DAY: guard AC-06 found '
                || l_violations || ' row(s) for ' || 'P_BUSINESS_DATE=' || TO_CHAR(P_BUSINESS_DATE, 'YYYY-MM-DD')
                || ' - Reject a staged collateral item without currency.');
        END IF;
        -- AC-07: Reject a staged collateral item that has no identity row in UBB_CORE2.COLLATERAL.
        SELECT COUNT(*) INTO l_violations FROM (
            SELECT s.COLLATERAL_REF FROM UBB_STAGING2.STG_COLLATERAL s WHERE s.LOAD_ID = UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD('CBS_SIM', 'COLLATERAL', P_BUSINESS_DATE) AND NOT EXISTS (SELECT 1 FROM UBB_CORE2.COLLATERAL c WHERE c.SOURCE_SYSTEM = 'CBS_SIM' AND c.COLLATERAL_REF = s.COLLATERAL_REF)
        );
        IF l_violations > 0 THEN
            RAISE_APPLICATION_ERROR(-20005, 'LOAD_DAY: guard AC-07 found '
                || l_violations || ' row(s) for ' || 'P_BUSINESS_DATE=' || TO_CHAR(P_BUSINESS_DATE, 'YYYY-MM-DD')
                || ' - Reject a staged collateral item that has no identity row in UBB_CORE2.COLLATERAL.');
        END IF;
        -- AC-08: Reject a run when collateral history rows already exist for the selected source load.
        SELECT COUNT(*) INTO l_violations FROM (
            SELECT h.LOAD_ID FROM UBB_CORE2.COLLATERAL_HIST h WHERE h.LOAD_ID = UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD('CBS_SIM', 'COLLATERAL', P_BUSINESS_DATE) GROUP BY h.LOAD_ID
        );
        IF l_violations > 0 THEN
            RAISE_APPLICATION_ERROR(-20005, 'LOAD_DAY: guard AC-08 found '
                || l_violations || ' row(s) for ' || 'P_BUSINESS_DATE=' || TO_CHAR(P_BUSINESS_DATE, 'YYYY-MM-DD')
                || ' - Reject a run when collateral history rows already exist for the selected source load.');
        END IF;
    END check_guards;

    PROCEDURE LOAD_DAY (
        P_BUSINESS_DATE IN DATE
    ) IS
    BEGIN
        SAVEPOINT SP_PKG_ETL_COLLATERAL;
        DBMS_APPLICATION_INFO.SET_MODULE('PKG_ETL_COLLATERAL', 'LOAD_DAY');
        IF P_BUSINESS_DATE IS NULL THEN
            RAISE_APPLICATION_ERROR(-20001, 'LOAD_DAY: P_BUSINESS_DATE must not be NULL');
        END IF;

        -- Refuse the source before writing anything.
        check_guards(P_BUSINESS_DATE);

        -- Insert only. Running the same parameters twice fails on the primary key.
        INSERT INTO UBB_CORE2.COLLATERAL_HIST (
            COLLATERAL_ID,
            LOAD_ID,
            LOAN_ID,
            COLLATERAL_TYPE,
            COLLATERAL_STATUS,
            CURRENCY_CODE,
            MARKET_VALUE_AMT,
            ELIGIBLE_VALUE_AMT,
            VALUATION_DATE,
            CREATED_AT,
            VALUATION_CURRENCY_CODE,
            ELIGIBILITY_FLAG,
            ELIGIBILITY_REASON_CODE,
            REGULATORY_HAIRCUT_PCT
        )
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
        WHERE STG_COLLATERAL.LOAD_ID = "UBB_CORE2"."PKG_ETL_CONTROL"."FIND_SOURCE_LOAD"('CBS_SIM', 'COLLATERAL', P_BUSINESS_DATE);

        DBMS_APPLICATION_INFO.SET_MODULE(NULL, NULL);
    EXCEPTION
        WHEN OTHERS THEN
            -- Undo this run's own work only; the caller's transaction stays open.
            ROLLBACK TO SAVEPOINT SP_PKG_ETL_COLLATERAL;
            DBMS_APPLICATION_INFO.SET_MODULE(NULL, NULL);
            RAISE;
    END LOAD_DAY;

END PKG_ETL_COLLATERAL;
/
