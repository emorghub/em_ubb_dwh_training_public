---
name: dev-1-implement-staging-change
description: Developer step. From the APPROVED delivery agreements of a change request (and its approved gap analysis), generate the staging DDL - ALTER TABLE for new attributes of an existing staging table, CREATE TABLE for a new delivery entity - into change-requests/<CR_ID>/staging/, compared with the table scripts in sql/ (never a database), review it against the agreements, and hand it over for manual deployment before any load that reads the new columns. Never deploys. Invoke when an agreement version of the CR is approved, or the gap analysis lists an in_interface input (delivered but not in staging).
argument-hint: "<CR_ID>"
---

# dev-1-implement-staging-change (developer)

You are helping a **developer** make staging receive what a change request
asks for. Every delivery entity `NAME` arrives in `UBB_STAGING2.STG_<NAME>`.
An agreement may deliver columns staging does not load - that is fine and
stays as it is. Staging gains only the columns the change request asks for:
the attributes its approved agreement versions mark `added` (every attribute
of a `new` entity), and the `in_interface` inputs of its approved gap
analysis, whose `Staging_Location` names the column. You generate the DDL,
review it, and hand it over. **You never deploy anything.**

Input: **$ARGUMENTS** (a CR_ID)

---

## Step 1 - Preconditions (stop if any fails)

```
python tools/change_request/cr.py status <CR_ID>
python tools/change_request/cr.py gate staging <CR_ID>
```

The gap analysis and every delivery agreement version of the change request
must be approved and valid. If not, stop and say which document needs whose
approval - never approve or edit one yourself.

## Step 2 - Generate

```
python tools/codegen/generate_staging.py <CR_ID>
```

For the columns the change request asks for (see above), it compares each
staging table script in `sql/` with the agreement and writes
`change-requests/<CR_ID>/staging/STG_<NAME>.sql`:

- **`ALTER TABLE ... ADD`** for attributes the table lacks. They are nullable:
  rows already loaded have no value.
- **`CREATE TABLE`** for an entity with no staging table yet, in the staging
  convention: `LOAD_ID` first, the attributes, `STAGED_AT` last; primary key
  `LOAD_ID` + the business key; foreign key to `UBB_CORE2.CTRL_LOAD`; one
  list partition per load; `GRANT SELECT` to `UBB_CORE2`.
- A type that differs from the table script is never changed: it is listed
  as a MANUAL DECISION in the file. Surface each one verbatim.

The SQL wording is in `tools/codegen/templates/staging_create.sql.j2` and
`staging_change.sql.j2`. A wrong file is fixed in the agreement (analyst,
`/ba-3-specify-baseline-changes`) or in a template (a deliberate team change),
**never by editing the generated file** - the `sql_gate` hook blocks that in
Claude Code (and in Copilot where hooks are enabled), and the next
generation would overwrite it anyway.

## Step 3 - Review

For each file, against the agreement it names in its header:

1. Every column the change request asks for is there, with the
   agreement's type and description (the column comment) - and nothing else:
   a delivered attribute nobody asked for is not added.
2. A new table's primary key is `LOAD_ID` plus exactly the agreement's
   business key, and those columns are NOT NULL.
3. The conventions match the existing staging scripts in
   `sql/UBB_Staging2.schema/` (e.g. `STG_COLLATERAL_1.sql`): column types,
   the `CTRL_LOAD` foreign key, partitioning by `LOAD_ID`, the grant.
4. Nothing drops, renames or narrows a column.

Then:

```
python tools/codegen/generate_staging.py <CR_ID> --check
```

must say every file is current (generated from the agreement's current
content) and none is left over.

## Step 4 - Hand over, then stop

Give the developer, in this order:

1. The files, in deployment order, and every MANUAL DECISION.
2. That they deploy as the staging schema owner **before** any load that
   reads the new columns (the mappings' code from `/dev-2-implement-mapping`
   comes after).
3. That the loader which reads each delivered file into its staging table
   must also read the new columns - it is outside this repository.
4. After deploying, the developer exports the changed staging table scripts
   into `sql/` - by hand, never by a query. Until then the tools show the
   columns as *planned*.

**Stop.** Do not deploy, run DDL or open a database connection - even if
asked in the same breath.

## Key invariants

- Staging DDL only from approved, valid delivery agreements; agreements are
  never edited here.
- Generated files are never hand-edited.
- Nothing is deployed by this skill.
- No database connection of any kind: no Oracle session, query, tunnel or
  script that opens one, not even to "just check a value".
