---
name: ba-4-create-mapping-spec
description: Analyst step 4 of 4. Turn one row of an approved change request's Load_Plan (CR_ID and Mapping_ID), or a report request (chat, pasted ticket or page text, a half-filled workbook, or a change to an existing mapping), into a complete, verified source-to-target mapping workbook specs/<folder>/<MAPPING_ID>.xlsx (one folder per mapping, e.g. specs/loan_limit_daily/M_LOAN_LIMIT_DAILY.xlsx) that code can be generated from. Researches the existing mappings and the table scripts in the sql/ folder first (never a database), interviews the analyst only about what those cannot answer, then verifies the draft against those scripts before stopping at status in_review for a person to approve. Invoke at the start of any new load, new UBB_CORE2 table, or change to an existing table's columns.
argument-hint: "[CR_ID (all its mappings), CR_ID MAPPING_ID, request text, pasted ticket text, workbook path, or existing Mapping_ID]"
---

# ba-4-create-mapping-spec (analyst)

You are helping an **analyst** produce the mapping workbook for one load.
The workbook is the only artifact: `specs/<folder>/<MAPPING_ID>.xlsx`, in a
folder of its own named after the Mapping_ID without `M_`, in lower case
(`M_LOAN_LIMIT_DAILY` goes in the folder `loan_limit_daily`).
The writer in Step 3 creates the folder; never save a workbook anywhere else. A
developer will generate the table DDL, the PL/SQL load and the utPLSQL
tests from it **without asking anyone anything** (`/dev-2-implement-mapping`), so
every fact the SQL needs must be in a structured cell - precisely, as SQL,
never as a sentence.

You do not write PL/SQL, DDL or tests here, and you never approve.

The whole process, for people: `docs/WORKFLOW.md`. The workbook format,
cell by cell: `references/workbook-format.md` in this skill folder.

Input: **$ARGUMENTS**

---

## Step 0 - Orient

1. Read `AGENT_BRIEFING.md` (objects in `sql/`, conventions) - never trust a
   column name from memory, an example, or another project. This repo's
   history has the cautionary tale (`PKG_LOAN_EXPOSURE` was once written
   against columns that never existed here).
2. `python tools/mapping_spec/validate_spec.py status` - what mappings exist.
3. Work out which path you are on:

| You were given | Path |
|---|---|
| A description in chat | A - new mapping |
| A ticket or page reference (e.g. `UBB-42`) | A - there is no ticket integration; ask the analyst to paste the text, and record the key in `Source_Ref` |
| A path to a workbook someone started in Excel | B - complete it |
| An existing `Mapping_ID` | C - change it |
| A change request and one of its mappings (`CR-ECB-001 M_COLLATERAL_RECOGNITION`) | D - a row of the approved Load_Plan |
| A change request only (`CR-ECB-001`), or its gap analysis file (`CR-ECB-001_Gap_Analysis.xlsx`) with no Mapping_ID | E - EVERY Load_Plan row not started, one after the other, in `Dependency_Order`; never just the first |
| Nothing | Report `status` (and `python tools/change_request/cr.py status`), ask what the analyst wants to build |

Record where the request came from in `Source_Ref` (ticket key, URL, or `chat`).

**Path D - a mapping of a change request.** The change request already went
through `/ba-1-analyse-requirement`, `/ba-2-analyse-data-gaps` and, where a
source must deliver more, `/ba-3-specify-baseline-changes`. Start with

```
python tools/change_request/cr.py gate mapping <CR_ID> <MAPPING_ID>
```

and stop if it says NOT YET - it names what is missing (an approval, a
delivery agreement version). Then read what was decided, from the approved
documents, never from memory:

```
python tools/change_request/cr.py show <CR_ID> gap_analysis --json
python tools/change_request/cr.py show <CR_ID> requirements --json
```

- The Load_Plan row is the brief: target table, grain, purpose, the mappings
  it depends on (they load first: `Preconditions`), its `Input_IDs` and
  `Req_IDs`. A different target or grain is a change of the gap analysis
  (back to `/ba-2-analyse-data-gaps`), not a decision taken here.
- The Gaps rows of its inputs say where each value is (`Core_Location`,
  `Staging_Location`) - verify each in `sql/` as in Step 1.
- The KPIs and Business_Rules of the requirements are the rules this mapping
  turns into SQL (formula, rounding, caps, missing inputs). A decision they
  already record goes on the Decisions sheet as `decided`, with the document
  and row as the reference on the Sources sheet - do not ask it again. What
  they leave open is a question for Step 2.
