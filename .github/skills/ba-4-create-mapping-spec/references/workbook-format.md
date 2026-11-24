# Mapping workbook format

One workbook per mapping: `specs/<folder>/<MAPPING_ID>.xlsx`. The layout is
owned by `tools/mapping_spec/workbook_format.py`; the rules below are enforced by
`validate_mapping` in `tools/mapping_spec/mapping_validation.py` (tests:
`tests/`). If a rule here is not enforced by that
code, this file says so. Keep the two in step.

Write workbooks through `python tools/mapping_spec/mapping_workbook.py write
<file>.json`, never by editing cells from an AI session. `mapping_workbook.py
schema` prints the JSON shape; `show <ID> --json` gives you the current one.

## Why it is this strict

The approved workbook is the only input to generating the target table's
DDL, the load package and its tests (`tools/codegen/generate.py`). Every
part of that SQL comes from a structured cell:

| SQL part | Comes from |
|---|---|
| `CREATE TABLE` columns, types, `NOT NULL` | Columns: `Target_Column`, `Target_Type`, `Nullable` |
| Primary key | Mapping: `Business_Key` (plus `VALID_FROM` for `scd2`) |
| Column comments | Columns: `Business_Name`, `Description` |
| `SELECT` list | Columns: `Transformation_Rule`, aliased as `Target_Column` |
| `FROM` / `JOIN ... ON` | Mapping: `Driving_Table`; Joins sheet |
| `WHERE` | Mapping: `Filter` |
| `GROUP BY` | Mapping: `Group_By` (aggregating loads only) |
| A per-row step under the `GROUP BY` (window functions, running totals) | Item_Columns sheet (optional, aggregating loads only) |
| Guards checked before the load writes anything | Acceptance_Criteria rows with `Check_Type = guard` |
| Delete / merge / insert / history shape | Mapping: `Load_Strategy`, `Reload_Predicate`, `Source_Snapshot`; Columns: `SCD_Type` |
| Procedure signature | Mapping: `PLSQL_Proc`, `Parameters` |
| Tests | Acceptance_Criteria sheet |

Prose has a place - `Intent`, `Not_For`, `Description`, `Notes`, the
Decisions sheet - but never carries a fact the SQL needs.

## Mapping sheet (Field | Value | Help)

Always required: `Mapping_ID` (equals the file name), `Status`,
`Target_Table`, `Business_Key`, `PLSQL_Proc`.

Additionally required before `Status = approved`: `Owner`, `Approved_By`,
`Approved_On` (YYYY-MM-DD), `Intent`, `Table_Description`,
`Grain`, `Parameters`, `Driving_Table`, `Filter`, `Load_Strategy`.

| Field | Meaning and rules |
|---|---|
| `Status` | `draft` -> `in_review` -> `approved`. Only a named person sets `approved`, in Excel. The writer tool refuses to. |
| `Source_Ref` | ticket key, URL, or `chat`. |
| `Target_Table` | `SCHEMA.TABLE`, e.g. `UBB_CORE2.LOAN_HIST`. |
| `Table_Description` | What one row means. Becomes the table comment. |
| `Business_Key` | Target columns, comma separated. Each must be a `Target_Column` with `Nullable = N`. Becomes the primary key. |
| `PLSQL_Proc` | `SCHEMA.PACKAGE.PROCEDURE`. |
| `Parameters` | `NAME TYPE` pairs separated by `;`, e.g. `P_BUSINESS_DATE DATE`, or `none`. A parameter name must not equal any source or target column name (checked) - in PL/SQL the column would win. |
| `Driving_Table` | `SCHEMA.TABLE` whose rows define the grain (the `FROM` table). |
| `Filter` | SQL condition without `WHERE`, columns as `TABLE.COLUMN`, parameters by name - or `none`. Referenced columns are checked. |
| `Group_By` | Aggregating loads only, else empty: the target columns that identify one target row when several source rows are summed into it, comma separated. See "Aggregating loads" below. |
| `Load_Strategy` | `full` / `delete_insert` / `merge` / `append` / `scd2` - see below. |
| `Reload_Predicate` | `delete_insert` only (required there, forbidden elsewhere): which target rows one run replaces, bare target column names, e.g. `BUSINESS_DATE = P_BUSINESS_DATE`. `verify_mapping.py` checks it names only target columns and parameters; whether the loaded rows satisfy it is for the tests. |
| `Source_Snapshot` | `scd2` only (required there, forbidden elsewhere): `full` = every run's source holds every key, so a key missing from it is recorded as deleted (`IS_DELETED = 'Y'`); `delta` = the source holds only changed keys, so a missing key is unchanged. |
| `Not_For`, `Preconditions`, `Error_Handling` | One item per line. |

Load strategies (the generated code, `tools/codegen/templates/package.sql.j2`):

