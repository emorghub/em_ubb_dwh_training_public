-- Query 4: ETL Audit & Staging Reconciliation (Anti-Join & Operational Metadata)
SELECT 
    sl.load_id,
    cl.business_date,
    sl.loan_ref,
    sl.cbs_partner_ref,
    sl.principal_amt,
    cjr.job_name,
    cjr.run_status,
    cjr.error_message AS run_error,
    cjl.log_level,
    cjl.message AS log_message
FROM STG_LOAN sl
JOIN CTRL_LOAD cl 
  ON sl.load_id = cl.load_id
LEFT JOIN CTRL_JOB_RUN cjr 
  ON cl.load_id = cjr.source_load_id
LEFT JOIN CTRL_JOB_LOG cjl 
  ON cjr.run_id = cjl.run_id 
 AND cjl.log_level = 'ERROR'
WHERE cl.business_date >= TRUNC(SYSDATE) - 7
  AND NOT EXISTS (
      SELECT 1 
      FROM LOAN_HIST lh
      JOIN LOAN l ON lh.loan_id = l.loan_id
      WHERE l.loan_ref = sl.loan_ref
        AND lh.load_id = sl.load_id
  );
