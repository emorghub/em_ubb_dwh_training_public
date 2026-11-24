# How the `/ba-4-create-mapping-spec` skill works

A short, plain-language explanation (about a 5 minute read) of what happens
when an analyst types `/ba-4-create-mapping-spec` in the AI assistant, and which
small programs the assistant runs along the way.

## What the skill is for

A "mapping" describes how data gets from source tables into one target table:
which source column fills which target column, how values are changed on the
way, which tables are joined, and what happens if the load runs twice. Each
mapping is saved as one Excel file: `specs/<folder>/<MAPPING_ID>.xlsx`.

The skill turns a request (a sentence typed in chat, text copied from a
ticket, a half-filled Excel file, or "please change mapping X") into that
Excel file. Later, a developer creates the real database code straight from
the file, *without asking anyone anything*. That is why every detail the code
needs must be in its own cell, written as SQL, not hidden in a sentence.

A "skill" is simply a written checklist that the AI assistant follows. This
one is in
[.claude/skills/ba-4-create-mapping-spec/SKILL.md](../.claude/skills/ba-4-create-mapping-spec/SKILL.md).
The checklist does not do the work itself: it tells the assistant which small
Python programs to run, from [tools/mapping_spec/](../tools/mapping_spec/) and
[tools/codegen/](../tools/codegen/).

## The steps

### Step 0 - Get your bearings

The assistant first reads `AGENT_BRIEFING.md`, a one-page overview of this
project, and then lists the mappings that already exist:

```
python tools/mapping_spec/validate_spec.py status
```

The list shows each mapping, its state (draft, in review, approved) and the
table it fills. From this the assistant knows what kind of job it has: a brand
new mapping, finishing a half-filled Excel file, or changing an existing
mapping.

Why this matters: if an analyst asks for "a daily load of loan limits" and the
assistant skips this, it would not know that `M_LOAN_LIMIT_DAILY` already fills
`UBB_CORE2.LOAN_LIMIT_HIST`. It would create a second mapping for the same
table, and the two loads would overwrite each other's rows.

### Step 1 - Look things up before asking

Before asking the analyst anything, the assistant finds out everything it can
on its own. It does this in three parts, from broad to narrow.

**1a. Existing mappings** in the mapping folders `specs/*/`. If another mapping already
calculates the same value, the assistant reuses that rule.

**1b. Tables and columns, from the `sql/` folder.** This folder holds the
table definitions copied out of the database (the `CREATE TABLE` scripts),
one folder per schema, such as `UBB_CORE2`. They tell the assistant the real
column names, their types, which columns may be empty, the keys, and the
allowed values. A small program,
[schema_catalog.py](../tools/mapping_spec/schema_catalog.py), reads these
scripts and turns them into a simple list of tables and columns:

```
python tools/mapping_spec/schema_catalog.py UBB_CORE2.LOAN_HIST
```

**1c. How data flows today, from the stored procedures.** The table
definitions say which columns exist, but not how data gets into them. That is
written in the existing load procedures (the `PKG_*.sql` files, also in
`sql/`). Reading all of them would take long and mostly be irrelevant, so the
assistant first picks the tables that matter (the target, the main source, the
tables to join) and asks only about those:

```
python tools/mapping_spec/package_usage.py UBB_CORE2.LOAN_HIST UBB_STAGING2.STG_LOAN
```

[package_usage.py](../tools/mapping_spec/package_usage.py) answers, for each
table, which procedure *writes* to it and which *reads* from it, with the file
name and line number. A real example:

```
UBB_CORE2.LOAN_HIST
  written by  UBB_CORE2.PKG_ETL_LOAN.LOAD_DAY  (INSERT)  sql/UBB_CORE2.schema/PKG_ETL_LOAN_1.sql:117
  read by     UBB_CORE2.PKG_ETL_LOAN.LOAD_DAY  sql/UBB_CORE2.schema/PKG_ETL_LOAN_1.sql:96
```

The assistant then opens only those procedures. What it does next depends on
what it found:

- **The target table is already filled by a procedure.** A second load would
  write to the same table, so the assistant asks the analyst first: does the
  new mapping replace the old load, or is the target table wrong?
- **A source table is filled by a procedure.** That load must run before the
  new one, so the assistant writes it down as a precondition. The code also
  shows how the source values were calculated.
- **A source table is read by a procedure.** Its joins and filters show how
  the table is really used (which keys, which date ranges), so the new mapping
  can do the same.

The program only tells which tables a procedure uses, not which columns; for
the column details the assistant reads the procedure code itself. It also
cannot see SQL that a procedure puts together as text while running
(`EXECUTE IMMEDIATE`); it points to those places so a person can read them.

