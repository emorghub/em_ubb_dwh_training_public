-- Query 2: Daily Multi-Currency Portfolio Valuation (FX Conversion & Window Functions)
WITH Target_Load AS (
    SELECT load_id, business_date
    FROM CTRL_LOAD
    WHERE dataset_name = 'LOAN'
      AND load_status IN ('VALIDATED', 'COMPLETED')
      AND business_date BETWEEN DATE '2026-10-01' AND DATE '2026-11-01'
),
Converted_Loans AS (
    SELECT 
        tl.business_date,
        lh.loan_id,
        lh.partner_id,
        lh.currency_code AS orig_currency,
        lh.principal_amt,
        NVL(fx.exchange_rate, 1) AS fx_rate,
        lh.principal_amt * NVL(fx.exchange_rate, 1) AS principal_amt_eur
    FROM Target_Load tl
    JOIN LOAN_HIST lh 
      ON lh.load_id = tl.load_id
    LEFT JOIN FX_RATE fx 
      ON fx.from_currency_code = lh.currency_code
     AND fx.to_currency_code = 'EUR'
     AND fx.rate_type = 'ECB'
     AND fx.rate_date = tl.business_date
)
SELECT 
    business_date,
    partner_id,
    COUNT(loan_id) AS active_loans,
    SUM(principal_amt_eur) AS daily_portfolio_eur,
    AVG(SUM(principal_amt_eur)) OVER (
        PARTITION BY partner_id 
        ORDER BY business_date 
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS rolling_7day_avg_exposure,
    RANK() OVER (
        PARTITION BY business_date 
        ORDER BY SUM(principal_amt_eur) DESC
    ) AS daily_partner_rank
FROM Converted_Loans
GROUP BY business_date, partner_id;
