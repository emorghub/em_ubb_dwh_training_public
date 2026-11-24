# Code templates

`tools/codegen/generate.py` turns an approved mapping workbook into SQL by
filling these [Jinja2](https://jinja.palletsprojects.com/) templates. The
Python decides *what* (which columns, which strategy, which tests); the
templates decide *how it is written*. To adopt this process with your own
coding conventions - logging framework, error handling, naming, headers -
change the templates, not the generator.

| Template | Produces |
|---|---|
| `_header.sql.j2` | The header every generated file starts with (mapping, fingerprint, approver). Keep the `mapping fingerprint <hash>` text: `generate.py --check` looks for it. |
| `table_create.sql.j2` | `<TABLE>.sql`: `CREATE TABLE`, primary key, column comments (scd2: plus the history columns, their checks and the one-open-version index) |
| `load_log_create.sql.j2` | `<TABLE>_LOAD_LOG.sql`, scd2 only: the table of dates loaded |
| `table_change.sql.j2` | `<MAPPING_ID>.sql`: safe `ALTER TABLE` statements for a table that already exists, plus the MANUAL DECISIONS block |
| `package.sql.j2` | `<PACKAGE>.sql`: the load package, one block per load strategy, plus `check_guards` when the mapping has guards |
| `test_package.sql.j2` | `UT_<TABLE>.sql`: utPLSQL tests, one per acceptance criterion; the file ends with a block that runs them |
| `test_data_package.sql.j2` | `UT_<TABLE>_DATA.sql`: the starting point for test data (written once); scd2 adds `NEXT_DATE` and `seed_next_date`, each guard a `seed_<AC_ID>` procedure |

`tools/codegen/generate_staging.py` fills three more, from a change request's
approved delivery agreements (one file per staging table,
`change-requests/<CR_ID>/staging/STG_<NAME>.sql`):

| Template | Produces |
|---|---|
| `_staging_header.sql.j2` | The header of every staging script (change request, agreement, entity, approver). Keep the `agreement fingerprint <hash>` text: `generate_staging.py --check` looks for it. |
| `staging_create.sql.j2` | A new staging table: `LOAD_ID`, the delivered attributes, `STAGED_AT`; primary key `LOAD_ID` + business key; foreign key to `UBB_CORE2.CTRL_LOAD`; list partition per load; comments; `GRANT SELECT` to `UBB_CORE2` |
| `staging_change.sql.j2` | `ALTER TABLE ... ADD` for attributes an existing staging table lacks (nullable), plus the MANUAL DECISIONS block for types that differ |

Variables of the staging templates: `cr_id`, `source_system`, `version`,
`agreement_file`, `entity`, `filename`, `generated_on`, `fingerprint`,
`approved_by`, `approved_on` (provenance); `table`, `columns` (`name`,
`type`, `nullable`, `description`), `name_width`, `key_columns`, `pk_name`,
`fk_name`, `load_table`, `core_schema`, `table_comment`, `manual_notes`.

`preflight_helpers.sql` is not a Jinja template: it is the fixed PL/SQL helper
block (`report`, `cnt`, `check_none`, ...) of the two deployment preflight
scripts that `/dev-3-prepare-deployment` writes. The assistant pastes the block
between `BEGIN HELPERS` and `END HELPERS` unchanged and adds only the mapping's
checks; `package_deployment.py` refuses a script that does not carry it. Change
a helper here, then rewrite the preflight scripts of mappings not yet deployed.

## Conventions the current templates follow

- **No `COMMIT` in a load procedure.** The caller owns the transaction
  (the scheduler job or the developer's session commits after the call). That is also what lets
  utPLSQL roll back everything a test did. If your scheduler calls
  procedures directly, commit in the scheduler's job, not in the procedure.
- **All or nothing.** Every load sets its own savepoint first and, on any
  error, rolls back to it and re-raises. A failed run therefore leaves the
  target exactly as it was - never a partial snapshot - even when the
  caller catches the error and commits. `ROLLBACK TO SAVEPOINT` of its own
  savepoint is the only rollback a procedure does; the caller's earlier work
  in the same transaction is never touched.
- **Guards run before anything is written.** A `guard` acceptance criterion
  is a query that finds source rows which must stop the run (a missing
  risk parameter, an ambiguous reference). The procedure counts each
  guard's rows first and raises `ORA-20005` (exception `e_guard_failed` in
  the package spec) naming the guard, the row count and the parameter
  values. `scd2` checks every date it will load or replay before it rewinds
  anything.
- **Aggregating loads** (`Group_By` filled in) add `GROUP BY` to the one
  source query, so the load, the tests and the verifier all see the same
  grouped rows. A `Group_By` column that holds a parameter or a constant is
  left out of the `GROUP BY` (it is the same on every row). With
  Item_Columns the query has two levels: the inner one computes the
  `Group_By` values and the item columns once per source row (window
  functions run there), the outer one, aliased `ITEM`, groups them.
- **`full` deletes instead of truncating**, because `TRUNCATE` commits.
- **Every parameter is mandatory**: a NULL raises `ORA-20001`.
- **`DBMS_APPLICATION_INFO`** marks the running load (module = package,
  action = procedure), visible in `V$SESSION` while it runs.
- **`merge` updates only when a value really changed** (NULL-safe
  `DECODE` compare), and never touches `SCD_Type 0` or key columns.
- **Source tables are aliased by their bare name**, so a mapping rule
  written as `S_ACCOUNT.CURRENT_BALANCE` works unchanged.
- **`scd2` keeps history** in `VALID_FROM` / `VALID_TO` (exclusive;
  `DATE '9999-12-31'` = current version) and, for a full snapshot,
  `IS_DELETED`. A run records its date in `<TABLE>_LOAD_LOG`. A run for a
  date on or before the latest logged one first *rewinds* (deletes versions
  from that date on, reopens the versions those loads closed), then loads
  the date and replays every later logged date, oldest first. That is
  exact because a load for date D only closes versions at D and adds
  versions from D, so any load order gives the history of loading every
  date once, in order. Each date is applied in three statements: close
  changed (or missing, or returning) keys, insert new versions, insert
  deleted versions. The all-or-nothing savepoint means a failed replay
  cannot leave the history half rewound.

## Errors and logging

A generated procedure **raises, it never logs**. Logging from inside would
need an autonomous transaction (a separate transaction that commits on its
own), and those rows would survive every utPLSQL test's rollback. So the
caller - the scheduler job - logs, and the numbered errors tell it what
happened:

| Code | Raised when | Nothing written? |
|---|---|---|
| `ORA-20001` | a parameter is NULL | yes |
| `ORA-20002` | `scd2`: the date has a time of day, or is not before `DATE '9999-12-31'` | yes |
| `ORA-20003` | `scd2` with a full snapshot: the source is empty for a date | yes (savepoint) |
| `ORA-20004` | `scd2`: the target has history the load log does not list | yes (savepoint) |
| `ORA-20005` | a guard found source rows (`<PACKAGE>.e_guard_failed`) | yes, checked first |
| any other | a database error during the load (constraint, conversion...) | yes (savepoint) |

In this repository the job log is `UBB_CORE2.PKG_ETL_CONTROL` (see its
package script in `sql/`); its procedures commit in autonomous transactions,
so a log row survives the rollback. A job calling a generated load:

```sql
DECLARE
    l_business_date DATE := DATE '2026-11-17';  -- the date the job runs for
    l_run_id        NUMBER;
BEGIN
    -- start_run checks the job and the source load (see PKG_ETL_CONTROL_1.sql)
    UBB_CORE2.PKG_ETL_CONTROL.start_run('<JOB_NAME>', l_business_date, <source load ID or NULL>, l_run_id);
    BEGIN
        UBB_CORE2.<PACKAGE>.<PROCEDURE>(P_BUSINESS_DATE => l_business_date);
        COMMIT;
        UBB_CORE2.PKG_ETL_CONTROL.complete_run(l_run_id, NULL, NULL);
    EXCEPTION
        WHEN OTHERS THEN
            ROLLBACK;  -- the load already undid its own work; this ends the job's transaction
            UBB_CORE2.PKG_ETL_CONTROL.fail_run(l_run_id, SQLERRM);
            RAISE;
    END;
END;
```

To log from inside the load instead, change the `EXCEPTION` block of
`package.sql.j2` - and accept that the tests then leave log rows behind.

## Variables available in every template

Built in `build_context()` in `generate.py`:

| Variable | Meaning |
|---|---|
| `mapping_id`, `workbook`, `fingerprint`, `approved_by`, `approved_on`, `generated_on`, `intent_one_line` | Provenance; `intent_one_line` is the Intent on one line, at most 160 characters |
| `target`, `target_schema`, `target_table`, `table_description`, `pk_name` | The target table |
| `name_width` | Length of the longest column name, for aligning column lists |
| `columns` | The mapped columns: `name`, `type`, `nullable`, `expr` (the SELECT expression), `scd_type`, `is_key`, `is_expr`, `is_history`, `business_name`, `description`, `comment` |
| `table_columns`, `primary_key` | Every column of the table (the mapped ones, then the scd2 history columns) and its primary key (Business_Key, plus `VALID_FROM` for scd2) |
| `key_columns`, `update_columns`, `change_columns` | Business key; columns a merge may update; the subset compared to decide whether to update |
| `package_schema`, `package`, `procedure`, `parameters` (`name`, `plsql_type`, `decl_type`, `test_value`) | The procedure |
| `load_strategy`, `strategy_summary`, `reload_predicate` | How rows are replaced |
| `source_query`, `source_query_8`, `source_query_12`, `source_query_16` | The source `SELECT` (with its `GROUP BY` when aggregating; with Item_Columns, an outer grouping `SELECT ... FROM (<per-row SELECT>) ITEM GROUP BY ...`), unindented and indented by 8/12/16 spaces; `source_query \| pad(n)` indents it by any n |
| `is_aggregating`, `group_by` | Whether `Group_By` is filled in, and its target column names |
| `savepoint_name` | The procedure's own savepoint (`SP_<PACKAGE>`), for the all-or-nothing rollback |
| `tests` (`id`, `proc`, `seed_proc`, `description`, `check_type`, `check_sql`, `expected_is_number`, `expected_literal`), `hash_expr`, `test_package`, `data_package` | Tests; `seed_proc` is the test data procedure a guard test calls |
| `guards`, `guard_error`, `parameter_message` | The `tests` entries whose `check_type` is `guard`; their error code (-20005); a PL/SQL expression naming the run's parameter values for an error message |
| `fixture_tables`, `cases` | Test data skeleton |
| `add_columns`, `widen_columns`, `relax_null_columns`, `manual_notes` | Change script for an existing table |
| `is_scd2`, `has_is_deleted`, `effective_param`, `tracked_columns`, `history_columns`, `open_valid_to`, `load_log`, `load_log_table`, `pk_log_name`, `ck_period_name`, `ck_deleted_name`, `uq_open_name` | scd2: whether it applies, whether the source is a full snapshot, the one DATE parameter, the SCD_Type 2 non-key columns compared, VALID_FROM/VALID_TO/IS_DELETED, `DATE '9999-12-31'`, the load log (qualified and bare), and object names |
| `next_date`, `next_cases` | scd2 tests: the test data's second load date and the cases its data must cover |

Filters: `sqlstr` (Oracle string literal body, quotes doubled), `ljust(width)`,
`pad(n)` (indent every line by n spaces).

## After changing a template

1. `python -m pytest -q` - the expected text may need
   updating, deliberately.
2. Generate a real mapping and compile the output on a scratch database
   before using it for real (see "How this was verified" in
   `docs/WORKFLOW.md`).
3. Regenerating changes the code of every mapping generated afterwards -
   existing deployed packages are only affected when regenerated and
   redeployed.