| Strategy | Each run... | Re-run of the same parameters |
|---|---|---|
| `full` | deletes every row, inserts the source result | same result |
| `delete_insert` | deletes rows matching `Reload_Predicate`, inserts the source result | same result |
| `merge` | updates rows whose business key exists (only `SCD_Type 1` columns, only when a value really changed), inserts the rest | same result |
| `append` | inserts only | fails on the primary key (so `rerun_idempotent` is rejected) |
| `scd2` | keeps history: closes the current version of each key whose `SCD_Type 2` values changed and adds a new one from the run's date | same result; a run for an earlier date than already loaded rebuilds the later history |

`scd2` (history) rules, all checked by the validator:

- The procedure takes **exactly one parameter, a `DATE`**: the date the
  source data is valid for. It becomes `VALID_FROM` of the versions a run
  adds. The `Filter` or a join condition must use it, so the source can be
  read as of any loaded date - a late or re-run date replays the later
  dates from the source, which must therefore still hold them.
- Do **not** list `VALID_FROM`, `VALID_TO` or `IS_DELETED` on the Columns
  sheet: the generator adds them, with `VALID_FROM` in the primary key.
  `VALID_TO` is exclusive and `DATE '9999-12-31'` marks the current
  version, so "as of date D" is `VALID_FROM <= D AND D < VALID_TO`.
  `IS_DELETED` exists only with `Source_Snapshot = full`.
- Every non-key column is `SCD_Type 2` (tracked: a change adds a version)
  or `0` (written with each new version, never compared, e.g. a load ID);
  at least one must be `2`. `SCD_Type 1` does not exist in an `scd2`
  mapping, and `2` does not exist in any other.
- The generator also writes `<TABLE>_LOAD_LOG.sql`: the table of loaded
  dates that a run for an earlier date replays.

Every strategy is all or nothing: on any error the load rolls back to its
own savepoint, so a failed run never leaves a partial snapshot.

## Aggregating loads (`Group_By`)

When several source rows become one target row (collateral summed per
loan, exposure per partner), fill `Group_By`. The source query gets
`GROUP BY` the expressions of those columns. Rules, all checked by the
validator - deliberately stricter than Oracle, so a "not a GROUP BY
expression" error (ORA-00979) is caught before anyone compiles:

- `Group_By` names Target_Columns and includes **every** `Business_Key`
  column; at least one of them must read a source column. A grouped
  column's rule uses no aggregate function.
- Every other column reads source columns **only inside an aggregate**
  (`SUM`, `MIN`, `MAX`, `COUNT`, `AVG`, `LISTAGG`, `MEDIAN`, `STDDEV`,
  `VARIANCE`, `ANY_VALUE`; `KEEP (...)` and `WITHIN GROUP (...)` are part
  of the call). A value that is the same on every row of the group is
  written `MAX(LOAN_HIST.OUTSTANDING_AMT)`, not copied (`direct` is
  rejected outside `Group_By`). Parameters and constants need no aggregate.
- An aggregate anywhere while `Group_By` is empty, or in the `Filter` or a
  join condition (that would be `HAVING`), is an error.
- With `merge` or `scd2`, a compared `NUMBER(p,s)` column that multiplies
  or divides without `ROUND` is a warning: the stored value is rounded, so
  every run would look like a change (scd2: a new version every day).

`verify_mapping.py` adds, for aggregating mappings: a join that returns
several rows per driving row is INFO (it is what gets summed); **two** such
joins are a double-counting WARN (they multiply each other); a `SUM` or
`COUNT` over a table that has one row per driving row, when a later join
returns several, is a WARN (each value is counted once per joined row);
and a business key equal to `Group_By` is unique by construction.

## Columns sheet (one row per target column, in table order)

Required in every row: `Target_Column`, `Source_Table`, `Transformation_Rule`.
Required before approval, in every row: `Target_Type`, `Nullable`,
`SCD_Type`, `Business_Name`, `Description`.

| Column | Meaning and rules |
|---|---|
| `Target_Column` | Oracle identifier, unique within the mapping. |
| `Target_Type` | Oracle type: `VARCHAR2(20)`, `NUMBER(18,2)`, `DATE`, `TIMESTAMP`, ... (checked). |
| `Nullable` | `Y` / `N`. |
| `Source_Table` | `SCHEMA.TABLE` (must be the driving table or a joined table), `PARAM`, `EXPR`, or `ITEM` (an Item_Columns value, see below). |
| `Source_Column` | The source column(s) the rule reads, comma separated (checked against the schema); the parameter name for `PARAM`; a label for `EXPR`. |
| `Transformation_Rule` | SQL only: `direct` (the one `Source_Column`, unchanged), `NULL`, or an Oracle expression with columns as `TABLE.COLUMN` (bare table name) and parameters by name. Every referenced column is checked. The validator warns when it looks like prose (heuristic). |
| `SCD_Type` | `1` = a merge overwrites the value; `0` = never updated once written (e.g. an insert timestamp); `2` = `scd2` only: a change closes the current version and adds a new one. |
| `Business_Name`, `Description` | For the business reader: they become the column comment. |
| `Notes` | Why the rule is what it is. |

