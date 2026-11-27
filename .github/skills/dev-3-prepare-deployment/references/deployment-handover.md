# Deployment runbook and preflight scripts

Written by the assistant (`/dev-3-prepare-deployment`, Step 2) after the code
is generated and reviewed by `/dev-2-implement-mapping`, next to the workbook in
`specs/<folder>/`. Nothing here is executed
by the assistant: the developer reads the runbook, reviews the scripts and
runs them by hand in the target database.

| File | What it is |
|---|---|
| `DEPLOY_<MAPPING_ID>_RUNBOOK.md` | Which file runs when, as which schema, with which parameters, and what to check |
| `DEPLOY_<MAPPING_ID>_PREFLIGHT_1_BEFORE_DDL.sql` | Read-only checks run in the target database after the staging scripts are deployed and before the mapping's own DDL |
| `DEPLOY_<MAPPING_ID>_PREFLIGHT_2_BEFORE_RUN.sql` | Read-only checks run after everything is deployed, for the business date of the first run |

The `DEPLOY_` prefix keeps them apart from the generated files (the change
script is `<MAPPING_ID>.sql`, so never name one of these after the mapping
alone). Create them with the file tools, never with shell redirection.
Every file starts with the header below. When the workbook changes, rewrite
all three; a file whose fingerprint differs from the workbook's is stale.
Each preflight script's usage comment gives its path inside the deployment
package, for example `@preflight/<file> TEST`, to be run from the package folder.

```
-- Deployment handover for mapping <MAPPING_ID> (specs/<folder>/<MAPPING_ID>.xlsx)
-- mapping fingerprint <hash>, approved by <name> on <date>; prepared <YYYY-MM-DD> by the assistant
-- READ ONLY: this script runs no DDL, no DML, no GRANT and no COMMIT.
```

(Use `<!-- ... -->` in the Markdown file.)

## What to read first (all offline, never a database)

- `python tools/codegen/generate.py <MAPPING_ID> --check` - the fingerprint and the file names.
- `python tools/mapping_spec/mapping_workbook.py show <MAPPING_ID>` - target,
  package and procedure, Parameters, source tables, Columns, the Decisions,
  Preconditions and Not_For, and every acceptance criterion (the `guard`
  ones, the `zero_rows` and `expected_value` ones).
- `python tools/codegen/verify_mapping.py <MAPPING_ID>` - the planned source
  columns (their staging script is in `change-requests/<CR_ID>/staging/`),
  and any other package that already writes the target.
- The change script or table script generated for it (new table or existing
  table, and the MANUAL DECISIONS verbatim).
- When `Source_Ref` names a change request: `python tools/change_request/cr.py
  status <CR_ID>` and the Load_Plan sheet of its gap analysis
  (`python tools/change_request/cr.py read change-requests/<CR_ID>/<CR_ID>_Gap_Analysis.xlsx`).
- The jobs: the `start_run('<JOB>', ...)` calls in the package scripts in
  `sql/` of the packages that write or read the target and its sources
  (`python tools/mapping_spec/package_usage.py <SCHEMA.TABLE> ...`).

Anything the repository does not contain - a wrapper or scheduler change, a
loader that fills staging, a configuration value, a date a decision still
leaves open - is not invented. It goes under "Open items" in the runbook with
the decision or precondition that asks for it, and the owner is left for the
developer to fill in.

## The runbook

1. **Scope** - mapping, target, strategy, the change request, whether the
   target table is new or altered, and every MANUAL DECISION verbatim.
2. **Parameters to decide before starting** - a table: name, meaning, where it
   comes from (workbook Parameters, a decision, the environment), and the
   value to use. Always: the environment (`TEST` or `PROD`) and the schema the
   developer connects as (the package schema). Plus the workbook's
   parameters for the first run.
