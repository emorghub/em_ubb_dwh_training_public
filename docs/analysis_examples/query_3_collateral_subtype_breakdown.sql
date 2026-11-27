-- Query 3: Multi-Subtype Collateral Valuation Breakdown (Polymorphic Joins & Subqueries)
SELECT 
    ch.load_id,
    cl.business_date,
    ch.collateral_type,
    COUNT(ch.collateral_id) AS total_collaterals,
    SUM(ch.market_value_amt) AS total_market_value,
    SUM(ch.eligible_value_amt) AS total_eligible_value,
    SUM(CASE WHEN re.collateral_id IS NOT NULL THEN re.appraised_value_amt ELSE 0 END) AS total_real_estate_appraised,
    SUM(CASE WHEN sec.collateral_id IS NOT NULL THEN (sec.quantity * sec.unit_market_price) ELSE 0 END) AS total_security_market_val,
    SUM(CASE WHEN g.collateral_id IS NOT NULL THEN g.guaranteed_amt ELSE 0 END) AS total_guaranteed_amt
FROM COLLATERAL_HIST ch
JOIN CTRL_LOAD cl 
  ON ch.load_id = cl.load_id
LEFT JOIN REAL_ESTATE_HIST re 
  ON ch.collateral_id = re.collateral_id 
 AND ch.load_id = re.load_id
LEFT JOIN SECURITY_COLLATERAL_HIST sec 
  ON ch.collateral_id = sec.collateral_id 
 AND ch.load_id = sec.load_id
LEFT JOIN GUARANTEE_HIST g 
  ON ch.collateral_id = g.collateral_id 
 AND ch.load_id = g.load_id
WHERE cl.business_date = DATE '2026-11-01'
  AND cl.load_status IN ('VALIDATED', 'COMPLETED')
GROUP BY 
    ch.load_id,
    cl.business_date,
    ch.collateral_type;
