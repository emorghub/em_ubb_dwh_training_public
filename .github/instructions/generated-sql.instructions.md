---
description: "Generated database code: never hand-edit, and only for an approved mapping"
applyTo: "specs/*/*.sql"
---

# Generated code in a mapping folder, specs/<folder>/

Every `.sql` file in a mapping folder is generated from the mapping workbook
next to it, `specs/<folder>/<MAPPING_ID>.xlsx`, by
`python tools/codegen/generate.py <MAPPING_ID>` (the `/dev-2-implement-mapping`
flow). See `specs/README.md` and `docs/WORKFLOW.md`.

- **Do not hand-edit generated files** (`<TABLE>.sql`, `<TABLE>_LOAD_LOG.sql`,
  `<MAPPING_ID>.sql`, `<PACKAGE>.sql`, `UT_<TABLE>.sql`). Fix the
  mapping (analyst, re-approval) or a template in `tools/codegen/templates/`,
  then regenerate.
- **The one exception is the test data package** `UT_<TABLE>_DATA.sql`:
  written once by the generator, then completed by hand (realistic values,
  negative cases, no TODO left).
- **`DEPLOY_<MAPPING_ID>_*` files are not generated** by `generate.py`: the
  deployment runbook and the two read-only preflight scripts that
  `/dev-3-prepare-deployment` writes after the code (Step 2). They are rewritten
  by the skill when the mapping changes, not edited by hand, and are never run
  by the assistant.
- **Only for an approved mapping.** A hook (`.github/hooks/sql_gate.py`,
  run by `.github/hooks/sql_gate.json`) blocks edits here when
  the mapping in the same folder is not approved. Hooks can be turned off,
  so check first with `python tools/mapping_spec/validate_spec.py status`.
- **Never deploy from the assistant.** A developer reviews and deploys.
- Before hand-over: `python tools/codegen/generate.py <MAPPING_ID> --check`.
