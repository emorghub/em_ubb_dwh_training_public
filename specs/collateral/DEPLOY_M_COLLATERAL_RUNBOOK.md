<!-- Deployment handover for mapping M_COLLATERAL (specs/collateral/M_COLLATERAL.xlsx) -->
<!-- mapping fingerprint 35a96c007d483467, approved by Emil Angelov on 2026-11-27; prepared 2026-11-27 by the assistant -->
<!-- READ ONLY handover: the assistant has not deployed anything and has not run any script. Deployment is the developer's, by hand. -->

# Deployment runbook - M_COLLATERAL

Run every command from the package folder (the folder this file is in), as SQL*Plus, SQLcl or SQL Developer
scripts (`@path`). Files are named by their path inside this folder. Check `verify.sh` (Linux) or `verify.ps1`
(Windows) first: it compares every file with `SHA256SUMS`.

## 1. Scope

| Item | Value |
|---|---|
| Mapping | `M_COLLATERAL` (fingerprint `35a96c007d483467`), approved by Emil Angelov on 2026-11-27 |
| Change request | `CR-ECB-001`, Load_Plan row `M_COLLATERAL`, Dependency_Order 1, `Depends_On` empty, change `new_load` |
| Target | `UBB_CORE2.COLLATERAL_HIST`, an **existing** table: the change script adds 4 columns (`VALUATION_CURRENCY_CODE`, `ELIGIBILITY_FLAG`, `ELIGIBILITY_REASON_CODE`, `REGULATORY_HAIRCUT_PCT`, all nullable) |
| Load | `UBB_CORE2.PKG_ETL_COLLATERAL.LOAD_DAY(P_BUSINESS_DATE DATE)`, strategy `append`, grain one row per collateral item per source load, key `COLLATERAL_ID, LOAD_ID` |
| Reads | `UBB_STAGING2.STG_COLLATERAL` (driving table, source load `CBS_SIM` / `COLLATERAL` found by `UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD`) and `UBB_CORE2.COLLATERAL` (identity rows, inner join on `SOURCE_SYSTEM = 'CBS_SIM'` and `COLLATERAL_REF`) |
| Not in this load | the loan link (`LOAN_ID` stays NULL, Q-16), recognition, haircut, FX, allocation, creating `COLLATERAL` identity rows |

Decisions of the workbook (verbatim):

- **D-01 Grain and key** - One collateral item per daily source load (COLLATERAL_ID, LOAD_ID), the existing primary key.
- **D-02 Valuation basis** - MARKET_VALUE_AMT (Q-14); ELIGIBLE_VALUE_AMT is stored as delivered but not used.
- **D-03 Valuation currency** - VALUATION_CURRENCY_CODE (Q-15); CURRENCY_CODE is kept as delivered.
- **D-04 Loan link** - No, it stays NULL (Q-16). The table comment of COLLATERAL_HIST ("one loan per collateral snapshot") should be corrected by the data model owner.
- **D-05 Collateral identity rows** - no loader in sql/ writes UBB_CORE2.COLLATERAL and a generated load writes one table only, so an identity load is missing from the Load_Plan. add a mapping for UBB_CORE2.COLLATERAL (back to /ba-2-analyse-data-gaps). AC-07 stops the run until the rows exist.
- **D-06 Haircut scale and range** - percentage points (the name ends in _PCT, as ALLOCATION_PCT, which is constrained to 0-100). the source owner confirms scale, range and nullability; then add a range check. The value is stored as delivered here; M_COLLATERAL_RECOGNITION applies the scale.
- **D-07 Eligibility domain** - Q-06 only says Y is eligible. Any other value, and NULL, is treated as not eligible by M_COLLATERAL_RECOGNITION until the source owner lists the domain.
- **D-RERUN Re-run rule** - append with a guard: rows already stored for the same LOAD_ID stop the run with ORA-20005, so a stored collateral snapshot is never overwritten (BR-11, Q-12). A corrected delivery arrives as a new LOAD_ID and adds new rows.
- **D-DATASET Dataset names in CTRL_LOAD** - use the delivery entity name as DATASET_NAME (as LOAN, LIMIT, PARTNER do in the existing loads). No script in sql/ lists the CTRL_LOAD rows, so the names used here are unconfirmed; the developer must check them against CTRL_LOAD and CTRL_JOB data.

