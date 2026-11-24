---
name: do-data-flow
description: Create a self-contained SVG data-flow diagram that traces an ETL package's implemented row lineage, transformations, keys, targets, and control metadata without inventing behavior.
argument-hint: "<ETL package script> [proposal/mapping/context]"
---

# do-data-flow

Create a clear, polished, standalone SVG **data-flow diagram** from the ETL
package script supplied with this request. Apply these instructions to that
script's package, source tables, target table(s), fields, and transformations;
do not reuse names, formulas, loads, or business rules from earlier examples.

Input: **$ARGUMENTS** (an ETL package script and, optionally, supporting
proposal, mapping, or discussion documents), or files supplied in the
conversation. If no package script is identified, ask for it.

## Existing output

- Before validating or rewriting an existing diagram, ask the human to choose
  **validate it** or **redraw it from scratch**.
- Do not validate or redraw the existing SVG automatically without that
  choice.
- If the human chooses **redraw it from scratch**, delete the existing SVG
  before creating its replacement. Do not read, inspect, validate, or compare
  the existing SVG before deleting it; use the package and supplied context
  as evidence instead. Delete only the selected diagram. If deletion fails,
  stop and report the failure.

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
- Verify every connector against the package body: its source, destination,
  direction, and any join or filter it represents must be supported. Show
  independent reads separately, even when they use the same filter; do not
  imply that a later CTE feeds an earlier statement.
- Show only paths and operations established by the package. Do not require
  any particular kind of transformation, identity operation, or target.
- **Evidence table first.** Before drawing, list every connector as
  `from -> to : package lines : what flows`. Draw a connector only when its
  row cites package lines (`L<start>[-L<end>]`), and compare the finished
  diagram with the table connector by connector. A connector that cannot be
  cited is removed, not softened with a label.
- **An arrow enters the node that consumes the rows.** If two statements read
  the same table, draw two arrows from it. If a statement writes a table that
  a later statement reads (a MERGE into an identity table, then a join to
  it), draw the table as its own node between them. Never let a CTE appear to
  feed a statement that does not read it, or a check appear to feed a CTE.
- **A guard is not a data step.** A validation that only counts rows and
  raises an error consumes data but produces none. Put it in a note, not in a
  node with an outgoing data arrow.
- **No dead ends.** Every source needs an outgoing data connector, every
  intermediate node an incoming and an outgoing one, every target an incoming
  one. A node that fails this is a guard (a note) or has no place in the
  diagram.

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
load IDs separately when the package takes them independently. Connect
relevant parameters to their depicted uses with dotted control arrows. Show
an output load/control record as a control-only path, not as a source of
business data, only when the package or supplied orchestration evidence
establishes that behavior. Use brief notes rather than a large control block
to identify who creates/passes the ID, how it labels output rows, and any
status transition supported by the evidence. Likewise, include input
validation and transaction ownership notes only when established by the
package or supplied context. Do not assume a scheduler, status, source name,
dataset name, commit, or rollback behavior.

## Visual and output requirements

- The visible diagram title is the full package name as declared, including
  its schema when specified and all package prefixes and suffixes; do not
  shorten it. For example, use `UBB_CORE2.PKG_ETL_EXPOSURE`, not `EXPOSURE`.
- Save a readable, zoomable, self-contained SVG in the folder containing the
  package script.
  Name it `<PACKAGE_SUBJECT>_Data_Flow.svg`, derived only from the package name:
  remove the schema, then strip irrelevant package prefixes such as `PKG_`,
  `ETL_`, or the combined `PKG_ETL_` in that order; preserve the remaining
  package subject and remove no meaningful suffix such as `_HIST` unless
  an explicit irrelevant suffix is present.
  Do not use a source or target table name as the output basename. For
  `UBB_CORE2.PKG_ETL_EXPOSURE`, the basename is `EXPOSURE_Data_Flow.svg`,
  even though the target table is `EXPOSURE_HIST`.
  Honor an explicitly requested output path instead.
