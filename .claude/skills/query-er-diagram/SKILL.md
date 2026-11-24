---
name: query-er-diagram
description: Generate a standalone SVG entity-relationship diagram from one or more SQL queries, showing query joins, cardinalities and filters verified against the repository's exported schema. Use when asked to draw or visualize the tables and relationships in a query.
argument-hint: "<SQL file(s)>"
---

# query-er-diagram

Create a standalone SVG diagram for each supplied SQL query. This is a
visualization of the query, not a change-request workflow step.
Never connect to a database: do not execute or modify the query, or change
schema exports.

Input: **$ARGUMENTS** (one or more SQL file paths), or query files supplied in
the conversation. If no query is identified, ask for it. If the user asks for
all queries in a folder, identify the query files in that folder first. Write
each SVG next to its query, using the same base filename and `.svg` extension.
Inspect an existing output before changing it and preserve unrelated edits.

## 1. Research the query

Read `AGENT_BRIEFING.md`, each complete query, and the relevant table and
constraint scripts under `sql/`. The exported scripts are the source of truth
for table columns and constraints. Resolve aliases, CTEs and subqueries to
their underlying tables, without treating a CTE or a parameter row as a
physical table. For unqualified or otherwise ambiguous table references, do
not guess which schema the query uses.

If a table has no `CREATE TABLE` script, mark its columns and keys unknown
and ask for the export; do not invent them. Mark other unproven cardinalities
and relationships as unknown and report the limitation.

## 2. Draw the query

Use [the reference diagram](assets/query_1_partner_risk_exposure.svg) in this
skill's `assets/` folder as the visual reference. Show:

- Every physical table used by the query, with its alias where useful.
  Include relevant join, filter, output and measure columns, and primary and
  foreign keys verified in the exports. Name the actual foreign-key target
  even when it is not shown as a query table.
- Query relationships with their complete predicates and join types, including
  joins through CTEs, self-joins and correlated subqueries. Distinguish query
  joins from declared foreign keys. Represent `EXISTS` and `NOT EXISTS` as
  semi-joins and anti-joins, not ordinary joins.
- Cardinalities at both ends, such as `1`, `0..1`, `0..n` or `unknown`, based
  on the full predicate and verified keys and nullability. They describe
  possible matching rows before join filtering or outer-join preservation,
  not a guarantee that a matching snapshot exists. Do not infer uniqueness
  from column names or sample data.
- Assume history periods do not overlap and state the assumption on the
  diagram. Infer at most one history row only when the query's point-in-time
  predicate and matching business key support it; do not apply that bound to
  unfiltered history.
- Every filter near or inside the table it applies to. Preserve `ON` versus
  `WHERE`, especially for outer joins. Label multi-table and subquery
  predicates at their actual scope and show `HAVING` separately as a
  post-aggregation filter. Include parameter values or expressions and
  identify CTE filters that apply to multiple aliases.

Match the reference's clear table boxes, dark headers, distinct key and
filter styling, readable labels and light background. Route connectors around
table and filter boxes; avoid overlaps with labels and other connectors where
possible. Size the canvas for the content and include an accessible SVG title
and description. Adapt the layout to the query.

## 3. Verify and hand over

Parse each SVG as XML, check that connectors do not cross table or filter
boxes, and compare the relationships, cardinalities and filters with the
query and exported scripts. Check the rendered diagram for legibility when a
renderer is available. Report the resulting file paths, assumptions and any
unresolved ambiguities or verification limitations.
