"""What tables and columns exist - read from the scripts in the ``sql/`` folder.

This module never connects to a database. The ``sql/`` folder holds the
exported scripts of the two schemas (one ``*.schema`` folder each, for
example ``sql/UBB_CORE2.schema/`` and ``sql/UBB_Staging2.schema/``), and
those scripts are the only source of truth the tools use for column names,
types, nullability, keys, check constraints and comments.

What it reads, from every ``*.sql`` file directly inside a ``*.schema`` folder:

- ``CREATE TABLE "OWNER"."NAME" (...)``: columns, types, defaults, NOT NULL,
  and the inline primary key, unique, foreign key and check constraints
- ``ALTER TABLE ... ADD CONSTRAINT`` and ``... MODIFY (... NOT NULL)``: the same
  facts when a script keeps its constraints in a separate file
- ``COMMENT ON TABLE`` and ``COMMENT ON COLUMN``
- ``GRANT ... ON "OWNER"."NAME"``: proves a table exists even when its own
  ``CREATE TABLE`` script is missing (state ``no_ddl``)

Packages, indexes, sequences, partitions and storage clauses are ignored.

To check a different folder (a test, a copy), set the environment variable
``UBB_SQL_DIR`` or call ``load_catalog(path)``.

Planned staging columns: ``catalog()`` (not ``load_catalog``) also holds the
staging tables and columns that an approved change request asks for but
``sql/`` does not have yet (tools/change_request/planned_staging.py). They
are marked: ``Column.planned`` / ``Table.planned`` name the document that
asks for them. Once
the staging change is deployed and ``sql/`` exported again, they come from
the scripts like any other column. ``UBB_PLANNED_STAGING=off`` leaves them out.

Planned mapping targets: the same overlay holds the tables and columns that
the Load_Plan mappings of an approved change request would create
(tools/change_request/planned_mappings.py), marked ``mapping <ID> (<status>)``,
so a later mapping can be written before an earlier one is deployed. A
mapping's own target is compared against ``deployed_table`` instead.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SQL_DIR_ENV = "UBB_SQL_DIR"
PLANNED_ENV = "UBB_PLANNED_STAGING"


def default_sql_dir() -> str:
    return os.environ.get(SQL_DIR_ENV) or os.path.join(REPO_ROOT, "sql")


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


@dataclass
class Column:
    name: str
    type: str  # normalised, e.g. VARCHAR2(30 CHAR), NUMBER(18,0), TIMESTAMP(6), DATE
    nullable: bool = True
    default: str = ""
    comment: str = ""
    planned: str = ""  # the document that asks for it, when sql/ does not have it yet


@dataclass
class ForeignKey:
    name: str
    columns: list
    ref_owner: str
    ref_table: str
    ref_columns: list


@dataclass
class Table:
    owner: str
    name: str
    has_ddl: bool = False
    columns: dict = field(default_factory=dict)  # NAME -> Column, in table order
    primary_key: list = field(default_factory=list)
    unique_keys: dict = field(default_factory=dict)  # constraint name -> [columns]
    foreign_keys: dict = field(default_factory=dict)  # constraint name -> ForeignKey
    checks: dict = field(default_factory=dict)  # constraint name -> condition text
    comment: str = ""
    source_files: list = field(default_factory=list)
    planned: str = ""  # the delivery agreement, when the whole table is not in sql/ yet

    @property
    def qualified(self) -> str:
        return "{0}.{1}".format(self.owner, self.name)

    def column_types(self) -> dict:
        return {name: col.type for name, col in self.columns.items()}

    def unique_column_sets(self) -> list:
        """Every column set that identifies one row: the primary key, then the unique keys."""
        sets = [list(self.primary_key)] if self.primary_key else []
        sets.extend(list(cols) for cols in self.unique_keys.values())
        return sets


@dataclass
class Catalog:
    sql_dir: str
    tables: dict = field(default_factory=dict)  # "OWNER.NAME" -> Table

    def table(self, qualified: str):
        return self.tables.get(str(qualified).strip().upper())

    def schemas(self) -> set:
        return {t.owner for t in self.tables.values()}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

CREATE_TABLE = re.compile(
    r'CREATE\s+(?:GLOBAL\s+TEMPORARY\s+)?TABLE\s+"(?P<owner>[^"]+)"\."(?P<name>[^"]+)"', re.IGNORECASE
)
ADD_CONSTRAINT = re.compile(
    r'ALTER\s+TABLE\s+"(?P<owner>[^"]+)"\."(?P<name>[^"]+)"\s+ADD\s+(?P<body>CONSTRAINT\b.*?)(?=\n\s*ALTER\s+TABLE|\Z)',
    re.IGNORECASE | re.DOTALL,
)
MODIFY_NOT_NULL = re.compile(
    r'ALTER\s+TABLE\s+"(?P<owner>[^"]+)"\."(?P<name>[^"]+)"\s+MODIFY\s*\(\s*"(?P<col>[^"]+)"\s+NOT\s+NULL', re.IGNORECASE
)
COMMENT_TABLE = re.compile(
    r"COMMENT\s+ON\s+TABLE\s+\"(?P<owner>[^\"]+)\"\.\"(?P<name>[^\"]+)\"\s+IS\s+'(?P<text>(?:[^']|'')*)'", re.IGNORECASE
)
COMMENT_COLUMN = re.compile(
    r"COMMENT\s+ON\s+COLUMN\s+\"(?P<owner>[^\"]+)\"\.\"(?P<name>[^\"]+)\"\.\"(?P<col>[^\"]+)\"\s+IS\s+'(?P<text>(?:[^']|'')*)'",
    re.IGNORECASE,
)
GRANT = re.compile(r'GRANT\s+[^;"]*?\s+ON\s+"(?P<owner>[^"]+)"\."(?P<name>[^"]+)"', re.IGNORECASE)
CONSTRAINT = re.compile(
    r'CONSTRAINT\s+"(?P<cname>[^"]+)"\s+(?P<kind>PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CHECK)\s*\(', re.IGNORECASE
)
REFERENCES = re.compile(
    r'REFERENCES\s+"(?P<owner>[^"]+)"\."(?P<name>[^"]+)"\s*\((?P<cols>[^)]*)\)', re.IGNORECASE
)
COLUMN_DEF = re.compile(r'^"(?P<name>[^"]+)"\s+(?P<rest>.*)$', re.DOTALL)
TYPE = re.compile(r"^(?P<base>[A-Za-z][A-Za-z0-9_]*)\s*(?P<args>\([^)]*\))?", re.DOTALL)


def _matching_paren(text: str, open_index: int) -> int:
    """Index of the ')' that closes the '(' at open_index, ignoring quotes."""
    depth = 0
    quote = ""
    index = open_index
    while index < len(text):
        ch = text[index]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _split_top_level(text: str) -> list:
    """Split on commas that are not inside parentheses or quotes."""
    parts = []
    depth = 0
    quote = ""
    current = []
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _names(text: str) -> list:
    """'"A", "B"' -> ['A', 'B']"""
    return [m.upper() for m in re.findall(r'"([^"]+)"', text)]


def normalise_type(base: str, args: str = "") -> str:
    """``TIMESTAMP (6)`` -> ``TIMESTAMP(6)``; ``NUMBER(18, 0)`` -> ``NUMBER(18,0)``."""
    base = base.upper()
    args = re.sub(r"\s*,\s*", ",", (args or "").strip())
    args = re.sub(r"\(\s*", "(", args)
    args = re.sub(r"\s*\)", ")", args)
    return base + args.upper()


def _parse_column(item: str):
    match = COLUMN_DEF.match(item)
    if not match:
        return None
    rest = match.group("rest").strip()
    type_match = TYPE.match(rest)
    if not type_match:
        return None
    col_type = normalise_type(type_match.group("base"), type_match.group("args") or "")
    after = rest[type_match.end():].strip()
    default = ""
    default_match = re.search(
        r"\bDEFAULT\b(.*?)(?=\bNOT\s+NULL\b|\bENABLE\b|\bNULL\b|$)", after, re.IGNORECASE | re.DOTALL
    )
    if default_match:
        default = " ".join(default_match.group(1).split())
    nullable = not re.search(r"\bNOT\s+NULL\b", after, re.IGNORECASE)
    return Column(name=match.group("name").upper(), type=col_type, nullable=nullable, default=default)


def _apply_constraint(table: Table, text: str) -> None:
    """Record one ``CONSTRAINT "N" <kind> (...)`` clause on the table. Safe to
    call twice for the same constraint (the export repeats them)."""
    match = CONSTRAINT.search(text)
    if not match:
        return
    name = match.group("cname").upper()
    kind = re.sub(r"\s+", " ", match.group("kind").upper())
    open_index = match.end() - 1
    close_index = _matching_paren(text, open_index)
    if close_index < 0:
        return
    inner = text[open_index + 1:close_index]
    if kind == "PRIMARY KEY":
        table.primary_key = _names(inner)
        for col in table.primary_key:
            if col in table.columns:
                table.columns[col].nullable = False
    elif kind == "UNIQUE":
        table.unique_keys[name] = _names(inner)
    elif kind == "FOREIGN KEY":
        ref = REFERENCES.search(text[close_index:])
        if ref:
            table.foreign_keys[name] = ForeignKey(
                name=name,
                columns=_names(inner),
                ref_owner=ref.group("owner").upper(),
                ref_table=ref.group("name").upper(),
                ref_columns=_names(ref.group("cols")),
            )
    elif kind == "CHECK":
        table.checks[name] = " ".join(inner.split())


def _get_table(catalog: Catalog, owner: str, name: str) -> Table:
    key = "{0}.{1}".format(owner.upper(), name.upper())
    table = catalog.tables.get(key)
    if table is None:
        table = Table(owner=owner.upper(), name=name.upper())
        catalog.tables[key] = table
    return table


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _parse_file(catalog: Catalog, path: str, text: str) -> None:
    rel = os.path.basename(path)

    for match in CREATE_TABLE.finditer(text):
        open_index = text.find("(", match.end())
        if open_index < 0:
            continue
        close_index = _matching_paren(text, open_index)
        if close_index < 0:
            continue
        table = _get_table(catalog, match.group("owner"), match.group("name"))
        table.has_ddl = True
        table.source_files.append(rel)
        for item in _split_top_level(text[open_index + 1:close_index]):
            if re.match(r"CONSTRAINT\b", item, re.IGNORECASE):
                _apply_constraint(table, item)
                continue
            column = _parse_column(item)
            if column is not None:
                table.columns[column.name] = column

    for match in ADD_CONSTRAINT.finditer(text):
        table = _get_table(catalog, match.group("owner"), match.group("name"))
        _apply_constraint(table, match.group("body"))

    for match in MODIFY_NOT_NULL.finditer(text):
        table = catalog.tables.get("{0}.{1}".format(match.group("owner").upper(), match.group("name").upper()))
        if table is not None and match.group("col").upper() in table.columns:
            table.columns[match.group("col").upper()].nullable = False

    for match in COMMENT_TABLE.finditer(text):
        table = _get_table(catalog, match.group("owner"), match.group("name"))
        table.comment = match.group("text").replace("''", "'")

    for match in COMMENT_COLUMN.finditer(text):
        table = _get_table(catalog, match.group("owner"), match.group("name"))
        column = table.columns.get(match.group("col").upper())
        if column is not None:
            column.comment = match.group("text").replace("''", "'")

    for match in GRANT.finditer(text):
        _get_table(catalog, match.group("owner"), match.group("name"))


def schema_folders(sql_dir: str) -> list:
    return sorted(path for path in glob.glob(os.path.join(sql_dir, "*.schema")) if os.path.isdir(path))


def load_catalog(sql_dir: str = None) -> Catalog:
    """Read every ``*.sql`` file directly inside every ``*.schema`` folder of sql_dir."""
    sql_dir = os.path.abspath(sql_dir or default_sql_dir())
    catalog = Catalog(sql_dir=sql_dir)
    texts = {}
    for folder in schema_folders(sql_dir):
        for path in sorted(glob.glob(os.path.join(folder, "*.sql"))):
            texts[path] = _read(path)

    # Two passes: table scripts first, so the separate constraint, comment and
    # grant files find their table whatever order the files are in.
    for path, text in texts.items():
        if CREATE_TABLE.search(text):
            _parse_file(catalog, path, text)
    for path, text in texts.items():
        if not CREATE_TABLE.search(text):
            _parse_file(catalog, path, text)
    return catalog


# ---------------------------------------------------------------------------
# Questions the tools ask (against the sql/ folder as it is now)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _cached(sql_dir: str, planned: bool) -> Catalog:
    found = load_catalog(sql_dir)
    if planned:
        _add_planned(found)
    return found


def _add_planned(found: Catalog) -> None:
    import sys

    folder = os.path.join(REPO_ROOT, "tools", "change_request")
    if folder not in sys.path:
        sys.path.insert(0, folder)
    try:
        import planned_mappings
        import planned_staging
    except ImportError as exc:  # python-docx missing
        sys.stderr.write("NOTE: planned staging columns are not shown ({0}).\n".format(exc))
        return
    planned_staging.overlay(found)
    planned_mappings.overlay(found)


def planned_enabled() -> bool:
    return os.environ.get(PLANNED_ENV, "").strip().lower() not in ("off", "0", "no", "false")


def catalog() -> Catalog:
    """The catalog of the default sql/ folder (or UBB_SQL_DIR), plus the
    planned staging columns of approved delivery agreements. Cached for the run."""
    return _cached(os.path.abspath(default_sql_dir()), planned_enabled())


def reload() -> None:
    _cached.cache_clear()


def schemas() -> set:
    return catalog().schemas()


def table(qualified: str):
    """The Table for ``SCHEMA.TABLE``, or None when the sql/ folder does not know it."""
    return catalog().table(qualified)


def deployed_table(qualified: str):
    """Like ``table``, but only what the sql/ folder really has - no planned
    tables or columns. A mapping's own target is compared against this."""
    return _cached(os.path.abspath(default_sql_dir()), False).table(qualified)