3. **Step 1 - Verify the earlier mappings of the change request are
   deployed (always present).**
   - A predecessor is every mapping of the Load_Plan with a lower `Dependency_Order`
     than this one, plus every mapping named in its `Depends_On`. List them in
     a table: mapping, Order, target, package, what must be in the database.
     Their workbook status (`approved`, code generated) is not deployment
     evidence.
   - For each, the target table and mapped columns exist and its package is
     valid: Preflight 1 section B checks it, and the developer also names the
     release record (ticket, date, who) for it.
   - Peers of the same Order are not predecessors; say so.
   - When there are none, state it and why ("Order 1, Depends_On empty"); the
     step stays, so the check is never forgotten for a later mapping.
   - Also verify the baseline loads this one reads (the upstream loads named
     in Preconditions, e.g. partner and limit): objects exist and are valid.
   - Stop when anything is missing; do not continue "to see what happens".
4. **Before changing anything** - pause the schedules and confirm no run is
   active for the jobs found above, and save the current state for rollback
   (`DBMS_METADATA.GET_DDL` of the target table and of every package that will
   be replaced, kept with the release ticket).
5. **Deployment steps in order** - a table: number, action, file, connect as,
   parameters, expected result, stop when. Name each file by its path inside
   the deployment package folder (see "The deployment package" below), not
   its repository path. Order:
   1. staging scripts of the change request that the mapping's planned
      columns need (`staging/<TABLE>.sql` in the package);
   2. the external steps the mapping's decisions name that run before it
      (for example the loader that fills the new staging column);
   3. grants: `GRANT SELECT` on each source table of another schema (the
      owner or a DBA runs them); the `INSERT` grants for the test data are
      for the test environment only. The package holds them as the files
      `grants_select` and `grants_test_only_insert` in `grants/` (Step 3 of
      the skill); name those files;
   4. **Preflight 1** (parameter: the environment);
   5. `ddl/<MAPPING_ID>.sql` when the table exists, otherwise
      `ddl/<TABLE>.sql` (plus `ddl/<TABLE>_LOAD_LOG.sql` for scd2 unless its table
      exists); say that the full `<TABLE>.sql` of an existing table is not in
      the package and must not be run;
   6. `code/<PACKAGE>.sql`; check it compiled without errors;
   7. `TEST` only: `test/UT_<TABLE>_DATA.sql`, then `test/UT_<TABLE>.sql`
      (which ends by running the tests); the report has no failures or errors;
   8. the external steps the decisions name that run after it (a wrapper that
      now calls the new package and drops the old write, a deployment-date
      setting, a scheduler change), each marked "outside this repository";
   9. **Preflight 2** (parameters: the workbook's parameters for the first
      run, then the environment).
6. **First run** - how to call it, with the parameters of the workbook: the
   procedure named in the decisions as the entry point (a wrapper) or
   `UBB_CORE2.<PACKAGE>.<PROC>` as in `tools/codegen/templates/README.md`
   ("Errors and logging"), who commits, and that the job logs it. Then the
   verification queries: each `zero_rows` and `expected_value` Check_SQL of the
   workbook unchanged with the parameter value filled in, each with the
   result that means success.
7. **Rollback** - which steps can be undone and how (restore the saved package
   source; additive nullable columns stay unless a reviewed rollback removes
   them; a loaded snapshot is escalated, not deleted); DDL commits, `ROLLBACK`
   does not undo it. When a wrapper was replaced: restore it only before the
   first successful run of the new load; after a successful snapshot escalate
   first, because the old wrapper would write the target again.
8. **Sign-off and afterwards** - what to record (environment, date, versions,
   job run ID, test report), resume the schedules, and export the new or
   changed table and package scripts into `sql/` by hand.
9. **Open items** - what is outside the repository or still undecided, as
   above.
10. **Where each file lives in the repository** - a closing table: package
    path, repository path (the runbook itself is the repository's
    `DEPLOY_<MAPPING_ID>_RUNBOOK`; the grant files are written by the tool).

## The preflight scripts

Common rules:

- One anonymous PL/SQL block per script; `SET SERVEROUTPUT ON SIZE UNLIMITED`,
  `SET VERIFY OFF`, `WHENEVER SQLERROR EXIT FAILURE`. Only `SELECT` runs, on
  `ALL_*` dictionary views (and `USER`/`SYS_CONTEXT`); no `COMMIT`.
