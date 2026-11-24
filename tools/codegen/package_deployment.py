"""Build the deployment package of one approved mapping: a zip with everything
a developer needs to deploy it from another machine, Windows or Linux.

    python tools/codegen/package_deployment.py M_LOAN_HIST
    python tools/codegen/package_deployment.py M_LOAN_HIST --include change-requests/CR-X/other_script.sql
    python tools/codegen/package_deployment.py M_LOAN_HIST --check

The zip holds ONE top folder, named after the mapping, so the packages of
several mappings can be unpacked into the same directory without clashing.
Inside it, next to each other at the top: README.txt, RUNBOOK.md (the runbook
the dev-3 skill wrote), MANIFEST.json, SHA256SUMS, verify.sh and verify.ps1;
below it, one level of folders and no deeper, so a path never has more than
two parts under the mapping's folder:

  M_X/staging/    the change request's staging script(s) the mapping's planned columns need
  M_X/grants/     grants_select.sql, grants_test_only_insert.sql (source tables of another schema)
  M_X/preflight/  DEPLOY_M_X_PREFLIGHT_1_BEFORE_DDL.sql, DEPLOY_M_X_PREFLIGHT_2_BEFORE_RUN.sql
  M_X/ddl/        the table script, or the change script M_X.sql when the table exists; the load log (scd2)
  M_X/code/       the load package
  M_X/test/       the test data and the utPLSQL tests (test environment only)
  M_X/external/   any file named with --include (an approved script from outside the
                  generators, for example an updated wrapper package), by its file name

Files keep their repository names; the runbook is the one repository file renamed
(DEPLOY_<MAPPING_ID>_RUNBOOK.md -> RUNBOOK.md). The runbook names files by their path
inside the package folder. Two files that would share a path are refused.

Text files are packed with LF line endings and no byte-order mark, so SQL*Plus
and SQLcl read them the same on Windows and on Linux. Entry names use "/" and
carry a fixed timestamp, so the same inputs give the same zip. Nothing is
deployed and no database is opened: the package is only files.

Refuses when the mapping is not approved or valid, when the generated code is
not current (generate.py --check), or when a DEPLOY_ file is missing or was
written for another fingerprint.

--check compares an existing package with the files as they are now (exit 1
when anything changed since it was built).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import generate  # noqa: E402
import schema_catalog  # noqa: E402
from mapping_validation import referenced_source_columns  # noqa: E402
from workbook_format import REPO_ROOT, bare_table  # noqa: E402

PACKAGE_FORMAT = 1
DEFAULT_OUT_DIR = os.path.join(REPO_ROOT, "deployment-packages")
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
TEXT_SUFFIXES = (".sql", ".md", ".txt", ".sh", ".ps1", ".json")
CR_PATTERN = re.compile(r"\bCR-[A-Za-z0-9]+-\d+\b")
MAPPING_FINGERPRINT = generate.FINGERPRINT_PATTERN
PREFLIGHT_HELPERS = os.path.join(REPO_ROOT, "tools", "codegen", "templates", "preflight_helpers.sql")
HELPERS_BEGIN = "-- BEGIN HELPERS"
HELPERS_END = "-- END HELPERS"

# Files the package adds around the items; --check ignores them.
META_FILES = ("README.txt", "MANIFEST.json", "SHA256SUMS", "verify.sh", "verify.ps1")

# The order the files are listed in: the runbook first, then roughly the order
# the runbook deploys them (it is the authority; external files go where it says).
ROLE_RANK = {
    "runbook": 0, "staging": 1, "grants": 2, "preflight_1": 3, "table_change": 4, "table_create": 4,
    "load_log": 5, "package": 6, "test_data": 7, "tests": 8, "external": 9, "preflight_2": 10,
}

# One level of folders below the mapping's own folder, never deeper.
ROLE_FOLDER = {
    "staging": "staging", "grants": "grants", "preflight_1": "preflight", "preflight_2": "preflight",
    "table_change": "ddl", "table_create": "ddl", "load_log": "ddl", "package": "code",
    "test_data": "test", "tests": "test", "external": "external",
}
RUNBOOK_NAME = "RUNBOOK.md"


class PackageError(Exception):
    pass


@dataclass
class Item:
    arc: str  # path inside the package folder, "/"-separated, at most folder/file
    data: bytes
    role: str
    environments: tuple = ("TEST", "PROD")
    note: str = ""
    source: str = ""  # repository path it came from; empty when the tool writes it


# ---------------------------------------------------------------------------
# Bytes
# ---------------------------------------------------------------------------


def clean_text(data: bytes) -> bytes:
    """No byte-order mark and LF line endings: SQL*Plus on Linux chokes on a
    CR inside a PL/SQL block, and on a BOM at the start of a script."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lines(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))


