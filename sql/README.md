# sql/ - the database, as files

The scripts in the `*.schema` folders are exported from the Oracle database
with SQL Developer, one folder per schema. They are the only source of truth
that the tools and the assistant use for table names, column names, types,
nullability, keys, check constraints and comments. **Nothing in this workflow
connects to a database.** When the database changes, a person exports the
scripts again.

| Folder | Contents |
|---|---|
| `UBB_CORE2.schema/` | Core schema: one file per table (`<TABLE>.sql`), its constraints (`<TABLE>_CONSTRAINT.sql`, `<TABLE>_REFCONSTRAINT.sql`), indexes, sequences and the `PKG_ETL_*` packages (`<PKG>.sql` is the package specification, `<PKG>_1.sql` the body) |
| `UBB_Staging2.schema/` | Staging schema: one `CREATE TABLE` script per `STG_*` table (`<TABLE>.sql`), its constraints (`<TABLE>_CONSTRAINT.sql`, `<TABLE>_REFCONSTRAINT.sql`) and grants |

The tools read these files through `tools/mapping_spec/schema_catalog.py`. It
understands `CREATE TABLE` (columns, defaults, NOT NULL, inline constraints),
`ALTER TABLE ... ADD CONSTRAINT`, `COMMENT ON` and `GRANT`, and ignores
indexes, sequences, packages and storage clauses.

## Things to know

- The `ANNOTATIONS_*`, `METADATA_ANNOTATIONS*`, `PRVT_ANNOTATIONS_INTERNAL` and
  `GROUP_ID_SEQ` objects and the `Generated-*.sql` files belong to the SQL
  Developer export, not to the project.
- Both schemas use automatic list partitioning on `LOAD_ID`; the export lists
  one `SYS_Pnnn` partition per load. They do not affect the tools.
- The files carry no passwords and no row data.
- To export again: in SQL Developer, export the objects of each schema with
  their DDL (tables including constraints and comments, packages), into the
  matching `*.schema` folder.
