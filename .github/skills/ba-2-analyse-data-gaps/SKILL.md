---
name: ba-2-analyse-data-gaps
description: Analyst step 2 of 4. From the APPROVED requirements of a change request, find for every required input where it is available today - in a CORE table, in a staging table, in a delivery agreement, in a source system, or nowhere - and plan the loads (one mapping per target table, in order). Writes change-requests/<CR_ID>/<CR_ID>_Gap_Analysis.xlsx from the table scripts in sql/, the existing mappings, the delivery agreements and the source systems catalog (never a database), with a reference for every finding, and stops at status in_review for a person to approve. Invoke after /ba-1-analyse-requirement is approved.
argument-hint: "<CR_ID>"
---

# ba-2-analyse-data-gaps (analyst)

You are helping an **analyst** answer, for every input the change request
needs: *is the data there, and if not, what has to change?* - and plan the
loads that will compute the KPIs. The output is
`change-requests/<CR_ID>/<CR_ID>_Gap_Analysis.xlsx`, written by a tool from
JSON. A person approves it in Excel.

You do not write delivery agreements (step 3), mappings (step 4) or SQL,
and you never approve.

Input: **$ARGUMENTS** (a CR_ID)

---

## Step 0 - Preconditions

```
python tools/change_request/cr.py gate gaps <CR_ID>
python tools/change_request/cr.py show <CR_ID> requirements --json
```

Stop if the gate says NOT YET: the requirements must be approved first.
Read `AGENT_BRIEFING.md`. To change an existing gap analysis, start from
`python tools/change_request/cr.py show <CR_ID> gap_analysis --json`.

## Step 1 - Find every input, in this order

For each row of the requirements' **Required_Data**, look in each place
below until you find it, and write down what each place says - with the
file and the place in it, on the **Sources** sheet. The scripts in `sql/` are
the only truth about tables and columns; **never connect to a database**.

1. **CORE** - a `UBB_CORE2` table has it *and something loads it*:
   - `python tools/mapping_spec/schema_catalog.py` lists the tables;
     `python tools/mapping_spec/schema_catalog.py UBB_CORE2.EXPOSURE_HIST`
     shows columns, keys and comments.
   - `python tools/mapping_spec/package_usage.py <SCHEMA.TABLE>` - which
     procedure writes it. A column no procedure and no approved mapping
     (`python tools/mapping_spec/validate_spec.py status`) fills is *not*
     available, even though the column exists.
   - The S2T baseline (`python tools/change_request/cr.py read
     business-documents/UBB_S2T_Baseline_v1.0_Draft.xlsx --sheet Mappings`) says
     which mappings are implemented and which are drafts.
2. **Staging** - a `UBB_STAGING2` table has it (same tools).
3. **Interface** - the approved delivery agreement of the source system
   delivers it: `python tools/change_request/cr.py agreement-json <SYSTEM>`
   (CBS_SIM, CRM_SIM, FX_SIM). An attribute can be delivered and still be
   missing from staging.
4. **Source system** - the source systems catalog lists it:
   ```
   python tools/mapping_spec/source_catalog.py find <word> [<word> ...]
   python tools/mapping_spec/source_catalog.py gaps <STG_TABLE or SYSTEM>
   ```
   **Never conclude that a source system does not have an attribute because
   the delivery agreement or staging does not.** Only the catalog (or the
   source owner) can say that.

Then give the input its **Level** and **Action**:

| Level | Means | Action | Who acts next |
|---|---|---|---|
| `in_core` | a CORE table has it and a load fills it | `none` or `mapping` | `/ba-4-create-mapping-spec` |
| `in_staging` | staging has it, CORE does not | `mapping` | `/ba-4-create-mapping-spec` |
| `in_interface` | the agreement delivers it, staging does not | `staging_change` | developer: `/dev-1-implement-staging-change` |
| `in_source` | the source has it, the interface does not | `delivery_change` (existing agreement) or `new_delivery` (no agreement yet) | `/ba-3-specify-baseline-changes`, then dev-1 |
| `not_in_source` | no source system has it | `source_owner` | the analyst takes it to the source owner; no skill follows it up |
| `conflict` | the documents disagree (e.g. `catalog_conflict`) | `clarify` | whoever owns the wrong document corrects it |

Fill the location column the level needs (`Core_Location`,
`Staging_Location` as `SCHEMA.TABLE.COLUMN`; `Interface_Location` as
`SYSTEM v1.0 3.3 COLLATERAL`; `Source_Location` as
`SYSTEM / Entity / ATTRIBUTE`, the system first). An `in_interface` input
also needs `Staging_Location`: the column staging will get,
`UBB_STAGING2.STG_<ENTITY>.ATTRIBUTE` - only the columns the change request
names this way are added. An agreement delivering more than staging loads is
normal, not a gap: record only what the requirements need. `Responsible` is a role,
never a person's name. `Status`: `decided` once the action is agreed,
`tracked` for a `not_in_source` input handed to the source owner, `open`
while undecided (blocks approval).

### Suggestions

Where the documents do not settle a row - the level is ambiguous, two
documents disagree, the right target table or the load plan is a judgement -
do not leave a bare `TODO:` and do not stop to interview. Fill the row with
your best understanding and mark it as a proposal for the analyst to accept
or change:

