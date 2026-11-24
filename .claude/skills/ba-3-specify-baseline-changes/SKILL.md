---
name: ba-3-specify-baseline-changes
description: Analyst step 3 of 4. From the APPROVED gap analysis of a change request, write the new versions of the baseline documents the change request changes - (A) every delivery agreement that must deliver more, v1.1 of an existing agreement (CBS_SIM, CRM_SIM, FX_SIM) or v1.0 for a source with no agreement yet (RISK_ENGINE_SIM), as change-requests/<CR_ID>/UBB_Delivery_Agreement_<SYSTEM>_v<VERSION>.docx, and (B) the business glossary, when the requirements propose glossary changes, as change-requests/<CR_ID>/UBB_Credit_Risk_Business_Glossary_v<VERSION>.xlsx - each the whole document with every addition marked and listed, rendered from JSON by a tool, never a database, and stopping at status in_review for a person to approve. The approved baselines are never changed. Invoke after /ba-2-analyse-data-gaps is approved, when an input needs delivery_change or new_delivery, or the requirements propose glossary changes.
argument-hint: "<CR_ID> [SOURCE_SYSTEM | glossary]"
---

# ba-3-specify-baseline-changes (analyst)

You are helping an **analyst** write the new versions of the baseline
documents a change request changes:

- **A - delivery agreements.** What a source system must deliver in
  addition. The analyst takes it to the source owner; once a person approves
  it, the developer extends staging from it (`/dev-1-implement-staging-change`)
  and the analyst can map the new columns (`/ba-4-create-mapping-spec`).
- **B - the business glossary.** The glossary changes decided in step 1
  (the Glossary_Changes sheet of the requirements). They are written only
  now, after the gap analysis is approved, so that every step-2 finding that
  changed a meaning has gone back into the requirements first. The analyst
  takes it to the glossary owner.

The approved baselines in `business-documents/` - the agreements in
`business-documents/UBB_Delivery_Agreements_Approved_v1.0/` and
`business-documents/UBB_Credit_Risk_Business_Glossary_v0.3.xlsx` - are **never
changed**: a change is a new file, with a higher version, in the change
request's folder. The new version is the whole document - every existing
entry, unchanged, plus the additions and changes, marked.

You never decide a glossary change here: the requirements decide it. You
only write what they say.

Input: **$ARGUMENTS**

---

## Step 0 - Preconditions and scope

```
python tools/change_request/cr.py gate delivery <CR_ID>
python tools/change_request/cr.py gate glossary <CR_ID>
python tools/change_request/cr.py show <CR_ID> gap_analysis --json
```

- Both gates say NOT YET because the requirements or the gap analysis are
  not approved: stop.
- `delivery` OK: part A is in scope. The rows with Action `delivery_change`
  or `new_delivery` are the scope, grouped by source system (the first word
  of `Source_Location`). Anything else is not this skill's to add - an input
  missing from those rows goes back to `/ba-2-analyse-data-gaps`.
- `glossary` OK: part B is in scope.
- A gate that says no agreement or no glossary change is needed: skip that
  part and say so.

The argument may narrow the work to one source system or to `glossary`.

## Part A - Delivery agreements

### A1 - Start from the current version

For a source with an agreement:

```
python tools/change_request/cr.py agreement-json <SYSTEM>
```

prints its current version (the approved baseline, or a newer version
already written for this CR) as JSON. Save it to
`.work/<CR_ID>_<SYSTEM>_agreement.json`. For a source **without** an
agreement (`RISK_ENGINE_SIM`), start from
`python tools/change_request/cr.py schema agreement` and take sections 1,
2, 4 and 5 (purpose, file standard, data quality, change control) from an
existing agreement, saying so to the analyst - the source owner must confirm
them.

### A2 - Specify the change

In the JSON:

- `version`: the next one (`1.0` -> `1.1`); `1.0` for a new source.
  `supersedes`: the approved version it replaces (empty for a new source).
  `cr_id`: the change request. `status`: `in_review`.
- **Keep every existing entity and attribute exactly as it is.** Add each
  new attribute to its entity with `"change": "added"`:
  - `name`: the attribute name from the source catalog
    (`python tools/mapping_spec/source_catalog.py find <word>`).
  - `type`: an Oracle type as staging writes it - lengths in characters:
    the catalog's `VARCHAR2(80)` becomes `VARCHAR2(80 CHAR)`, `CHAR(1)`
    becomes `CHAR(1 CHAR)`, `TIMESTAMP` becomes `TIMESTAMP(6)`. Say which
    types you converted.
  - `description`: the business meaning from the catalog.
- A new entity has `"change": "new"`, a `filename`
  (`<SYSTEM>_<ENTITY>_YYYYMMDD.csv`), a `business_key` from the catalog, a
  `snapshot` (ask: daily full?) and its attributes. It will arrive in the
  staging table `UBB_STAGING2.STG_<ENTITY>` - choose the entity name with
  that in mind (`CREDIT_RISK_ASSESSMENT`).
- `changes`: one row per added attribute (`add_attribute`) or new entity
  (`new_entity`): `reason` (why, for the source owner) and `input_ids` (the
  gap analysis inputs it serves).
- **A "What changed" paragraph, always.** Insert as the first paragraph of
  `purpose` (section 1) a text that starts `What changed in version <V>
  (change request <CR_ID>):` and says: the version it supersedes, the
  entities and attributes added (`ENTITY: ATTR, ATTR; ENTITY: ATTR`), that
  everything else is unchanged from the previous version, and that the
  additions are marked in the Change column of section 3 and listed in the
  "Changes in this version" table in section 5. For a new source
  (version 1.0) say it is the first version and name the new entity with
  its number of attributes. Replace the paragraph when rewriting; never
  duplicate it. The reader of the agreement must see what changed without
  comparing two files.