def helper_block(template: str = PREFLIGHT_HELPERS) -> str:
    """The fixed PL/SQL helpers of the preflight scripts, between the two marker lines."""
    with open(template, encoding="utf-8") as handle:
        text = handle.read()
    start = text.index(HELPERS_BEGIN) + len(HELPERS_BEGIN)
    return _lines(text[start:text.index(HELPERS_END)]).strip("\n")


def has_helper_block(script: str, template: str = PREFLIGHT_HELPERS) -> bool:
    """A preflight script carries the helper block unchanged (trailing blanks and line endings aside)."""
    return helper_block(template) in _lines(script)


def _arc(path: str) -> str:
    try:
        rel = os.path.relpath(os.path.abspath(path), REPO_ROOT)
    except ValueError:  # another drive on Windows
        rel = ".."
    if rel.startswith("..") or os.path.isabs(rel):
        raise PackageError("{0} is outside the repository, so it cannot be packaged".format(path))
    return rel.replace(os.sep, "/")


def _read(path: str) -> bytes:
    with open(path, "rb") as handle:
        data = handle.read()
    return clean_text(data) if path.lower().endswith(TEXT_SUFFIXES) else data


def _file_item(path: str, role: str, environments=("TEST", "PROD"), note: str = "") -> Item:
    """A repository file, placed by its role: the runbook at the top, the rest one folder down."""
    source = _arc(path)
    arc = RUNBOOK_NAME if role == "runbook" else "{0}/{1}".format(ROLE_FOLDER[role], os.path.basename(path))
    return Item(arc, _read(path), role, tuple(environments), note, source)


# ---------------------------------------------------------------------------
# What goes in
# ---------------------------------------------------------------------------


def deploy_file_names(mapping_id: str) -> dict:
    return {
        "runbook": "DEPLOY_{0}_RUNBOOK.md".format(mapping_id),
        "preflight_1": "DEPLOY_{0}_PREFLIGHT_1_BEFORE_DDL.sql".format(mapping_id),
        "preflight_2": "DEPLOY_{0}_PREFLIGHT_2_BEFORE_RUN.sql".format(mapping_id),
    }


def planned_staging_scripts(mapping) -> tuple:
    """([paths of the staging scripts], [mappings that must be deployed first]).

    Only the source columns the mapping reads count, as in verify_mapping.py.
    A planned column that an approved delivery agreement promises needs the
    change request's staging script for its table. A table or column planned
    by another mapping is a predecessor: that mapping's own package."""
    referenced = referenced_source_columns(mapping)
    scripts, upstream = [], []
    for qualified in mapping.source_tables:
        found = schema_catalog.table(qualified)
        if found is None:
            continue
        labels = set()
        if found.planned and any(table == bare_table(qualified) for table, _column in referenced):
            labels.add(found.planned)
        for table, column in referenced:
            if table == bare_table(qualified) and column in found.columns and found.columns[column].planned:
                labels.add(found.columns[column].planned)
        for label in sorted(labels):
            if label.startswith("mapping "):
                upstream.append(label[len("mapping "):])
                continue
            cr = CR_PATTERN.search(label)
            if not cr:
                raise PackageError("{0}: cannot tell which change request promises it ({1})".format(qualified, label))
            path = os.path.join(REPO_ROOT, "change-requests", cr.group(0), "staging", bare_table(qualified) + ".sql")
            if not os.path.isfile(path):
                raise PackageError(
                    "{0} has planned columns ({1}) but {2} does not exist - run "
                    "python tools/codegen/generate_staging.py {3}".format(qualified, label, _arc(path), cr.group(0)))
            if path not in scripts:
                scripts.append(path)
    return scripts, sorted(set(upstream))