- Parameters are positional arguments, read once at the top with
  `DEFINE p_<name> = '&1'` (`&2` ...) and used afterwards as `&p_<name>`. SQL*Plus
  substitutes `&` everywhere in the file, in strings and comments too, so the
  script has no other `&` and the header comment describes the arguments in
  words ("the first argument"). They are documented at the top, checked first,
  with the format stated. Preflight 1 takes the environment (`TEST` or
  `PROD`); Preflight 2 takes the workbook's parameters in their order (a
  `DATE` as `YYYY-MM-DD`), then the environment.
- Each check prints one line: `PASS`, `FAIL`, `WARN` or `INFO` (a fact to read,
  such as the database name or the source load IDs), an ID, what it checks and
  the detail (found / expected). A `FAIL` counts; a `WARN` and an `INFO` do not.
  A check that cannot run (a view the user may not read, an error) is a
  `FAIL`, or a `WARN` where this file says so - never silently skipped.
- The block validates its parameters first (the environment is `TEST` or
  `PROD`; a date is `YYYY-MM-DD` and at midnight) and stops with
  `RAISE_APPLICATION_ERROR(-20999, ...)` when one is wrong.
- The block ends with `RAISE_APPLICATION_ERROR(-20999, '<n> preflight check(s) failed')`
  when `n > 0`, otherwise prints `PREFLIGHT 1 OK` or `PREFLIGHT 2 OK`.
- Names come from the workbook and from `sql/`; never from memory. Quote them
  as literals in upper case, schema-qualified.
- No line is longer than a few thousand characters (SQL*Plus limits a line);
  one guard per line is fine.

Helpers (the same in both scripts; build the query, call the helper). They are
fixed code in `tools/codegen/templates/preflight_helpers.sql`: paste the part
between `BEGIN HELPERS` and `END HELPERS` unchanged, never rewrite or "improve"
a helper in one script. It also declares `g_failed`, `g_schema` and `g_env`. A
change to a helper is a change to that file:

| Helper | What it does |
|---|---|
| `report(level, id, text, detail)` | Prints one line, counts a `FAIL` |
| `cnt(sql)` / `str(sql)` | A number or a string a query returns; `-1` / `NULL` when the query itself fails, so a missing object is a `FAIL`, not a crash |
| `q(value)` | Quotes a literal for the dynamic SQL |
| `check_none(id, text, sql, level)` | `sql` returns the offending rows; none is a `PASS`; `level` is `FAIL` or `WARN` |
| `table_columns(id, owner, table, 'A, B, C')` | The table exists and has every column (one line, naming the missing ones) |
| `column_type(bad, owner, table, col, type, precision, scale, char_length, nullable)` | One column with its mapped type; a mismatch is added to `bad` and reported once |
| `valid_package(id, owner, name)` | Spec and body `VALID`, no `ALL_ERRORS` |
| `has_grant(id, owner, table, privilege)` | A direct grant to the current schema in `ALL_TAB_PRIVS` |
| `object_state(id, owner, name, type)` | Preflight 1 only: status and `LAST_DDL_TIME` for the rollback notes |

Skeleton of a script (the script's own variables, such as the business date of
preflight 2, go right after `DECLARE`, **before** the helper block: PL/SQL
requires every variable to be declared before the first procedure or function,
so a variable placed after the helpers does not compile (PLS-00103); the
helper block follows unchanged; the checks go where it says; the same
skeleton is at the top of the helper file):

```sql
SET SERVEROUTPUT ON SIZE UNLIMITED
SET VERIFY OFF
SET DEFINE ON
WHENEVER SQLERROR EXIT FAILURE
DEFINE p_env = '&1'
DECLARE
    -- variables of the script itself first (none in preflight 1 unless a check needs one)
    -- then the helper block of tools/codegen/templates/preflight_helpers.sql, unchanged
BEGIN
    IF g_env NOT IN ('TEST', 'PROD') THEN
        report('FAIL', 'P', 'the environment parameter is TEST or PROD', 'got ' || NVL(g_env, 'nothing'));
        RAISE_APPLICATION_ERROR(-20999, 'preflight stopped: the environment parameter must be TEST or PROD');
    END IF;
    -- checks here
    IF g_failed > 0 THEN
        RAISE_APPLICATION_ERROR(-20999, g_failed || ' preflight check(s) failed');
    END IF;
    DBMS_OUTPUT.PUT_LINE('PREFLIGHT 1 OK');
END;
/
```