MANUAL DECISIONS of the change script `ddl/M_COLLATERAL.sql`: it lists none; it executes only additive changes (the 4 columns and their comments). Nothing else about the table changes.

## 2. Parameters to decide before starting

| Name | Meaning | Comes from | Value |
|---|---|---|---|
| Environment | `TEST` or `PROD`; the first argument of Preflight 1 and the last of Preflight 2 | the environment | _decide_ |
| Connect as | the schema that owns the load package | workbook `PLSQL_Proc` | `UBB_CORE2` |
| `P_BUSINESS_DATE` | reporting date of the first run, `YYYY-MM-DD`, at midnight; a `CBS_SIM` / `COLLATERAL` source load for it must be `VALIDATED` or `COMPLETED` | workbook Parameters (`P_BUSINESS_DATE DATE`); the date itself is not in the repository | _decide_ |
| Job name | the `CTRL_JOB` entry that logs the run | not in the repository (open item 1) | _decide_ |

## 3. Step 1 - Verify the earlier mappings of the change request are deployed

Predecessors: every mapping of the Load_Plan with a lower `Dependency_Order`, plus every mapping in `Depends_On`.

| Mapping | Order | Target | Package | What must be in the database |
|---|---|---|---|---|
| none | - | - | - | `M_COLLATERAL` is Order 1 and its `Depends_On` is empty |

- There are no predecessors. The step stays so the check is not forgotten for a later mapping.
- Peers of Order 1 (`M_LOAN`, `M_PARTNER`, `M_FX_RATE`, `M_RISK_ASSESSMENT`) are **not** predecessors; this load does not read their targets. Mappings of Order 2 and later (`M_LOAN_COLLATERAL_REL`, `M_COLLATERAL_RECOGNITION`, `M_EXPOSURE`) read this target and deploy after it.
- Baseline objects this load reads (Preconditions of the workbook): Preflight 1 section B checks that `UBB_CORE2.CTRL_LOAD`, `UBB_CORE2.PKG_ETL_CONTROL` (valid, with `FIND_SOURCE_LOAD`) and `UBB_CORE2.COLLATERAL` (with its unique key) exist.
- The CBS_SIM v1.1 staging change (`staging/STG_COLLATERAL.sql`) is a precondition of the mapping, not a predecessor mapping: it is step 5.1 below.
- Stop when anything is missing. Do not continue "to see what happens".

## 4. Before changing anything

1. Pause the schedules and confirm no run is active. The repository knows no job for this load; the preflight scripts look for `CTRL_JOB` rows whose `DATASET_NAME` is `COLLATERAL` (job names in Preflight 1, F-01) and for enabled scheduler jobs that mention `PKG_ETL_COLLATERAL`.
2. Save the current state for rollback, with the release ticket: `DBMS_METADATA.GET_DDL('TABLE', 'COLLATERAL_HIST', 'UBB_CORE2')`. `PKG_ETL_COLLATERAL` is new in the repository (no script in `sql/`); if Preflight 1 G-01 or G-02 shows it already exists, save `DBMS_METADATA.GET_DDL('PACKAGE_SPEC', ...)` and `GET_DDL('PACKAGE_BODY', ...)` too.

## 5. Deployment steps, in order