def grants_items(mapping) -> list:
    """GRANT files for the source tables that live in another schema than the load package."""
    schema = mapping.proc_parts[0]
    others = []
    for qualified in mapping.source_tables:
        if qualified.split(".")[0] != schema and qualified not in others:
            others.append(qualified)
    if not others:
        return []
    header = (
        "-- Grants for mapping {0} (mapping fingerprint {1}).\n"
        "-- Written by tools/codegen/package_deployment.py. Run by the owner of the source schema or a DBA;\n"
        "-- the load package is definer-rights, so each grant must be direct, not through a role.\n"
    ).format(mapping.mapping_id, mapping.fingerprint())
    select = header + "\n" + "".join("GRANT SELECT ON {0} TO {1};\n".format(t, schema) for t in others)
    insert = (
        header + "-- TEST ENVIRONMENT ONLY: the test data package inserts into these tables. Never run in production.\n\n"
        + "".join("GRANT INSERT ON {0} TO {1};\n".format(t, schema) for t in others)
    )
    return [
        Item("grants/grants_select.sql", select.encode("utf-8"), "grants",
             note="run by the owner of the source schema or a DBA"),
        Item("grants/grants_test_only_insert.sql", insert.encode("utf-8"), "grants", ("TEST",),
             "test environment only"),
    ]


def collect(mapping, include=()) -> tuple:
    """([Item] in listing order, [upstream mapping IDs])."""
    check = argparse.Namespace(mapping=mapping.path, out_dir=None)
    if generate.cmd_check(check) != 0:
        raise PackageError("the generated code is not current: fix what generate.py --check reports, then rebuild")

    folder = os.path.dirname(os.path.abspath(mapping.path))
    fingerprint = mapping.fingerprint()
    paths = generate.output_paths(mapping, folder)
    items = []

    staging, upstream = planned_staging_scripts(mapping)
    for path in staging:
        items.append(_file_item(path, "staging", note="before the mapping's own DDL; run by the staging schema owner or a DBA"))
    items.extend(grants_items(mapping))

    names = deploy_file_names(mapping.mapping_id)
    for key in ("runbook", "preflight_1", "preflight_2"):
        path = os.path.join(folder, names[key])
        if not os.path.isfile(path):
            raise PackageError("missing {0}: write it first (dev-3-prepare-deployment, Step 2)".format(_arc(path)))
        item = _file_item(path, key, note="the runbook" if key == "runbook" else "read-only checks")
        text = item.data.decode("utf-8", errors="replace")
        found = MAPPING_FINGERPRINT.search(text)
        if not found or found.group(1) != fingerprint:
            raise PackageError("{0} was written for fingerprint {1}, the workbook is now {2}: rewrite it".format(
                item.arc, found.group(1) if found else "?", fingerprint))
        if key != "runbook" and not has_helper_block(text):
            raise PackageError("{0} does not contain the helper block of {1} unchanged: paste it, do not "
                               "rewrite the helpers".format(item.arc, _arc(PREFLIGHT_HELPERS)))
        items.append(item)

    current_cols, current_pk, source = generate.existing_target(mapping)
    plan = generate.plan_changes(mapping, generate.table_columns(mapping), current_cols, current_pk, source)
    if plan.table_exists:
        change = paths["change"]
        found = None
        if os.path.isfile(change):
            with open(change, encoding="utf-8") as handle:
                found = MAPPING_FINGERPRINT.search(handle.read())
        if not found or found.group(1) != fingerprint:
            raise PackageError("the target table exists but {0} is missing or was generated from another "
                               "fingerprint than {1}: run generate.py {2}".format(
                                   _arc(change), fingerprint, mapping.mapping_id))
        items.append(_file_item(change, "table_change",
                                note="the table exists: this replaces the full CREATE TABLE script"))
    else:
        items.append(_file_item(paths["table"], "table_create"))
        if mapping.is_scd2 and schema_catalog.table_state(
                mapping.target_schema + "." + generate.load_log_name(mapping)) != "ok":
            items.append(_file_item(paths["load_log"], "load_log"))
    items.append(_file_item(paths["package"], "package"))
    items.append(_file_item(paths["test_data"], "test_data", ("TEST",), "test environment only"))
    items.append(_file_item(paths["tests"], "tests", ("TEST",), "test environment only; ends by running the tests"))

    seen = {item.arc for item in items}
    for extra in include:
        path = extra if os.path.isabs(extra) else os.path.join(REPO_ROOT, extra)
        if not os.path.isfile(path):
            raise PackageError("--include {0}: no such file".format(extra))
        item = _file_item(path, "external", note="named with --include; reviewed by the developer")
        if item.source in {i.source for i in items}:
            continue
        if item.arc in seen:
            raise PackageError("--include {0}: {1} would share its path in the package with another file; "
                               "rename one of them".format(extra, item.arc))
        seen.add(item.arc)
        items.append(item)
    clashes = sorted(name for name in seen if sum(1 for i in items if i.arc == name) > 1)
    if clashes:
        raise PackageError("two files would share one path in the package: " + ", ".join(clashes))
    items.sort(key=lambda item: ROLE_RANK[item.role])
    return items, upstream