- `Source_Ref` = `<CR_ID> Load_Plan <MAPPING_ID>`; `Intent` names the
  `Req_IDs`.
- Every acceptance scenario of the change request this mapping serves becomes
  an acceptance criterion, and its `Notes` name the `REQ-..` and `IN-..` IDs
  it proves: `python tools/change_request/cr.py trace <CR_ID>` follows them.
- The mappings it depends on (`Depends_On`) must already have a workbook,
  in review or approved - the gate says so. What they create is not in
  `sql/` yet: see "Planned columns" in Step 1d.

**Path E - a whole change request** (`/ba-4-create-mapping-spec CR-ECB-001`,
no Mapping_ID; a gap analysis file means the same, its CR_ID is the folder name).
Do not ask which mappings to do and do not stop after the first: the answer is
all of them, ordered by the Load_Plan `Dependency_Order` column (rows with the same
`Dependency_Order` are independent, take them in the order listed). Keep a todo per row
and finish none of the turn until every row is written or skipped with a
reason. Run `python tools/change_request/cr.py status <CR_ID>` and take
the Load_Plan rows that are `not started`, in `Dependency_Order` (an earlier `Dependency_Order` can
be read by a later one, so never out of order). Then, for **each** row in turn,
the whole of Path D, Steps 0-4, with that mapping's own gate, research,
interview (one question at a time, nothing carried over from another mapping
unless the requirements record it), writing and verification. Do not wait for
a person to approve a mapping before starting the next: its workbook, in
review, already makes its target tables and columns visible as planned to the
mappings after it.

- A row that already has a workbook is skipped, never rewritten (a change to
  it is path C). A row whose gate says NOT YET - an agreement not approved -
  is skipped and listed with the reason; so is every row that depends on it.
- If an earlier mapping changes after a later one was written (an answer in a
  later interview changes its target), run `verify_mapping.py` again for the
  later mappings: they read the earlier workbook every time.

Hand over once at the end (Step 5): a table of `Dependency_Order`, `Mapping_ID`, status,
open questions and the verification warnings for every mapping, then the order
in which a person approves them. A mapping cannot be approved before the
mapping it reads from (the validator names it). Then **stop**.

## Step 1 - Research before asking anything

Collect facts from two sources and record every finding that shaped a
decision as a row on the **Sources** sheet (`source_type`: sql, user,
other). Do this before the interview: the analyst's time goes to decisions,
not to facts you could look up.

**1a. Existing mappings** - `specs/*/*.xlsx`
(`python tools/mapping_spec/validate_spec.py status` lists them). If another
mapping already derives the same value, or already writes the same target
table, reuse its rule or explain the difference.

**1b. The scripts in `sql/`** - one `*.schema` folder per schema. **Never
connect to a database** - no Oracle session, query, tunnel or script that
opens one, not even to "just check a value" (see the project's
assistant instructions file). Table scripts give column names,
types, nullability, primary/unique/foreign keys, check constraints (allowed
values) and table comments; the `PKG_*.sql` scripts are the existing PL/SQL
(how a join is really written, which load must run first). List the tables with
`python tools/mapping_spec/schema_catalog.py`, read one with
`python tools/mapping_spec/schema_catalog.py UBB_CORE2.LOAN_HIST`, or open
the file. A table the catalog reports as `no_ddl` has no
`CREATE TABLE` script: its columns are unknown - tell the analyst, do not
guess.

**1c. The existing loads of those tables.** Once you know which tables
matter - the target, the driving table, the tables you expect to join - run,
for those tables only:

```
python tools/mapping_spec/package_usage.py <SCHEMA.TABLE> [<SCHEMA.TABLE> ...]
```

It lists, from the package scripts in `sql/`, which procedures write each
table and which read it, with file and line. Then read every procedure it
names (not the whole package folder):

- **The target is already written by a procedure** - a second load would
  write the same table. Tell the analyst before anything else: does this
  mapping replace that load (path C), or is the target wrong?
- **A source is written by a procedure** - that load must run first; note it
  in `Preconditions`. Its code shows how the column you read was derived.
- **A source is read by a procedure** - its joins and filters show how the
  table is really used (keys, validity dates, source-system filters); reuse
  them or explain the difference.