| # | Action | File | Connect as | Parameters | Expected result | Stop when |
|---|---|---|---|---|---|---|
| 5.1 | Add the 4 staging columns (CBS_SIM v1.1) | `staging/STG_COLLATERAL.sql` | `UBB_STAGING2` owner or a DBA | none | `ALTER TABLE` and 4 comments succeed | an error, or the columns already exist (then skip, do not re-run) |
| 5.2 | Outside this repository: the inbound loader fills the new staging columns | - | - | - | staged rows carry valuation currency, eligibility flag and reason, haircut | the loader is not changed (open item 2); the load would store NULLs |
| 5.3 | Grant `SELECT` on the staging table to the package schema | `grants/grants_select.sql` | `UBB_STAGING2` owner or a DBA | none | `GRANT SELECT ON UBB_STAGING2.STG_COLLATERAL TO UBB_CORE2` succeeds (`sql/` already shows this grant; running it again is harmless) | an error |
| 5.3a | `TEST` only: grant `INSERT` on the staging table for the test data | `grants/grants_test_only_insert.sql` | `UBB_STAGING2` owner or a DBA | none | `GRANT INSERT ON UBB_STAGING2.STG_COLLATERAL TO UBB_CORE2` succeeds. **Never in production.** | - |
| 5.4 | **Preflight 1** | `preflight/DEPLOY_M_COLLATERAL_PREFLIGHT_1_BEFORE_DDL.sql` | `UBB_CORE2` | 1: environment (`TEST` or `PROD`) | ends with `PREFLIGHT 1 OK`; read every `WARN` and `INFO` line | any `FAIL` |
| 5.5 | Add the 4 columns to the target | `ddl/M_COLLATERAL.sql` | `UBB_CORE2` | none | `ALTER TABLE` and 4 `COMMENT` succeed. The full `COLLATERAL_HIST.sql` of the existing table is **not** in the package and must not be run | an error, or the columns already exist (Preflight 1 D-02 warned) |
| 5.6 | Create the load package | `code/PKG_ETL_COLLATERAL.sql` | `UBB_CORE2` | none | no compile errors (`SHOW ERRORS`) | any compile error |
| 5.7 | `TEST` only: test data package | `test/UT_COLLATERAL_HIST_DATA.sql` | `UBB_CORE2` | none | package and body created without errors. Its header lists `GRANT INSERT ON UBB_CORE2.COLLATERAL TO UBB_CORE2`: not needed, it is the same schema | any compile error |
| 5.8 | `TEST` only: test package, which also runs the tests | `test/UT_COLLATERAL_HIST.sql` | `UBB_CORE2` | none | the report has no failures and no errors (tests `t_fixture_has_rows`, `t_ac_01` to `t_ac_08`) | any failure or error |
| 5.9 | Outside this repository: the scheduler job or a wrapper that calls `LOAD_DAY` and logs with `PKG_ETL_CONTROL` | - | - | - | a `CTRL_JOB` row for the dataset `COLLATERAL` and a job that calls the procedure (open item 1) | - |
| 5.10 | **Preflight 2** | `preflight/DEPLOY_M_COLLATERAL_PREFLIGHT_2_BEFORE_RUN.sql` | `UBB_CORE2` | 1: the business date `YYYY-MM-DD`; 2: environment | ends with `PREFLIGHT 2 OK`; read every `WARN` and `INFO` line | any `FAIL` |

Example: `@preflight/DEPLOY_M_COLLATERAL_PREFLIGHT_2_BEFORE_RUN.sql 2026-11-30 TEST` (the date is only an example).

Preflight 2 `AC-07` fails until the `UBB_CORE2.COLLATERAL` identity rows exist for every staged `COLLATERAL_REF` (open item 3), and `G-01` fails until exactly one source load exists for the date.

## 6. First run

- The entry point is `UBB_CORE2.PKG_ETL_COLLATERAL.LOAD_DAY(P_BUSINESS_DATE => ...)`; the workbook names no wrapper.
- The procedure never commits and never logs. The caller commits; the scheduled job logs with `UBB_CORE2.PKG_ETL_CONTROL` (`start_run`, `complete_run`, `fail_run`). A run by hand in the session:

