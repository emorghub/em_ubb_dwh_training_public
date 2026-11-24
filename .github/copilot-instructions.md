# Copilot Instructions - UBB DWH Training

This repository is an Oracle + Python data-warehouse training project
simulating a small bank (UBB). It showcases how analysts and developers use
an AI assistant across their workflow: from a change request, through
requirements, a data gap analysis, delivery agreement changes and
source-to-target mappings, to generated and tested database code. Layout,
schemas, conventions, and verification commands are documented in
`AGENT_BRIEFING.md` - read that first. The process itself, for people, is
`docs/WORKFLOW.md`.

This file holds process rules that don't change with the schema. Which
tool does what, the conventions and the known gaps are in
`AGENT_BRIEFING.md`. Which tables, columns and mappings exist is written
nowhere but in `sql/` and the mapping folders `specs/*/` - read them there (the commands
are in `AGENT_BRIEFING.md`); no document copies them, so none goes stale.

## Repository command working directory

Before running a command with a repository-relative path, confirm that the
current working directory is the repository root. If it needs to change,
issue the directory change as a standalone command and wait for it to succeed
before running any relative-path command. Never chain a directory change
with a relative-path command; if the change fails, stop rather than running
from the previous directory. This applies to every shell.

## When something is unclear, ask - never guess

If a request is ambiguous, or a decision is not answered by the documents,
the `sql/` scripts or the mappings, ask the person before acting - one
question at a time - instead of filling the gap with an assumption or a
"sensible default". Research first, so the question is one only a person
can answer. A guess that looks plausible is worse than an open question:
it hides the gap from the reviewer. In the analyst skills, the interview
step and the open questions in the workbook are where this happens.

## No database connection - columns come from the `sql/` folder

**Never connect to a database.** No Oracle session, no query, no tunnel, and
no tool or script that opens one - not for research, not for verification,
not to "just check a value". The `sql/` folder is the only source of truth
for table names, column names, types, nullability, keys, check constraints
and comments. It holds the scripts exported from the database, one
`*.schema` folder per schema, and `tools/mapping_spec/schema_catalog.py`
reads them.

Before writing PL/SQL, or naming a column in a mapping, verify it in those
scripts - never from memory, an example file, or another project. This
repository's own history contains a cautionary tale: `PKG_LOAN_EXPOSURE` was
first written against column names (`value_date`, `account_ref`, `ccy`) that
were never real in this repo. See `AGENT_BRIEFING.md` "Conventions that
aren't obvious from the code".

- A table with no `CREATE TABLE` script in `sql/` (the catalog reports it as
  `no_ddl`) has unknown columns. Say so and ask for the script to be
  exported; do not guess.
- What only data can answer (row counts, whether a key really is unique, the
  values a column holds) is asked of the analyst in the interview, or written
  as an acceptance criterion. The developer's utPLSQL tests check it after
  deployment, by hand.
- If the database changed, the `sql/` scripts are exported again by a person.
  Do not "refresh" them by querying.
- One exception, always labelled: a staging column that an **approved**
  change request asks for but `sql/` does not have yet is shown as
  *planned* (`schema_catalog.py` names the document that asks for it), so an analyst can map
  it before the staging change is deployed. It is never a guess: it comes
  from the approved agreement, and it disappears once `sql/` is exported
  again after deployment.

## The workflow: seven skills, a person's approval after each

A change request (CR) is worked on in `change-requests/<CR_ID>/`. Each step
writes a document a person reviews and approves (in Excel or Word) before
the next step may start; `python tools/change_request/cr.py gate` enforces
the order.

1. `/ba-1-analyse-requirement` (analyst) - the CR document becomes
   `<CR_ID>_Requirements.xlsx`: requirements, KPIs, dimensions, business
   rules, required inputs, proposed glossary changes.
2. `/ba-2-analyse-data-gaps` (analyst) - every required input is found in
   CORE, staging, a delivery agreement, a source system, or nowhere:
   `<CR_ID>_Gap_Analysis.xlsx`, with the Load_Plan (one mapping per target
   table, in order). An input no source system has is only recorded: the
   analyst takes it to the source owner.
3. `/ba-3-specify-baseline-changes` (analyst) - a source that must deliver
   more gets a new agreement version, `UBB_Delivery_Agreement_<SYS>_v<V>.docx`
   in the CR folder; the approved baseline in `business-documents/` is never changed.
4. `/ba-4-create-mapping-spec` (analyst) - one Load_Plan row (or a plain
   request) becomes a mapping workbook `specs/<folder>/<MAPPING_ID>.xlsx`,
   verified against the table scripts in `sql/`.