The tool finds tables, not columns, and cannot see SQL built at run time
(`EXECUTE IMMEDIATE`); it lists those places to read by hand. Record each
procedure that shaped a decision on the Sources sheet (`source_type` sql).

**1d. Gap analysis - is every source field the request needs really
there?** A request often needs a field no staging table has yet (a haircut,
a risk parameter, a priority). Do not stop at "not in `sql/`": find out
whether a source system could deliver it. The analysts' source systems
catalog (`business-documents/*Source_Systems*.xlsx`) lists every attribute each
source has and whether today's interface delivers it:

```
python tools/mapping_spec/source_catalog.py find <word> [<word> ...]
python tools/mapping_spec/source_catalog.py gaps <STG_TABLE> [<STG_TABLE> ...]
```

`find` searches names and descriptions; `gaps` lists, for the staging
tables this mapping reads, every attribute that is not simply delivered.
Each comes back with a status:

| Status | What it means | What the analyst needs |
|---|---|---|
| `interface_change` | the source has it, the staging table exists, the column does not | an interface change request: delivery agreement, staging and core column |
| `new_interface` | the source has it, nothing receives it | a new interface: delivery agreement, staging table, core table |
| `catalog_conflict` | the catalog and `sql/` disagree (a column the catalog calls delivered is missing, or the reverse, often a stale duplicate row) | someone corrects the catalog or re-exports `sql/` - before it is mapped |
| (no match) | neither the catalog nor `sql/` knows it | the business says where it comes from |

Record every gap the mapping depends on as an **open** row on the Decisions
sheet, Topic `Gap: <TABLE>.<COLUMN>`, the Question naming the status and
what is needed, and the catalog row on the Sources sheet (`source_type`
other, the catalog file and sheet). An open gap blocks approval, which is
right: a mapping cannot be generated against a column that does not exist.
Never map such a column as if it were there. Run `gaps` for every staging
table the mapping reads even when nothing seems missing - a
`catalog_conflict` on a column you use means one of the two documents is
wrong, and the analyst must hear it.

**Planned columns (path D).** A column that an approved delivery agreement
of the change request promises, but that is not deployed yet, is already in
the table list: `schema_catalog.py` marks it *planned* and names the
agreement. Map it like any other column - `verify_mapping.py` warns that the
staging change (`/dev-1-implement-staging-change`) must be deployed first.
In path D the gap analysis already classified every input: a gap it did not
foresee is not solved here - stop and send it back to `/ba-2-analyse-data-gaps`.

A table or column that **another mapping of the same change request** creates
(a `Depends_On` mapping that loads a new table, or adds columns to an existing
one) is not in `sql/` until that mapping's code is deployed and `sql/` is
exported again. Once its workbook exists, `in_review` or `approved`,
`schema_catalog.py` shows it as planned too, as `mapping <ID> (<status>)`,
taken from that workbook's Columns sheet - never from memory. Map it like any
other column; `verify_mapping.py` warns that the earlier mapping must be
deployed first. The workbook is read every time, so if it changes, the next
verification shows it. A mapping cannot be approved while the mapping it reads
from is not approved (the validator names it). The mapping's own target is
always compared with `sql/` as it is, never with planned columns.

A fact you cannot find in any of these places (what values a column really
holds, how many rows) is a question for Step 2's interview, not a guess, and
may become an acceptance criterion.

## Step 2 - Interview: one question at a time

Ask only what research could not answer. One question per message, restate
the answer in one sentence before the next, never batch, never assume a
default. Record each on the **Decisions** sheet (`status: decided`, who,
when); anything unresolved stays `open` - that blocks approval, which is
the point.

Decisions never to guess:

- **Grain** - one row per what? And the **business key** that makes a row
  unique (becomes the primary key, all columns `Nullable = N`). If the grain
  is coarser than the driving table's rows (several collateral items summed
  per loan), the mapping aggregates: `Group_By` lists the columns of one
  target row, and every other column is an aggregate - ask how each one is
  summed and rounded, and whether a joined row can be counted twice (see
  "Aggregating loads" in `references/workbook-format.md`).
- **Caps and allocations in order** - when a sum must not exceed a limit
  (recognised collateral at most the exposure), ask how the cap is shared:
  **proportionally** (`LEAST(SUM(...), MAX(gross))`, one aggregating
  mapping) or **by priority** (the first item fills first, e.g. by
  `ALLOCATION_PRIORITY`). Priority needs a running total per item, written
  on the Item_Columns sheet with a window function, and it needs the
  ordering column to exist in `sql/` - if it does not, it is a gap (Step
  1d). Record the choice on the Decisions sheet.
