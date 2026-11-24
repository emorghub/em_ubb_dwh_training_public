---
name: dev-3-prepare-deployment
description: Developer step 3. From an APPROVED mapping whose code dev-2-implement-mapping has generated and reviewed, write the deployment runbook (ordered steps with schema, parameters and stop conditions, including a step that verifies the earlier mappings of the change request are deployed) and two read-only preflight scripts (table columns, grants, running loads, the mapping's guards at run time) next to the workbook, then build the deployment package, a zip with everything needed to deploy from another machine, Windows or Linux. Never deploys, never runs a script, never opens a database connection. Invoke after /dev-2-implement-mapping, when the developer wants to deploy.
argument-hint: "<Mapping_ID>"
---

# dev-3-prepare-deployment (developer)

You are helping a **developer** get one mapping, whose code is already
generated and reviewed, ready to be deployed - possibly from a machine that
does not have this repository. You write the runbook and the preflight
scripts, and build the package that holds them with the code. **You never
deploy anything, never run a script, never open a database connection**: the
developer reviews the files and runs them by hand.

Process for people: `docs/WORKFLOW.md`, step 7. Runbook, preflight scripts and
package in detail: `references/deployment-handover.md` in this skill folder.

**Running as GitHub Copilot:** the `sql_gate` hook runs for Copilot too
(`.github/hooks/sql_gate.json`), but hooks are a preview feature in VS Code
and can be turned off - check the status yourself (`validate_spec.py
status`) before writing the `DEPLOY_` files, two of which are `.sql`, into a
mapping folder: only an approved, valid mapping may have files there. See
`.github/instructions/generated-sql.instructions.md`.

Input: **$ARGUMENTS** (a Mapping_ID)

---

## Step 1 - Preconditions (stop if any fails)

```
python tools/mapping_spec/validate_spec.py status
python tools/mapping_spec/validate_spec.py validate
python tools/mapping_spec/validate_spec.py sql-gate specs/<folder>/DEPLOY_<MAPPING_ID>_PREFLIGHT_1_BEFORE_DDL.sql
python tools/mapping_spec/validate_spec.py sql-gate specs/<folder>/DEPLOY_<MAPPING_ID>_PREFLIGHT_2_BEFORE_RUN.sql
python tools/codegen/generate.py <MAPPING_ID> --check
```

- Run these yourself, in this order, before writing or building anything:
  never rely on the hook or on the assistant's permission prompt alone. The
  `sql-gate` checks tell whether the two `DEPLOY_` `.sql` files may be written
  into the mapping folder (the mapping is valid and approved); they work on
  the path, so the files need not exist yet.
- The workbook is `approved` and validates, the `sql-gate` checks pass, and
  `generate.py --check` says the code is current and the test data complete.
  If not, stop and send the
  developer back to `/dev-2-implement-mapping <MAPPING_ID>` (or, for an
  unapproved workbook, to the analyst, `/ba-4-create-mapping-spec`). Never
  approve or edit a workbook yourself.
- If the mapping belongs to a change request (its `Source_Ref` names one, e.g.
  `CR-ECB-001`), run `python tools/change_request/cr.py status <CR_ID>` and
  read the Load_Plan: the mappings with a lower `Dependency_Order`, and those in
  `Depends_On`, must be deployed before this one. Say so, and if a staging
  script the mapping needs is missing, send the developer to
  `/dev-1-implement-staging-change <CR_ID>`.
- Ask the developer which files outside the generators belong to this
  deployment, for example an approved script of an updated wrapper package or
  a loader change that is already in the repository. Anything not in the
  repository stays an open item.

## Step 2 - Prepare the deployment runbook and the preflight scripts

Write, next to the workbook in `specs/<folder>/`, with the file tools:

- `DEPLOY_<MAPPING_ID>_RUNBOOK.md` - which file runs when, as which schema,
  with which parameters, and what to check. It is written for the
  deployment package of Step 3: every file is named by its path inside the
  package folder (`staging/`, `grants/`, `preflight/`, `ddl/`, `code/`,
  `test/`), and every command runs from that folder. It always has a step that
  verifies the earlier mappings of the change request (every mapping of the
  Load_Plan with a lower `Dependency_Order`, plus its `Depends_On`) are really deployed,
  not merely approved - and says so explicitly when there are none.
- `DEPLOY_<MAPPING_ID>_PREFLIGHT_1_BEFORE_DDL.sql` - read-only checks the
  developer runs in the target database before the mapping's DDL: where
  the session is connected, the earlier mappings' objects, the source
  tables and columns (including planned staging columns), the target
  state, grants, running loads.
- `DEPLOY_<MAPPING_ID>_PREFLIGHT_2_BEFORE_RUN.sql` - read-only checks after
  deployment, for the business date of the first run: the target as
  deployed, valid packages and procedure signature, a single writer,
  grants, running loads, and every `guard` of the workbook for that date.

Everything about content, file layout and the checks is in
`references/deployment-handover.md` - follow it. Rules that matter most:

- The PL/SQL helpers of the two preflight scripts are fixed code in
  `tools/codegen/templates/preflight_helpers.sql`. Paste its helper block
  unchanged and write only the mapping's own checks; never rewrite a helper.
  `package_deployment.py` refuses a preflight script that does not carry the
  block unchanged.

- Everything comes from the workbook, the generated files, `verify_mapping.py`,
  the change request and the scripts in `sql/` - never from a database and
  never from memory. What the repository cannot answer (a wrapper or loader
  change, a scheduler setting, an open date) goes under "Open items" with
  its owner left blank; do not invent it.
- The preflight scripts only `SELECT`: no DDL, no DML, no `GRANT`, no
  `COMMIT`. They exit with an error when a check fails.
- **You write them; you never run them.** They need a database connection,
  which is the developer's, and the developer reviews them first.
- These are not generated by `generate.py` and not checked by `--check`:
  each carries the mapping fingerprint, and you rewrite all three whenever
  the workbook changes. Keep the `DEPLOY_<MAPPING_ID>_` prefix in their names.

## Step 3 - Build the deployment package

So the mapping can be deployed from another machine, Windows or Linux, without
the repository:

Before building, run again, in the same call or just before it, the checks
of Step 1 - the workbook may have changed since:

```
python tools/mapping_spec/validate_spec.py validate
python tools/mapping_spec/validate_spec.py sql-gate specs/<folder>/DEPLOY_<MAPPING_ID>_PREFLIGHT_1_BEFORE_DDL.sql
python tools/mapping_spec/validate_spec.py sql-gate specs/<folder>/DEPLOY_<MAPPING_ID>_PREFLIGHT_2_BEFORE_RUN.sql
python tools/codegen/generate.py <MAPPING_ID> --check
python tools/codegen/package_deployment.py <MAPPING_ID>
python tools/codegen/package_deployment.py <MAPPING_ID> --check
```

Stop at the first command that fails; do not run the package commands
after a failure.

It writes `deployment-packages/<MAPPING_ID>_<fingerprint>.zip` (git-ignored).
The zip holds one top folder named after the mapping, so the packages of
several mappings can be unpacked into the same directory without clashing.
In it, next to the README, sit the runbook of Step 2 (as `RUNBOOK`), a
manifest, `SHA256SUMS` and `verify.sh` / `verify.ps1`; below it, one level of
folders and nothing deeper: `staging/` (the staging script(s) the mapping
needs), `grants/` (for source tables in another schema), `preflight/` (the two
scripts of Step 2), `ddl/` (the table script, or the change script
`<MAPPING_ID>.sql`), `code/` (the load package), `test/` (test data and tests,
test environment only) and `external/` (`--include` files). Details:
`references/deployment-handover.md`, "The deployment package".

- Run it only when `generate.py --check` passes and the three `DEPLOY_` files
  of Step 2 are written for the current fingerprint; it refuses otherwise.
  Fix what it names; never work around it.
- `--include <repo file>` packs one more file the developer supplies that is
  already in the repository (for example the approved script of an updated
  wrapper package). Never write such a file yourself to fill a gap: leave
  it under "Open items" in the runbook.
- Rebuild after any change to the workbook, the generated files or the
  `DEPLOY_` files; `--check` says whether the zip still matches.
- Report the zip path and any "mappings to be deployed first" the tool prints.

## Step 4 - Hand over, then stop

Give the developer, in this order:

1. The package path, how to verify it on the other machine (`verify.sh` on
   Linux, `verify.ps1` on Windows), and the runbook inside it.
2. The parameters each script needs, and what was left under "Open items"
   (with the decision or precondition that asks for it).
3. The deployment order, which is the runbook's: first the staging scripts of
   the change request (`change-requests/<CR_ID>/staging/`, from
   `/dev-1-implement-staging-change`) when the mapping reads planned columns;
   Preflight 1; then the change script (existing table) or the table script
   (new table); the package; the test data package; the test package; the
   steps outside this repository; Preflight 2. Mappings of one change
   request deploy in Load_Plan order.
4. How to test and run, by hand in SQL Developer, SQLcl or SQL*Plus, as the
   runbook lays it out: `EXEC ut.run('<SCHEMA>.UT_<TABLE>');`, then call the
   load procedure with the parameters from the workbook. The load raises
   numbered errors and never logs; a scheduled job logs them with
   `UBB_CORE2.PKG_ETL_CONTROL` (example and error codes in
   `tools/codegen/templates/README.md`, "Errors and logging").
5. After deploying, the developer exports the new or changed table and
   package scripts into `sql/` - by hand, never by a query - so every tool
   sees the deployed state.

**Stop.** Do not deploy, do not run DDL, do not load packages, do not run a
preflight script, do not copy or unpack the package on another machine, do
not open a database connection - even if asked in the same breath; confirm the
developer has reviewed the files first and remind them deployment is theirs.

## Key invariants

- Only for an approved, valid mapping whose generated code is current; the
  workbook and the generated files are never edited here.
- The `DEPLOY_<MAPPING_ID>_*` runbook and preflight scripts are not
  generated: you write them in Step 2 and rewrite them when the workbook
  changes. Each carries the mapping fingerprint; `--check` does not look at
  them, but the package tool does.
- Nothing is deployed by this skill, the preflight scripts are not run by it,
  and the deployment package is built, never unpacked or run, by it.
- No database connection of any kind: no Oracle session, query, tunnel or
  script that opens one, not even to "just check a value", not to run a
  preflight script, not to deploy.
