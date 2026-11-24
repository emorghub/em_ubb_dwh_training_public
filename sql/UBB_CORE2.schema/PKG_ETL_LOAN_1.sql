--------------------------------------------------------
--  DDL for Package Body PKG_ETL_LOAN
--------------------------------------------------------

  CREATE OR REPLACE EDITIONABLE PACKAGE BODY "UBB_CORE2"."PKG_ETL_LOAN" AS
  PROCEDURE load_day(p_business_date IN DATE) IS
    v_load_id NUMBER(18);
    v_limit_load_id NUMBER(18);
    v_run_id NUMBER(18);
    v_rows_read NUMBER := 0;
    v_rows_written NUMBER := 0;
    v_existing NUMBER := 0;
    v_bad NUMBER := 0;
    v_new NUMBER := 0;
    v_committed BOOLEAN := FALSE;
    v_error VARCHAR2(4000);
  BEGIN
    IF p_business_date IS NULL OR p_business_date <> TRUNC(p_business_date) THEN
      RAISE_APPLICATION_ERROR(-20300, 'Business date must be at midnight');
    END IF;

    v_load_id := UBB_CORE2.PKG_ETL_CONTROL.find_source_load('CBS_SIM', 'LOAN', p_business_date);
    v_limit_load_id := UBB_CORE2.PKG_ETL_CONTROL.find_source_load('CBS_SIM', 'LIMIT', p_business_date);
    UBB_CORE2.PKG_ETL_CONTROL.start_run('LOAD_LOAN', p_business_date, v_load_id, v_run_id);

    SELECT COUNT(*) INTO v_rows_read
    FROM UBB_STAGING2.STG_LOAN WHERE LOAD_ID = v_load_id;

    SELECT COUNT(*) INTO v_bad FROM (
      SELECT LOAN_REF FROM UBB_STAGING2.STG_LOAN
      WHERE LOAD_ID = v_load_id
      GROUP BY LOAN_REF HAVING COUNT(*) > 1
    );
    IF v_bad > 0 THEN
      RAISE_APPLICATION_ERROR(-20301, 'Duplicate LOAN_REF in staging: ' || v_bad);
    END IF;

    SELECT COUNT(*) INTO v_bad
    FROM UBB_STAGING2.STG_LOAN s
    WHERE s.LOAD_ID = v_load_id
      AND (s.LOAN_REF IS NULL OR s.CBS_PARTNER_REF IS NULL
           OR s.CURRENCY_CODE IS NULL);
    IF v_bad > 0 THEN
      RAISE_APPLICATION_ERROR(-20302, 'Missing mandatory loan source fields: ' || v_bad);
    END IF;

    -- Resolve exactly one CRM Partner valid at the Loan business date.
    SELECT COUNT(*) INTO v_bad
    FROM UBB_STAGING2.STG_LOAN s
    WHERE s.LOAD_ID = v_load_id
      AND (SELECT COUNT(*)
           FROM UBB_CORE2.PARTNER_HIST ph
           JOIN UBB_CORE2.PARTNER p ON p.PARTNER_ID = ph.PARTNER_ID
           WHERE p.SOURCE_SYSTEM = 'CRM_SIM'
             AND ph.CBS_PARTNER_REF = s.CBS_PARTNER_REF
             AND ph.VALID_FROM <= p_business_date
             AND ph.VALID_TO > p_business_date) <> 1;
    IF v_bad > 0 THEN
      RAISE_APPLICATION_ERROR(-20303, 'Missing or ambiguous Partner references: ' || v_bad);
    END IF;

    -- Check that the corresponding Limit snapshot is already loaded.
    SELECT COUNT(*) INTO v_bad
    FROM UBB_CORE2.CTRL_JOB_RUN jr
    WHERE jr.JOB_NAME = 'LOAD_LIMIT'
      AND jr.SOURCE_LOAD_ID = v_limit_load_id
      AND jr.RUN_STATUS = 'COMPLETED';
    IF v_bad = 0 THEN
      RAISE_APPLICATION_ERROR(-20304, 'Credit Limit snapshot ETL not completed for business date');
    END IF;

    -- Validate Limit reference and its Partner association for this date.
    -- A NULL LIMIT_REF is accepted only if LOAN_HIST.LIMIT_ID is nullable.
    SELECT COUNT(*) INTO v_bad
    FROM UBB_STAGING2.STG_LOAN s
    WHERE s.LOAD_ID = v_load_id
      AND s.LIMIT_REF IS NOT NULL
      AND (SELECT COUNT(*)
           FROM UBB_CORE2.CREDIT_LIMIT lim
           JOIN UBB_CORE2.LIMIT_HIST lh
             ON lh.LIMIT_ID = lim.LIMIT_ID AND lh.LOAD_ID = v_limit_load_id
           JOIN UBB_CORE2.PARTNER_HIST ph
             ON ph.PARTNER_ID = lh.PARTNER_ID
            AND ph.VALID_FROM <= p_business_date AND ph.VALID_TO > p_business_date
           JOIN UBB_CORE2.PARTNER p
             ON p.PARTNER_ID = ph.PARTNER_ID AND p.SOURCE_SYSTEM = 'CRM_SIM'
           WHERE lim.SOURCE_SYSTEM = 'CBS_SIM'
             AND lim.LIMIT_REF = s.LIMIT_REF
             AND ph.CBS_PARTNER_REF = s.CBS_PARTNER_REF) <> 1;
    IF v_bad > 0 THEN
      RAISE_APPLICATION_ERROR(-20305, 'Missing, ambiguous or Partner-mismatched Credit Limits: ' || v_bad);
    END IF;

    -- Existing snapshot is immutable: do not overwrite it on a rerun.
    SELECT COUNT(*) INTO v_existing
    FROM UBB_CORE2.LOAN_HIST WHERE LOAD_ID = v_load_id;
    IF v_existing > 0 THEN
      IF v_existing <> v_rows_read THEN
        RAISE_APPLICATION_ERROR(-20306, 'Partial Loan snapshot exists; manual recovery required');
      END IF;
      UBB_CORE2.PKG_ETL_CONTROL.log_message(v_run_id, 'INFO',
        'Loan snapshot already exists; no business rows changed');
      UBB_CORE2.PKG_ETL_CONTROL.complete_run(v_run_id, v_rows_read, 0);
      RETURN;
    END IF;

    MERGE INTO UBB_CORE2.LOAN t
    USING (SELECT DISTINCT LOAN_REF FROM UBB_STAGING2.STG_LOAN
           WHERE LOAD_ID = v_load_id) s
    ON (t.SOURCE_SYSTEM = 'CBS_SIM' AND t.LOAN_REF = s.LOAN_REF)
    WHEN NOT MATCHED THEN
      INSERT (LOAN_ID, SOURCE_SYSTEM, LOAN_REF)
      VALUES (UBB_CORE2.SEQ_LOAN.NEXTVAL, 'CBS_SIM', s.LOAN_REF);
    v_new := SQL%ROWCOUNT;
    v_rows_written := v_new;

    INSERT INTO UBB_CORE2.LOAN_HIST (
      LOAN_ID, LOAD_ID, PARTNER_ID, LIMIT_ID,
      LOAN_TYPE, LOAN_STATUS, CURRENCY_CODE,
      PRINCIPAL_AMT, UNDRAWN_AMT, OVERDUE_AMT, INTEREST_RATE,
      START_DATE, MATURITY_DATE
    )
    SELECT l.LOAN_ID, v_load_id, ph.PARTNER_ID, lim.LIMIT_ID,
           s.LOAN_TYPE, s.LOAN_STATUS, s.CURRENCY_CODE,
           s.PRINCIPAL_AMT, s.UNDRAWN_AMT, s.OVERDUE_AMT, s.INTEREST_RATE,
           s.START_DATE, s.MATURITY_DATE
    FROM UBB_STAGING2.STG_LOAN s
    JOIN UBB_CORE2.LOAN l
      ON l.SOURCE_SYSTEM = 'CBS_SIM' AND l.LOAN_REF = s.LOAN_REF
    JOIN UBB_CORE2.PARTNER_HIST ph
      ON ph.CBS_PARTNER_REF = s.CBS_PARTNER_REF
     AND ph.VALID_FROM <= p_business_date AND ph.VALID_TO > p_business_date
    JOIN UBB_CORE2.PARTNER p
      ON p.PARTNER_ID = ph.PARTNER_ID AND p.SOURCE_SYSTEM = 'CRM_SIM'
    LEFT JOIN UBB_CORE2.CREDIT_LIMIT lim
      ON lim.SOURCE_SYSTEM = 'CBS_SIM' AND lim.LIMIT_REF = s.LIMIT_REF
    LEFT JOIN UBB_CORE2.LIMIT_HIST lh
      ON lh.LIMIT_ID = lim.LIMIT_ID AND lh.LOAD_ID = v_limit_load_id
    WHERE s.LOAD_ID = v_load_id
      AND (s.LIMIT_REF IS NULL OR
           (lh.LIMIT_ID IS NOT NULL AND lh.PARTNER_ID = ph.PARTNER_ID));
    v_bad := SQL%ROWCOUNT;
    IF v_bad <> v_rows_read THEN
      RAISE_APPLICATION_ERROR(-20307, 'Loan insert count differs from staging count');
    END IF;
    v_rows_written := v_rows_written + v_bad;

    COMMIT;
    v_committed := TRUE;
    UBB_CORE2.PKG_ETL_CONTROL.complete_run(v_run_id, v_rows_read, v_rows_written);
    DBMS_OUTPUT.PUT_LINE('LOAN ' || TO_CHAR(p_business_date, 'YYYY-MM-DD') ||
      ' load_id=' || v_load_id || ' read=' || v_rows_read ||
      ' written=' || v_rows_written);
  EXCEPTION WHEN OTHERS THEN
    v_error := SQLERRM;
    IF NOT v_committed THEN ROLLBACK; END IF;
    IF v_run_id IS NOT NULL THEN
      BEGIN
        UBB_CORE2.PKG_ETL_CONTROL.fail_run(v_run_id, v_error);
      EXCEPTION WHEN OTHERS THEN NULL;
      END;
    END IF;
    RAISE;
  END load_day;
END PKG_ETL_LOAN;
