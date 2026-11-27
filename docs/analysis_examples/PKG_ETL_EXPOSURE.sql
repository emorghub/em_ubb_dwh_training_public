-- DEMONSTRATION ONLY: this is an analysis fixture, not an exported schema
-- script and not deployment-ready. It is intentionally outside sql/ and specs/.
--
-- Candidate assumptions to discuss, not approved business rules:
--   * CCF is 50%.
--   * ECB direct FX rates are used for the business date.
--   * ALLOCATED_VALUE_AMT is already eligible after allocation/haircuts.
--   * All three input load IDs refer to the requested business date.
--   * The caller resolves the authoritative collateral and FX load IDs.
--   * All loans in the chosen LOAN_HIST snapshot are included.
--
-- The scheduler creates the DERIVED_EXPOSURE CTRL_LOAD row in STARTED state
-- and calls PKG_ETL_CONTROL.START_RUN with a NULL source-load ID before
-- invoking LOAD_DAY. The caller commits on success, then completes the run.
-- On failure it rolls back, records the output load as FAILED separately,
-- and calls PKG_ETL_CONTROL.FAIL_RUN. This package never commits or rolls back.

CREATE OR REPLACE EDITIONABLE PACKAGE "UBB_CORE2"."PKG_ETL_EXPOSURE" AUTHID DEFINER AS
    PROCEDURE load_day(
        p_business_date      IN DATE,
        p_loan_load_id       IN NUMBER,
        p_collateral_load_id IN NUMBER,
        p_fx_load_id         IN NUMBER,
        p_exposure_load_id   IN NUMBER,
        p_rows_read          OUT NUMBER,
        p_rows_written       OUT NUMBER
    );
END PKG_ETL_EXPOSURE;
/

