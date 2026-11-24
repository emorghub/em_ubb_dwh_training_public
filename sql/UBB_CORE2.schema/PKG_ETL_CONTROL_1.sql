--------------------------------------------------------
--  DDL for Package Body PKG_ETL_CONTROL
--------------------------------------------------------

  CREATE OR REPLACE EDITIONABLE PACKAGE BODY "UBB_CORE2"."PKG_ETL_CONTROL" AS
 FUNCTION find_source_load(
   p_source_system IN VARCHAR2,
   p_dataset_name IN VARCHAR2,
   p_business_date IN DATE
 ) RETURN NUMBER IS
   v_id NUMBER;
 BEGIN
   -- Require exactly one validated or completed authoritative load.
   -- A duplicate indicates unresolved rerun/supersession ambiguity.
   SELECT LOAD_ID INTO v_id
   FROM CTRL_LOAD
   WHERE SOURCE_SYSTEM = p_source_system
     AND DATASET_NAME = p_dataset_name
     AND BUSINESS_DATE = TRUNC(p_business_date)
     AND LOAD_STATUS IN ('VALIDATED','COMPLETED');
   RETURN v_id;
 EXCEPTION
   WHEN NO_DATA_FOUND THEN
     RAISE_APPLICATION_ERROR(-20011,'No validated source load for dataset/date');
   WHEN TOO_MANY_ROWS THEN
     RAISE_APPLICATION_ERROR(-20012,'Multiple eligible source loads; resolve supersession');
 END;

 PROCEDURE start_run(
   p_job_name IN VARCHAR2,
   p_business_date IN DATE,
   p_source_load_id IN NUMBER,
   p_run_id OUT NUMBER
 ) IS
   PRAGMA AUTONOMOUS_TRANSACTION;
   v_active CHAR(1);
   v_date DATE;
   v_status VARCHAR2(12);
   v_dataset VARCHAR2(30);
   v_source_dataset VARCHAR2(30);
   v_existing NUMBER;
 BEGIN
   SELECT IS_ACTIVE, DATASET_NAME INTO v_active,v_dataset
   FROM CTRL_JOB WHERE JOB_NAME = p_job_name;
   IF v_active <> 'Y' THEN
     RAISE_APPLICATION_ERROR(-20013,'Job is inactive');
   END IF;
   IF p_business_date IS NULL OR p_business_date <> TRUNC(p_business_date) THEN
     RAISE_APPLICATION_ERROR(-20014,'Business date must be midnight');
   END IF;
   IF p_source_load_id IS NOT NULL THEN
     SELECT BUSINESS_DATE,LOAD_STATUS,DATASET_NAME
       INTO v_date,v_status,v_source_dataset
       FROM CTRL_LOAD WHERE LOAD_ID=p_source_load_id;
     IF v_date <> p_business_date OR v_status NOT IN ('VALIDATED','COMPLETED')
       OR v_source_dataset <> v_dataset THEN
       RAISE_APPLICATION_ERROR(-20015,'Source load does not match job/date/status');
     END IF;
   ELSIF v_dataset <> 'DERIVED_EXPOSURE' THEN
     RAISE_APPLICATION_ERROR(-20016,'Source load required for staging jobs');
   END IF;
   SELECT COUNT(*) INTO v_existing FROM CTRL_JOB_RUN
     WHERE JOB_NAME=p_job_name AND BUSINESS_DATE=p_business_date
       AND RUN_STATUS='RUNNING';
   IF v_existing > 0 THEN
     RAISE_APPLICATION_ERROR(-20017,'A run is already marked RUNNING for job/date');
   END IF;
   p_run_id := SEQ_CTRL_JOB_RUN.NEXTVAL;
   INSERT INTO CTRL_JOB_RUN(RUN_ID,JOB_NAME,BUSINESS_DATE,SOURCE_LOAD_ID,RUN_STATUS)
   VALUES(p_run_id,p_job_name,p_business_date,p_source_load_id,'RUNNING');
   COMMIT;
 EXCEPTION
   WHEN OTHERS THEN ROLLBACK; RAISE;
 END;

 PROCEDURE log_message(
   p_run_id IN NUMBER,
   p_level IN VARCHAR2,
   p_message IN VARCHAR2
 ) IS
   PRAGMA AUTONOMOUS_TRANSACTION;
 BEGIN
   INSERT INTO CTRL_JOB_LOG(LOG_ID,RUN_ID,LOG_LEVEL,MESSAGE)
   VALUES(SEQ_CTRL_JOB_LOG.NEXTVAL,p_run_id,UPPER(p_level),SUBSTR(p_message,1,2000));
   COMMIT;
 EXCEPTION WHEN OTHERS THEN ROLLBACK; RAISE;
 END;

 PROCEDURE complete_run(
   p_run_id IN NUMBER,
   p_rows_read IN NUMBER,
   p_rows_written IN NUMBER
 ) IS
   PRAGMA AUTONOMOUS_TRANSACTION;
 BEGIN
   UPDATE CTRL_JOB_RUN
   SET RUN_STATUS='COMPLETED', FINISHED_AT=SYSTIMESTAMP,
       ROWS_READ=p_rows_read, ROWS_WRITTEN=p_rows_written
   WHERE RUN_ID=p_run_id AND RUN_STATUS='RUNNING';
   IF SQL%ROWCOUNT <> 1 THEN
     RAISE_APPLICATION_ERROR(-20018,'Run not RUNNING or does not exist');
   END IF;
   COMMIT;
 EXCEPTION WHEN OTHERS THEN ROLLBACK; RAISE;
 END;

 PROCEDURE fail_run(
   p_run_id IN NUMBER,
   p_error_message IN VARCHAR2
 ) IS
   PRAGMA AUTONOMOUS_TRANSACTION;
 BEGIN
   UPDATE CTRL_JOB_RUN
   SET RUN_STATUS='FAILED', FINISHED_AT=SYSTIMESTAMP,
       ERROR_MESSAGE=SUBSTR(p_error_message,1,2000)
   WHERE RUN_ID=p_run_id AND RUN_STATUS='RUNNING';
   IF SQL%ROWCOUNT <> 1 THEN
     RAISE_APPLICATION_ERROR(-20019,'Run not RUNNING or does not exist');
   END IF;
   COMMIT;
 EXCEPTION WHEN OTHERS THEN ROLLBACK; RAISE;
 END;
END PKG_ETL_CONTROL;