One strict rule for all of Step 1: **the assistant never connects to the
database.** The files in `sql/` are the only source it trusts. If a table has
no `CREATE TABLE` script, its columns are unknown and the assistant must say
so instead of guessing. Things only real data can answer (how many rows,
whether a key is really unique) become questions for the analyst or checks
for later testing.

Every finding that influenced a decision is noted and later written to the
**Sources** sheet of the Excel file.

### Step 2 - Ask the analyst, one question at a time

Now the assistant asks only what it could not look up. One question per
message, and it repeats each answer back in one sentence before moving on.
These are the things it must never guess:

- **Grain**: one row of the target table per *what*? (For example, one row per
  loan per business date.) And the **business key**: the columns that make
  each row unique.
- **Load strategy**: what happens when the load runs twice with the same
  input. The options are `full` (replace the whole table), `delete_insert`
  (replace only the matching rows, for example one business date), `merge`
  (update rows that exist, add new ones), `append` (only add rows) and
  `scd2` (keep history: when a value changes, the old row is closed with an
  end date and a new row is added, so the table can answer "what was true
  on date X").
- **Parameters**: the values the load is started with, usually the business
  date (`P_BUSINESS_DATE`).
- **Filter**: which source rows are read.
- **Joins**: which table the load starts from, which tables are joined to it,
  and what happens when no match is found (`inner` drops the row, `left` keeps
  it with empty values).
- **Every target column**: name, type, whether it may be empty, how it is
  calculated (written as SQL), and a business name and description.
- **Out of scope**: what the load deliberately does not do, so the request
  does not keep growing.
- **Acceptance criteria**: checks that prove the load worked. The assistant
  always suggests "the key is unique", "every source row was loaded" and
  "running it twice gives the same result", plus at least one business check
  from the analyst, such as totals matching the source.

Each answer is written to the **Decisions** sheet. Anything not yet answered
stays marked `open`, and an open question blocks approval.

### Step 3 - Create the Excel file

The assistant **never types into Excel cells itself**. It writes the content
into a plain text file in a scratch folder (`.work/<MAPPING_ID>.json`), and a
program turns that text file into the Excel file:

```
python tools/mapping_spec/mapping_workbook.py write .work/<MAPPING_ID>.json
```

This creates `specs/<folder>/<MAPPING_ID>.xlsx` with the same layout every
time, and checks it right away.

### Step 4 - Double-check the Excel file before handing it over

The Excel file now exists, but the AI wrote it from research and answers.
Before a person looks at it, two programs check it automatically, so mistakes
are found now and not later, when the code fails in the database.

**First check - is the Excel file filled in correctly?**

```
python tools/mapping_spec/validate_spec.py validate
```

This checks all mapping files: are the required fields filled in, are the
values allowed ones (for example, the load strategy is one of the five
options), does the file name match the mapping ID, and does every table and
column it names exist in `sql/`.

**Second check - does it match the real tables?**

```
python tools/codegen/verify_mapping.py <MAPPING_ID>
```

[verify_mapping.py](../tools/codegen/verify_mapping.py) compares the Excel
file with the table definitions in `sql/`. What it checks, and what would go
wrong otherwise:

| It checks that... | Otherwise... |
|---|---|
| every source table and column in the file really exists | the code fails, because it reads a column that isn't there |
| a value copied unchanged fits its target column (for example, 100 characters of text into a 50-character column) | the load fails when a value is too long |
| a source column that may be empty is not copied into a target column that must never be empty | the load fails on the first empty value |
| no other procedure already fills the target table | two loads write the same table and overwrite each other |
| each join uses a key that is unique in the joined table | one source row can match several rows, so the target gets duplicates |
| the target table's existing columns are compared with the file (new, changed, missing) | nobody notices that an existing table must be changed, not created |

Each result is marked **PASS** (fine), **FAIL** (must be fixed), **WARN** (a
person must decide) or **INFO** (just for information). When something fails, the
assistant does not quietly fix it: it explains the problem to the analyst,
agrees on the fix, and creates the file again (Step 3).

**What it cannot check.** It never looks at real data, only at the table
definitions. So it cannot know how many rows a load produces, or whether a key
is really unique in the data. That is tested later, after the developer has
installed the code, using the acceptance criteria from the Excel file.

### Step 5 - Hand over and stop

The Excel file is saved with the status `in_review`. The assistant sums up the
grain, key, load strategy, joins, warnings, the decisions it made on its own,
open questions and acceptance criteria. It then explains how a *person*
approves the mapping in Excel, and stops. Creating the code is a separate
skill, `/dev-2-implement-mapping`, run by a developer.
