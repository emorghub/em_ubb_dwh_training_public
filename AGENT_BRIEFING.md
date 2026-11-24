# AGENT_BRIEFING.md

> Read this first. It holds what does not change when the database does: the
> tools, the conventions and the known gaps. It deliberately lists no tables,
> columns or mappings - read those from `sql/` and the mapping folders `specs/*/` (below).
> When a tool or convention changes, update this file by hand.

## What this repo is

A training project simulating a small bank's data warehouse (UBB DWH), built
to show how analysts and developers use an AI assistant (Claude Code or
GitHub Copilot). `UBB_STAGING2` holds source-shaped staging tables and
`UBB_CORE2` holds core tables and the PL/SQL packages that load them. A
change request goes through seven skills, each ending at a document a person
approves, described for people in `docs/WORKFLOW.md`: the analyst writes the
requirements (`/ba-1-analyse-requirement`), the gap analysis and load plan
(`/ba-2-analyse-data-gaps`), new delivery agreement and glossary versions
(`/ba-3-specify-baseline-changes`) and one mapping workbook per load
(`/ba-4-create-mapping-spec`); the developer generates, reviews and deploys
the staging changes (`/dev-1-implement-staging-change`) and the load code
(`/dev-2-implement-mapping`), and gets a deployment runbook, preflight scripts
and a deployment package for it (`/dev-3-prepare-deployment`). A small request
without a change request starts directly at `/ba-4-create-mapping-spec`.

The separate `/query-er-diagram` skill visualizes SQL queries as SVG diagrams
of their joins, cardinalities and filters. It reads the exported schema and
does not execute queries or form part of the approval workflow.

The separate `/do-data-flow` skill traces an ETL package's implemented row
lineage and transformations into a standalone SVG, without treating fixture
behavior as approved business policy. Its diagrams use the full package name
as title and arrow samples in the legend; an existing diagram is deleted
without reading it only when a person chooses a redraw. The SVG is drawn from
a layout spec by `tools/data_flow/flow_svg.py`, which refuses a connector
without cited package lines and then checks the result (text fit, connector
and label overlaps, gaps, dead ends, palette contrast and colour-vision
distinctness); the skill requires zero defects before delivery.

## Repository command working directory

Before running a command with a repository-relative path, confirm that the
current working directory is the repository root. If it needs to change,
issue the directory change as a standalone command and wait for it to succeed
before running any relative-path command. Never chain a directory change
with a relative-path command; if the change fails, stop rather than running
from the previous directory. This applies to every shell.

## No database connection - the `sql/` folder is the source of truth

The assistant never connects to a database (see `CLAUDE.md`). Everything it
knows about the schemas comes from the scripts in `sql/`:

- `sql/UBB_CORE2.schema/` - tables, constraints, indexes, sequences and the
  `PKG_ETL_*` packages of `UBB_CORE2`, as exported by SQL Developer.
- `sql/UBB_Staging2.schema/` - `UBB_STAGING2`.
- `tools/mapping_spec/schema_catalog.py` reads the `CREATE TABLE`,
  constraint, comment and grant statements in those folders (columns, types,
  nullability, primary/unique/foreign keys, check constraints, comments).
- `tools/mapping_spec/package_usage.py <SCHEMA.TABLE> ...` lists which
  package procedures write or read the given tables (from the package body
  scripts, with file and line). It finds tables, not columns: how a column is
  derived is read by opening the procedure it names.
- A person re-exports the scripts when the database changes. Nothing
  refreshes them by querying.
- **Planned staging columns** are the one, labelled addition:
  `schema_catalog.catalog()` also holds the staging tables and columns that
  an **approved** change request asks for but `sql/` lacks
  (`tools/change_request/planned_staging.py`): the attributes its approved
  agreement versions mark `added` (or a `new` entity), and the `in_interface`
  inputs of its approved gap analysis. They are marked `planned` with the
  document that asks for them. An agreement may deliver columns staging does
  not load; those are never planned. An entity `NAME` arrives in
  `UBB_STAGING2.STG_<NAME>`. `verify_mapping.py` warns about every planned
  column a mapping reads, `source_catalog.py` reports it as `planned`, and
  `schema_catalog.load_catalog()` (what the generators compare against) never
  includes them. `UBB_PLANNED_STAGING=off` turns the overlay off.