- **Load strategy**, i.e. what a re-run of the same parameters does:
  `full` (replace the whole table), `delete_insert` (replace the rows
  matching `Reload_Predicate`, e.g. `BUSINESS_DATE = P_BUSINESS_DATE`),
  `merge` (update existing keys, insert new ones; `SCD_Type 0` columns are
  never updated), `append` (insert only; a re-run fails), `scd2` (keep
  history: a change closes the current version and adds a new one). For
  `scd2` also ask: which columns are tracked (`SCD_Type 2`) and which are
  only written with each version (`0`); `Source_Snapshot` - does every run
  deliver every key (`full`: a missing key was deleted) or only changes
  (`delta`); and can the source still be read for an earlier date (the
  one `DATE` parameter must be used in the `Filter` or a join), because a
  late date replays the later ones. Rules: `references/workbook-format.md`.
- **Parameters** of the load procedure (usually `P_BUSINESS_DATE DATE`). A
  parameter must never share a name with a column (PL/SQL would silently
  read the column) - use the `P_` prefix.
- **Row scope** (`Filter`) - which source rows a run reads, or `none`. Ask
  even when "all rows" seems obvious.
- **Joins** - the driving table (one of its rows = one target row), each
  joined table, and for each: what happens to a driving row with no match?
  Left out (`inner`) or kept with empty values (`left`). Propose the
  condition from the keys and `*_REF` columns in the table scripts, and say
  so when the join is likely to multiply rows (the columns it uses are not a
  primary or unique key of the joined table) - confirm that is really the
  intended grain. Step 4 checks this against the declared keys.
- Every **target column**: name, Oracle type, nullable, the rule as SQL,
  and its business name and description (they become the column comment -
  write them for a business reader).
- What is **out of scope** (`Not_For`) - stops scope creep later.
- **Acceptance criteria** - how anyone can tell it worked. Always propose
  `unique_key`, `all_source_rows_loaded`, and `rerun_idempotent` (unless
  `append`); then at least one business check of the analyst's own as
  `zero_rows` (SQL that finds violating rows) or `expected_value` (SQL
  returning one value that must equal `Expected`), e.g. a reconciliation
  of totals against the source. Then ask: is there source data that must
  stop the **whole run** rather than be loaded or left out (a missing
  parameter, an ambiguous reference, a load that has not completed)?
  Each becomes a `guard`: SQL that finds those source rows; the load
  checks it before writing anything and fails, so nothing partial is
  written.

## Step 3 - Write the workbook

Never edit cells yourself. Build the mapping as JSON and let the tool
render it:

1. `python tools/mapping_spec/mapping_workbook.py schema` - the JSON shape
   and every field's meaning.
2. Write the JSON to `.work/<MAPPING_ID>.json` (a git-ignored scratch
   folder - create it if it is missing; path C: start from
   `python tools/mapping_spec/mapping_workbook.py show <ID> --json`).
3. `python tools/mapping_spec/mapping_workbook.py write .work/<MAPPING_ID>.json`
   - writes `specs/<folder>/<MAPPING_ID>.xlsx` and validates it.
   - Status must be `draft` or `in_review`; the tool refuses `approved`
     and refuses to fill `Approved_By`/`Approved_On`.
   - Path C: changed content automatically drops a previous approval;
     note the change and its reason on the Decisions sheet.

Rules for the cells (full detail in `references/workbook-format.md`):

- `Transformation_Rule` is SQL only: `direct`, `NULL`, or an Oracle
  expression usable in a `SELECT`, columns written as `TABLE.COLUMN`
  (bare table name): `TRIM(UPPER(STG_LOAN.LOAN_REF))`. Explanations go
  in `notes`.
- A value with no source column: `source_table` `PARAM` (a parameter, named
  in `source_column`) or `EXPR` (computed, e.g. `SYSTIMESTAMP`).
- `Check_SQL` may use parameters by name (`P_BUSINESS_DATE`), must not end
  with `;`.