```sql
DECLARE
    l_business_date DATE := TO_DATE('<business date>', 'YYYY-MM-DD');  -- the date of the first run, at midnight
BEGIN
    UBB_CORE2.PKG_ETL_COLLATERAL.LOAD_DAY(P_BUSINESS_DATE => l_business_date);
END;
/
-- check the verification queries below, then COMMIT or ROLLBACK
```

- Errors: `ORA-20001` the parameter is NULL; `ORA-20005` a guard found rows (AC-05 date not at midnight, AC-06 staged item without currency, AC-07 staged item without identity row, AC-08 rows already stored for the source load); `ORA-20011` / `ORA-20012` no or more than one eligible source load (from `FIND_SOURCE_LOAD`); any other code is a database error. Nothing is written after an error.
- A job that logs the run follows the example in `tools/codegen/templates/README.md`, "Errors and logging": `start_run('<JOB_NAME>', date, <source load ID>, run_id)`, the call, `COMMIT`, `complete_run`; on error `ROLLBACK` and `fail_run`. `start_run` needs a `CTRL_JOB` row that is active and has the dataset `COLLATERAL`.

Verification queries (the `zero_rows` criteria of the workbook, unchanged; replace `P_BUSINESS_DATE` by `TO_DATE('<business date>', 'YYYY-MM-DD')`). Success means **no rows**:

```sql
-- AC-03: Value, valuation currency, eligibility flag and haircut equal the delivered values.
SELECT s.COLLATERAL_REF FROM UBB_STAGING2.STG_COLLATERAL s JOIN UBB_CORE2.COLLATERAL c ON c.SOURCE_SYSTEM = 'CBS_SIM' AND c.COLLATERAL_REF = s.COLLATERAL_REF JOIN UBB_CORE2.COLLATERAL_HIST h ON h.COLLATERAL_ID = c.COLLATERAL_ID AND h.LOAD_ID = s.LOAD_ID WHERE s.LOAD_ID = UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD('CBS_SIM', 'COLLATERAL', P_BUSINESS_DATE) AND (DECODE(h.MARKET_VALUE_AMT, s.MARKET_VALUE_AMT, 0, 1) = 1 OR DECODE(h.VALUATION_CURRENCY_CODE, s.VALUATION_CURRENCY_CODE, 0, 1) = 1 OR DECODE(h.ELIGIBILITY_FLAG, s.ELIGIBILITY_FLAG, 0, 1) = 1 OR DECODE(h.REGULATORY_HAIRCUT_PCT, s.REGULATORY_HAIRCUT_PCT, 0, 1) = 1)

-- AC-04: Collateral is not linked to a loan in this table.
SELECT h.COLLATERAL_ID FROM UBB_CORE2.COLLATERAL_HIST h WHERE h.LOAD_ID = UBB_CORE2.PKG_ETL_CONTROL.FIND_SOURCE_LOAD('CBS_SIM', 'COLLATERAL', P_BUSINESS_DATE) AND h.LOAN_ID IS NOT NULL
```

`AC-01` (no collateral item twice in one source load) and `AC-02` (every item of the source load is stored) have no query in the workbook; the tests `t_ac_01` and `t_ac_02` check them in `TEST`.

## 7. Rollback

- The change script is additive and its columns are nullable: they stay unless a reviewed rollback removes them. DDL commits; `ROLLBACK` does not undo it.
- The package is new in the repository: before the first successful run it can be dropped by a reviewed script, or the saved source (step 4.2) restored if one existed. No wrapper is replaced by this change.
- After a successful run the loaded snapshot is escalated, not deleted: a stored snapshot is never overwritten (D-RERUN) and later loads read it.
- `TEST` only: the test packages `UT_COLLATERAL_HIST` and `UT_COLLATERAL_HIST_DATA` can be dropped; every test rolls back its own data.

## 8. Sign-off and afterwards

