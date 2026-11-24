---
name: dev-2-implement-mapping
description: Developer step. From an APPROVED mapping workbook specs/<folder>/<MAPPING_ID>.xlsx, re-verify the mapping (the table scripts in sql/, existing mappings), generate the create-or-alter table SQL, the PL/SQL load package and the utPLSQL tests into the mapping's own folder specs/<folder>/, next to the workbook, finish the test data, review the code against the workbook, and hand the files over for manual deployment. Never deploys. Invoke when a mapping is approved and the developer wants the code.
argument-hint: "<Mapping_ID>"
---

# dev-2-implement-mapping (developer)

You are helping a **developer** turn one approved mapping into code. The
mapping workbook is the contract; your job is to prove it still holds,
generate the code from it, finish what generation cannot do (realistic test
data), review the result, and hand it over. **You never deploy anything** -
creating the table and loading the packages is done by the developer by
hand, after reviewing your output.

Process for people: `docs/WORKFLOW.md`, step 6. Review checklist:
`references/review-checklist.md` in this skill folder. Deployment runbook,
preflight scripts and the deployment package are the next skill,
`/dev-3-prepare-deployment`.

**Running as GitHub Copilot:** the `sql_gate` hook runs for Copilot too
(`.github/hooks/sql_gate.json`), but hooks are a preview feature in VS Code
and can be turned off - check the status yourself (`validate_spec.py
status`) before touching the `.sql` files in a mapping folder. `generate.py` itself refuses
unapproved mappings in both tools. See
`.github/instructions/generated-sql.instructions.md`.

Input: **$ARGUMENTS** (a Mapping_ID)

---

## Step 1 - Preconditions (stop if any fails)

```
python tools/mapping_spec/validate_spec.py status
python tools/mapping_spec/validate_spec.py validate
python tools/mapping_spec/mapping_workbook.py show <MAPPING_ID>
```

- The workbook exists, is `approved`, and validates. If it is not approved,
  stop and say who needs to approve it (the analyst flow,
  `/ba-4-create-mapping-spec`). Never approve it yourself, never edit it.
- In Claude Code, the `sql_gate` hook blocks edits to the `.sql` files in
  a mapping folder for unapproved mappings anyway; `generate.py`
  refuses them in every tool.
- If the mapping belongs to a change request (its `Source_Ref` names one,
  e.g. `CR-ECB-001`), run `python tools/change_request/cr.py status <CR_ID>`.
  The mappings before it in the Load_Plan load first - say so if they are
  not approved or generated yet. Source columns that an approved delivery
  agreement promises but `sql/` does not have yet show up as **planned**
  (`verify_mapping.py` warns); their staging script comes from
  `/dev-1-implement-staging-change` and is deployed before this load.

## Step 2 - Verify the mapping independently

The analyst verified it when drafting; the scripts in `sql/` may have been
re-exported since, so verify again. Report each check as PASS / WARN / FAIL.

1. **The table scripts in `sql/`** (no database is ever used):
   `python tools/codegen/verify_mapping.py <MAPPING_ID>`
   Sources and columns exist, the target table's current state (new or
   existing, and how it differs), type fit and nullability of direct copies,
   whether another package in `sql/` already writes the target (WARN),
   whether each join matches a primary or unique key (else it may multiply
   rows), and that the Reload_Predicate names only target columns. Row counts and real key uniqueness
   cannot be checked without data - the generated utPLSQL tests do that after
   deployment.
2. **Existing mappings**: `python tools/mapping_spec/validate_spec.py status`
   and a look through the mapping folders `specs/*/` - does another mapping already write
   this table or these columns? Two loads writing one table - another
   mapping, or the package `verify_mapping.py` warned about - is a FAIL
   unless the mapping says why. The same value derived differently in another
   mapping is a WARN, explain.

Any FAIL: **stop**. List the problems and send the mapping back to the
analyst (`/ba-4-create-mapping-spec <MAPPING_ID>`). A developer never quietly
"fixes" an approved mapping - changing it would need a new approval anyway.

## Step 3 - Generate

```
python tools/codegen/generate.py <MAPPING_ID>
```

Writes into the mapping's own folder, next to the workbook
(`specs/<folder>/`, e.g. `specs/limit_monitor_daily/`), one file per
database object, named after the object it creates. Never write generated
code anywhere else.

- `<TABLE>.sql` - full `CREATE TABLE` (primary key, comments).
- `<TABLE>_LOAD_LOG.sql` - `scd2` only: the table of loaded dates, which
  a run for an earlier date replays.