- Arrange the main flow left-to-right, following the operations actually
  implemented by the package. Node sizing is mandatory: each box must be
  large enough to contain every line of text, title, formula, and padding
  with no clipping or text touching a border. Measure the rendered text
  bounds, not only the SVG source, and enlarge or split a node if needed.
  Never shrink text or abbreviate required content merely to preserve a
  smaller box; expand the canvas and reposition nodes instead. Blank area
  inside a node is allowed only after all text is fully contained and a
  consistent text-safe margin remains.
- Size every box from its own measured text: the widest line plus padding,
  and one line height per line. Boxes need not share a width or a height.
  After any resize, recheck the gaps and connector anchors between the boxes
  it touches.
- Omit stage headings and schema qualifiers from node labels by default.
  Include a schema qualifier in a node label when needed to distinguish
  objects or otherwise avoid ambiguity. The full package title is an exception.
- Make the data flow the diagram's dominant visual structure. Give each
  source, meaningful transformation, identity merge, calculation, and target
  its own clearly bounded node. Keep distinct source branches distinct until
  the SQL shows where they join. Place a source-to-target path so it can be
  followed at a glance, with joins and branch re-entry points explicit.
- Keep control parameters visually separate from the business-row path.
  Keep secondary checks, assumptions, and caveats in brief notes that do not
  interrupt or compete with the main data flow.
- Leave enough visible whitespace between adjacent boxes, including control
  parameter boxes, to distinguish the connector line's solid or dotted style
  and its arrowhead clearly. Leave at least 60 SVG units between connected
  boxes, and increase the gap where needed to show multiple dots and the
  arrowhead or to route a branch. Leave at least 35 units between vertically
  stacked boxes that are not directly connected. Verify visibility in the
  rendered diagram; enlarge gaps as needed. Keep text and labels inside their
  nodes; never let connectors, arrowheads, or annotations cover text or enter
  unrelated nodes. Use orthogonal routes for branches and joins.
- Use restrained, consistent solid arrows for business data and dotted arrows
  only for control metadata. Every arrow must connect meaningful endpoints.
  Arrowheads should be modest relative to the connectors and boxes: do not use
  thick, oversized arrows to make the flow more visible. Make the flow clear
  through whitespace, alignment, distinctive colors, and explicit short
  connector labels. Minimize crossings and avoid all connector overlaps.
- Treat connector overlap as a blocking visual defect, not an acceptable
  fallback. No two connectors may share a segment, run on top of another
  connector, enter or pass through text or an unrelated node, or have one
  arrowhead conceal another. Connectors may cross only where a junction
  point is visibly unambiguous and neither route changes direction through
  the same segment. Before delivery, inspect every route segment and enlarge
  the canvas or add separate routing gutters as needed. If overlapping
  routes cannot be separated cleanly, redesign the node layout rather than
  leaving the overlap. Arrows do not need to start or end at the middle of a
  box side; attach them at a corner or another clear position on a side
  instead.
- Route connectors only through the gaps between boxes. A connector never runs
  along, or within 12 units of, a box border it does not start or end on, and
  two parallel connectors keep at least 12 units apart. Connectors that meet
  one box side attach at least 20 units apart; they never share the last
  segment or stack arrowheads. A long connector that skips a column runs
  through empty space, not past a box.
- **Every connector has a label** saying what flows or is applied (for
  example "active rows" or "LOAD_ID filter"), set on a small chip with a
  background on a straight stretch of the connector, clear of corners and
  arrowhead. The chip lies wholly inside the gap between boxes: it never
  touches a box, another connector or another chip. If it does not fit,
  widen the gap or shorten the label; never drop the label or let it overlap
  a box.