### Preflight 1 - before the mapping's DDL

Run as the schema that owns the package, after the staging scripts and the
earlier steps of the runbook.

- **A. Where am I.** Print the database name (`SYS_CONTEXT('USERENV','DB_NAME')`)
  and the current schema; `FAIL` when the schema is not the package schema.
  The developer confirms the environment against the runbook.
- **B. Earlier mappings of the change request** (one block per predecessor of
  runbook Step 1, from its workbook): the target table exists (`ALL_TABLES`);
  every column of its Columns sheet exists with the same data type
  (`ALL_TAB_COLUMNS`); the package of its `PLSQL_Proc` has a `VALID` spec and
  body (`ALL_OBJECTS`). Print `INFO none` when there are no predecessors. Also
  the same checks for the baseline objects the Preconditions name.
- **C. What this mapping reads.** Every source table and column in the
  workbook exists, including the *planned* staging columns the staging script
  adds (their absence means that script is not deployed yet); the data type
  of each direct copy fits the target.
- **D. The target.** New table: it does not exist yet (`FAIL` if it does).
  Existing table: it exists, and each column the change script adds does not
  exist yet - already there is a `WARN` ("change script already applied"), not
  a failure.
- **E. Grants.** For each source table of another schema, `SELECT` granted to
  the package schema directly (`ALL_TAB_PRIVS`, `GRANTEE = g_schema`; a role
  does not count for a definer-rights package). With environment `TEST`, also
  `INSERT` on each source table the test data writes, and the utPLSQL package
  `UT` is present (`ALL_OBJECTS`).
- **F. Running loads.** No `CTRL_JOB_RUN` row has `RUN_STATUS = 'RUNNING'` for
  the jobs found in "What to read first" (list them in the file). `WARN` when
  an enabled scheduler job (`ALL_SCHEDULER_JOBS`) mentions one of those
  packages - the schedule is paused by the runbook, this only reminds. `WARN`
  when `V$SESSION` is not readable, otherwise `FAIL` when a session's `MODULE`
  is one of those packages.
- **G. Rollback state.** For the package that will be replaced, print its
  current status and `LAST_DDL_TIME`; `WARN` when invalid. `WARN` for every other
  invalid object in the schema.

### Preflight 2 - after deployment, before the first run

Parameters: the workbook's, in order, then the environment (`TEST` or
`PROD`). A guard or check refers to a parameter by its name in the workbook;
replace each name by its value, as a literal -
`DATE` as `TO_DATE('&p_business_date','YYYY-MM-DD')`, a number as `TO_NUMBER('&p_x')`, text as
`'&p_x'` - in the SQL text that is passed to `check_none`, quoted with
`q'~ ... ~'`. After writing, compare each embedded guard with the workbook's
Check_SQL (undo the replacement and compare the text); they must be identical.

- **A.** As Preflight 1 A.
- **B. The target as deployed.** Every column of the Columns sheet exists with
  the mapped data type, length or precision and nullability (`ALL_TAB_COLUMNS`);
  the primary key columns are the Business_Key (`ALL_CONSTRAINTS`,
  `ALL_CONS_COLUMNS`); each comment exists when the table scripts create it.
- **C. The load code.** Spec and body of the package are `VALID`
  (`ALL_OBJECTS`, and no rows in `ALL_ERRORS`); the procedure exists with the
  workbook's parameters, names, order and types (`ALL_ARGUMENTS`). The entry
  point the decisions name (the wrapper) is `VALID` too. With `TEST`, the
  `UT_<TABLE>` and `UT_<TABLE>_DATA` packages are `VALID`.
- **D. One writer.** When `verify_mapping.py` reported another package that
  writes the target (or `package_usage.py` shows one), no object other than
  this package inserts into, merges into, updates or deletes from the target:
  a case-insensitive text search of `ALL_SOURCE` (package bodies, procedures,
  functions, triggers), skipping comment lines and the `UT_*` test packages.
  A hit is a `FAIL`, and the line says it is a text search, so the developer
  looks at the hit. When the decisions say a wrapper calls the new package,
  also check that the wrapper's body mentions `<PACKAGE>.<PROC>` (text search,
  `FAIL` otherwise) and that it is `VALID`.
