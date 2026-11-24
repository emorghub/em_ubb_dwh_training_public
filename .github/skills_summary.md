## ba-1-analyse-requirement
Analyst step 1. Turns a change request document into `change-requests/<CR_ID>/<CR_ID>_Requirements.xlsx`: requirements quoted from it (explicit, interpretation or assumption), KPIs, dimensions, business rules, required inputs, proposed glossary changes. Stops at `in_review`; a person approves in Excel.

## ba-2-analyse-data-gaps
Analyst step 2. From approved requirements, finds every input in CORE, staging, a delivery agreement, a source system, or nowhere, and plans the loads (one mapping per target table): `<CR_ID>_Gap_Analysis.xlsx`. Stops at `in_review`; a person approves in Excel.

## ba-3-specify-baseline-changes
Analyst step 3. From an approved gap analysis, writes the new version of each delivery agreement that must deliver more, into the change request's folder; the baseline agreements are never changed. Stops at `in_review`; a person approves in Word.

## ba-4-create-mapping-spec
Analyst step 4. Turns one approved Load_Plan row, or a small request (chat, pasted ticket text, a started workbook, or a change to an existing mapping), into a verified mapping workbook `specs/<folder>/<ID>.xlsx`, researching the existing mappings and the table scripts in `sql/` first (never a database). Stops at `in_review`; a person approves in Excel.

## dev-1-implement-staging-change
Developer step. From the approved delivery agreements of a change request, generates the staging `ALTER`/`CREATE TABLE` scripts into `change-requests/<CR_ID>/staging/`, reviews them, and hands over for manual deployment.

## dev-2-implement-mapping
Developer step. From an approved mapping workbook, re-verifies it, generates the table DDL (create or alter), the PL/SQL load package and the utPLSQL tests into the mapping's own folder `specs/<folder>/`, next to the workbook, finishes the test data, reviews, and hands over for manual deployment.

## dev-3-prepare-deployment
Developer step 3. For a mapping whose code is generated, writes the deployment runbook (ordered steps, schema, parameters, a check that the earlier mappings of the change request are deployed) and two read-only preflight scripts next to the workbook, then builds the deployment package, a zip for deploying from another machine, Windows or Linux. Never deploys or runs anything.

## query-er-diagram
Visualizes one or more SQL queries as SVG diagrams of their tables, joins, cardinalities and filters, using the exported schema without connecting to a database. This is separate from the change-request workflow.

## do-data-flow
Traces an ETL package's implemented row flow, transformations, keys, targets and control metadata into a self-contained SVG data-flow diagram, without inventing behavior or treating illustrative fixtures as approved business policy.
