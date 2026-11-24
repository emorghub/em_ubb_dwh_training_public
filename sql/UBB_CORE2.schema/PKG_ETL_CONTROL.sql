--------------------------------------------------------
--  DDL for Package PKG_ETL_CONTROL
--------------------------------------------------------

  CREATE OR REPLACE EDITIONABLE PACKAGE "UBB_CORE2"."PKG_ETL_CONTROL" AUTHID DEFINER AS
 FUNCTION find_source_load(
   p_source_system IN VARCHAR2,
   p_dataset_name IN VARCHAR2,
   p_business_date IN DATE
 ) RETURN NUMBER;
 PROCEDURE start_run(
   p_job_name IN VARCHAR2,
   p_business_date IN DATE,
   p_source_load_id IN NUMBER,
   p_run_id OUT NUMBER
 );
 PROCEDURE log_message(
   p_run_id IN NUMBER,
   p_level IN VARCHAR2,
   p_message IN VARCHAR2
 );
 PROCEDURE complete_run(
   p_run_id IN NUMBER,
   p_rows_read IN NUMBER,
   p_rows_written IN NUMBER
 );
 PROCEDURE fail_run(
   p_run_id IN NUMBER,
   p_error_message IN VARCHAR2
 );
END PKG_ETL_CONTROL;