- `<MAPPING_ID>.sql` - only if the table exists: the
  safe ALTERs, plus a MANUAL DECISIONS block for anything that could lose
  data. Surface every manual decision to the developer verbatim.
- `<PACKAGE>.sql` - the load package, shaped by the strategy, named after
  the package in the workbook's `PLSQL_Proc`.
- `UT_<TABLE>.sql` - utPLSQL tests, one per acceptance criterion.
- `UT_<TABLE>_DATA.sql` - test data, written once, never overwritten.

The SQL wording comes from `tools/codegen/templates/` (their README
explains the conventions). If generated code is wrong, the fix belongs in
the mapping (analyst) or in a template (a deliberate team change) - never a
hand-edit of a generated file, which the next generation would overwrite.
The only file you edit is the test data package.

## Step 4 - Finish the test data (`specs/<folder>/UT_<TABLE>_DATA.sql`)

The generator writes a happy path whose join keys already match; you make
it realistic and complete:

1. Choose the parameter test values (the constants at the top) so no real
   staging data matches them - the tests must not depend on what happens to
   be loaded. `DATE '2000-01-01'` works for business dates.
2. Replace every placeholder with a realistic value: the **allowed values**
   and formats you can see in the table scripts (check constraints such as
   `PARTNER_TYPE IN ('PERSON','COMPANY')`, column comments, the column
   lengths) - but prefix test IDs with `UT` so they can never collide with
   real ones. Do not query a database for sample values.
3. Add one row per case listed in the file's comment: a row outside the
   Filter, a driving row whose inner-join lookup is missing, a left-join
   row without a match, and data that each `zero_rows`/`expected_value`
   check would catch if the load were wrong. The generated tests must be
   able to fail.
   For `scd2`, also fill `seed_next_date`: the source as of `NEXT_DATE`
   with a changed key, a new key and (full snapshot) a key left out, as
   its comment lists. The history tests load both dates in both orders.
   For an aggregating mapping (`Group_By`), give at least one target row
   two source rows, so the tests prove they are summed into one.
   For each `guard`, fill its `seed_<AC_ID>` procedure with source rows
   that break it; `seed` itself must pass every guard, or every test fails
   with `ORA-20005`.
4. Remove every `TODO`.

## Step 5 - Review

Walk `references/review-checklist.md` against the workbook, item by item,
and report the result. Then:

```
python tools/codegen/generate.py <MAPPING_ID> --check
```

must report the code current (fingerprints match the workbook) and the test
data complete.

## Step 6 - Hand over, then stop

Give the developer, in this order:

1. What was verified (Step 2 results) and every MANUAL DECISION.
2. The grants `generate.py` printed (read on the source tables; insert on
   them for the test data only).
3. The files in the order they go into the database: first the staging
   scripts of the change request (`change-requests/<CR_ID>/staging/`, from
   `/dev-1-implement-staging-change`) when the mapping reads planned columns;
   then the change script (existing table) or the table script (new table);
   the package; the test data package; the test package. Mappings of one
   change request deploy in Load_Plan order. Name a prerequisite only if the
   mapping reads that planned column: check it against the `verify_mapping.py`
   WARNs (Step 2) and the workbook's Columns, Joins and Filter, never relay
   `generate.py`'s "deploy first" list unchecked.
4. How to test, by hand in SQL Developer or SQL*Plus:
   `EXEC ut.run('<SCHEMA>.UT_<TABLE>');`, then call the load procedure with
   the parameters from the workbook and commit. The load raises numbered
   errors and never logs; a scheduled job logs them with
   `UBB_CORE2.PKG_ETL_CONTROL` (example and error codes in
   `tools/codegen/templates/README.md`, "Errors and logging").
5. The next step: `/dev-3-prepare-deployment <MAPPING_ID>` writes the
   deployment runbook and the preflight scripts and builds the deployment
   package for deploying from another machine.
6. After deploying, the developer exports the new or changed table and
   package scripts into `sql/` - by hand, never by a query - so every tool
   sees the deployed state.

**Stop.** Do not deploy, do not run DDL, do not load packages, do not open a
database connection - even if
asked in the same breath; confirm the developer has reviewed the files
first and remind them deployment is theirs.

## Key invariants

- Code only from an approved, valid mapping; the workbook is never edited here.
- Generated files are never hand-edited; the test data package is the only
  generated file you write by hand.
- Every generated file carries the mapping fingerprint; `--check` must pass
  before hand-over.
- Nothing is deployed by this skill.
- No database connection of any kind: no Oracle session, query, tunnel or
  script that opens one, not even to "just check a value", not to pick test
  data, not to deploy.
