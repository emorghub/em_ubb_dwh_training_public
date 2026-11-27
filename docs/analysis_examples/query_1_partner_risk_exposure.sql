-- Query 1: Partner Risk Exposure & Collateral Coverage (As-of EUR Aggregation)
-- Precheck: this must return no rows before running the report.
WITH query_params AS (SELECT DATE '2026-11-19' AS as_of_date FROM dual),
latest_loads AS (
    SELECT load_id, started_at FROM (
        SELECT cl.load_id, cl.started_at,
           ROW_NUMBER() OVER (PARTITION BY cl.source_system, cl.dataset_name ORDER BY cl.started_at DESC, cl.load_id DESC) load_rank
        FROM CTRL_LOAD cl CROSS JOIN query_params qp
        WHERE cl.business_date = qp.as_of_date
          AND cl.load_status IN ('VALIDATED', 'COMPLETED')
    )
    WHERE load_rank = 1
),
selected_loans AS (
    SELECT lh.loan_id, lh.partner_id, lh.currency_code
    FROM LOAN_HIST lh JOIN latest_loads ll ON ll.load_id = lh.load_id
),
report_partners AS (SELECT DISTINCT partner_id FROM selected_loans),
selected_limits AS (
    SELECT lim.limit_id, lim.partner_id, lim.currency_code
    FROM (
        SELECT lim.limit_id, lim.partner_id, lim.currency_code, lim.valid_from, lim.valid_to,
               ROW_NUMBER() OVER (PARTITION BY lim.limit_id ORDER BY ll.started_at DESC, lim.load_id DESC) AS facility_rank
        FROM LIMIT_HIST lim JOIN latest_loads ll ON ll.load_id = lim.load_id
    ) lim
    JOIN report_partners rp ON rp.partner_id = lim.partner_id CROSS JOIN query_params qp
    WHERE lim.facility_rank = 1
      AND (lim.valid_from IS NULL OR lim.valid_from <= qp.as_of_date)
      AND (lim.valid_to IS NULL OR qp.as_of_date < lim.valid_to)
),
selected_collateral AS (
    SELECT lcr.loan_id, lcr.allocated_value_amt, lcr.allocation_currency_code
    FROM LOAN_COLLATERAL_REL_HIST lcr
    JOIN latest_loads ll ON ll.load_id = lcr.load_id
    JOIN (SELECT DISTINCT loan_id FROM selected_loans) sl ON sl.loan_id = lcr.loan_id
),
required_currencies AS (
    SELECT currency_code FROM selected_loans UNION
    SELECT currency_code FROM selected_limits UNION
    SELECT allocation_currency_code FROM selected_collateral WHERE allocation_currency_code IS NOT NULL
),
missing_fx_rates AS (
    SELECT DISTINCT rc.currency_code
    FROM required_currencies rc CROSS JOIN query_params qp
    WHERE rc.currency_code <> 'EUR'
      AND NOT EXISTS (
          SELECT 1 FROM FX_RATE fx JOIN latest_loads ll ON ll.load_id = fx.load_id
          WHERE fx.from_currency_code = rc.currency_code AND fx.to_currency_code = 'EUR'
            AND fx.rate_date = qp.as_of_date AND fx.rate_type = 'ECB'
      )
)
SELECT 'MISSING_ECB_RATE' AS issue, currency_code FROM missing_fx_rates
UNION ALL
SELECT 'MISSING_COLLATERAL_CURRENCY', CAST(NULL AS VARCHAR2(3))
FROM selected_collateral
WHERE allocated_value_amt IS NOT NULL AND allocation_currency_code IS NULL
ORDER BY issue, currency_code;

