---
description: "How mapping workbooks are written, and the rule that only a human may approve one"
applyTo: "specs/*/*.xlsx"
---

# Mapping workbooks

A file here is a mapping workbook, `specs/<folder>/<MAPPING_ID>.xlsx`: the
whole contract for one load, and the only input the DDL, PL/SQL and tests are
generated from. There is no Markdown copy. Use `/ba-4-create-mapping-spec` rather
than working on these files freehand. Format, cell by cell:
`.github/skills/ba-4-create-mapping-spec/references/workbook-format.md`. Process:
`docs/WORKFLOW.md`.

## Never edit cells directly

Write the mapping as JSON and render it:

```
python tools/mapping_spec/mapping_workbook.py schema          # the JSON shape
python tools/mapping_spec/mapping_workbook.py show <ID> --json # current content
python tools/mapping_spec/mapping_workbook.py write <file>.json
```

The writer applies the layout, dropdowns and approval rules consistently,
and validates.

## The rule that matters most

**Never approve.** Never set `Status` to `approved`, never write a name into
`Approved_By` - not yours, not the developer's on their behalf. A named
person approves in Excel. The writer refuses to record an approval, and
drops an existing one when the content changes.

## Content rules the validator enforces

- `Transformation_Rule` is SQL only: `direct`, `NULL`, or an Oracle
  expression with columns as `TABLE.COLUMN`. Explanations go in Notes.
- Every referenced column must exist in the table scripts under `sql/` (never
  check a database); every source table must be the driving table or
  a joined table; a parameter must not share a column's name.
- Before approval: every column has type, nullable, SCD type, business name
  and description; at least two acceptance criteria; no `TODO` anywhere; no
  open decision.

## The tools enforce these rules - run them

A hook (`.github/hooks/sql_gate.json`) blocks generated code for an
unapproved mapping, but no hook checks the workbook itself: these rules are
enforced by the writer, the validator and the generator - run them, do not
work around them:

```
python tools/mapping_spec/validate_spec.py validate
python tools/mapping_spec/validate_spec.py status
python tools/codegen/verify_mapping.py <ID>
```
