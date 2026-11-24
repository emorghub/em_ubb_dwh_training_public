"""Generate the staging table changes a change request needs, from its
approved delivery agreements.

    python tools/codegen/generate_staging.py CR-ECB-001
    python tools/codegen/generate_staging.py CR-ECB-001 --check

Each delivery entity NAME arrives in UBB_STAGING2.STG_<NAME>. An agreement
may deliver columns staging does not load; staging gains only what the
change request asks for: the attributes its approved agreement versions mark
added or changed (every attribute of a new entity), and the in_interface
inputs of its approved gap analysis (delivered, not in staging yet). Those
are compared with the staging table script in sql/ and, per table that needs
a change, one file is written:

  change-requests/<CR_ID>/staging/STG_<NAME>.sql
      CREATE TABLE  when sql/ has no such table (a new interface), or
      ALTER TABLE   adding the missing columns, nullable

A type that differs is never changed automatically: it is listed in the file
for a person to decide. The SQL wording is in tools/codegen/templates/
(staging_create.sql.j2, staging_change.sql.j2).

Refuses unless the gap analysis and every agreement used are approved and
valid. Never deploys and never connects to a database. --check verifies
instead: every file that is needed exists and was generated from the
agreement's current content (fingerprint), and no other file is left over.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mapping_spec"))
sys.path.insert(0, os.path.join(HERE, "..", "change_request"))

from generate import environment  # noqa: E402

import ba_documents  # noqa: E402
import planned_staging  # noqa: E402
import schema_catalog  # noqa: E402
import workflow  # noqa: E402,F401  (planned_staging needs it on the path)

FINGERPRINT_PATTERN = re.compile(r"agreement fingerprint ([0-9a-f]{16})")
CORE_SCHEMA = "UBB_CORE2"


class StagingError(Exception):
    pass


def output_dir(cr_id: str) -> str:
    return os.path.join(ba_documents.cr_folder(cr_id), "staging")


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, ba_documents.REPO_ROOT).replace(os.sep, "/")
    except ValueError:
        return path


def planned_changes(cr_id: str) -> list:
    """[(TableChange, agreement)] for every staging table that must change."""
    problems = workflow.gate("staging", cr_id)
    if problems:
        raise StagingError("staging changes for {0} cannot be generated yet:\n  - {1}".format(
            cr_id, "\n  - ".join(problems)))
    # compared with the sql/ folder as it is, without planned columns
    changes, _problems = planned_staging.plan_for_cr(cr_id, schema_catalog.load_catalog())
    return changes


def render(change, cr_id: str, today: _dt.date) -> str:
    agreement, entity = change.agreement, change.entity
    columns = change.add_columns
    names = ["LOAD_ID", "STAGED_AT"] + [c.name for c in columns]
    table_name = change.table.split(".")[1]
    context = {
        "cr_id": cr_id,
        "source_system": agreement.source_system,
        "version": agreement.version,
        "agreement_file": _rel(agreement.path),
        "entity": entity.name,
        "filename": entity.filename,
        "generated_on": today.isoformat(),
        "fingerprint": agreement.fingerprint(),
        "approved_by": agreement.approved_by or "(approved baseline)",
        "approved_on": agreement.approved_on or "-",
        "table": change.table,
        "columns": columns,
        "name_width": max(len(n) for n in names),
        "key_columns": change.key_columns,
        "pk_name": "PK_" + table_name,
        "fk_name": "FK_" + table_name + "_LOAD",
        "load_table": planned_staging.LOAD_TABLE,
        "core_schema": CORE_SCHEMA,
        "table_comment": "{0} {1} daily delivery ({2}), delivery agreement v{3}; business key {4}.".format(
            agreement.source_system, entity.name, entity.filename, agreement.version, entity.business_key),
        "manual_notes": change.manual_notes,
        "origins": [_rel(o) for o in change.origins],
    }
    template = "staging_change.sql.j2" if change.exists else "staging_create.sql.j2"
    return environment().get_template(template).render(context)


def cmd_generate(cr_id: str) -> int:
    changes = planned_changes(cr_id)
    today = _dt.date.today()
    folder = output_dir(cr_id)
    if not changes:
        print("Every staging table already matches its delivery agreement: nothing to generate.")
        return 0
    print("Staging changes for {0} (compared with the table scripts in sql/, no database):".format(cr_id))
    written = []
    for change in changes:
        path = os.path.join(folder, change.table.split(".")[1] + ".sql")
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(render(change, cr_id, today))
        written.append(path)
        kind = "ALTER, {0} new column(s)".format(len(change.add_columns)) if change.exists else "CREATE TABLE"
        print("  wrote    {0}  ({1}; from {2} v{3})".format(
            _rel(path), kind, change.agreement.source_system, change.agreement.version))
        for note in change.manual_notes:
            print("           MANUAL: " + note)
    for path in sorted(glob.glob(os.path.join(folder, "*.sql"))):
        if path not in written:
            print("  NOTE     {0} is no longer needed - delete it if it was never deployed".format(_rel(path)))
    print("\nDeploy by hand, after review, as the staging schema owner, BEFORE any load that reads them:")
    for number, path in enumerate(written, start=1):
        print("  {0}. {1}".format(number, _rel(path)))
    print("Then: the loader that reads each delivered file into its staging table must also read the new")
    print("columns (outside this repository), and sql/ is exported again so it matches the database.")
    return 0


def cmd_check(cr_id: str) -> int:
    changes = planned_changes(cr_id)
    folder = output_dir(cr_id)
    problems = []
    expected = set()
    for change in changes:
        path = os.path.join(folder, change.table.split(".")[1] + ".sql")
        expected.add(os.path.normcase(path))
        if not os.path.exists(path):
            problems.append("missing {0}".format(_rel(path)))
            continue
        with open(path, encoding="utf-8") as handle:
            match = FINGERPRINT_PATTERN.search(handle.read())
        if not match or match.group(1) != change.agreement.fingerprint():
            problems.append("{0} was generated from another version of {1} - regenerate".format(
                _rel(path), os.path.basename(change.agreement.path)))
    for path in glob.glob(os.path.join(folder, "*.sql")):
        if os.path.normcase(path) not in expected:
            problems.append("{0} is not needed by any approved agreement (stale)".format(_rel(path)))
    if problems:
        print("NOT READY:")
        for problem in problems:
            print("  - " + problem)
        return 1
    print("{0}: {1} staging change file(s), all current.".format(cr_id, len(changes)))
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("cr_id", help="the change request, e.g. CR-ECB-001")
    parser.add_argument("--check", action="store_true", help="verify the generated files instead of writing")
    args = parser.parse_args(argv)
    try:
        return cmd_check(args.cr_id) if args.check else cmd_generate(args.cr_id)
    except StagingError as exc:
        print("ERROR: {0}".format(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
