Create a clear, polished, standalone SVG **data-flow diagram** from the ETL
package script supplied with this request. Apply these instructions to that
script's package, source tables, target table(s), fields, and transformations;
do not reuse names, formulas, loads, or business rules from earlier examples.

## Evidence and interpretation

- Treat the supplied package body as the authority for what the code does.
  Trace its actual source reads, predicates, joins, expressions, merges,
  inserts/updates, generated keys, and output columns. Use the package
  specification only for interface details not evident in the body.
- If an accompanying proposal, mapping, or discussion document is supplied,
  use it only to identify decisions that remain unresolved or to qualify
  assumptions. Do not let it override the package's implemented behavior.
- Do not infer behavior from table or column names, or invent source systems,
  load relationships, row filters, join rules, output grain, defaults,
  validations, or orchestration steps. If the script does not establish a
  detail, omit it or label it explicitly as unspecified.
- Distinguish implemented fixture behavior from approved business policy.
  Mark assumptions and unresolved rules as illustrative/open when the
  supplied evidence says they are not approved. Do not claim approval or
  deployment readiness without explicit evidence.
- The diagram explains data lineage; it is not a workflow chart, a code
  review, or a substitute for validating the package against its schema.

## Trace the row flow

Follow each business-data path from source rows to target rows, including
branches that join again later:

1. **Sources and selection:** For every source table, show how its rows are
   selected (load ID, date, status, key predicate, or other actual filter) and
   list the fields used downstream. Preserve independent source-load IDs as
   independent inputs; do not imply they are the same load unless the code
   proves that.
2. **Preparation:** Show meaningful joins, filters, lookups, currency/unit
   conversions, deduplication, and aggregation. Label the join keys and group
   grain where the SQL establishes them. Show missing/ambiguous-reference
   behavior only when the package implements it.
3. **Identity and keys:** If the package merges into an identity or dimension
   table, show its match key, reuse behavior, and how a new key is created.
   Clearly distinguish merge inputs/match keys from keys produced by the
   merge; show the source of any other values used only for new identities.
4. **Calculations:** Show the actual formulas and relevant conditions in
   compact form. Label configurable or disputed parameters as assumptions
   when the supplied evidence identifies them as unresolved; never present a
   candidate value as an approved rule.
5. **Targets:** Show the target table(s), row grain when established, and the
   principal output columns, including generated IDs, load/audit fields, and
   calculated values needed to understand lineage.

## Separate data from control

Keep business rows and operational metadata visually distinct. Show input
load IDs separately when the package takes them independently. Show an output
load/control record as a control-only path, not as a source of business data,
only when the package or supplied orchestration evidence establishes that
behavior. Identify who creates/passes the ID, how it labels output rows, and
any status transition supported by the evidence. Likewise, include input
validation and transaction ownership notes only when established by the
package or supplied context. Do not assume a scheduler, status, source name,
dataset name, commit, or rollback behavior.

## Visual and output requirements

- Save a readable, zoomable, self-contained SVG in target's folder.
  Name it `<TARGET>_Data_Flow.svg` using the package name without irrelevant prefixes and suffixes.
  Honor an explicitly requested output path instead.
- Arrange the main flow left-to-right: source rows → preparation and
  aggregation → identity/calculation → target rows. Use a wide layout with
  enough spacing for labels and branches.
- Use solid, clearly routed arrows for business data. Use dashed arrows only
  for control metadata. Avoid crossings, overlaps, and tightly clustered
  paths; use orthogonal routes and short labels to clarify branches.
- Use a consistent semantic palette: primary input data blue, additional
  input streams in distinct colors (for example purple and amber),
  conversions cyan, generated/stable identity flow green, calculated values
  dark blue, and control metadata dashed amber. Adapt the input colors when
  there are more streams, and include every used color in a compact legend.
  Never use the same color for conversion and identity flow.
- Make source/target names, selection rules, key fields, and formulas
  readable when zoomed. Keep validation, transaction, assumptions, and
  unresolved-rule notes secondary to the row flow.
- Do not add unsupported source-system claims, invented data, or
  approved-sounding business rules. Deliver the SVG itself, not a screenshot.