5. `/dev-1-implement-staging-change` (developer) - approved agreements become
   staging `ALTER`/`CREATE TABLE` scripts in `change-requests/<CR_ID>/staging/`
   (`tools/codegen/generate_staging.py`).
6. `/dev-2-implement-mapping` (developer) - an approved mapping becomes table
   DDL, a PL/SQL load package and utPLSQL tests next to its workbook
   (`tools/codegen/generate.py`).
7. `/dev-3-prepare-deployment` (developer) - a mapping with generated code gets
   a deployment runbook and two read-only preflight scripts next to its
   workbook, and a deployment package (zip) for deploying from another machine
   (`tools/codegen/package_deployment.py`).

**A named person approves every document. A developer reviews and deploys
every script by hand** - the assistant never does either.

## Approval rules

- Never set a document's `Status` to `approved`, and never write your own
  name, a tool name, or the user's name into `Approved_By` on their behalf.
  Approval is a person's act, in Excel or Word.
- Never edit workbook cells or Word documents directly; write the content as
  JSON and render it: `python tools/mapping_spec/mapping_workbook.py write`
  (mappings), `python tools/change_request/cr.py write` (requirements, gap
  analysis), `python tools/change_request/cr.py write-agreement` (delivery
  agreements). The writers refuse to record an approval and drop an existing
  one when the content changes.
- Documents of a change request are updated in place; every content change
  adds a Change_Log revision. Baseline documents in `business-documents/` (delivery
  agreements, glossary, S2T baseline, source catalog) are never changed: a
  change is a new, higher version in the change request's folder.
- Code is generated only from an approved, valid mapping. `generate.py`
  refuses otherwise. Generated files are never hand-edited; only the test
  data package `UT_<TABLE>_DATA.sql` is. A change request's staging scripts
  (`change-requests/<CR_ID>/staging/`) are never edited at all.

**A hook guards generated code.** `.github/hooks/sql_gate.json` runs
`.github/hooks/sql_gate.py` before every file edit: it
blocks edits to the `.sql` files in a mapping folder for an unapproved mapping. Hooks are a
preview feature in VS Code and an organization can turn them off, so do not
rely on the hook alone - run the same checks yourself:

```
python tools/change_request/cr.py status
python tools/mapping_spec/validate_spec.py status
python tools/mapping_spec/validate_spec.py validate
python tools/change_request/cr.py validate
python tools/mapping_spec/validate_spec.py sql-gate <.sql file in specs/<folder>/>
```

Path-scoped guidance in `.github/instructions/` reminds you of these rules
when you open a mapping workbook (`specs/*/*.xlsx`) or the generated SQL
next to it (`specs/*/*.sql`), but
nothing stops you from ignoring it. Treat it as a real commitment anyway.

## Before making changes

1. Read `AGENT_BRIEFING.md`.
2. Inspect the owning PL/SQL procedure (its source is the package script in
   `sql/`), the Python orchestrator, or the test before editing.

## Conventions

- Package and procedure names are always fully schema-qualified
  (`UBB_CORE2.PKG_X.PROC`), in mappings, generated code and tests.
- Generated load procedures never `COMMIT`; the caller (the scheduler job or
  the developer's session) owns the transaction, which is also what lets
  utPLSQL roll back each test.
- Update `AGENT_BRIEFING.md` by hand when a tool or convention changes -
  never list tables, columns or mappings in it or here.

## Skill usage

Reusable skills are in `.github/skills/<skill-name>/SKILL.md`.

- `/ba-1-analyse-requirement` - analyst: change request -> requirements workbook.
- `/ba-2-analyse-data-gaps` - analyst: approved requirements -> gap analysis and load plan.
- `/ba-3-specify-baseline-changes` - analyst: approved gap analysis -> new delivery
  agreement versions.
- `/ba-4-create-mapping-spec` - analyst: Load_Plan row or request -> verified
  mapping workbook.
- `/dev-1-implement-staging-change` - developer: approved agreements -> staging DDL
  for manual deployment.
- `/dev-2-implement-mapping` - developer: approved workbook -> generated, reviewed
  code for manual deployment.
- `/dev-3-prepare-deployment` - developer: generated code -> deployment runbook,
  preflight scripts and a deployment package (zip).
- `/query-er-diagram` - visualize SQL queries and their relationships.
- `/do-data-flow` - trace an ETL package's implemented data lineage into an SVG.

## Verification

```
python -m pytest -q
python tools/mapping_spec/validate_spec.py validate
python tools/change_request/cr.py validate
```

After changing a mapping, also run `python tools/codegen/verify_mapping.py
<ID>`; after changing a template in `tools/codegen/templates/`, see that
folder's README.
