---
name: ba-1-analyse-requirement
description: Analyst step 1 of 4. Turn a change request document (e.g. business-documents/UBB_CR_ECB_001_...docx) into the requirements workbook change-requests/<CR_ID>/<CR_ID>_Requirements.xlsx - requirements quoted from the CR, KPI definitions, reporting dimensions, business rules, every business input the KPIs need, and proposed glossary changes - researched from the CR, the business glossary and the S2T baseline (never a database), interviewing the analyst only about what those cannot answer, and stopping at status in_review for a person to approve. Invoke at the start of every new change request, or to change its requirements.
argument-hint: "[path to the change request .docx, or CR_ID to change existing requirements]"
---

# ba-1-analyse-requirement (analyst)

You are helping an **analyst** turn a change request (CR) into a precise,
reviewable requirements analysis. The output is one workbook,
`change-requests/<CR_ID>/<CR_ID>_Requirements.xlsx`, written by a tool from
JSON - never by editing cells. A person approves it in Excel; only then can
the gap analysis (`/ba-2-analyse-data-gaps`) start.

You do not look for tables or columns here (that is step 2), you do not
write mappings or SQL, and you never approve.

The whole process, for people: `docs/WORKFLOW.md`. The workbook layout and
every column's meaning: `python tools/change_request/cr.py schema requirements`.

Input: **$ARGUMENTS**

---

## Step 0 - Orient

1. Read `AGENT_BRIEFING.md` (tools, conventions, the precedence of the
   documents).
2. `python tools/change_request/cr.py status` - which change requests exist.
3. Work out the path:

| You were given | Path |
|---|---|
| A change request document (`.docx`) | A - new requirements. The CR_ID is the document's ID (`CR-ECB-001`) |
| A CR_ID whose requirements exist | B - change them: start from `python tools/change_request/cr.py show <CR_ID> requirements --json` |
| Text pasted in chat | A - ask for the CR's ID; record `chat` in Source_Documents |
| Nothing | Report `status`, ask which change request to analyse |

## Step 1 - Read before asking anything

Word and Excel files are read through the tool (Copilot and Claude Code
cannot read them reliably otherwise):

```
python tools/change_request/cr.py read <change request .docx>
python tools/change_request/cr.py read business-documents/UBB_Credit_Risk_Business_Glossary_v0.3.xlsx
python tools/change_request/cr.py read business-documents/UBB_S2T_Baseline_v1.0_Draft.xlsx --sheet "Business & ETL Rules"
```

- **The change request** is the requirement. A fictional or "inspired"
  regulatory text is still only what it says: never add requirements of the
  real regulation from memory.
- **The glossary** gives the business entities, attributes (`AT-...`),
  relationships, DQ rules (`DQ-...`) and calculation principles (`CR-...`)
  that exist, with their status (Established, Validate, Proposed). Reuse its
  names and IDs.
- **The S2T baseline** shows which KPI derivations already exist or are
  still open (`M_EXPOSURE` is a design draft). It is a baseline: never
  changed by this skill.

Record every finding that shaped a row on the **Sources** sheet, with the
file and the place in it (section, sheet and ID).

## Step 2 - Analyse

Fill these sheets. IDs are stable once written (`REQ-01`, `KPI-01`, ...):
other documents refer to them.

**Requirements** - one row per requirement, the CR's words in `CR_Text`,
restated as one testable statement in `Requirement`, and its `Kind`:

| Kind | Means | Example |
|---|---|---|
| `explicit` | the CR says it | "Net Unsecured Exposure is non-negative" |
| `interpretation` | how UBB reads the CR | "gross exposure = outstanding + undrawn x CCF" |
| `assumption` | not in the CR at all; needs a business decision | "reporting currency is EUR" |

An `interpretation` or `assumption` always has an open question (below)
until someone with the authority has confirmed it.

**Suggestions, not TODOs.** Never leave a field as a bare `TODO:`. Where
something is undecided, work out your best understanding from the CR, the
glossary and the S2T baseline, write it in the field with the prefix
`SUGGESTION: `, and keep the matching open question `open`. The analyst
then accepts it (removes the prefix, sets the question `decided`) or
changes it. See "Suggestions" below.

**KPIs** - one row per measure: definition for a business reader; the
`Formula` in business terms naming `IN-..` inputs and `BR-..` rules; grain,
date rule (which effective dates count on a reporting date), currency rule,
aggregation, rounding, exceptions (missing or invalid inputs). **Never
invent a regulatory formula or treat an illustrative one as required** -
the glossary marks `PD x LGD x EAD` as illustrative. When the CR leaves the
formula or another field (currency rule, aggregation, rounding, exceptions)
to the analyst, write your best candidate as `SUGGESTION: ...` with an open
question, never as a decided fact.

**Dimensions** - what results are analysed by (borrower, economic sector,
connected-client group, collateral category, ...), with key and effective
dating.

**Business_Rules** - the rules the CR asks the analyst to specify
(eligibility, valuation freshness, allocation of shared collateral, haircut
order, caps against over-recognition, missing FX rates, missing risk
parameters, ambiguous references). One row each; an undecided rule is
`SUGGESTION: ...` (your best understanding of the rule) with an open
question.

