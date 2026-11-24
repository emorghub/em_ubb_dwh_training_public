"""Which stored procedures read or write a given table - from the package scripts in ``sql/``.

``schema_catalog.py`` knows the tables and columns; this module answers the
next question: for the tables a mapping touches, which existing PL/SQL
already writes them (another load on the same target table) or reads them
(a load that depends on them, or one that must run first). Ask it about the
few tables that matter, then open only the procedures it names.

    python tools/mapping_spec/package_usage.py UBB_CORE2.LOAN_HIST UBB_STAGING2.STG_LOAN

It never connects to a database. It reads every ``CREATE ... PACKAGE BODY``
script directly inside a ``*.schema`` folder of ``sql/`` (or ``UBB_SQL_DIR``).

How a reference is found, per package body:

- Comments and string literals are blanked out first, so a log message or a
  comment that names a table is not a reference.
- ``OWNER.TABLE`` matches anywhere; a bare ``TABLE`` matches only in a
  package of the same owner (that is how Oracle resolves it).
- A reference is a **write** when it directly follows ``INSERT INTO``,
  ``MERGE INTO``, ``UPDATE``, ``DELETE [FROM]``, ``TRUNCATE TABLE`` or the
  ``INTO`` of an ``INSERT ALL/FIRST``. Every other reference is a **read**.
- It belongs to the nearest ``PROCEDURE``/``FUNCTION`` declared above it.

What it cannot see: SQL built at run time (``EXECUTE IMMEDIATE``,
``DBMS_SQL``) - those places are listed so a person or the assistant can read
them - and access through synonyms or views. It finds tables, not columns:
how a column is derived is read from the procedure itself.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import schema_catalog  # noqa: E402

PACKAGE_BODY = re.compile(
    r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:NON)?EDITIONABLE\s+)?PACKAGE\s+BODY\s+"?(?P<owner>\w+)"?\s*\.\s*"?(?P<name>\w+)"?',
    re.IGNORECASE,
)
SUBPROGRAM = re.compile(r'\b(?:PROCEDURE|FUNCTION)\s+"?(?P<name>[A-Za-z]\w*)"?', re.IGNORECASE)
DYNAMIC_SQL = re.compile(r"\bEXECUTE\s+IMMEDIATE\b|\bDBMS_SQL\s*\.", re.IGNORECASE)
WRITE_BEFORE = re.compile(
    r"\b(?P<verb>INSERT\s+INTO|MERGE\s+INTO|UPDATE|DELETE\s+FROM|DELETE|TRUNCATE\s+TABLE)\s*$", re.IGNORECASE
)
MULTI_INSERT = re.compile(r"\bINSERT\s+(?:ALL|FIRST)\b", re.IGNORECASE)
INTO_BEFORE = re.compile(r"\bINTO\s*$", re.IGNORECASE)


@dataclass
class PackageBody:
    owner: str
    name: str
    path: str
    text: str  # comments and string literals blanked, quotes removed; same length and line breaks
    procedures: list = field(default_factory=list)  # [(offset, NAME)] in text order

    @property
    def qualified(self) -> str:
        return "{0}.{1}".format(self.owner, self.name)

    def line_of(self, offset: int) -> int:
        return self.text.count("\n", 0, offset) + 1

    def procedure_at(self, offset: int) -> str:
        current = ""
        for start, name in self.procedures:
            if start > offset:
                break
            current = name
        return current


@dataclass(frozen=True)
class Usage:
    table: str  # OWNER.TABLE that was asked about
    package: str  # OWNER.PACKAGE
    procedure: str  # PROCEDURE name, "" for code outside any procedure
    access: str  # "write" or "read"
    verb: str  # INSERT, MERGE, UPDATE, DELETE, TRUNCATE, or "" for a read
    path: str
    line: int

    @property
    def where(self) -> str:
        return "{0}.{1}".format(self.package, self.procedure) if self.procedure else self.package


def blank_comments_and_strings(text: str) -> str:
    """Replace comments and string literals with spaces, keep line breaks, and drop
    the double quotes around identifiers. Offsets and line numbers stay the same."""
    out = []
    index = 0
    length = len(text)
    while index < length:
        ch = text[index]
        two = text[index:index + 2]
        if two == "--":
            end = text.find("\n", index)
            end = length if end < 0 else end
            out.append(" " * (end - index))
            index = end
        elif two == "/*":
            end = text.find("*/", index + 2)
            end = length if end < 0 else end + 2
            out.append(re.sub(r"[^\n]", " ", text[index:end]))
            index = end
        elif ch == "'":
            end = index + 1
            while end < length:
                if text[end] == "'":
                    if text[end + 1:end + 2] == "'":
                        end += 2
                        continue
                    break
                end += 1
            end = min(end + 1, length)
            out.append(re.sub(r"[^\n]", " ", text[index:end]))
            index = end
        elif ch == '"':
            out.append(" ")
            index += 1
        else:
            out.append(ch)
            index += 1
    return "".join(out)


def load_package_bodies(sql_dir: str = None) -> list:
    """Every package body script directly inside a ``*.schema`` folder of sql_dir."""
    sql_dir = os.path.abspath(sql_dir or schema_catalog.default_sql_dir())
    bodies = []
    for folder in schema_catalog.schema_folders(sql_dir):
        for path in sorted(glob.glob(os.path.join(folder, "*.sql"))):
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                raw = handle.read()
            match = PACKAGE_BODY.search(raw)
            if not match:
                continue
            text = blank_comments_and_strings(raw)
            body = PackageBody(owner=match.group("owner").upper(), name=match.group("name").upper(), path=path, text=text)
            body.procedures = [(m.start(), m.group("name").upper()) for m in SUBPROGRAM.finditer(text)]
            bodies.append(body)
    return bodies


def _write_verb(body: PackageBody, offset: int) -> str:
    """The write statement a table reference at offset is the target of, or ''."""
    before = body.text[max(0, offset - 200):offset]
    match = WRITE_BEFORE.search(before)
    if match:
        return match.group("verb").split()[0].upper()
    if INTO_BEFORE.search(before):
        statement_start = body.text.rfind(";", 0, offset) + 1
        if MULTI_INSERT.search(body.text[statement_start:offset]):
            return "INSERT"
    return ""


def _table_pattern(owner: str, name: str, same_owner: bool):
    qualified = r"(?<![\w$#.]){0}\s*\.\s*{1}(?![\w$#])".format(re.escape(owner), re.escape(name))
    if not same_owner:
        return re.compile(qualified, re.IGNORECASE)
    bare = r"(?<![\w$#.]){0}(?![\w$#])".format(re.escape(name))
    return re.compile("{0}|{1}".format(qualified, bare), re.IGNORECASE)


def _split(qualified: str):
    parts = [p.strip().strip('"').upper() for p in str(qualified).split(".")]
    if len(parts) != 2 or not all(parts):
        raise ValueError("expected SCHEMA.TABLE, got {0!r}".format(qualified))
    return parts[0], parts[1]


def find_usages(tables, bodies: list = None) -> dict:
    """{OWNER.TABLE: [Usage]} for each table asked about, writes first, in file order."""
    bodies = load_package_bodies() if bodies is None else bodies
    found = {}
    for qualified in tables:
        owner, name = _split(qualified)
        key = "{0}.{1}".format(owner, name)
        usages = []
        for body in bodies:
            pattern = _table_pattern(owner, name, body.owner == owner)
            for match in pattern.finditer(body.text):
                verb = _write_verb(body, match.start())
                usages.append(Usage(
                    table=key,
                    package=body.qualified,
                    procedure=body.procedure_at(match.start()),
                    access="write" if verb else "read",
                    verb=verb,
                    path=body.path,
                    line=body.line_of(match.start()),
                ))
        usages.sort(key=lambda u: (u.access != "write", u.package, u.procedure, u.line))
        found[key] = usages
    return found


def writers(qualified: str, bodies: list = None) -> list:
    """The procedures that write the table: [(OWNER.PACKAGE.PROCEDURE, path, first line)]."""
    seen = {}
    for usage in find_usages([qualified], bodies)[_join(*_split(qualified))]:
        if usage.access == "write" and usage.where not in seen:
            seen[usage.where] = (usage.where, usage.path, usage.line)
    return list(seen.values())


def dynamic_sql(bodies: list = None) -> list:
    """[(OWNER.PACKAGE.PROCEDURE, path, line)] of every place that builds SQL at run time."""
    bodies = load_package_bodies() if bodies is None else bodies
    places = []
    for body in bodies:
        for match in DYNAMIC_SQL.finditer(body.text):
            proc = body.procedure_at(match.start())
            where = "{0}.{1}".format(body.qualified, proc) if proc else body.qualified
            places.append((where, body.path, body.line_of(match.start())))
    return places


def _join(owner: str, name: str) -> str:
    return "{0}.{1}".format(owner, name)


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, schema_catalog.REPO_ROOT).replace(os.sep, "/")
    except ValueError:
        return path


def render(found: dict, dynamic: list) -> str:
    lines = []
    for table, usages in found.items():
        state = schema_catalog.table_state(table)
        note = {"ok": "", "no_ddl": "  (no CREATE TABLE script: columns unknown)", "unknown": "  (not in the sql/ folder)"}[state]
        lines.append(table + note)
        if not usages:
            lines.append("  no package in sql/ reads or writes it")
        grouped = {}
        for usage in usages:
            grouped.setdefault((usage.access, usage.where, usage.path), []).append(usage)
        for (access, where, path), group in grouped.items():
            verbs = sorted({u.verb for u in group if u.verb})
            label = "written by" if access == "write" else "read by"
            lines.append("  {0:10}  {1}{2}  {3}:{4}".format(
                label,
                where,
                "  ({0})".format(", ".join(verbs)) if verbs else "",
                _rel(path),
                ",".join(str(u.line) for u in group),
            ))
        lines.append("")
    if dynamic:
        lines.append("Not analysed - SQL built at run time; read these by hand:")
        for where, path, line in dynamic:
            lines.append("  {0}  {1}:{2}".format(where, _rel(path), line))
        lines.append("")
    lines.append("Tables only: open the procedures above to see how each column is derived.")
    return "\n".join(lines)


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("tables", nargs="+", help="SCHEMA.TABLE, one or more")
    args = parser.parse_args(argv)
    try:
        for table in args.tables:
            _split(table)
    except ValueError as exc:
        print("ERROR: {0}".format(exc))
        return 1
    bodies = load_package_bodies()
    print(render(find_usages(args.tables, bodies), dynamic_sql(bodies)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