-- Report: run only after the precheck above returns no rows.
WITH query_params AS (SELECT DATE '2026-11-19' AS as_of_date FROM dual),
latest_loads AS (
    SELECT load_id, started_at FROM (
        SELECT cl.load_id, cl.started_at,
           ROW_NUMBER() OVER (PARTITION BY cl.source_system, cl.dataset_name ORDER BY cl.started_at DESC, cl.load_id DESC) load_rank
        FROM CTRL_LOAD cl CROSS JOIN query_params qp
        WHERE cl.business_date = qp.as_of_date
          AND cl.load_status IN ('VALIDATED', 'COMPLETED')
    )
    WHERE load_rank = 1
),
selected_loans AS (
    SELECT lh.loan_id, lh.partner_id, lh.currency_code, lh.principal_amt, lh.overdue_amt
    FROM LOAN_HIST lh JOIN latest_loads ll ON ll.load_id = lh.load_id
),
selected_limits AS (
    SELECT lim.limit_id, lim.partner_id, lim.currency_code, lim.approved_amt, lim.utilized_amt
    FROM (
        SELECT lim.limit_id, lim.partner_id, lim.currency_code, lim.approved_amt, lim.utilized_amt,
               lim.valid_from, lim.valid_to,
               ROW_NUMBER() OVER (PARTITION BY lim.limit_id ORDER BY ll.started_at DESC, lim.load_id DESC) AS facility_rank
        FROM LIMIT_HIST lim JOIN latest_loads ll ON ll.load_id = lim.load_id
    ) lim CROSS JOIN query_params qp
    WHERE lim.facility_rank = 1
      AND (lim.valid_from IS NULL OR lim.valid_from <= qp.as_of_date)
      AND (lim.valid_to IS NULL OR qp.as_of_date < lim.valid_to)
),
selected_fx_rates AS (
    SELECT from_currency_code, exchange_rate FROM (
        SELECT fx.from_currency_code, fx.exchange_rate,
               ROW_NUMBER() OVER (PARTITION BY fx.from_currency_code ORDER BY ll.started_at DESC, fx.load_id DESC) AS rate_rank
        FROM FX_RATE fx JOIN latest_loads ll ON ll.load_id = fx.load_id
        CROSS JOIN query_params qp
        WHERE fx.to_currency_code = 'EUR' AND fx.rate_date = qp.as_of_date
          AND fx.rate_type = 'ECB'
    )
    WHERE rate_rank = 1
),
converted_loans AS (
    SELECT sl.loan_id, sl.partner_id,
           sl.principal_amt * CASE sl.currency_code WHEN 'EUR' THEN 1 ELSE fx.exchange_rate END AS principal_eur,
           sl.overdue_amt * CASE sl.currency_code WHEN 'EUR' THEN 1 ELSE fx.exchange_rate END AS overdue_eur
    FROM selected_loans sl LEFT JOIN selected_fx_rates fx ON fx.from_currency_code = sl.currency_code
),
loan_totals AS (
    SELECT partner_id, COUNT(DISTINCT loan_id) AS total_loans,
           SUM(principal_eur) AS total_principal_eur, SUM(overdue_eur) AS total_overdue_eur
    FROM converted_loans GROUP BY partner_id
),
partner_limits AS (
    SELECT lim.partner_id,
           SUM(lim.approved_amt * CASE lim.currency_code WHEN 'EUR' THEN 1 ELSE fx.exchange_rate END) AS total_approved_limit_eur,
           SUM(lim.utilized_amt * CASE lim.currency_code WHEN 'EUR' THEN 1 ELSE fx.exchange_rate END) AS total_utilized_limit_eur
    FROM selected_limits lim
    JOIN (SELECT DISTINCT partner_id FROM selected_loans) rp ON rp.partner_id = lim.partner_id
    LEFT JOIN selected_fx_rates fx ON fx.from_currency_code = lim.currency_code
    GROUP BY lim.partner_id
),
selected_collateral AS (
    SELECT lcr.loan_id, lcr.allocated_value_amt, lcr.allocation_currency_code
    FROM LOAN_COLLATERAL_REL_HIST lcr JOIN latest_loads ll ON ll.load_id = lcr.load_id
    WHERE EXISTS (SELECT 1 FROM selected_loans sl WHERE sl.loan_id = lcr.loan_id)
),
collateral_by_loan AS (
    SELECT sc.loan_id,
           SUM(sc.allocated_value_amt * CASE sc.allocation_currency_code WHEN 'EUR' THEN 1 ELSE fx.exchange_rate END)
               AS allocated_value_eur
    FROM selected_collateral sc LEFT JOIN selected_fx_rates fx
      ON fx.from_currency_code = sc.allocation_currency_code
    GROUP BY sc.loan_id
),
partner_collateral AS (
    SELECT sl.partner_id, SUM(NVL(cbl.allocated_value_eur, 0)) AS total_allocated_collateral_eur
    FROM selected_loans sl LEFT JOIN collateral_by_loan cbl ON cbl.loan_id = sl.loan_id
    GROUP BY sl.partner_id
),
partners_as_of AS (
    SELECT ph.partner_id, ph.partner_name, ph.customer_segment, ph.risk_rating
    FROM PARTNER_HIST ph CROSS JOIN query_params qp
    WHERE ph.valid_from <= qp.as_of_date AND ph.valid_to > qp.as_of_date
)
SELECT ph.partner_id, ph.partner_name, ph.customer_segment, ph.risk_rating,
       lt.total_loans, lt.total_principal_eur, lt.total_overdue_eur,
       pl.total_approved_limit_eur, pl.total_utilized_limit_eur,
       NVL(pc.total_allocated_collateral_eur, 0) AS total_allocated_collateral_eur
FROM partners_as_of ph JOIN loan_totals lt ON lt.partner_id = ph.partner_id
LEFT JOIN partner_limits pl ON pl.partner_id = ph.partner_id
LEFT JOIN partner_collateral pc ON pc.partner_id = ph.partner_id
WHERE lt.total_principal_eur > 100000;