**Required_Data** - every business input the KPIs, dimensions and rules
need, once each, by business name (`Regulatory haircut`, not a column
name), with its glossary attribute (`AT-...`) or `new`. No table or column
names here: where an input lives is step 2's question.

**Glossary_Changes** - what the glossary should gain or change: new
attributes, new or changed definitions, new DQ rules, new calculations. This
is where a glossary change is decided; the glossary file is not changed
here. `/ba-3-specify-baseline-changes` writes the new glossary version from
these rows once the gap analysis is approved, so a step-2 finding that
changes a meaning comes back here first.

### Suggestions

A `SUGGESTION:` is a proposal for the analyst to accept or change - it is
never a decision.

- Applies to every free-text cell that would otherwise be `TODO:` (KPI
  Formula, Currency_Rule, Aggregation, Rounding, Exceptions; Dimension Key;
  Business_Rules Rule; Glossary_Changes Notes; ...). Put `SUGGESTION: ` at
  the very start of the cell, then the content as if it were decided, then
  the reason it is only a suggestion (what the documents leave open).
- Base it only on what the CR, the glossary and the S2T baseline say, and
  name them. If nothing supports a proposal, still write `TODO: ...` with
  the question; never invent a regulatory formula, threshold or parameter.
  An illustrative glossary formula may be suggested, labelled as illustrative.
- Every suggestion has an Open_Questions row: `Status = open`, `Answer =
  SUGGESTION: <the same proposal>` or empty, `Decided_By` and `Decided_On`
  empty. A suggestion is never `decided`: only a person's answer decides.
- A `Kind = interpretation` or `assumption` requirement built on a
  suggestion keeps its open question.
- The tool treats an approved document that still contains `SUGGESTION:` as
  invalid, so the analyst must accept (delete the prefix, set the question
  `decided`, fill `Decided_By`/`Decided_On` themselves) or replace each one.

## Step 3 - Interview: one question at a time

Ask only what the documents could not answer and a `SUGGESTION:` cannot
carry for the analyst to review in the workbook. One question per message;
restate the answer in one sentence before the next; never batch, never
assume a default (a suggestion is not a default: it stays `open`). Record each on the **Open_Questions** sheet with
`Ask_Whom` (business, risk methodology, a source owner): answered ones as
`decided` (`Decided_By`/`Decided_On` only when a person states them),
unresolved ones stay `open` - with your `SUGGESTION:` in `Answer` when you
have one - and that blocks approval, which is the point. The
analyst may hand the workbook over with open questions for the business to
answer.

## Step 4 - Write the workbook

```
python tools/change_request/cr.py schema requirements
```

Write the JSON to `.work/<CR_ID>_requirements.json` (a git-ignored scratch
folder) and render it:

```
python tools/change_request/cr.py write .work/<CR_ID>_requirements.json
```

- `Status` is `draft` or `in_review`; the tool refuses `approved` and
  refuses to fill `Approved_By`/`Approved_On`.
- Rewriting an existing workbook with changed content needs a top-level
  `"change_note"` (what changed and why): it goes on the Change_Log sheet with
  a new revision. Changed content drops an earlier approval.
- **Never fill people or dates on your own** (`Owner`, `Approved_By`,
  `Approved_On`, `Decided_By`, `Decided_On`): not from the user's name, the
  git user or today's date. Fill one only when the analyst states it.
- Every FAIL the tool prints is fixed (by asking, if needed) and the workbook
  written again. WARNs (a requirement no KPI serves, an input nothing needs)
  are explained to the analyst or fixed.

## Step 5 - Hand over, then stop

1. Tell the analyst, in this order: the requirements by kind (every
   `interpretation` and `assumption` called out); the KPIs with their
   formulas; dimensions; the business rules (say which are `SUGGESTION:`
   and which are still `TODO`); the required inputs;
   the glossary changes; the open questions, numbered, with whom to ask and
   your suggested answer.
2. How to approve: review every `SUGGESTION:` - accept it (delete the
   prefix, set its question `decided`, fill `Decided_By`/`Decided_On`) or
   replace it. Then open `change-requests/<CR_ID>/<CR_ID>_Requirements.xlsx`
   in Excel, sheet Document: `Status = approved`, `Approved_By` = their own
   name, `Approved_On` = today (YYYY-MM-DD); then
   `python tools/change_request/cr.py validate <CR_ID>` must say OK.
3. Next step: `/ba-2-analyse-data-gaps <CR_ID>`, once approved.
4. **Stop.** Do not start the gap analysis in the same turn.

## Key invariants

- The workbook is written only through `cr.py write`; you never set
  `approved` or write a name into `Approved_By`.
- Nothing is invented: a requirement is quoted from the CR, a formula or
  rule nobody decided is a `SUGGESTION:` (or `TODO` if nothing supports a
  proposal) with an open question that stays `open`, and regulatory text is
  never filled in from memory.
- Baseline documents (glossary, S2T baseline, delivery agreements, source
  catalog) are read, never changed.
- No database is ever used: no Oracle session, query, tunnel or script that
  opens one - this step does not even need the `sql/` folder.
- Every finding is on the Sources sheet; every question on Open_Questions.