- An unresolved fact is written `TODO: ...` - never a plausible guess.
- **Suggestions.** Where research supports a proposal but the analyst has not
  answered (and no one is available to ask), write it as `SUGGESTION: ` at the
  very start of the cell (Decisions `Decision`, Notes), then the proposal and
  what remains uncertain - the same marker `/ba-1-analyse-requirement` and
  `/ba-2-analyse-data-gaps` use. Never write `PROPOSED` or any other wording.
  The Decisions row stays `open` (never `decided`; `Decided_By`/`Decided_On`
  empty): only the analyst's answer decides. To accept, the analyst deletes the
  prefix, sets the row `decided` and fills the name and date. Base it only on
  the documents and `sql/`; with no support, write `TODO: ...` with the question.
- **Never fill the people and date fields on your own:** `Owner`,
  `Approved_By`, `Approved_On`, and any other field that names a person or
  records a date (for example a created, requested or reviewed date). Do not
  use the user's name, the git user, the OS user, a tool name or today's date
  to fill them. Leave them empty; the analyst fills them in Excel. Fill one
  only if the analyst states the value explicitly in this conversation (for
  example "the owner is Maria"). `Source_Ref` is only what the analyst
  actually gave you (ticket key, URL) or `chat`.

**Path B (half-filled workbook):** read it with
`mapping_workbook.py show <path> --json`, fill the gaps through Steps 1-2,
then write it as in Step 3 to `specs/<folder>/<MAPPING_ID>.xlsx`.

**Path C, a table with no mapping yet** (e.g. `UBB_CORE2.LOAN_HIST`,
loaded today by `UBB_CORE2.PKG_ETL_LOAN`):
first write a **baseline** mapping that describes today's load exactly -
read it from the package script in `sql/` and the table scripts,
record "baseline reconstructed from <PACKAGE> script" on the Decisions sheet - then apply the requested change on top.

## Step 4 - Prove it against the table scripts

```
python tools/mapping_spec/validate_spec.py validate
python tools/codegen/verify_mapping.py <MAPPING_ID>
```

`verify_mapping.py` reads only the scripts in `sql/`. It checks that every
source table and column exists, that direct copies fit their target type, that
a nullable source is not copied into a NOT NULL column unchecked, how the
target differs from the table script (new, retyped, missing), whether another
package in `sql/` already writes the target table, whether each join matches
a primary or unique key (otherwise it may multiply rows), and that the
Reload_Predicate uses target columns. It cannot see data: row counts, real
key uniqueness and rows left out by an inner join are what the
acceptance criteria and the developer's tests check after deployment - say so
to the analyst. Every FAIL is a conversation with the analyst, then a rewrite
(Step 3) - never a silent tweak.

## Step 5 - Hand over, then stop

1. Write the workbook with Status `in_review`.
2. Tell the analyst, in this order:
   - target table and grain; business key
   - load strategy and what a re-run does
   - row scope and each join with its type
   - the verification warnings (grain, nullability, types) and what only the
     tests can check
   - every decision you made that they did not state explicitly
   - the gaps (Step 1d): each missing table or column with its status and
     the change request it needs, and every `catalog_conflict`
   - open questions, numbered
   - the acceptance criteria
3. Tell them how to approve: open `specs/<folder>/<MAPPING_ID>.xlsx` in
   Excel, Mapping sheet: `Status = approved`, `Approved_By` = their own name,
   `Approved_On` = today (YYYY-MM-DD); then
   `python tools/mapping_spec/validate_spec.py validate` must say OK.
4. Next step, for the developer: `/dev-2-implement-mapping <MAPPING_ID>` -
   preceded by `/dev-1-implement-staging-change <CR_ID>` when the mapping
   reads planned columns. Path D: also name the next Load_Plan row
   (`python tools/change_request/cr.py status <CR_ID>`). Planned columns of
   another mapping: it is generated and deployed before this one.
5. **Stop.** Do not generate code in the same turn.

## Key invariants

- You never set `approved`, never write a name into `Approved_By` - not
  yours, not the user's on their behalf. If asked to approve, explain the
  Excel steps; the person does it.
- You never fill `Owner`, dates or any other person-or-date field by
  yourself (see Step 3). Empty is correct; a guessed value is wrong.
- A changed mapping loses its approval (the writer enforces this).
- Column names and types come from the table scripts in `sql/`, never from a
  database and never from memory. Step 4 checks the whole mapping against
  those scripts - no column name is treated as final until it does.
- No live database pull, ever: no Oracle session, query, tunnel or script
  that opens one, not even to "just check a value". What only data can answer
  goes to the interview or becomes an acceptance criterion.
- Every finding that shaped a decision is on the Sources sheet; every
  question is on the Decisions sheet.
- The workbook is the single source of truth. There is no Markdown copy.
