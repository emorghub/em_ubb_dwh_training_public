"""Turn a mapping into the SQL pieces every generated artifact shares.

The load package, the utPLSQL tests and the checks in verify_mapping.py all
use the *same* source query and the same type rules, built here once, so what
the analyst verified is exactly what the package executes.

Conventions baked in here (and documented in templates/README.md):
- A source table is aliased by its bare name (UBB_STAGING2.STG_LOAN ->
  STG_LOAN), so Transformation_Rule text written as STG_LOAN.COLUMN works
  unchanged.
- Procedure parameters appear in rules, filters and checks by their bare
  name (P_BUSINESS_DATE). Inside the generated PL/SQL that is the variable.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mapping_spec"))

from mapping_validation import column_refs  # noqa: E402
from workbook_format import ITEM_ALIAS, OPEN_VALID_TO, Mapping, bare_table  # noqa: E402

TYPE_PATTERN = re.compile(r"^\s*([A-Z0-9]+)\s*(?:\(\s*(\d+)\s*(?:,\s*(-?\d+))?\s*(CHAR|BYTE)?\s*\))?", re.I)


@dataclass
class TargetColumn:
    name: str
    type: str
    nullable: bool
    expr: str
    scd_type: str
    is_key: bool
    is_expr: bool  # computed with no source column (EXPR), e.g. SYSTIMESTAMP
    business_name: str
    description: str
    is_history: bool = False  # added by an scd2 load (VALID_FROM, VALID_TO, IS_DELETED)

    @property
    def comment(self) -> str:
        """Text for COMMENT ON COLUMN: business name and meaning."""
        return ": ".join(part for part in (self.business_name, self.description) if part)


def column_expression(col) -> str:
    """The SELECT-list expression for one Columns row."""
    rule = col.transformation_rule.strip()
    if rule.lower() == "direct":
        return "{0}.{1}".format(bare_table(col.source_table), col.source_columns[0])
    if rule.upper() == "NULL":
        return "NULL"
    return rule


def target_columns(mapping: Mapping) -> list:
    keys = set(mapping.business_key)
    result = []
    for col in mapping.columns:
        name = col.target_column.strip().upper()
        result.append(
            TargetColumn(
                name=name,
                type=col.target_type.strip().upper(),
                nullable=col.nullable.strip().upper() != "N",
                expr=column_expression(col),
                scd_type=col.scd_type.strip() or "1",
                is_key=name in keys,
                is_expr=col.source_table.strip().upper() == "EXPR",
                business_name=col.business_name.strip(),
                description=col.description.strip(),
            )
        )
    return result


def history_columns(mapping: Mapping) -> list:
    """The columns an scd2 load adds after the mapped ones; [] for any other
    strategy. Their names are fixed (workbook_format.SCD2_HISTORY_COLUMNS)."""
    if not mapping.is_scd2:
        return []

    def history(name, ctype, business_name, description):
        return TargetColumn(name, ctype, False, "", "", False, False, business_name, description, is_history=True)

    result = [
        history("VALID_FROM", "DATE", "Valid From",
                "First date this version is valid for (inclusive): the load date that created it."),
        history("VALID_TO", "DATE", "Valid To",
                "First date this version is no longer valid for (exclusive); {0} = the current version. "
                "As of date D: VALID_FROM <= D AND D < VALID_TO.".format(OPEN_VALID_TO)),
    ]
    if mapping.source_snapshot == "full":
        result.append(history("IS_DELETED", "CHAR(1 CHAR)", "Is Deleted",
                              "Y = the key was missing from the source snapshot from VALID_FROM on; the other "
                              "values are the last ones seen. N = the key was in the source."))
    return result


def table_columns(mapping: Mapping) -> list:
    """Every column of the target table: the mapped ones, then the history columns."""
    return target_columns(mapping) + history_columns(mapping)


def primary_key(mapping: Mapping) -> list:
    """The target's primary key: Business_Key, plus VALID_FROM for scd2."""
    return mapping.business_key + (["VALID_FROM"] if mapping.is_scd2 else [])


def from_clause(mapping: Mapping, indent: str = "") -> str:
    """FROM ... JOIN ... ON ... lines, driving table first."""
    lines = ["{0}FROM {1} {2}".format(indent, mapping.driving_table, bare_table(mapping.driving_table))]
    for join in mapping.joins:
        keyword = "LEFT JOIN" if join.join_type.strip().lower() == "left" else "JOIN"
        table = join.table.strip().upper()
        lines.append("{0}{1} {2} {3}".format(indent, keyword, table, bare_table(table)))
        lines.append("{0}  ON {1}".format(indent, join.condition.strip()))
    return "\n".join(lines)


def group_by_expressions(mapping: Mapping) -> list:
    """The GROUP BY list of an aggregating mapping: the expressions of the
    Group_By columns that read a source column. A Group_By column holding a
    parameter or a constant is the same on every row, so it needs no grouping
    (and a PL/SQL variable in GROUP BY is best avoided)."""
    wanted = set(mapping.group_by)
    return [c.expr for c in target_columns(mapping) if c.name in wanted and column_refs(c.expr)]