- **E. Grants.** As Preflight 1 E, `SELECT` only (the test-only `INSERT` stays
  in `TEST`).
- **F. Running loads.** As Preflight 1 F, plus: no `RUNNING` run for the
  business date.
- **G. The guards.** For each `guard` acceptance criterion, in the workbook's
  order: its Check_SQL, parameters replaced, as `check_none('<AC_ID>',
  '<description>', ...)`. The generated package runs the same checks when it
  loads and would stop with `ORA-20005`; this tells the developer first, with
  the row count, and names the source loads the date depends on.
- **H. The date's data is not loaded yet.** For `append`, `delete_insert`
  and `merge` loads whose Reload_Predicate or key identifies the date: the
  target has no rows for it where the workbook says a re-run is refused (a
  `WARN` where a re-run is allowed). `scd2`: the date is not before the latest
  entry of the load log unless a replay is intended (`WARN`).

### Before handing them over

- Read each script through for anything that writes: the only statements are
  `SELECT`, the PL/SQL around them and `RAISE_APPLICATION_ERROR`. There is no
  `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `ALTER`, `CREATE`, `DROP`, `GRANT`,
  `TRUNCATE` or `COMMIT` in executable code (the generated guard queries are
  `SELECT`s).
- Every name and column in them exists in `sql/` or in the workbook.
- The header fingerprint equals the one `generate.py --check` printed.
- In the runbook, every file named exists in the folder and every step has a
  parameter column, even if it says "none".
- The scripts have not been run and are not run by the assistant.

## The deployment package (Step 3 of the skill)

```
python tools/codegen/package_deployment.py <MAPPING_ID> [--include <repo file>]...
python tools/codegen/package_deployment.py <MAPPING_ID> --check
```

builds `deployment-packages/<MAPPING_ID>_<fingerprint>.zip` (the folder is
git-ignored) so the mapping can be deployed from another machine, Windows or
Linux, without the repository.

**Layout.** The zip holds one top folder named after the mapping, so the
packages of several mappings can be unpacked into the same directory without
clashes. In it, next to each other: the README, the runbook (as `RUNBOOK` in
Markdown, renamed from `DEPLOY_<MAPPING_ID>_RUNBOOK`), a manifest, a checksum
list, `verify.sh` and `verify.ps1`. Below it, one level of folders and nothing
deeper, so no path has more than two parts under the mapping's folder:

| Folder | Holds | From |
|---|---|---|
| (top) | the runbook | Step 2 |
| `staging/` | the staging script(s) the mapping's planned columns need | `change-requests/<CR_ID>/staging/` |
| `grants/` | `grants_select.sql`, `grants_test_only_insert.sql` (source tables of another schema) | written by the tool |
| `preflight/` | the two preflight scripts, same names | Step 2 |
| `ddl/` | the table script, or the change script `<MAPPING_ID>.sql` when the table exists; the load log (scd2) | the generator |
| `code/` | the load package | the generator |
| `test/` | the test data and the utPLSQL tests (test environment only) | the generator |
| `external/` | any `--include` file, by its file name | a file the developer supplies that is already in the repository, for example an approved script of an updated wrapper; never invent one |

Files keep their repository names (no dates, no folder prefixes); two files
that would share a path are refused.

**The runbook is written for the package.** It names every file by its path
inside the package folder (`ddl/<MAPPING_ID>.sql`, `preflight/DEPLOY_..._1_...`,
`staging/STG_<NAME>.sql`), tells the developer to run every command from that
folder, and ends with a table "Where each file lives in the repository". The
preflight scripts' usage line gives the same package path.

Text files are packed with LF endings and no byte-order mark. The tool refuses
when the mapping is not approved, `generate.py --check` fails, a `DEPLOY_` file
is missing or stale, or a planned staging script was not generated. It prints
the mappings that must be deployed first and are not in the package (planned
by another mapping of the change request). `--check` says whether a package
built earlier still matches the files (rebuild after any change). Unpacking a
newer package of the same mapping over an older one needs the old folder
deleted first; the README says so.

The assistant builds the zip and stops: it does not copy it anywhere, unpack it
on another machine, run `verify.sh` or `verify.ps1`, or deploy it.