- **Planned mapping targets** are the second labelled addition, same overlay:
  the tables and columns the Load_Plan mappings of an approved change request
  create (`tools/change_request/planned_mappings.py`), read from the workbook
  of every such mapping that is `in_review` or `approved` and marked
  `mapping <ID> (<status>)`. They let a later mapping (higher `Dependency_Order`) be
  specified before an earlier one is deployed. The gate
  (`cr.py gate mapping`) requires a workbook for every `Depends_On` mapping, a
  mapping cannot be approved while an upstream one it reads is not approved,
  and a mapping's own target is always compared with
  `schema_catalog.deployed_table()` (`sql/` only).

## Key files

| File | Purpose |
|---|---|
| `sql/*.schema/` | The exported database scripts: the only source of truth for tables and columns |
| `docs/WORKFLOW.md` | The analyst -> developer process and the skills |
| `business-documents/` | The analysts' baseline documents: the change request, glossary, S2T baseline, source systems catalog and the approved delivery agreements. Read with `cr.py read`; never changed |
| `change-requests/<CR_ID>/` | One folder per change request: `<CR_ID>_Requirements.xlsx`, `<CR_ID>_Gap_Analysis.xlsx` (with the Load_Plan), new delivery agreement versions `UBB_Delivery_Agreement_<SYS>_v<V>.docx`, a new glossary version `UBB_Credit_Risk_Business_Glossary_v<V>.xlsx`, generated `staging/STG_*.sql`, and the generated `<CR_ID>_Traceability.xlsx` |
| `tools/change_request/cr.py` | Command line for change requests: `read` any .docx/.xlsx, `schema`, `write`, `show`, `agreement-json`, `write-agreement`, `glossary-json`, `write-glossary`, `validate`, `status`, `gate`, `trace` |
| `tools/change_request/ba_documents.py` | Layout, validation and approval rules of the requirements and gap analysis workbooks |
| `tools/change_request/delivery_agreement.py` | Reads the delivery agreements (the v1.0 Word layout and its own), writes new versions, validates them |
| `tools/change_request/glossary_version.py` | Reads the glossary, writes a change request's new glossary version from the requirements' Glossary_Changes, validates it against both |
| `tools/change_request/workflow.py` | Which step may start (`gate`), from the approval state of the documents before it |
| `tools/change_request/planned_staging.py` | Staging tables and columns the approved agreements promise, compared with `sql/` |
| `tools/change_request/planned_mappings.py` | Tables and columns the earlier Load_Plan mappings of a change request create, read from their workbooks |
| `tools/codegen/generate_staging.py` | Generates staging `ALTER`/`CREATE TABLE` scripts from a change request's approved agreements |
| `tools/codegen/package_deployment.py` | Builds `deployment-packages/<MAPPING_ID>_<fingerprint>.zip` of one approved mapping (git-ignored): one top folder named after the mapping (several packages unpack into one directory without clashes) with the README and the runbook side by side, then one level of folders (`staging/`, `grants/`, `preflight/`, `ddl/`, `code/`, `test/`, `external/`), checksums and `verify.sh` / `verify.ps1`, for deploying from another machine, Windows or Linux; `--check` compares it with the files now. Never deploys |
| `tools/data_flow/flow_svg.py` | `/do-data-flow`: `render` a layout spec (JSON) to an SVG and `check` any such SVG for layout, label, lineage-evidence and palette defects; exits 1 on a defect |
| `specs/<folder>/<MAPPING_ID>.xlsx` | One mapping workbook per load, each in its own folder (the Mapping_ID without `M_`, lower case, e.g. `specs/loan_limit_daily/`): the source-to-target contract code is generated from |
| `tools/mapping_spec/schema_catalog.py` | Reads the table scripts in `sql/` (no database) |
| `tools/mapping_spec/package_usage.py` | Which package procedures write or read given tables (no database) |
| `tools/mapping_spec/source_catalog.py` | Gap analysis: the analysts' source systems catalog (`business-documents/*Source_Systems*.xlsx`) compared with `sql/` - which attributes need an interface change, a new interface, or a correction because the two disagree |
| `tools/mapping_spec/workbook_format.py` | The workbook layout: read and write the Excel file, fingerprint |
| `tools/mapping_spec/mapping_workbook.py` | Command line to write, show and diff workbooks (`write` never records an approval) |
| `tools/mapping_spec/mapping_validation.py` | The validation rules for a mapping |
| `tools/mapping_spec/validate_spec.py` | `validate`, `status`, `sql-gate` |
| `tools/codegen/verify_mapping.py` | Checks a mapping against the scripts in `sql/` (columns, types, nullability, grain from the keys, other loads of the target) |
| `tools/codegen/generate.py`, `sqlmodel.py`, `templates/` | Generates DDL, the load package and utPLSQL tests from an approved mapping |
| `specs/<folder>/*.sql` | Generated code, written next to the mapping's workbook, one file per database object: `<TABLE>.sql`, `<TABLE>_LOAD_LOG.sql` (`scd2` only), `<MAPPING_ID>.sql` (change script), `<PACKAGE>.sql`, `UT_<TABLE>.sql`, `UT_<TABLE>_DATA.sql` |
| `specs/<folder>/DEPLOY_<MAPPING_ID>_*` | Not generated: the deployment runbook (`_RUNBOOK.md`) and the two read-only preflight scripts (`_PREFLIGHT_1_BEFORE_DDL.sql`, `_PREFLIGHT_2_BEFORE_RUN.sql`) that `/dev-3-prepare-deployment` writes after the code, never runs, and rewrites when the mapping changes; their format is `.github/skills/dev-2-implement-mapping/references/deployment-handover.md`. Keep the `DEPLOY_<MAPPING_ID>_` prefix |
| `tests/` | pytest tests of the tools; none needs a database |
| `.claude/hooks/`, `.github/hooks/` | `sql_gate.py` and `_hooklib.py` (PreToolUse block: generated SQL of unapproved mappings, and every edit to a change request's generated staging scripts); each assistant folder holds its own identical copy, run by Claude Code (`.claude/settings.json`) and by Copilot (`.github/hooks/sql_gate.json`) |
| `.claude/skills/`, `.github/skills/` | The skills, for Claude Code and for Copilot |
| `.vscode/settings.json` | Copilot auto-approval for the repository's own tools in their documented form (`cr.py` writers only from `.work/*.json`) and for edits in `specs/` and `.work/`; never for `change-requests/`, `generate.py --reset-test-data`, pipes or inline scripts. Update it when a tool or command form changes |

## Objects in `sql/`

The `sql/` folder is the whole truth about the database; nothing here copies
it. Every tool reads it directly, so a table exported into `sql/` is known
to all of them at once. To see what is there now:

```
python tools/mapping_spec/schema_catalog.py                      # every table, per schema
python tools/mapping_spec/schema_catalog.py UBB_CORE2.LOAN_HIST  # its columns, keys, checks, comments
python tools/mapping_spec/package_usage.py UBB_CORE2.LOAN_HIST   # which procedures write or read it
python tools/mapping_spec/source_catalog.py gaps STG_LOAN         # what the source has that sql/ does not
python tools/mapping_spec/validate_spec.py status                # every mapping and its state
```

A table listed as `no CREATE TABLE script` has unknown columns: ask for it to
be exported, do not guess. The `ANNOTATIONS_*` tables belong to the SQL
Developer extension, not to this project.

## Conventions that aren't obvious from the code

- Before writing or fixing any PL/SQL against a table, verify the real column
  names in the table script under `sql/` - do not assume names from an
  example, a spec template, or another project.
- Package and procedure names are always fully schema-qualified
  (`UBB_CORE2.PKG_X.PROC`).
- Mapping workbooks are never edited cell by cell by an assistant: the
  mapping is written as JSON and rendered with `mapping_workbook.py write`,
  which refuses to record an approval and drops an existing one when the
  content changes. The change-request documents follow the same rules through
  `cr.py write`, `cr.py write-agreement` and `cr.py write-glossary`.
- Change-request documents are updated in place: every content change is a
  new revision on the Change_Log sheet, and git keeps the earlier states. A
  document records the fingerprint of the approved one it was built from
  (`Based_On`); when that one changes, the later one fails validation until
  it is rewritten and approved again.
- Baseline documents in `business-documents/` are never changed. A delivery
  agreement change is a new, higher version (v1.1; v1.0 for a new source) in
  the change request's folder, and it is the whole contract. A glossary
  change is decided in the requirements (Glossary_Changes, ba-1) and written
  by ba-3 as a new glossary version only after the gap analysis is approved;
  it is built from the requirements (`Based_On`) and fails validation when
  they change.
- Gap levels (ba-2): `in_core`, `in_staging`, `in_interface` (delivered, not
  in staging: dev-1), `in_source` (the source has it, the interface does not:
  ba-3), `not_in_source` (recorded and handed to the source owner; no skill
  follows it up), `conflict`. "Not in the agreement" never means "not in the
  source": only the source catalog says that.
- Generated load procedures never `COMMIT` (the caller does), so utPLSQL
  `--%rollback(auto)` can undo each test.
- The utPLSQL test data package `UT_<TABLE>_DATA` is the only hand-edited
  generated file in a mapping folder.
- Staging has no foreign keys between tables: the links are `*_REF` columns
  that the load packages turn into core IDs. Read the join in the package
  (`sql/UBB_CORE2.schema/PKG_ETL_*_1.sql`) before mapping across tables.

## Verification commands

```
python -m pytest -q
python tools/mapping_spec/validate_spec.py validate
python tools/mapping_spec/validate_spec.py status
python tools/codegen/verify_mapping.py <MAPPING_ID>
python tools/change_request/cr.py validate
python tools/change_request/cr.py status
python tools/codegen/generate_staging.py <CR_ID> --check
```

None of them opens a database connection.

## Known gaps

- `Preconditions` and `Error_Handling` are descriptive text; nothing runs
  them. A rule that must stop a run is written as a `guard` acceptance
  criterion: the generated package checks it before writing anything and
  raises `ORA-20005`. Every other `Check_SQL` becomes a test only. A mapping
  whose `Error_Handling` needs more (rejecting single rows into an error
  table, loading the rest) cannot be generated yet - that is a second
  target table.
- Generated loads raise numbered errors and never log; the calling job logs
  them (`tools/codegen/templates/README.md`, "Errors and logging").
- Aggregation is `GROUP BY` (`Group_By`), optionally over a per-row step
  (the Item_Columns sheet) where window functions such as a running total
  run. Still not supported: `HAVING`, `WITH`, `UNION`, and filtering rows on
  a window function ("latest row per key"). The validator is stricter than
  Oracle on purpose - a column not in `Group_By` reads source columns (or,
  with Item_Columns, item columns) only inside an aggregate.
- A field the source systems catalog lists but `sql/` lacks can be mapped
  only once an approved delivery agreement promises it (then it is
  *planned*); until then `source_catalog.py` names the gap and the analyst
  records it as an open decision, which blocks approval.
- `generate_staging.py` writes the staging DDL only. The loader that reads a
  delivered file into its staging table is outside this repository and must
  be extended by hand.
- `cr.py trace` links an acceptance criterion to a requirement or input only
  when the criterion's Description or Notes name the `REQ-..`/`IN-..` ID.
- `verify_mapping.py` checks structure (columns, types, nullability, grain
  from the declared keys). It cannot count rows, prove a key unique in the
  data, or see values; the acceptance criteria become utPLSQL tests that the
  developer runs after deploying.
- `package_usage.py` cannot see SQL built at run time (`EXECUTE IMMEDIATE`,
  `DBMS_SQL`; it lists those places), nor access through synonyms or views.

## Project-specific notes

- `.github/` mirrors `.claude/` so GitHub Copilot has the same skills. The two
  folders are shipped separately, so each is self-contained and neither names
  the other (`tests/test_hooks.py` checks this):
  `.github/copilot-instructions.md` is the repo-wide equivalent of
  `CLAUDE.md`, `.github/instructions/` holds path-scoped reminders
  (`specs/*/*.xlsx`, `specs/*/*.sql`), and `.github/skills/*/SKILL.md`
  are the skills. `.github/hooks/sql_gate.json` runs
  `.github/hooks/sql_gate.py`, an identical copy of the gate that
  `.claude/settings.json` runs from `.claude/hooks/`
  (`tests/test_hooks.py` keeps the copies identical); hooks are a preview feature in
  VS Code and can be turned off, so the `.github/` copies still say which
  checks to run by hand. When a `.claude/skills/*/SKILL.md` changes, update
  the matching `.github/skills/*/SKILL.md` to keep them in step.
- `git config diff.xlsx.textconv` makes `git diff` show workbook content
  (`.gitattributes` marks `*.xlsx`). A new clone needs it set once; the
  command is in `docs/WORKFLOW.md` setup.