- Use distinct, visually distinctive colors for each separate data flow.
  Assign a unique color to each independent source branch and preserve that
  color across its connector, source node, relevant preparation nodes, arrowhead,
  and any labels for that flow. Do not use the same color for unrelated source
  branches, and do not use shades or hues that are likely to be confused at
  normal viewing size or for common color-vision deficiencies. Reserve a
  separate neutral color for control metadata; never encode business flow
  meaning by control color or by hue alone. The compact legend must name every
  flow color and show arrow samples, not dots, matching the color and solid or
  dotted line style used for each named flow throughout the SVG.
  Before delivery, verify that source nodes and connectors remain distinguishable
  on both white and dark backgrounds, that adjacent flows have strong enough
  contrast against the canvas and against each other, and that every color-coded
  path is independently identifiable by a label or node text. This is a hard
  requirement: an existing fixed palette is not a reason to reuse a color; choose
  a fresh, high-contrast palette for the flows actually present.
  A node that joins several branches (a merge, a join CTE, the final
  projection) and the rows after it take one separate "derived" color; its
  inbound arrows keep their branch colors. Measure the palette instead of
  judging it by eye: every color needs a contrast of at least 3:1 on both white
  and `#0F172A`, and every pair a CIE76 distance of at least 30 normally and at
  least 14 simulated for protanopia, deuteranopia and tritanopia
  (`flow_svg.py` computes both). Search for such a palette when a hand-picked one fails.
- Make source/target names, selection rules, key fields, and formulas
  readable at the intended viewing size and when zoomed. The node-width and
  node-height rules are hard constraints: allocate enough room to contain
  rendered text, wrap long text, or split detailed notes into a separate node.
  Do not allow clipping, crowding, border contact, tiny text, or text covered
  by a connector or arrowhead. Check the rendered SVG at fit-to-window and
  zoomed sizes, not just its XML. Perform a final geometric check of every
  text bounding box against its node, every connector against every text and
  node bounding box, and every arrowhead against neighboring lines and nodes.
  Adjust and recheck until no text-box, text-line, box, connector, or
  arrowhead overlap remains. A diagram with any of these defects is not ready
  for delivery.
  Keep validation, transaction, assumptions, and unresolved-rule notes
  secondary to the row flow.
- Do not add unsupported source-system claims, invented data, or
  approved-sounding business rules. Deliver the SVG itself, not a screenshot.

## Build with the tool and check before delivery

Do not hand-place SVG coordinates. Lay the diagram out as data and let
`tools/data_flow/flow_svg.py` draw and check it (no database, no network).

1. **Write the layout spec** as JSON in a scratch folder outside the
   repository (the session folder, not `docs/`): the full package name as
   `title`, the `columns` with their gaps, one `flows` entry per independent
   source branch plus one `derived` and one `control` flow, the `nodes` (kind
   `source`, `step`, `target`, `control` or `note`; text lines; column and y)
   and the `edges` (box side, offset or `"match"` for a straight line, label,
   flow and `evidence`). Gaps must leave room for the labels. The schema is in
   the module docstring. Do not keep the spec unless asked.
2. **Render:** `python tools/data_flow/flow_svg.py render <spec.json>
   <package folder>/<SUBJECT>_Data_Flow.svg`. If the person chose to redraw,
   delete the old SVG first, as above. The tool sizes each box from measured
   text, derives every anchor from the box edges, refuses a connector without
   evidence, a label or room for the label, writes the SVG, and then checks it.
3. **Zero defects.** `check` reports text outside its box, a connector through
   or within 12 units of a box, overlapping or too-close connectors, shared
   anchors, gaps under 60 (connected) or 35 (not connected), labels touching
   anything, dead ends, a schema qualifier in a node title, a title other than
   the full package name, and palette contrast or distinctness failures.
   Fix every defect by changing the spec and rendering again. Never edit the
   SVG by hand and never lower a threshold to pass.
4. **Look at it.** The checker cannot judge readability or meaning. Open the
   SVG in the browser fitted to the window and zoomed on every junction and
   box border, adding a changing `?v=N` to the URL because the browser caches
   the file. Fix what you see, whatever the checker said.
5. **Re-check the lineage.** Compare every connector with the evidence table
   once more, and confirm that no source, branch or output of the package is
   missing from the diagram.
6. **Report only what you did.** The summary names the checker result, that
   the evidence table was compared with the diagram and that the render was
   viewed, and lists any open point. Never write "verified" or "ready" for a
   step you did not run. If a defect remains, say so instead of delivering.