def _select_list(pairs: list, indent: str) -> str:
    """SELECT <expr> AS <alias>, ... one per line, the aliases aligned. The
    continuation lines of a multi-line expression get the same indent."""
    width = min(max((len(e) for e, _a in pairs if "\n" not in e), default=0), 60)
    lines = []
    for index, (expr, alias) in enumerate(pairs):
        sep = "," if index < len(pairs) - 1 else ""
        expr = expr.replace("\n", "\n" + indent)
        lines.append("{0}       {1} AS {2}{3}".format(indent, expr.ljust(width), alias, sep))
    lines[0] = "{0}SELECT {1}".format(indent, lines[0][len(indent) + 7:])
    return "\n".join(lines)


def _where(mapping: Mapping, indent: str) -> list:
    return ["{0}WHERE {1}".format(indent, mapping.filter.strip())] if mapping.has_filter else []


def _group_by(expressions: list, indent: str) -> list:
    if not expressions:
        return []
    return ["{0}GROUP BY {1}".format(indent, (",\n{0}         ".format(indent)).join(expressions))]


def source_query(mapping: Mapping, indent: str = "") -> str:
    """SELECT <expr> AS <target column>, ... FROM ... WHERE <filter>
    [GROUP BY <expr of each Group_By column>].

    With Item_Columns, two levels: the inner query computes the Group_By
    values and the item columns once per source row (where a window function
    may run), and the outer query groups those rows by the Group_By values:

        SELECT ITEM.<group col>, <aggregate of ITEM.x> ...
        FROM (SELECT <group expr> AS <group col>, <item rule> AS <item>
              FROM ... WHERE <filter>) ITEM
        GROUP BY ITEM.<group col>, ...

    The column aliases are the target column names, so anything wrapping
    this query (MERGE USING, a dry-run check, a test) can refer to target
    names directly.
    """
    cols = target_columns(mapping)
    if not mapping.item_columns:
        parts = [_select_list([(c.expr, c.name) for c in cols], indent), from_clause(mapping, indent)]
        parts += _where(mapping, indent)
        parts += _group_by(group_by_expressions(mapping), indent)
        return "\n".join(parts)

    inner_indent = indent + "    "
    wanted = set(mapping.group_by)
    grouped = [c for c in cols if c.name in wanted and column_refs(c.expr)]
    inner_pairs = [(c.expr, c.name) for c in grouped]
    inner_pairs += [(item.transformation_rule.strip(), item.name) for item in mapping.item_columns]
    inner = [_select_list(inner_pairs, inner_indent), from_clause(mapping, inner_indent)]
    inner += _where(mapping, inner_indent)

    outer_names = {c.name for c in grouped}
    outer_pairs = [
        ("{0}.{1}".format(ITEM_ALIAS, c.name) if c.name in outer_names else c.expr, c.name) for c in cols
    ]
    parts = [_select_list(outer_pairs, indent), "{0}FROM (".format(indent)]
    parts += inner
    parts.append("{0}) {1}".format(indent, ITEM_ALIAS))
    parts += _group_by(["{0}.{1}".format(ITEM_ALIAS, c.name) for c in grouped], indent)
    return "\n".join(parts)


def sql_string(text: str) -> str:
    """Oracle string literal body (quotes doubled), single line."""
    return " ".join(str(text).split()).replace("'", "''")


# ---------------------------------------------------------------------------
# Oracle types, as written in the table scripts and in the workbook
# ---------------------------------------------------------------------------


def parse_type(text: str):
    """('VARCHAR2', 20, None) / ('NUMBER', 18, 2) / ('DATE', None, None)."""
    match = TYPE_PATTERN.match(str(text or "").upper())
    if not match:
        return (str(text).upper(), None, None)
    base = match.group(1)
    length = int(match.group(2)) if match.group(2) else None
    scale = int(match.group(3)) if match.group(3) else None
    if base in ("DECIMAL", "NUMERIC"):
        base = "NUMBER"
    if base == "INTEGER":
        base, length, scale = "NUMBER", 38, 0
    if base == "NUMBER" and length is not None and scale is None:
        scale = 0  # NUMBER(10) and NUMBER(10,0) are the same type
    if base == "TIMESTAMP":
        length = None
    return (base, length, scale)


def fits(source_type: str, target_type: str) -> bool:
    """True when every value of source_type fits into target_type."""
    s_base, s_len, s_scale = parse_type(source_type)
    t_base, t_len, t_scale = parse_type(target_type)
    if s_base != t_base:
        return False
    if t_base in ("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "RAW"):
        return s_len is None or (t_len is not None and t_len >= s_len)
    if t_base == "NUMBER":
        if t_len is None:
            return True
        if s_len is None:
            return False
        s_scale = s_scale or 0
        t_scale = t_scale or 0
        return t_scale >= s_scale and (t_len - t_scale) >= (s_len - s_scale)
    return True