# ---------------------------------------------------------------------------
# Writing the zip
# ---------------------------------------------------------------------------

VERIFY_SH = """#!/bin/sh
# Checks every file of this package against SHA256SUMS. Works on Linux and macOS.
cd "$(dirname "$0")" || exit 2
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c SHA256SUMS
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 -c SHA256SUMS
else
    echo "sha256sum or shasum is needed" >&2
    exit 2
fi
"""

VERIFY_PS1 = """# Checks every file of this package against SHA256SUMS. Windows PowerShell 5.1 and PowerShell 7.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$bad = 0
foreach ($line in Get-Content -LiteralPath 'SHA256SUMS') {
    if ($line -notmatch '^([0-9a-f]{64})  (.+)$') { continue }
    $expected = $Matches[1]
    $file = $Matches[2]
    if (-not (Test-Path -LiteralPath $file)) { Write-Host "MISSING  $file"; $bad++; continue }
    $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -eq $expected) { Write-Host "OK       $file" } else { Write-Host "FAILED   $file"; $bad++ }
}
if ($bad -gt 0) { Write-Host "$bad file(s) differ or are missing."; exit 1 }
Write-Host 'All files match.'
"""

README = """DEPLOYMENT PACKAGE - {mapping_id}

Mapping fingerprint : {fingerprint}
Approved by         : {approved_by} on {approved_on}
Change request      : {change_request}
Target              : {target}
Load procedure      : {proc}
Built on            : {built_on} from {commit}

This package holds files only. Nothing in it has been run, and nothing in it opens a
database connection by itself: a developer reviews every file and runs it by hand.

1. Verify the package (after copying it to the other machine)
   Linux / macOS : sh verify.sh
   Windows       : powershell -ExecutionPolicy Bypass -File verify.ps1
   Every line must say OK.

2. Read the runbook
   RUNBOOK.md (in this folder, next to this file)
   It lists the steps in order, with the schema to connect as, the parameters, the expected
   result and the stop condition of each, and what is outside this package (open items).
   Paths in the runbook are relative to this folder: run every command from here.

3. Run the SQL files
   Needs SQLcl (Java 11 or later) or SQL*Plus, a network route to the database and the
   database users the runbook names. Never put a password on the command line; let the
   tool ask for it.

   Linux, macOS and Windows alike:   sql UBB_CORE2@//host:1521/SERVICE
                                     (SQL*Plus: sqlplus UBB_CORE2@//host:1521/SERVICE)

   then, at the SQL prompt, one file at a time, from this folder, with the arguments the
   runbook gives, for example:       @preflight/FILE.sql TEST
   All files are UTF-8 with LF line endings. If SQL*Plus shows garbled characters, set
   NLS_LANG=.AL32UTF8 first (Windows: chcp 65001 as well).

4. After deployment
   A developer exports the changed table and package scripts into the repository's sql/
   folder by hand, so the repository matches the database.

Unpacking next to other packages
--------------------------------
Everything is inside one folder named {mapping_id}, with at most one level of folders below
it, so the packages of different mappings can be unpacked into the same directory without
overwriting each other. Unpacking a newer package of the same mapping into the same
directory overwrites the older one file by file and can leave files of the old version
behind: delete the old {mapping_id} folder first (MANIFEST.json holds the fingerprint).

Files
-----
{files}
Not in this package (see the runbook, "Open items"): anything the repository does not hold,
such as a wrapper or scheduler change, a loader, or a configuration value.
"""


