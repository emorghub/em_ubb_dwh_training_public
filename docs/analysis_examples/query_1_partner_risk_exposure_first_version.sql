-- Query 1: Partner Risk Exposure & Collateral Coverage (SCD2 Point-in-Time Join + Aggregation)
-- Corrected version of the first draft. Fixes:
--  1. Snapshot tables (LOAN_HIST, LIMIT_HIST, LOAN_COLLATERAL_REL_HIST) are loaded by different
--     datasets, so each has its own LOAD_ID: the old join lh.load_id = lim.load_id / lcr.load_id
--     never matched. Each table is now filtered by the authoritative load of the business date.
--  2. PARTNER_HIST is SCD2, not a daily snapshot: it is resolved by valid_from/valid_to only.
--     The old filter on the business date of its load_id dropped partners whose version was
--     loaded on another day.
--  3. Joining loan x limit x collateral multiplied rows, inflating every SUM. Each measure is now
--     aggregated at its own grain (loan, limit, partner) before it is combined.
--  4. Amounts in different currencies were added up. Everything is converted to EUR (ECB rate).
--  5. Limits are only counted when valid on the as-of date.
-- Run the precheck of query_1_partner_risk_exposure.sql first: a missing ECB rate gives NULL here.
WITH query_params AS (SELECT DATE '2026-11-19' AS as_of_date FROM dual),
latest_loads AS (
    SELECT load_id, started_at FROM (
        SELECT cl.load_id, cl.started_at,
               ROW_NUMBER() OVER (PARTITION BY cl.source_system, cl.dataset_name
                                  ORDER BY cl.started_at DESC, cl.load_id DESC) AS load_rank
        FROM CTRL_LOAD cl CROSS JOIN query_params qp
        WHERE cl.business_date = qp.as_of_date
          AND cl.load_status IN ('VALIDATED', 'COMPLETED')
    )
    WHERE load_rank = 1
),
selected_fx_rates AS (
    SELECT from_currency_code, exchange_rate FROM (
        SELECT fx.from_currency_code, fx.exchange_rate,
               ROW_NUMBER() OVER (PARTITION BY fx.from_currency_code
                                  ORDER BY ll.started_at DESC, fx.load_id DESC) AS rate_rank
        FROM FX_RATE fx
        JOIN latest_loads ll ON ll.load_id = fx.load_id
        CROSS JOIN query_params qp
        WHERE fx.to_currency_code = 'EUR'
          AND fx.rate_date = qp.as_of_date
          AND fx.rate_type = 'ECB'
    )
    WHERE rate_rank = 1
),
selected_loans AS (
    SELECT lh.loan_id, lh.partner_id,
           lh.principal_amt * CASE lh.currency_code WHEN 'EUR' THEN 1 ELSE fx.exchange_rate END AS principal_eur,
           lh.overdue_amt   * CASE lh.currency_code WHEN 'EUR' THEN 1 ELSE fx.exchange_rate END AS overdue_eur
    FROM LOAN_HIST lh
    JOIN latest_loads ll ON ll.load_id = lh.load_id
    LEFT JOIN selected_fx_rates fx ON fx.from_currency_code = lh.currency_code
),
loan_totals AS (
    SELECT partner_id,
           COUNT(*)          AS total_loans,
           SUM(principal_eur) AS total_principal_eur,
           SUM(overdue_eur)   AS total_overdue_eur
    FROM selected_loans
    GROUP BY partner_id
),
partner_limits AS (
    SELECT lim.partner_id,
           SUM(lim.approved_amt * CASE lim.currency_code WHEN 'EUR' THEN 1 ELSE fx.exchange_rate END) AS total_approved_limit_eur,
           SUM(lim.utilized_amt * CASE lim.currency_code WHEN 'EUR' THEN 1 ELSE fx.exchange_rate END) AS total_utilized_limit_eur
    FROM (
        SELECT l.limit_id, l.partner_id, l.currency_code, l.approved_amt, l.utilized_amt,
               l.valid_from, l.valid_to,
               ROW_NUMBER() OVER (PARTITION BY l.limit_id
                                  ORDER BY ll.started_at DESC, l.load_id DESC) AS limit_rank
        FROM LIMIT_HIST l
        JOIN latest_loads ll ON ll.load_id = l.load_id
    ) lim
    CROSS JOIN query_params qp
    LEFT JOIN selected_fx_rates fx ON fx.from_currency_code = lim.currency_code
    WHERE lim.limit_rank = 1
      AND (lim.valid_from IS NULL OR lim.valid_from <= qp.as_of_date)
      AND (lim.valid_to   IS NULL OR qp.as_of_date < lim.valid_to)
    GROUP BY lim.partner_id
),
collateral_by_loan AS (
    SELECT lcr.loan_id,
           SUM(lcr.allocated_value_amt
               * CASE lcr.allocation_currency_code WHEN 'EUR' THEN 1 ELSE fx.exchange_rate END) AS allocated_value_eur
    FROM LOAN_COLLATERAL_REL_HIST lcr
    JOIN latest_loads ll ON ll.load_id = lcr.load_id
    LEFT JOIN selected_fx_rates fx ON fx.from_currency_code = lcr.allocation_currency_code
    GROUP BY lcr.loan_id
),
partner_collateral AS (
    SELECT sl.partner_id, SUM(NVL(cbl.allocated_value_eur, 0)) AS total_allocated_collateral_eur
    FROM selected_loans sl
    LEFT JOIN collateral_by_loan cbl ON cbl.loan_id = sl.loan_id
    GROUP BY sl.partner_id
)
SELECT
    ph.partner_id,
    ph.partner_name,
    ph.customer_segment,
    ph.risk_rating,
    lt.total_loans,
    lt.total_principal_eur,
    lt.total_overdue_eur,
    pl.total_approved_limit_eur,
    pl.total_utilized_limit_eur,
    NVL(pc.total_allocated_collateral_eur, 0) AS total_allocated_collateral_eur
FROM PARTNER_HIST ph
CROSS JOIN query_params qp
JOIN loan_totals lt          ON lt.partner_id = ph.partner_id
LEFT JOIN partner_limits pl  ON pl.partner_id = ph.partner_id
LEFT JOIN partner_collateral pc ON pc.partner_id = ph.partner_id
WHERE ph.valid_from <= qp.as_of_date
  AND ph.valid_to   >  qp.as_of_date
  AND lt.total_principal_eur > 100000;