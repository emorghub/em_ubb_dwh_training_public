--------------------------------------------------------
--  DDL for Package Body PKG_ETL_LIMIT
--------------------------------------------------------

  CREATE OR REPLACE EDITIONABLE PACKAGE BODY "UBB_CORE2"."PKG_ETL_LIMIT" AS
  PROCEDURE load_day(p_business_date IN DATE) IS
    v_load_id NUMBER(18);
    v_run_id NUMBER(18);
    v_read NUMBER := 0;
    v_written NUMBER := 0;
    v_bad NUMBER;
    v_committed BOOLEAN := FALSE;
  BEGIN
    IF p_business_date IS NULL OR p_business_date <> TRUNC(p_business_date) THEN
      RAISE_APPLICATION_ERROR(-20200,'Business date must be midnight');
    END IF;
    v_load_id := PKG_ETL_CONTROL.find_source_load('CBS_SIM','LIMIT',p_business_date);
    PKG_ETL_CONTROL.start_run('LOAD_LIMIT',p_business_date,v_load_id,v_run_id);
    SELECT COUNT(*) INTO v_read FROM UBB_STAGING2.STG_LIMIT WHERE LOAD_ID=v_load_id;

    -- A snapshot may not have duplicate source business keys.
    SELECT COUNT(*) INTO v_bad FROM (
      SELECT LIMIT_REF FROM UBB_STAGING2.STG_LIMIT
      WHERE LOAD_ID=v_load_id GROUP BY LIMIT_REF HAVING COUNT(*)>1
    );
    IF v_bad>0 THEN RAISE_APPLICATION_ERROR(-20201,'Duplicate LIMIT_REF in source load'); END IF;
    SELECT COUNT(*) INTO v_bad FROM UBB_STAGING2.STG_LIMIT
      WHERE LOAD_ID=v_load_id AND (LIMIT_REF IS NULL OR CBS_PARTNER_REF IS NULL
                                   OR CURRENCY_CODE IS NULL);
    IF v_bad>0 THEN RAISE_APPLICATION_ERROR(-20202,'Mandatory source fields missing'); END IF;

    -- Every CBS reference must match exactly one CRM partner version valid on business date.
    SELECT COUNT(*) INTO v_bad
    FROM UBB_STAGING2.STG_LIMIT s
    WHERE s.LOAD_ID=v_load_id AND (
      SELECT COUNT(*)
      FROM UBB_CORE2.PARTNER_HIST ph
      JOIN UBB_CORE2.PARTNER p ON p.PARTNER_ID=ph.PARTNER_ID
      WHERE p.SOURCE_SYSTEM='CRM_SIM'
        AND ph.CBS_PARTNER_REF=s.CBS_PARTNER_REF
        AND ph.VALID_FROM<=p_business_date AND ph.VALID_TO>p_business_date
    ) <> 1;
    IF v_bad>0 THEN
      RAISE_APPLICATION_ERROR(-20203,
        'CBS partner reference missing or ambiguous for '||v_bad||' limit rows');
    END IF;

    -- Resolve identities with a set-based MERGE.
    MERGE INTO UBB_CORE2.CREDIT_LIMIT t
    USING (
      SELECT DISTINCT LIMIT_REF FROM UBB_STAGING2.STG_LIMIT WHERE LOAD_ID=v_load_id
    ) s
    ON (t.SOURCE_SYSTEM='CBS_SIM' AND t.LIMIT_REF=s.LIMIT_REF)
    WHEN NOT MATCHED THEN
      INSERT (LIMIT_ID,SOURCE_SYSTEM,LIMIT_REF)
      VALUES (UBB_CORE2.SEQ_CREDIT_LIMIT.NEXTVAL,'CBS_SIM',s.LIMIT_REF);
    v_written := SQL%ROWCOUNT;

    -- Idempotency: reject partial existing snapshot; skip an already complete snapshot.
    SELECT COUNT(*) INTO v_bad FROM UBB_CORE2.LIMIT_HIST WHERE LOAD_ID=v_load_id;
    IF v_bad > 0 THEN
      IF v_bad <> v_read THEN
        RAISE_APPLICATION_ERROR(-20205,'Partial existing snapshot; manual recovery required');
      END IF;
      -- Do not overwrite published history on a rerun.
      COMMIT;
      v_committed := TRUE;
      PKG_ETL_CONTROL.complete_run(v_run_id,v_read,v_written);
      RETURN;
    END IF;

    INSERT INTO UBB_CORE2.LIMIT_HIST (
      LIMIT_ID,LOAD_ID,PARTNER_ID,LIMIT_TYPE,LIMIT_STATUS,CURRENCY_CODE,
      APPROVED_AMT,UTILIZED_AMT,VALID_FROM,VALID_TO
    )
    SELECT l.LIMIT_ID,v_load_id,ph.PARTNER_ID,
           s.LIMIT_TYPE,s.LIMIT_STATUS,s.CURRENCY_CODE,
           s.APPROVED_AMT,s.UTILIZED_AMT,s.VALID_FROM,s.VALID_TO
    FROM UBB_STAGING2.STG_LIMIT s
    JOIN UBB_CORE2.CREDIT_LIMIT l
      ON l.SOURCE_SYSTEM='CBS_SIM' AND l.LIMIT_REF=s.LIMIT_REF
    JOIN UBB_CORE2.PARTNER_HIST ph
      ON ph.CBS_PARTNER_REF=s.CBS_PARTNER_REF
     AND ph.VALID_FROM<=p_business_date AND ph.VALID_TO>p_business_date
    JOIN UBB_CORE2.PARTNER p
      ON p.PARTNER_ID=ph.PARTNER_ID AND p.SOURCE_SYSTEM='CRM_SIM'
    WHERE s.LOAD_ID=v_load_id;
    IF SQL%ROWCOUNT <> v_read THEN
      RAISE_APPLICATION_ERROR(-20204,'Inserted rows differ from source rows');
    END IF;
    v_written := v_written + SQL%ROWCOUNT;
    COMMIT;
    v_committed := TRUE;
    PKG_ETL_CONTROL.complete_run(v_run_id,v_read,v_written);
    DBMS_OUTPUT.PUT_LINE('LIMIT '||TO_CHAR(p_business_date,'YYYY-MM-DD')||
      ' read='||v_read||' written='||v_written||' load='||v_load_id);
  EXCEPTION WHEN OTHERS THEN
    IF NOT v_committed THEN ROLLBACK; END IF;
    IF v_run_id IS NOT NULL THEN
      DECLARE v_error VARCHAR2(4000) := SQLERRM;
      BEGIN PKG_ETL_CONTROL.fail_run(v_run_id,v_error);
      EXCEPTION WHEN OTHERS THEN NULL;
      END;
    END IF;
    RAISE;
  END load_day;
END PKG_ETL_LIMIT;