def sums_text(entries: dict) -> str:
    return "".join("{0}  {1}\n".format(entries[name], name) for name in sorted(entries))


def _zip_entry(archive: zipfile.ZipFile, arc: str, data: bytes) -> None:
    info = zipfile.ZipInfo(arc, date_time=FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3  # Unix, so the permission bits below are honoured by unzip
    info.external_attr = (0o755 if arc.endswith(".sh") else 0o644) << 16
    archive.writestr(info, data)


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=REPO_ROOT, capture_output=True,
                             text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return "git commit " + out.stdout.strip()
    except Exception:  # noqa: BLE001 - the commit is information, never a reason to fail
        pass
    return "an unknown commit"


def build_zip(mapping, items: list, upstream: list, out_path: str, today=None) -> dict:
    """Write the package; return {path: sha256} of what it holds apart from SHA256SUMS."""
    today = today or _dt.date.today()
    cr = CR_PATTERN.search(mapping.get("Source_Ref"))
    commit = _git_commit()
    root = mapping.mapping_id

    listing = "".join(
        "  {0:<44} {1}{2}\n".format(
            item.arc,
            item.role + ("" if len(item.environments) == 2 else " ({0} only)".format("/".join(item.environments))),
            "  - " + item.note if item.note else "")
        for item in items)
    readme = README.format(
        mapping_id=mapping.mapping_id, fingerprint=mapping.fingerprint(),
        approved_by=mapping.get("Approved_By") or "?", approved_on=mapping.get("Approved_On") or "?",
        change_request=cr.group(0) if cr else "none", target=mapping.target, proc=mapping.plsql_proc,
        built_on=today.isoformat(), commit=commit, files=listing)

    manifest = {
        "package_format": PACKAGE_FORMAT,
        "package_folder": root,
        "mapping_id": mapping.mapping_id,
        "fingerprint": mapping.fingerprint(),
        "approved_by": mapping.get("Approved_By"),
        "approved_on": mapping.get("Approved_On"),
        "change_request": cr.group(0) if cr else None,
        "target": mapping.target,
        "load_procedure": mapping.plsql_proc,
        "parameters": ["{0} {1}".format(n, t).strip() for n, t in mapping.parameters],
        "built_on": today.isoformat(),
        "source": commit,
        "upstream_mappings_to_deploy_first": upstream,
        "files": [{"path": i.arc, "repository_path": i.source or None, "role": i.role,
                   "environments": list(i.environments), "sha256": sha256(i.data), "size": len(i.data),
                   "note": i.note} for i in items],
    }
    payload = {item.arc: item.data for item in items}
    payload["README.txt"] = readme.encode("utf-8")
    payload["MANIFEST.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    payload["verify.sh"] = VERIFY_SH.encode("utf-8")
    payload["verify.ps1"] = VERIFY_PS1.encode("utf-8")
    sums = {name: sha256(data) for name, data in payload.items()}
    payload["SHA256SUMS"] = sums_text(sums).encode("utf-8")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with zipfile.ZipFile(out_path, "w") as archive:
        for name in [i.arc for i in items] + list(META_FILES):
            _zip_entry(archive, root + "/" + name, payload[name])
    return sums


def package_root(names: list) -> str:
    """The one top folder every entry sits in, or '' when there is not exactly one."""
    roots = {name.split("/", 1)[0] for name in names}
    return roots.pop() if len(roots) == 1 and all("/" in name for name in names) else ""


def read_sums(archive: zipfile.ZipFile) -> dict:
    """{path inside the package folder: sha256} from the package's SHA256SUMS."""
    root = package_root(archive.namelist())
    listed = {}
    for line in archive.read(root + "/SHA256SUMS").decode("utf-8").splitlines():
        digest, _sep, name = line.partition("  ")
        listed[name] = digest
    return listed


def verify_zip(path: str) -> list:
    """Problems found re-reading the package: unsafe or misplaced entries (not in
    one top folder, deeper than folder/file), or content that differs from its
    own SHA256SUMS. [] when it is sound."""
    problems = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for name in names:
            if "\\" in name or name.startswith("/") or ".." in name.split("/") or re.match(r"^[A-Za-z]:", name):
                problems.append("unsafe entry name: " + name)
        root = package_root(names)
        if not root:
            return problems + ["the entries are not all inside one top folder"]
        for name in names:
            if name.count("/") > 2:
                problems.append("more than one folder level below {0}: {1}".format(root, name))
        listed = read_sums(archive)
        inside = {name[len(root) + 1:]: name for name in names}
        for rel, name in inside.items():
            if rel != "SHA256SUMS" and listed.get(rel) != sha256(archive.read(name)):
                problems.append("checksum mismatch: " + rel)
        problems.extend("listed but missing: " + rel for rel in listed if rel not in inside)
    return problems


def package_path(mapping, out_dir=None) -> str:
    return os.path.join(out_dir or DEFAULT_OUT_DIR, "{0}_{1}.zip".format(mapping.mapping_id, mapping.fingerprint()))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_build(args) -> int:
    mapping = generate.load_approved(args.mapping)
    items, upstream = collect(mapping, args.include)
    out_path = package_path(mapping, args.out_dir)
    build_zip(mapping, items, upstream, out_path)
    problems = verify_zip(out_path)
    if problems:
        os.remove(out_path)
        raise PackageError("the package failed its own check:\n  " + "\n  ".join(problems))
    print("Deployment package for {0} (fingerprint {1}):".format(mapping.mapping_id, mapping.fingerprint()))
    print("  {0}  ({1} bytes)".format(generate._rel(out_path), os.path.getsize(out_path)))
    for item in items:
        print("    {0:<13} {1}".format(item.role, item.arc))
    if upstream:
        print("  NOTE: mappings to be deployed first (not in this package): " + ", ".join(upstream))
    print("  Copy it to the other machine, run verify.sh (Linux) or verify.ps1 (Windows), then follow the runbook.")
    print("  Nothing was deployed or run.")
    return 0


def cmd_check(args) -> int:
    mapping = generate.load_approved(args.mapping)
    out_path = package_path(mapping, args.out_dir)
    if not os.path.isfile(out_path):
        print("NOT BUILT: {0} does not exist (fingerprint {1})".format(generate._rel(out_path), mapping.fingerprint()))
        return 1
    problems = verify_zip(out_path)
    items, _upstream = collect(mapping, args.include)
    with zipfile.ZipFile(out_path) as archive:
        listed = read_sums(archive)
    for item in items:
        if listed.get(item.arc) != sha256(item.data):
            problems.append("{0} changed since the package was built".format(item.arc))
    expected = {item.arc for item in items} | set(META_FILES)
    problems.extend("{0} is in the package but no longer expected".format(n) for n in sorted(set(listed) - expected))
    if problems:
        print("STALE: {0}".format(generate._rel(out_path)))
        for problem in problems:
            print("  - " + problem)
        return 1
    print("{0}: the package is current (fingerprint {1}).".format(mapping.mapping_id, mapping.fingerprint()))
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("mapping", help="Mapping_ID or path to an approved workbook")
    parser.add_argument("--include", action="append", default=[],
                        help="an extra repository file to pack (repeatable), for example an updated wrapper script")
    parser.add_argument("--out-dir", help="default: deployment-packages/ in the repository")
    parser.add_argument("--check", action="store_true", help="compare an existing package with the files now")
    args = parser.parse_args(argv)
    try:
        return cmd_check(args) if args.check else cmd_build(args)
    except (PackageError, generate.GenerationError) as exc:
        print("ERROR: {0}".format(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
