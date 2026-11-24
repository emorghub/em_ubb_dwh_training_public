# Review checklist for generated code

Walk through this with the mapping workbook open
(`python tools/mapping_spec/mapping_workbook.py show <MAPPING_ID>`). Each
item is a yes/no; report every "no" to the developer with the line it is on.

## Table (`<TABLE>.sql`, or `<MAPPING_ID>.sql`)

- [ ] Every row of the Columns sheet is a column, in the same order, with
      the same type and `NOT NULL` exactly where Nullable = N.
- [ ] The primary key is exactly the Business_Key (scd2: Business_Key plus
      VALID_FROM).
- [ ] scd2 only: VALID_FROM, VALID_TO (and IS_DELETED for a full snapshot)
      follow the mapped columns; the period check, the IS_DELETED check and
      the one-open-version unique index are there; `<TABLE>_LOAD_LOG.sql`
      exists.
- [ ] Every column has a comment built from Business_Name and Description.
- [ ] Change script only: nothing is dropped; every widening is real; every
      MANUAL DECISION has been shown to the developer.

## Load package (`<PACKAGE>.sql`)

- [ ] Package and procedure names match PLSQL_Proc; parameters match
      Parameters (names, order, types) and each is checked for NULL.
- [ ] The `SELECT` list is exactly the Transformation_Rules, each aliased
      to its Target_Column; `direct` rules read the right source column.
- [ ] `FROM` is the Driving_Table; every join is there, with the right type
      (`JOIN` for inner, `LEFT JOIN` for left) and condition.
- [ ] The `WHERE` is the Filter (none when Filter is `none`).
- [ ] Aggregating only: the `GROUP BY` lists the rules of the Group_By
      columns that read a source column (a parameter or constant is left
      out); every other `SELECT` expression reads source columns only
      inside an aggregate.
- [ ] Item_Columns only: the source query has two levels - the inner one
      selects the Group_By rules and each item rule (aliased by its
      Item_Column) from the sources with the Filter; the outer one reads only
      `ITEM.<name>`, parameters and constants, and groups by `ITEM.<Group_By
      column>`.
- [ ] Guards only: `check_guards` holds every `guard` Check_SQL unchanged,
      is called before the first DELETE/MERGE/INSERT (scd2: for the date and
      every later loaded date, before `rewind`), and raises `-20005`; the
      spec declares `e_guard_failed`.
- [ ] The strategy block matches Load_Strategy:
      delete_insert deletes exactly the Reload_Predicate rows first;
      full deletes everything first (no TRUNCATE);
      merge matches on the business key, updates only SCD_Type 1 non-key
      columns, only when a value changed;
      append only inserts;
      scd2 compares exactly the SCD_Type 2 non-key columns (NULL-safe),
      rewinds and replays from the load log when the date was already
      loaded or is earlier than a loaded one, and (full snapshot) records
      missing keys as deleted and refuses an empty snapshot.
- [ ] There is no `COMMIT` in the procedure, and the only rollback is
      `ROLLBACK TO SAVEPOINT` of the savepoint it sets as its first
      statement, in the exception handler, followed by `RAISE`.
- [ ] The header carries the mapping ID, the current fingerprint and the
      approver.

## Tests (`UT_<TABLE>.sql`)

- [ ] One test per acceptance criterion, named after its AC_ID, plus
      `t_fixture_has_rows` (scd2: plus `t_history_next_date`,
      `t_history_out_of_order` and `t_history_rerun_earlier_date`).
- [ ] A `guard` test loads, calls the guard's `seed_<AC_ID>`, expects the
      next run refused (`e_guard_failed`) and the target unchanged.
- [ ] `zero_rows` / `expected_value` tests embed the Check_SQL unchanged.
- [ ] Parameter constants come from the data package.

## Test data (`UT_<TABLE>_DATA.sql`)

- [ ] No `TODO` left.
- [ ] Parameter test values match no real staging data.
- [ ] Values are realistic: allowed values and formats taken from the table scripts
      in `sql/` (check constraints, column comments, lengths), test IDs prefixed
      `UT` so they never collide with real rows.
- [ ] There is a row for every case in the file's comment (outside the
      filter, missing inner-join lookup, left-join without a match, and data
      each business check would catch).
- [ ] Every row the happy path needs joins correctly (same key values on
      both sides of each join condition).
- [ ] scd2 only: `seed_next_date` holds the source as of `NEXT_DATE` and
      covers every case in its comment (a changed key, a new key, and for
      a full snapshot a missing key), without colliding with seed's rows.
- [ ] Aggregating only: at least one target row gets two source rows.
- [ ] Item_Columns only: one group's rows are in an order that matters
      (e.g. the second item is cut by what the first already covers).
- [ ] Guards only: `seed` passes every guard, and each `seed_<AC_ID>`
      inserts rows its guard's Check_SQL finds for the test parameters.

## Before hand-over

- [ ] `python tools/codegen/generate.py <MAPPING_ID> --check` passes.