- What the source owner must still confirm (allowed values, nullability,
  delivery time) is written `TODO: ...` in the description - an agreement
  with TODO cannot be approved - and listed for the analyst.

### A3 - Write the document

```
python tools/change_request/cr.py write-agreement .work/<CR_ID>_<SYSTEM>_agreement.json
```

It writes `change-requests/<CR_ID>/UBB_Delivery_Agreement_<SYSTEM>_v<VERSION>.docx`
in the Word styles of the baseline, with the additions marked in a
`Change` column, a "Changes in this version" table, and the approval table in
section 6. It refuses to overwrite a baseline version, refuses while the gap
analysis is not approved, never records an approval, and drops one when the
content changes. Fix every FAIL it prints (an added attribute not listed in
`changes`, a type staging does not use, a business key that is not an
attribute). One document per source system.

## Part B - The business glossary

### B1 - Start from the current version

```
python tools/change_request/cr.py show <CR_ID> requirements --json
python tools/change_request/cr.py glossary-json <CR_ID>
```

The first gives the Glossary_Changes rows (`GC-..`) - the whole scope of
part B. The second prints the glossary to edit as JSON: this CR's own
version if one exists, else the newest baseline prepared as the next version
(`version` `0.4`, `supersedes` `0.3`, nothing marked). Save it to
`.work/<CR_ID>_glossary.json`. Set `status` to `in_review` and leave
`approved_by`/`approved_on` empty, also when you start from an existing
version.

### B2 - Apply each glossary change

Apply every GC row, and nothing else. Each row of a glossary sheet has a
`Change` (`added` or `changed`, empty when untouched) and a `Change_ID` (the
GC that asks for it). The Change_Type decides where it goes:

| Change_Type | Sheet | Row |
|---|---|---|
| `new_entity` | Entities | `added`, next `EN-` ID |
| `new_attribute` | Business Attributes | `added`, next `AT-` ID, `Entity ID` from the GC's Entity |
| `new_relationship` | Relationships | `added`, next ID |
| `new_dq_rule` / `changed_dq_rule` | Business DQ Rules | `added` (next `DQ-` ID) / `changed` (the row in `Glossary_Ref`) |
| `new_calculation` / `changed_calculation` | Business Calculations | `added` (next `CR-` ID) / `changed` (the row in `Glossary_Ref`) |
| `changed_definition` | the sheet of `Glossary_Ref` | `changed` |

- Take the text from the GC's `Proposed_Text`, word for word where it fits a
  column. A column the GC does not settle (`Business Data Type`, `Key Type`,
  `Definition Status`) gets the glossary's own vocabulary; for
  `Definition Status` write `Proposed - <CR_ID>`.
- Never remove a row and never change an unmarked row: the glossary owner
  retires an entry through its `Definition Status`.
- Do not touch the columns. Update the `About` sheet's `Version` line to the
  new version and the change request.
- What the GC leaves open for the glossary owner is written `TODO: ...` in
  the cell - a version with TODO cannot be approved - and listed for the
  analyst. A GC that turns out wrong or incomplete is **not** fixed here: it
  goes back to `/ba-1-analyse-requirement`, and part B is redone once the
  requirements (and the gap analysis, which then fails validation) are
  approved again.

### B3 - Write the workbook

```
python tools/change_request/cr.py write-glossary .work/<CR_ID>_glossary.json
```

It writes `change-requests/<CR_ID>/UBB_Credit_Risk_Business_Glossary_v<VERSION>.xlsx`:
a Document sheet with the approval fields, every glossary sheet with the
added rows green and the changed rows yellow, a `Changes_In_This_Version`
sheet (each change with the text it replaces), and the About sheet. It
refuses to overwrite a baseline version and refuses while the gap analysis
is not approved and valid; it never records an approval and drops one when
the content changes. Fix every FAIL it prints (a GC not applied, a row
changed without a mark, a row removed, a GC on the wrong sheet).

## Step 4 - Hand over, then stop

1. Tell the analyst:
   - per source system: the version written, every added attribute and new
     entity with its reason, the converted types, and every TODO the source
     owner must answer;
   - for the glossary: the version written, each GC with the row it became,
     and every TODO the glossary owner must answer.
2. How to approve:
   - an agreement in Word, section 6 "Agreement status": `Status` =
     `approved`, `Approved by` = the approving person's own name, `Approved
     on` = YYYY-MM-DD;
   - the glossary in Excel, sheet Document: `Status = approved`,
     `Approved_By` = the glossary owner's own name, `Approved_On` =
     YYYY-MM-DD;
   - then `python tools/change_request/cr.py validate <CR_ID>`.
3. Next steps, once approved: the developer's
   `/dev-1-implement-staging-change <CR_ID>`; the analyst's
   `/ba-4-create-mapping-spec <CR_ID> <MAPPING_ID>` for the Load_Plan rows -
   the new columns show up as *planned* until the staging change is
   deployed. The glossary version blocks no load.
4. **Stop.**

## Key invariants

- Baselines are never changed; a change is always a new, higher version in
  the change request's folder, written by `cr.py write-agreement` or
  `cr.py write-glossary`.
- Nothing is invented: attribute names, types and meanings come from the
  source catalog; glossary changes come from the approved requirements' GC
  rows; what neither says is `TODO` for the owner.
- No database is ever used: no Oracle session, query, tunnel or script that
  opens one.
- You never approve and never fill a person's name or a date yourself.