- Record: environment, date, the mapping fingerprint `35a96c007d483467`, the release ticket, the job run ID, the preflight outputs and, for `TEST`, the test report.
- Resume the schedules paused in step 4.
- Export the changed table script of `UBB_CORE2.COLLATERAL_HIST`, the new package `UBB_CORE2.PKG_ETL_COLLATERAL` and `UBB_STAGING2.STG_COLLATERAL` into `sql/` **by hand**, never by a query, so every tool sees the deployed state.

## 9. Open items

The owner is left for the developer to fill in.

| # | Open item | Asked by | Owner |
|---|---|---|---|
| 1 | No scheduler job or wrapper calls `LOAD_DAY`, and no `CTRL_JOB` row for the dataset `COLLATERAL` is in `sql/`. Someone must register the job (`PKG_ETL_CONTROL.start_run` needs it) and decide the date of the first run. | the workbook names no entry point; `start_run` calls in `sql/` exist only for `LOAD_LIMIT`, `LOAD_LOAN`, `LOAD_PARTNER` | |
| 2 | The inbound loader that fills `VALUATION_CURRENCY_CODE`, `ELIGIBILITY_FLAG`, `ELIGIBILITY_REASON_CODE`, `REGULATORY_HAIRCUT_PCT` in `STG_COLLATERAL` is outside the repository. | Preconditions: "the inbound loader fills it" | |
| 3 | No loader creates the `UBB_CORE2.COLLATERAL` identity rows, so guard AC-07 stops every run until they exist; the Load_Plan has no mapping for them. | D-05 (back to `/ba-2-analyse-data-gaps`) | |
| 4 | Confirm that `SOURCE_SYSTEM` `CBS_SIM` and `DATASET_NAME` `COLLATERAL` are what `CTRL_LOAD` really holds. Preflight 1 B-08 / B-09 and Preflight 2 G-01 / G-02 print what is there. | D-DATASET | |
| 5 | The source owner confirms scale, range and nullability of `REGULATORY_HAIRCUT_PCT` and the allowed values of `ELIGIBILITY_FLAG` (a range check is still to be added). Preflight 2 H-03 and H-04 only warn. | D-06, D-07 | |
| 6 | The table comment of `COLLATERAL_HIST` ("one loan per collateral snapshot") is to be corrected by the data model owner. | D-04 | |
| 7 | No file outside the generators belongs to this deployment (the developer confirmed). Nothing is in `external/`. | Step 1 of the skill | |

## 10. Where each file lives in the repository

| Package path | Repository path |
|---|---|
| `RUNBOOK.md` | `specs/collateral/DEPLOY_M_COLLATERAL_RUNBOOK.md` |
| `staging/STG_COLLATERAL.sql` | `change-requests/CR-ECB-001/staging/STG_COLLATERAL.sql` |
| `grants/grants_select.sql`, `grants/grants_test_only_insert.sql` | written by `tools/codegen/package_deployment.py` |
| `preflight/DEPLOY_M_COLLATERAL_PREFLIGHT_1_BEFORE_DDL.sql` | `specs/collateral/DEPLOY_M_COLLATERAL_PREFLIGHT_1_BEFORE_DDL.sql` |
| `preflight/DEPLOY_M_COLLATERAL_PREFLIGHT_2_BEFORE_RUN.sql` | `specs/collateral/DEPLOY_M_COLLATERAL_PREFLIGHT_2_BEFORE_RUN.sql` |
| `ddl/M_COLLATERAL.sql` | `specs/collateral/M_COLLATERAL.sql` |
| `code/PKG_ETL_COLLATERAL.sql` | `specs/collateral/PKG_ETL_COLLATERAL.sql` |
| `test/UT_COLLATERAL_HIST_DATA.sql` | `specs/collateral/UT_COLLATERAL_HIST_DATA.sql` |
| `test/UT_COLLATERAL_HIST.sql` | `specs/collateral/UT_COLLATERAL_HIST.sql` |