def table_state(qualified: str) -> str:
    """``ok`` (columns known), ``no_ddl`` (only a grant or reference was found:
    the table exists but its columns are unknown), or ``unknown``."""
    found = table(qualified)
    if found is None:
        return "unknown"
    return "ok" if found.has_ddl else "no_ddl"


def columns_of(qualified: str):
    """{COLUMN: TYPE} for ``SCHEMA.TABLE``, or None when the columns are not known."""
    found = table(qualified)
    if found is None or not found.has_ddl:
        return None
    return found.column_types()


# ---------------------------------------------------------------------------
# Command line: what is in sql/ right now
# ---------------------------------------------------------------------------


def render_table(found: Table) -> str:
    lines = ["{0}{1}".format(found.qualified, "" if found.has_ddl else "  (no CREATE TABLE script: columns unknown)")]
    if found.planned:
        lines.append("  PLANNED: not in sql/ yet - promised by " + found.planned)
    if found.comment:
        lines.append("  comment: " + found.comment)
    for col in found.columns.values():
        lines.append("  {0:30} {1:24} {2}{3}{4}{5}".format(
            col.name, col.type, "NULL" if col.nullable else "NOT NULL",
            "  DEFAULT " + col.default if col.default else "",
            "  -- " + col.comment if col.comment else "",
            "  [planned: {0}]".format(col.planned) if col.planned and not found.planned else "",
        ))
    if found.primary_key:
        lines.append("  primary key: " + ", ".join(found.primary_key))
    for name, cols in found.unique_keys.items():
        lines.append("  unique {0}: {1}".format(name, ", ".join(cols)))
    for fk in found.foreign_keys.values():
        lines.append("  foreign key {0}: {1} -> {2}.{3} ({4})".format(
            fk.name, ", ".join(fk.columns), fk.ref_owner, fk.ref_table, ", ".join(fk.ref_columns)))
    for name, condition in found.checks.items():
        lines.append("  check {0}: {1}".format(name, condition))
    return "\n".join(lines)