- `Level`, `Action` and the location columns hold your best reading, backed
  by what the tools printed (they are choice or location columns and carry no
  prefix).
- `Notes` starts with `SUGGESTION: ` followed by why you read it this way
  and what remains uncertain. On a Load_Plan row the suggestion goes in its
  `Notes`; any free-text cell that would be `TODO:` becomes `SUGGESTION: ...`.
- `Status` of the Gaps row stays `open` (never `decided` or `tracked`: only
  the analyst decides), with an Open_Questions row (`Status = open`,
  `Answer = SUGGESTION: ...`, `Decided_By`/`Decided_On` empty) for each
  decision that needs more than a click.
- Never suggest what no document supports: a `not_in_source` conclusion
  still needs the catalog; if nothing supports a proposal, write `TODO: ...`
  with the question.
- The tool treats an approved document that still contains `SUGGESTION:` as
  invalid: the analyst accepts (deletes the prefix, sets `Status` to
  `decided`/`tracked`) or changes each one.

## Step 2 - Plan the loads (Load_Plan)

The code generator builds **one target table per mapping**, from one SELECT
with joins, optional `GROUP BY` aggregation and per-row window functions
(`docs/WORKFLOW.md`, `tools/codegen/templates/README.md`). A KPI that needs
several steps or two grains becomes several mappings, chained. For each
mapping, one row:

- `Mapping_ID` (`M_...`), `Target_Table` (`SCHEMA.TABLE`), `Change`
  (`new_table`, `new_columns` for an existing table, `new_load` for an
  existing table no mapping loads yet - e.g. `EXPOSURE_HIST` - or
  `changed_load`), `Grain`, `Purpose`.
- `Depends_On`: the mappings whose target it reads; `Dependency_Order` puts them first.
  `Dependency_Order` is a dependency level, not a priority: the same `Dependency_Order` means
  independent mappings. No cycles - the tool checks.
- `Input_IDs` and `Req_IDs` it serves, so every requirement can be traced to
  a load. Fill `Mapping_IDs` on the Gaps rows with Action `mapping` too.

Reuse existing CORE tables when their grain fits (read their comments: a
comment can disagree with another table's - that is a `conflict` to raise).
Propose the plan in full - a `SUGGESTION:` in the rows' `Notes` where it is
a judgement - and let the analyst accept or change it.

## Step 3 - Interview: one question at a time

Ask only what the documents could not answer and a `SUGGESTION:` cannot
carry for the analyst to review in the workbook. One question per message,
restate the answer, never assume (a suggestion is not a decision: it stays
`open`). Record each on **Open_Questions**; unresolved ones stay `open`.

## Step 4 - Write the workbook

```
python tools/change_request/cr.py schema gap_analysis
python tools/change_request/cr.py write .work/<CR_ID>_gap_analysis.json
```

The tool refuses while the requirements are not approved, records which
version of them it was built from (`Based_On`: if the requirements change
later, this document must be reviewed and approved again), never records an
approval, and needs a `"change_note"` when rewriting changed content. Fix
every FAIL it prints: an input of the requirements without a Gaps row, a
level whose action or location does not fit, a load plan that names unknown
mappings or loops. Never fill people or dates on your own.

## Step 5 - Hand over, then stop

1. Tell the analyst, in this order: the inputs by level (a table);
   everything that goes to a source owner (`not_in_source`) - for the analyst
   to take there; every `conflict` and who must correct which document; the
   load plan in order, with what each mapping computes; every
   `SUGGESTION:` (which rows, and why it is only a proposal); the open
   questions.
2. How to approve: review each `SUGGESTION:` - accept it (delete the
   prefix, set the row `decided`/`tracked`, close its question) or change it.
   Then Excel, `change-requests/<CR_ID>/<CR_ID>_Gap_Analysis.xlsx`,
   sheet Document (`Status`, `Approved_By`, `Approved_On`); then
   `python tools/change_request/cr.py validate <CR_ID>`.
3. Next steps, once approved: `/ba-3-specify-baseline-changes <CR_ID>` when an
   input is `delivery_change` or `new_delivery`, or the requirements propose
   glossary changes; the developer's
   `/dev-1-implement-staging-change <CR_ID>` for `in_interface` inputs;
   `/ba-4-create-mapping-spec <CR_ID> <MAPPING_ID>` for each Load_Plan row, in
   order.
4. **Stop.**

## Key invariants

- Every finding has a reference (file and place); every level is backed by
  what the tools printed, never by memory or by an example.
- "Not delivered" is never "not in the source": the catalog decides that.
- A `SUGGESTION:` is a proposal, never a decision: its row stays `open`.
- Baseline documents are never changed; the requirements are not changed
  here either (a missing input goes back to `/ba-1-analyse-requirement`).
- A finding that changes what an input or a KPI *means* (a source defines
  it differently, a missing input is replaced by another) is a `conflict`
  with an open question to the analyst: the requirements - and with them
  their Glossary_Changes - are corrected in `/ba-1-analyse-requirement`
  before this gap analysis is approved. The glossary version is written
  only afterwards, in `/ba-3-specify-baseline-changes`.
- No database is ever used: no Oracle session, query, tunnel or script that
  opens one.
- You never approve, and never fill a person's name or a date yourself.