## Item_Columns sheet (optional; aggregating loads only)

Some values must be computed per source row **before** they are summed,
with a window function - typically a running total. Example: a cap that
follows a priority, where each collateral item covers only what the items
before it left of the exposure:

| Item_Column | Transformation_Rule |
|---|---|
| `RECOGNISED` | `LEAST(COLL.VALUE_AMT, GREATEST(LOAN.GROSS_AMT - NVL(SUM(COLL.VALUE_AMT) OVER (PARTITION BY REL.LOAN_REF ORDER BY REL.ALLOCATION_PRIORITY ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0), 0))` |
| `GROSS` | `LOAN.GROSS_AMT` |

Oracle does not allow a window function inside `SUM` in one query, so the
generator then builds two levels: an inner query with the `Group_By` values
and the item columns, one row per source row, and an outer query that
groups it (alias `ITEM`):

```sql
SELECT ITEM.LOAN_ID AS LOAN_ID, ROUND(SUM(ITEM.RECOGNISED), 2) AS RECOGNISED_AMT, ...
FROM (SELECT <Group_By rules>, <item rules> FROM ... WHERE <Filter>) ITEM
GROUP BY ITEM.LOAN_ID
```

Rules, all checked by the validator:

- Only with `Group_By`. Columns: `Item_Column` (Oracle name, unique, not a
  `Group_By` column's name), `Transformation_Rule`, `Description`, `Notes`.
- An item rule reads source tables and parameters (checked against `sql/`),
  uses no aggregate (a window function with `OVER` is fine) and never reads
  another item column - repeat the expression instead.
- On the Columns sheet, a `Group_By` column still reads the source tables;
  every other column reads item columns only: `Source_Table` `ITEM`,
  `Source_Column` the item column(s), rule an aggregate such as
  `SUM(ITEM.RECOGNISED)` (or a parameter or constant).
- `verify_mapping.py` follows `ITEM.x` back to the tables its rule reads for
  the double-counting check.

## Joins sheet (one row per joined table, in order)

| Column | Meaning and rules |
|---|---|
| `Table` | `SCHEMA.TABLE`, joined to the driving table (or an earlier join). A table may appear once (no self-joins). |
| `Join_Type` | `inner`: a driving row with no match is left out. `left`: kept, joined columns empty. This **is** the answer to "what happens when the lookup is missing" - write the same decision in `Error_Handling`. |
| `Condition` | Equality condition with `TABLE.COLUMN` on both sides, must reference the joined table (checked). |

## Acceptance_Criteria sheet (each row becomes one utPLSQL test)

At least 2 before approval. `AC_ID` unique.

| Check_Type | Test generated | Needs |
|---|---|---|
| `unique_key` | No business key occurs twice in the target | - |
| `rerun_idempotent` | Running the load twice leaves the same row count and content | not with `append` |
| `all_source_rows_loaded` | Every business key the source query produces is in the target | - |
| `zero_rows` | `Check_SQL` (finds rule-breaking rows) returns no rows | `Check_SQL` |
| `expected_value` | `Check_SQL` returns one value equal to `Expected` (numeric compare when numeric) | `Check_SQL`, `Expected` |
| `guard` | Not only a test: the load package runs `Check_SQL` (it finds **source** rows that must stop the whole run) before writing anything and fails with `ORA-20005` when it finds any. The test loads good data, adds rows that break the guard, and expects the run refused and the target unchanged | `Check_SQL` |

`Check_SQL` may use parameters by name; in the test they are constants from
the test data package, in a guard the procedure's own parameters. No
trailing `;`. A `guard` is how "no partial snapshot when X is missing" is
written: `Preconditions` and `Error_Handling` stay descriptive text that
nothing runs.

## Sources and Decisions sheets

- **Sources**: `Topic`, `Source_Type` (sql, user, other; `sql` = a script in the `sql/` folder), `Reference`, `Finding`.
- **Decisions**: `ID`, `Topic`, `Question`, `Decision`, `Decided_By`,
  `Decided_On`, `Status` (`open` / `decided`). Any `open` row blocks approval.

## Approval

Before approval nothing is required beyond the always-required fields, so a
draft can be saved at any point. An approved workbook fails validation if
any cell contains `TODO`, any decision is open, any column lacks a
type/nullable/SCD type/business name/description, or there are fewer than 2
acceptance criteria.

The content fingerprint (`mapping_workbook.py fingerprint <ID>`) covers
everything except `Status`, `Approved_By`, `Approved_On`. The writer keeps
an approval only when the fingerprint is unchanged; every generated SQL
file carries the fingerprint it was generated from.