def main(argv=None) -> int:
    """No argument: every table in sql/, per schema, and whether its columns are known.
    SCHEMA.TABLE arguments: the columns, keys, checks and comments of those tables."""
    import argparse
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="What tables and columns exist - read from the scripts in sql/.")
    parser.add_argument("tables", nargs="*", help="SCHEMA.TABLE; none lists every table")
    args = parser.parse_args(argv)

    if args.tables:
        status = 0
        for name in args.tables:
            found = table(name)
            if found is None:
                print("{0}: not in the sql/ folder".format(name.upper()))
                status = 1
            else:
                print(render_table(found))
            print()
        return status

    by_schema = {}
    for found in catalog().tables.values():
        by_schema.setdefault(found.owner, []).append(found)
    for owner in sorted(by_schema):
        found = sorted(by_schema[owner], key=lambda t: t.name)
        unknown = [t.name for t in found if not t.has_ddl]
        print("{0} ({1} tables{2})".format(owner, len(found), ", {0} without CREATE TABLE".format(len(unknown)) if unknown else ""))
        for t in found:
            note = "" if t.has_ddl else "  (no CREATE TABLE script: columns unknown)"
            if t.planned:
                note = "  (PLANNED: not in sql/ yet - {0})".format(t.planned)
            elif any(c.planned for c in t.columns.values()):
                note = "  ({0} planned column(s))".format(sum(1 for c in t.columns.values() if c.planned))
            print("  {0}{1}".format(t.name, note))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
