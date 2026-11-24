# Mappings and their code

Every load has its own folder here. It holds the load's Excel mapping
workbook, named after its `Mapping_ID`, and the code generated from it. The
folder is the `Mapping_ID` without its `M_` prefix, in lower case:

```
specs/
  limit_monitor_daily/
    M_LIMIT_MONITOR_DAILY.xlsx       the mapping workbook (analyst)
    LIMIT_MONITOR_DAILY.sql          generated: the table
    PKG_LIMIT_MONITOR.sql            generated: the load package
    UT_LIMIT_MONITOR_DAILY.sql       generated: the utPLSQL tests
    UT_LIMIT_MONITOR_DAILY_DATA.sql  generated once, then finished by hand: the test data
    DEPLOY_M_LIMIT_MONITOR_DAILY_RUNBOOK.md                      written by dev-3: the deployment runbook
    DEPLOY_M_LIMIT_MONITOR_DAILY_PREFLIGHT_1_BEFORE_DDL.sql      written by dev-3: read-only checks before the DDL
    DEPLOY_M_LIMIT_MONITOR_DAILY_PREFLIGHT_2_BEFORE_RUN.sql      written by dev-3: read-only checks before the first run
  loan_limit_daily/
    M_LOAN_LIMIT_DAILY.xlsx          not approved yet, so no code
```

`mapping_workbook.py write` creates the folder, and `validate_spec.py
validate` fails for a workbook whose file or folder name does not match its
`Mapping_ID`. The workbook is the whole contract for that load: what it
reads, what it writes, how each column is derived, how the tables join,
what a re-run does, and how anyone can tell it worked. It is the single
source of truth - there is no Markdown or YAML copy - and it is detailed
enough that the table DDL, the PL/SQL load and the utPLSQL tests are
generated from it without further questions.

How the workbook fits into the whole process (analyst -> developer ->
documentation): `docs/WORKFLOW.md`. Every sheet and cell, and what the
validator enforces: `.claude/skills/ba-4-create-mapping-spec/references/workbook-format.md`.


## Lifecycle

| Status | Meaning |
|---|---|
| `draft` | Being written. May be incomplete. |
| `in_review` | Complete as far as the analyst knows; waiting for a person to approve. |
| `approved` | Signed off by the person named in `Approved_By` on `Approved_On`. Code may be generated. |

Approval is done by a person in Excel, on the Mapping sheet. An approved
workbook must validate: no `TODO` anywhere, no open decision, every column
typed and described, at least two acceptance criteria.

## What is enforced

| Rule | How |
|---|---|
| An AI never approves | `mapping_workbook.py write` refuses `Status = approved` and never fills `Approved_By`/`Approved_On` |
| A changed mapping loses its approval | The writer compares content fingerprints and drops the approval when they differ |
| Only complete mappings are approved | `validate_spec.py validate` fails otherwise |
| Code comes only from approved mappings | `tools/codegen/generate.py` refuses otherwise; the `sql_gate` hook (Claude Code and Copilot) blocks edits to the `.sql` files in a mapping folder too |
| Column names are real | `validate_spec.py validate` and `verify_mapping.py` check every source column, rule, join and filter reference against the table scripts in `sql/` |

A person editing the workbook directly in Excel after approval is not
detected by the writer; treat approval as a real commitment, and re-set
the status to `in_review` if you change content.

## Generated code

`python tools/codegen/generate.py <MAPPING_ID>` writes the code of an
approved mapping into the mapping's own folder, next to the workbook, one
file per database object, named after the object it creates. Nothing here is
deployed by the tools: a developer reviews the files and runs them by hand.

| File | What it is |
|---|---|
| `<TABLE>.sql` | Full `CREATE TABLE` with primary key and column comments |
| `<TABLE>_LOAD_LOG.sql` | `scd2` only: the table of loaded dates a run for an earlier date replays |
| `<MAPPING_ID>.sql` | `ALTER TABLE` script, only when the table already has a script in `sql/` |
| `<PACKAGE>.sql` | The PL/SQL load package (named after the package in `PLSQL_Proc`) |
| `UT_<TABLE>.sql` | utPLSQL tests, one per acceptance criterion |
| `UT_<TABLE>_DATA.sql` | Test data: generated once, then edited by the developer, never overwritten |

- Generated files are never hand-edited; change the mapping (or a template in
  `tools/codegen/templates/`) and generate again. Only `UT_<TABLE>_DATA.sql`
  is edited by hand.
- Every generated file carries the fingerprint of the workbook it came from.
  `generate.py <MAPPING_ID> --check` fails when the workbook changed since.
- These files are separate from `sql/`, which holds only the scripts exported
  from the database.

## Commands

```
python tools/mapping_spec/validate_spec.py status          # what exists and where it stands
python tools/mapping_spec/validate_spec.py validate        # check every workbook
python tools/mapping_spec/mapping_workbook.py show <ID>    # a workbook as text (--json for JSON)
python tools/codegen/verify_mapping.py <ID>                # check against the table scripts in sql/ (no database)
```

To see workbook changes as text in `git diff`, once per clone:

```
git config diff.xlsx.textconv "python tools/mapping_spec/mapping_workbook.py textconv"
```