CREATE OR REPLACE EDITIONABLE PACKAGE BODY "UBB_CORE2"."PKG_ETL_EXPOSURE" AS
    c_demo_ccf       CONSTANT NUMBER := 0.50;
    c_demo_rate_type CONSTANT VARCHAR2(20) := 'ECB';

    PROCEDURE assert_input_load(
        p_load_id          IN NUMBER,
        p_business_date    IN DATE,
        p_label            IN VARCHAR2,
        p_expected_source  IN VARCHAR2 DEFAULT NULL,
        p_expected_dataset IN VARCHAR2 DEFAULT NULL
    ) IS
        v_matches NUMBER;
    BEGIN
        SELECT COUNT(*)
          INTO v_matches
          FROM UBB_CORE2.CTRL_LOAD
         WHERE LOAD_ID = p_load_id
           AND BUSINESS_DATE = p_business_date
           AND LOAD_STATUS IN ('VALIDATED', 'COMPLETED')
           AND (p_expected_source IS NULL OR SOURCE_SYSTEM = p_expected_source)
           AND (p_expected_dataset IS NULL OR DATASET_NAME = p_expected_dataset);

        IF v_matches <> 1 THEN
            RAISE_APPLICATION_ERROR(
                -20401,
                p_label || ' load is missing, not complete, or has the wrong date/source'
            );
        END IF;
    END assert_input_load;

    PROCEDURE assert_output_load(
        p_load_id       IN NUMBER,
        p_business_date IN DATE
    ) IS
        v_matches NUMBER;
    BEGIN
        SELECT COUNT(*)
          INTO v_matches
          FROM UBB_CORE2.CTRL_LOAD
         WHERE LOAD_ID = p_load_id
           AND SOURCE_SYSTEM = 'INTERNAL'
           AND DATASET_NAME = 'DERIVED_EXPOSURE'
           AND BUSINESS_DATE = p_business_date
           AND LOAD_STATUS = 'STARTED';

        IF v_matches <> 1 THEN
            RAISE_APPLICATION_ERROR(
                -20402,
                'Expected one STARTED DERIVED_EXPOSURE output load for the business date'
            );
        END IF;
    END assert_output_load;

    PROCEDURE load_day(
        p_business_date      IN DATE,
        p_loan_load_id       IN NUMBER,
        p_collateral_load_id IN NUMBER,
        p_fx_load_id         IN NUMBER,
        p_exposure_load_id   IN NUMBER,
        p_rows_read          OUT NUMBER,
        p_rows_written       OUT NUMBER
    ) IS
        v_loan_rows       NUMBER := 0;
        v_identity_rows   NUMBER := 0;
        v_exposure_rows   NUMBER := 0;
        v_existing_rows   NUMBER := 0;
        v_bad_allocations NUMBER := 0;
        v_orphan_allocs   NUMBER := 0;
        v_missing_fx      NUMBER := 0;
    BEGIN
        p_rows_read := 0;
        p_rows_written := 0;

        IF p_business_date IS NULL OR p_business_date <> TRUNC(p_business_date) THEN
            RAISE_APPLICATION_ERROR(-20400, 'Business date must be at midnight');
        END IF;

        assert_input_load(
            p_loan_load_id, p_business_date, 'Loan', 'CBS_SIM', 'LOAN'
        );

        -- Source-system and dataset identifiers for these two loads must be
        -- confirmed from the operating process before this fixture is adapted.
        assert_input_load(
            p_collateral_load_id, p_business_date, 'Collateral allocation'
        );
        assert_input_load(
            p_fx_load_id, p_business_date, 'FX rate'
        );
        assert_output_load(p_exposure_load_id, p_business_date);

        SELECT COUNT(*)
          INTO v_existing_rows
          FROM UBB_CORE2.EXPOSURE_HIST
         WHERE LOAD_ID = p_exposure_load_id;

        IF v_existing_rows > 0 THEN
            RAISE_APPLICATION_ERROR(
                -20403,
                'Output load already has exposure rows; snapshots are immutable'
            );
        END IF;

        SELECT COUNT(*)
          INTO v_bad_allocations
          FROM UBB_CORE2.LOAN_COLLATERAL_REL_HIST
         WHERE LOAD_ID = p_collateral_load_id
           AND RELATION_STATUS = 'ACTIVE'
           AND (ALLOCATED_VALUE_AMT IS NULL OR ALLOCATION_CURRENCY_CODE IS NULL);

        IF v_bad_allocations > 0 THEN
            RAISE_APPLICATION_ERROR(
                -20404,
                'Active collateral allocations have a missing amount or currency'
            );
        END IF;

        SELECT COUNT(*)
          INTO v_orphan_allocs
          FROM UBB_CORE2.LOAN_COLLATERAL_REL_HIST lcr
         WHERE lcr.LOAD_ID = p_collateral_load_id
           AND lcr.RELATION_STATUS = 'ACTIVE'
           AND NOT EXISTS (
               SELECT 1
                 FROM UBB_CORE2.LOAN_HIST lh
                WHERE lh.LOAD_ID = p_loan_load_id
                  AND lh.LOAN_ID = lcr.LOAN_ID
           );

        IF v_orphan_allocs > 0 THEN
            RAISE_APPLICATION_ERROR(
                -20405,
                'Collateral allocations reference loans outside the selected loan snapshot'
            );
        END IF;

        SELECT COUNT(*)
          INTO v_missing_fx
          FROM (
              SELECT DISTINCT lcr.ALLOCATION_CURRENCY_CODE AS FROM_CCY,
                              lh.CURRENCY_CODE AS TO_CCY
                FROM UBB_CORE2.LOAN_COLLATERAL_REL_HIST lcr
                JOIN UBB_CORE2.LOAN_HIST lh
                  ON lh.LOAD_ID = p_loan_load_id
                 AND lh.LOAN_ID = lcr.LOAN_ID
               WHERE lcr.LOAD_ID = p_collateral_load_id
                 AND lcr.RELATION_STATUS = 'ACTIVE'
                 AND lcr.ALLOCATION_CURRENCY_CODE <> lh.CURRENCY_CODE
          ) currency_pairs
         WHERE NOT EXISTS (
             SELECT 1
               FROM UBB_CORE2.FX_RATE fx
              WHERE fx.LOAD_ID = p_fx_load_id
                AND fx.RATE_DATE = p_business_date
                AND fx.RATE_TYPE = c_demo_rate_type
                AND fx.FROM_CURRENCY_CODE = currency_pairs.FROM_CCY
                AND fx.TO_CURRENCY_CODE = currency_pairs.TO_CCY
         );

        IF v_missing_fx > 0 THEN
            RAISE_APPLICATION_ERROR(
                -20406,
                'A direct FX rate is missing for one or more active collateral currency pairs'
            );
        END IF;

        SELECT COUNT(*)
          INTO v_loan_rows
          FROM UBB_CORE2.LOAN_HIST
         WHERE LOAD_ID = p_loan_load_id;

        MERGE INTO UBB_CORE2.EXPOSURE e
        USING (
            SELECT lh.LOAN_ID, l.LOAN_REF
              FROM UBB_CORE2.LOAN_HIST lh
              JOIN UBB_CORE2.LOAN l
                ON l.LOAN_ID = lh.LOAN_ID
               AND l.SOURCE_SYSTEM = 'CBS_SIM'
             WHERE lh.LOAD_ID = p_loan_load_id
        ) source_rows
           ON (e.LOAN_ID = source_rows.LOAN_ID)
        WHEN NOT MATCHED THEN
            INSERT (EXPOSURE_ID, SOURCE_SYSTEM, EXPOSURE_REF, LOAN_ID)
            VALUES (
                UBB_CORE2.SEQ_EXPOSURE.NEXTVAL,
                'CBS_SIM',
                source_rows.LOAN_REF,
                source_rows.LOAN_ID
            );

        v_identity_rows := SQL%ROWCOUNT;

        INSERT INTO UBB_CORE2.EXPOSURE_HIST (
            EXPOSURE_ID,
            LOAD_ID,
            LOAN_ID,
            LIMIT_ID,
            PARTNER_ID,
            CURRENCY_CODE,
            OUTSTANDING_AMT,
            UNDRAWN_AMT,
            GROSS_EXPOSURE_AMT,
            ELIGIBLE_COLLATERAL_AMT,
            NET_EXPOSURE_AMT,
            CALC_RULE_VERSION
        )
        WITH loan_snapshot AS (
            SELECT lh.LOAN_ID,
                   lh.LIMIT_ID,
                   lh.PARTNER_ID,
                   lh.CURRENCY_CODE,
                   lh.PRINCIPAL_AMT,
                   lh.UNDRAWN_AMT
              FROM UBB_CORE2.LOAN_HIST lh
             WHERE lh.LOAD_ID = p_loan_load_id
        ),
        collateral_by_loan AS (
            SELECT lcr.LOAN_ID,
                   SUM(
                       CASE
                           WHEN lcr.ALLOCATION_CURRENCY_CODE = ls.CURRENCY_CODE
                               THEN lcr.ALLOCATED_VALUE_AMT
                           ELSE lcr.ALLOCATED_VALUE_AMT * fx.EXCHANGE_RATE
                       END
                   ) AS ELIGIBLE_COLLATERAL_AMT
              FROM UBB_CORE2.LOAN_COLLATERAL_REL_HIST lcr
              JOIN loan_snapshot ls
                ON ls.LOAN_ID = lcr.LOAN_ID
              LEFT JOIN UBB_CORE2.FX_RATE fx
                ON fx.LOAD_ID = p_fx_load_id
               AND fx.RATE_DATE = p_business_date
               AND fx.RATE_TYPE = c_demo_rate_type
               AND fx.FROM_CURRENCY_CODE = lcr.ALLOCATION_CURRENCY_CODE
               AND fx.TO_CURRENCY_CODE = ls.CURRENCY_CODE
             WHERE lcr.LOAD_ID = p_collateral_load_id
               AND lcr.RELATION_STATUS = 'ACTIVE'
             GROUP BY lcr.LOAN_ID
        )
        SELECT e.EXPOSURE_ID,
               p_exposure_load_id,
               ls.LOAN_ID,
               ls.LIMIT_ID,
               ls.PARTNER_ID,
               ls.CURRENCY_CODE,
               ls.PRINCIPAL_AMT,
               ls.UNDRAWN_AMT,
               ls.PRINCIPAL_AMT + (ls.UNDRAWN_AMT * c_demo_ccf),
               NVL(cb.ELIGIBLE_COLLATERAL_AMT, 0),
               GREATEST(
                   0,
                   ls.PRINCIPAL_AMT + (ls.UNDRAWN_AMT * c_demo_ccf)
                       - NVL(cb.ELIGIBLE_COLLATERAL_AMT, 0)
               ),
               'DEMO_CCF_50_ECB'
          FROM loan_snapshot ls
          JOIN UBB_CORE2.EXPOSURE e
            ON e.LOAN_ID = ls.LOAN_ID
          LEFT JOIN collateral_by_loan cb
            ON cb.LOAN_ID = ls.LOAN_ID;

        v_exposure_rows := SQL%ROWCOUNT;
        p_rows_read := v_loan_rows;
        p_rows_written := v_identity_rows + v_exposure_rows;

        UPDATE UBB_CORE2.CTRL_LOAD
           SET LOAD_STATUS = 'COMPLETED',
               FINISHED_AT = SYSTIMESTAMP,
               SOURCE_ROW_COUNT = v_loan_rows,
               TARGET_ROW_COUNT = v_exposure_rows
         WHERE LOAD_ID = p_exposure_load_id
           AND LOAD_STATUS = 'STARTED';

        IF SQL%ROWCOUNT <> 1 THEN
            RAISE_APPLICATION_ERROR(
                -20407,
                'Output load was not STARTED or no longer exists'
            );
        END IF;
    END load_day;
END PKG_ETL_EXPOSURE;
/
