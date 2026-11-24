"""Tables and columns that another mapping of the same change request creates.

A change request's Load_Plan chains mappings: a later one reads the table (or
the new columns) an earlier one loads. None of that is in ``sql/`` until the
developer has generated, reviewed and deployed the earlier mapping and ``sql/``
is exported again. Until then the analyst can already map against it:
``schema_catalog`` adds, from the workbook of every Load_Plan mapping of a CR
whose gap analysis is approved, the target columns ``sql/`` does not have yet,
marked *planned* ``mapping <ID> (<status>)``.

- Only workbooks that are ``in_review`` or ``approved`` count; the workbook is
  read every time, so a later change of the earlier mapping shows up the next
  time the later one is verified or validated.
- A mapping that reads a column planned by a mapping that is not approved yet
  cannot be approved (``mapping_validation``).
- ``verify_mapping.py`` warns, and ``generate.py`` says, that the earlier
  mapping must be deployed first.

The target side of a mapping never sees these: ``schema_catalog.deployed_table``
is what is really in ``sql/``. Nothing here reads a database.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mapping_spec"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "codegen"))

import ba_documents  # noqa: E402
import planned_staging  # noqa: E402
import schema_catalog  # noqa: E402
import workflow  # noqa: E402
from sqlmodel import primary_key, table_columns  # noqa: E402
from workbook_format import mapping_path, read_mapping  # noqa: E402

PREFIX = "mapping "
COUNTED_STATUSES = ("in_review", "approved")
LABEL = re.compile(r"^mapping (\S+) \((\w+)\)$")


def label(mapping_id: str, status: str) -> str:
    return "{0}{1} ({2})".format(PREFIX, mapping_id, status)


def parse_label(planned: str):
    """(Mapping_ID, status) of a planned label written by this module, else None."""
    found = LABEL.match(planned or "")
    return (found.group(1), found.group(2)) if found else None


def plan_mappings(cr_id: str) -> list:
    """The Mapping objects of the Load_Plan of `cr_id` that already have a
    counted workbook; [] unless the CR's gap analysis is approved and valid."""
    state = workflow.load(cr_id)
    if not state.approved_and_valid(state.gap_analysis):
        return []
    found = []
    for row in state.gap_analysis.sheet("load_plan"):
        mapping_id = row.get("Mapping_ID", "").strip()
        if not mapping_id:
            continue
        try:
            path = mapping_path(mapping_id)
        except ValueError:
            continue
        if not os.path.exists(path):
            continue
        try:
            mapping = read_mapping(path)
        except Exception:  # an unreadable workbook is reported by validate_spec, not here
            continue
        if mapping.status in COUNTED_STATUSES and mapping.target:
            found.append(mapping)
    return found


def overlay(catalog) -> None:
    """Add to `catalog` every table and column the Load_Plan mappings of the
    approved change requests would create that it does not have, marked planned."""
    for cr_id in ba_documents.list_cr_ids():
        if not ba_documents.CR_ID_PATTERN.match(cr_id):
            continue
        for mapping in plan_mappings(cr_id):
            _add(catalog, mapping)


def _add(catalog, mapping) -> None:
    source = label(mapping.mapping_id, mapping.status)
    table = catalog.table(mapping.target)
    is_new = table is None or not table.has_ddl
    if is_new:
        owner, name = mapping.target.split(".")
        table = schema_catalog.Table(
            owner=owner, name=name, has_ddl=True, planned=source,
            comment="Planned: loaded by {0}.".format(mapping.mapping_id))
        table.primary_key = primary_key(mapping)
        catalog.tables[mapping.target] = table
    for column in table_columns(mapping):
        if column.name in table.columns:
            continue
        table.columns[column.name] = schema_catalog.Column(
            column.name, planned_staging._normal(column.type),
            nullable=column.nullable if is_new else True,  # existing rows have no value
            comment=column.comment, planned=source)
