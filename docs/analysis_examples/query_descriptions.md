# SQL Performance Benchmark & Optimization Guide

This package contains complex SQL queries generated for the Core & Staging database models, accompanied by architectural descriptions, execution plan bottlenecks, and performance optimization strategies.

---

## Query 1: Partner Risk Exposure & Collateral Coverage (SCD2 Point-in-Time Join)
**File:** `query_1_partner_risk_exposure.sql`

### Business Goal
Calculates the aggregate financial exposure for active bank partners on a given business date (`2026-11-01`). It computes total active loans, total principal, overdue balances, approved/utilized credit limit thresholds, and allocated collateral market values. It correctly resolves partner history using Slowly Changing Dimension (SCD Type 2) temporal logic (`valid_from` <= `as_of_date` < `valid_to`).

### Key Schema Elements Involved
- `PARTNER_HIST` (SCD2 history table keyed by `PARTNER_ID` + `VALID_FROM`)
- `LOAN_HIST`, `LIMIT_HIST`, `LOAN_COLLATERAL_REL_HIST` (Snapshot tables partitioned by `LOAD_ID`)
- `CTRL_LOAD` (Technical load metadata table mapped to `BUSINESS_DATE`)

### Execution Bottlenecks & Analysis Opportunities
1. **SCD2 Range Join Performance:** Range predicates (`ph.valid_from <= X AND ph.valid_to > X`) often prevent single-key index lookups and can lead to nested loops over large datasets.
2. **Partition Pruning Verification:** Check whether Oracle performs **KEY Partition Pruning** or **BLOOM FILTERing** on `LOAN_HIST` and `LOAN_COLLATERAL_REL_HIST` using the subquery/join to `CTRL_LOAD`.
3. **Multi-level Aggregation:** Evaluate the memory footprint of `COUNT(DISTINCT lh.loan_id)` alongside multiple `SUM()` aggregations in the execution plan hash group-by step.

### Recommended Optimization Strategies
- Build a composite index on `PARTNER_HIST(VALID_FROM, VALID_TO, PARTNER_ID)` or `(IS_CURRENT, PARTNER_ID)`.
- Consider creating a Materialized View for daily aggregated partner totals if this query is executed frequently in daily reporting dashboards.

---

## Query 2: Daily Multi-Currency Portfolio Valuation & Rolling Analytics
**File:** `query_2_multi_currency_valuation.sql`

### Business Goal
Translates daily outstanding loan principal into a unified base currency (`EUR`) using snapshot-matched FX rates from `FX_RATE`. It computes 7-day rolling average portfolio exposure per partner and ranks partners by daily portfolio size using SQL Window Functions.

### Key Schema Elements Involved
- `LOAN_HIST` (Daily partitioned loan snapshots)
- `FX_RATE` (Versioned exchange rate table indexed by `IX_FX_RATE_LOOKUP`)
- `CTRL_LOAD` (Technical control register for date-to-load resolution)

### Execution Bottlenecks & Analysis Opportunities
1. **Window Function Memory Spills:** Analytic functions (`AVG(...) OVER (...)`, `RANK() OVER (...)`) require sorting memory. Inspect SQL MONITOR outputs to see if TEMP tablespace spills occur.
2. **Predicate Pushdown:** Verify if the `business_date BETWEEN ...` predicate in the CTE (`Target_Load`) correctly pushes down into `LOAN_HIST` partition scans.
3. **FX Rate Lookup Efficiency:** Check if `IX_FX_RATE_LOOKUP` (`FROM_CURRENCY_CODE`, `TO_CURRENCY_CODE`, `RATE_TYPE`, `RATE_DATE`) is fully utilized or if implicit type conversion occurs (e.g., `CHAR(3)` vs `VARCHAR2(3)`).

### Recommended Optimization Strategies
- Ensure currency code data types (`CHAR(3)` vs `VARCHAR2(3)`) match exactly between `LOAN_HIST` and `FX_RATE` to avoid implicit `SYS_OP_C2C` function wrappers that disable index usage.
- Parallelize execution (`/*+ PARALLEL(lh, 4) */`) when running over long historical date ranges.

---

## Query 3: Multi-Subtype Collateral Valuation Breakdown
**File:** `query_3_collateral_subtype_breakdown.sql`

### Business Goal
Breaks down total collateral values across specialized subtype entities (`REAL_ESTATE_HIST`, `SECURITY_COLLATERAL_HIST`, `GUARANTEE_HIST`) linked to the core `COLLATERAL_HIST` snapshot.

### Key Schema Elements Involved
- `COLLATERAL_HIST` (Parent collateral snapshot table)
- `REAL_ESTATE_HIST` (Property subtype: area, appraised value)
- `SECURITY_COLLATERAL_HIST` (Pledged securities subtype: ISIN, quantity, unit price)
- `GUARANTEE_HIST` (Third-party guarantee subtype: guarantor reference, guaranteed amount)

### Execution Bottlenecks & Analysis Opportunities
1. **Multiple Outer Joins to Large Tables:** Left joining three separate subtype tables on `(COLLATERAL_ID, LOAD_ID)` leads to repeated full partition scans or index lookups across multiple large partition tables.
2. **Parallel Skew (`PQ_DISTRIBUTE`):** When running in parallel, evaluate whether data distribution across parallel query servers (`HASH/HASH` vs `BROADCAST`) creates data skew.

### Recommended Optimization Strategies
- Test replacing multiple `LEFT JOIN` structures with a `UNION ALL` subquery structure over individual subtype tables to eliminate wide row construction and excessive outer join overhead.
- Ensure composite primary keys `(COLLATERAL_ID, LOAD_ID)` exist and are indexed locally on all subtype partitions.

---

## Query 4: ETL Audit & Staging Data Quality Reconciliation
**File:** `query_4_etl_audit_reconciliation.sql`

### Business Goal
Reconciles staging loan data (`STG_LOAN`) against the core data warehouse layer (`LOAN_HIST`) for recent load dates. It identifies staging records that failed to process into `LOAN` core tables and links them to job execution runs (`CTRL_JOB_RUN`) and error logs (`CTRL_JOB_LOG`).

### Key Schema Elements Involved
- `STG_LOAN` (Staging table partitioned by `LOAD_ID`)
- `LOAN` & `LOAN_HIST` (Core target tables)
- `CTRL_LOAD`, `CTRL_JOB_RUN`, `CTRL_JOB_LOG` (ETL pipeline control metadata)

### Execution Bottlenecks & Analysis Opportunities
1. **Anti-Join Transformation:** Examine whether Oracle transforms `NOT EXISTS` into a `HASH JOIN RIGHT ANTI` or falls back to an expensive `FILTER` step.
2. **Natural vs. Surrogate Key Lookups:** Joining `STG_LOAN.LOAN_REF` (source business key) to `LOAN.LOAN_REF` to `LOAN_HIST.LOAN_ID` involves joining legacy string keys to numeric surrogate keys.

### Recommended Optimization Strategies
- Ensure unique/unique-bitmap indexes exist on `LOAN(SOURCE_SYSTEM, LOAN_REF)` to facilitate fast join transformations during staging reconciliation queries.
- Ensure partition pruning occurs on `STG_LOAN` using `TRUNC(SYSDATE) - 7` converted to matching `LOAD_ID` sets.
