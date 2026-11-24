"""Staging columns a change request asks for that sql/ does not have yet.

A delivery agreement entity NAME arrives in the staging table
``UBB_STAGING2.STG_<NAME>``. An agreement may deliver columns that staging
does not load - that is allowed, and nothing here touches them. Staging
gains only what a change request asks for (``workflow.staging_requests``):

- the attributes an approved agreement version of the CR marks ``added`` or
  ``changed``, and every attribute of an entity it marks ``new``;
- the ``in_interface`` inputs of the CR's approved gap analysis (delivered
  already, not loaded into staging yet).

For those:

- the developer generates the CREATE or ALTER script with
  ``tools/codegen/generate_staging.py`` (skill dev-1-implement-staging-change),
  deploys it, and has ``sql/`` exported again; and
- until then, the analyst can already map the column: ``schema_catalog``
  adds it to the tables it reads from ``sql/``, marked *planned* with the
  document that asks for it, and ``verify_mapping.py`` warns about every
  planned table or column a mapping uses.

Nothing here reads a database.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mapping_spec"))

import ba_documents  # noqa: E402
import schema_catalog  # noqa: E402
import workflow  # noqa: E402

STAGING_SCHEMA = "UBB_STAGING2"
LOAD_TABLE = "UBB_CORE2.CTRL_LOAD"
# Planned new staging tables get the columns every staging table has.
LOAD_ID = ("LOAD_ID", "NUMBER(18,0)")
STAGED_AT = ("STAGED_AT", "TIMESTAMP(6)")


def staging_table(entity_name: str) -> str:
    return "{0}.{1}".format(STAGING_SCHEMA, workflow.staging_table_of(entity_name))


@dataclass
class PlannedColumn:
    name: str
    type: str
    description: str
    nullable: bool = True


@dataclass
class TableChange:
    """What one staging table needs so that it receives what a change request asks for."""

    table: str  # SCHEMA.TABLE
    agreement: object  # delivery_agreement.Agreement
    entity: object  # delivery_agreement.Entity
    exists: bool = False
    origins: list = field(default_factory=list)  # the documents that ask for it
    add_columns: list = field(default_factory=list)  # PlannedColumn
    manual_notes: list = field(default_factory=list)

    @property
    def needed(self) -> bool:
        return not self.exists or bool(self.add_columns) or bool(self.manual_notes)

    @property
    def key_columns(self) -> list:
        return [LOAD_ID[0]] + self.entity.key_columns


def _split(type_text: str):
    text = type_text.strip()
    if "(" in text:
        base, rest = text.split("(", 1)
        return base.strip(), "(" + rest
    return text, ""


def _normal(type_text: str) -> str:
    return schema_catalog.normalise_type(*_split(type_text))


def plan_entity(agreement, entity, catalog, only=None) -> TableChange:
    """Compare one delivery entity with its staging table in `catalog` (the
    sql/ folder, without planned columns). `only`: the attribute names asked
    for; None means every attribute (a new entity)."""
    qualified = staging_table(entity.name)
    found = catalog.table(qualified)
    change = TableChange(table=qualified, agreement=agreement, entity=entity,
                         exists=found is not None and found.has_ddl)
    keys = set(entity.key_columns)
    wanted = None if only is None else {n.upper() for n in only}
    if not change.exists:
        wanted = None  # a table is created whole: every attribute of the entity
    for attr in entity.attributes:
        name = attr.name.upper()
        if wanted is not None and name not in wanted:
            continue
        column = PlannedColumn(name, _normal(attr.type), attr.description, nullable=name not in keys)
        if not change.exists:
            change.add_columns.append(column)
            continue
        current = found.columns.get(name)
        if current is None:
            column.nullable = True  # existing rows have no value
            change.add_columns.append(column)
        elif _normal(current.type) != column.type:
            change.manual_notes.append(
                "{0}.{1}: the table script has {2}, the agreement says {3}. Decide and change it by hand "
                "if needed.".format(qualified, name, current.type, column.type))
    return change


def plan_requests(requests: list, catalog=None) -> list:
    """One TableChange per staging table, merging every request for it."""
    catalog = catalog or schema_catalog.load_catalog()
    merged = {}
    for request in requests:
        table = staging_table(request.entity.name)
        known = merged.get(table)
        if known is None:
            merged[table] = known = {"request": request, "names": set(), "all": False, "origins": []}
        if request.attributes is None:
            known["all"] = True
        else:
            known["names"] |= request.attributes
        if request.origin not in known["origins"]:
            known["origins"].append(request.origin)
    changes = []
    for table in sorted(merged):
        item = merged[table]
        request = item["request"]
        change = plan_entity(request.agreement, request.entity, catalog, None if item["all"] else item["names"])
        change.origins = item["origins"]
        changes.append(change)
    return changes


def plan_for_cr(cr_id: str, catalog=None) -> tuple:
    """(TableChanges that are needed, problems) for one change request."""
    requests, problems = workflow.staging_requests(workflow.load(cr_id))
    return [c for c in plan_requests(requests, catalog) if c.needed], problems


def overlay(catalog) -> None:
    """Add to `catalog` every staging table and column an approved change
    request asks for that it does not have, marked planned."""
    for cr_id in ba_documents.list_cr_ids():
        if not ba_documents.CR_ID_PATTERN.match(cr_id):
            continue
        requests, _problems = workflow.staging_requests(workflow.load(cr_id))
        for change in plan_requests(requests, catalog):
            if not change.add_columns:
                continue
            source = ", ".join(_rel(o) for o in change.origins)
            owner, name = change.table.split(".")
            table = catalog.table(change.table)
            if table is None or not table.has_ddl:
                table = schema_catalog.Table(owner=owner, name=name, has_ddl=True,
                                             comment="Planned: delivery entity {0} of {1} v{2}.".format(
                                                 change.entity.name, change.agreement.source_system,
                                                 change.agreement.version))
                table.planned = source
                table.columns[LOAD_ID[0]] = schema_catalog.Column(LOAD_ID[0], LOAD_ID[1], nullable=False,
                                                                  planned=source)
                table.primary_key = change.key_columns
                catalog.tables[change.table] = table
            for column in change.add_columns:
                table.columns[column.name] = schema_catalog.Column(
                    column.name, column.type, nullable=column.nullable, comment=column.description,
                    planned=source)
            if table.planned:
                table.columns[STAGED_AT[0]] = schema_catalog.Column(STAGED_AT[0], STAGED_AT[1], nullable=False,
                                                                    default="SYSTIMESTAMP", planned=source)


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, ba_documents.REPO_ROOT).replace(os.sep, "/")
    except ValueError:
        return path
