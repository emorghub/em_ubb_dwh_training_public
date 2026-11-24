"""Create, write, show and diff mapping workbooks (specs/<folder>/<ID>.xlsx).

The workbook is what an analyst reads and edits in Excel. An AI assistant
(Claude Code or GitHub Copilot) never edits cells directly: it writes the
mapping as JSON and lets this tool render the workbook, so the layout,
dropdowns and approval rules are always the same.

Commands
--------
new <MAPPING_ID>          Create an empty draft workbook to fill in by hand.
schema                    Print the JSON shape `write` accepts, with every
                          field's help text. Start here when drafting.
write <file.json | ->     Create or replace a workbook from JSON. The output
                          path is specs/<folder>/<Mapping_ID>.xlsx unless
                          --out is given. Validates it.
show <ID | path>          Print a workbook as readable text (--json for JSON).
fingerprint <ID | path>   Print the content hash stamped into generated code.
textconv <path>           Plain-text rendering of any .xlsx for `git diff`.

Approval rules the writer enforces (the same rules a person must follow):
- `write` never sets Status to approved and never fills Approved_By or
  Approved_On. Approval is done by a named person, in Excel.
- Rewriting an approved workbook with *unchanged* content keeps the approval.
- Rewriting it with *changed* content drops the approval: Status becomes
  what the JSON says (draft or in_review) and the approval fields are
  cleared. A stale approval on changed content is worse than none.

Usage
-----
    python tools/mapping_spec/mapping_workbook.py schema
    python tools/mapping_spec/mapping_workbook.py write draft.json
    python tools/mapping_spec/mapping_workbook.py show M_CUSTOMER_ACCOUNT
    python tools/mapping_spec/mapping_workbook.py show M_CUSTOMER_ACCOUNT --json > draft.json

To see workbook changes as text in `git diff`, run once per clone:
    git config diff.xlsx.textconv "python tools/mapping_spec/mapping_workbook.py textconv"
(.gitattributes already routes *.xlsx through that driver.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from workbook_format import (  # noqa: E402
    APPROVAL_FIELDS,
    COLUMN_HEADERS,
    ITEM_COLUMN_HEADERS,
    CRITERIA_HEADERS,
    DECISION_HEADERS,
    JOIN_HEADERS,
    MAPPING_FIELDS,
    REPO_ROOT,
    SOURCE_HEADERS,
    VALID_CHECK_TYPES,
    VALID_JOIN_TYPES,
    VALID_SOURCE_TYPES,
    Mapping,
    is_mapping_workbook,
    mapping_from_dict,
    mapping_path,
    mapping_to_dict,
    read_mapping,
    resolve_mapping_path,
    write_mapping,
)

AI_WRITABLE_STATUSES = ("draft", "in_review")


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
    except ValueError:
        return path


def _report(mapping: Mapping) -> int:
    from mapping_validation import validate_mapping

    report = validate_mapping(mapping)
    for warning in report.warnings:
        print("  WARN  " + warning)
    for error in report.errors:
        print("  FAIL  " + error)
    if report.ok:
        print("Validation: OK ({0} warning(s)).".format(len(report.warnings)))
    else:
        print("Validation: {0} problem(s) - fine for a draft, must be zero before approval.".format(len(report.errors)))
    return 0 if report.ok else 1


# ---------------------------------------------------------------------------


def cmd_new(args) -> int:
    path = os.path.abspath(args.out) if args.out else mapping_path(args.mapping_id)
    if os.path.exists(path):
        print("ERROR: {0} already exists.".format(_rel(path)))
        return 1
    mapping = Mapping(fields={"Mapping_ID": args.mapping_id, "Status": "draft"}, path=path)
    write_mapping(mapping, path)
    print("wrote {0} (empty draft)".format(_rel(path)))
    return 0


def cmd_schema(args) -> int:
    example = {
        "mapping": {spec.name: "<{0}>".format(spec.help) for spec in MAPPING_FIELDS},
        "columns": [dict(zip(_keys("columns"), ("<{0}>".format(h) for h in COLUMN_HEADERS)))],
        "item_columns": [dict(zip(_keys("item_columns"), ("<{0}>".format(h) for h in ITEM_COLUMN_HEADERS)))],
        "joins": [dict(zip(_keys("joins"), ("<{0}>".format(h) for h in JOIN_HEADERS)))],
        "acceptance_criteria": [dict(zip(_keys("acceptance_criteria"), ("<{0}>".format(h) for h in CRITERIA_HEADERS)))],
        "sources": [dict(zip(_keys("sources"), ("<{0}>".format(h) for h in SOURCE_HEADERS)))],
        "decisions": [dict(zip(_keys("decisions"), ("<{0}>".format(h) for h in DECISION_HEADERS)))],
    }
    example["mapping"]["Status"] = "draft | in_review  (never approved - a person does that in Excel)"
    example["mapping"]["Approved_By"] = ""
    example["mapping"]["Approved_On"] = ""
    print(json.dumps(example, indent=2, ensure_ascii=False))
    print()
    print("Allowed values: Join_Type {0}; Check_Type {1}; Source_Type {2}.".format(
        "|".join(VALID_JOIN_TYPES), "|".join(VALID_CHECK_TYPES), "|".join(VALID_SOURCE_TYPES)))
    print("Multi-line Mapping fields (Not_For, Preconditions, Error_Handling) may be a string")
    print("with newlines or a JSON list of strings. Row order = column order / join order.")
    return 0


def _keys(section: str) -> list:
    blank = mapping_from_dict({section: [{}]})
    attr = {"acceptance_criteria": "criteria"}.get(section, section)
    row = getattr(blank, attr)[0]
    return list(vars(row).keys())


def cmd_write(args) -> int:
    raw = sys.stdin.read() if args.json_file == "-" else open(args.json_file, "r", encoding="utf-8").read()
    try:
        new = mapping_from_dict(json.loads(raw))
    except (ValueError, json.JSONDecodeError) as exc:
        print("ERROR: {0}".format(exc))
        return 1
    if not new.mapping_id:
        print("ERROR: mapping.Mapping_ID is required.")
        return 1

    path = os.path.abspath(args.out) if args.out else mapping_path(new.mapping_id)
    new.path = path
    existing = read_mapping(path) if os.path.exists(path) else None

    wants_approval = new.status == "approved" or new.get("Approved_By") or new.get("Approved_On")
    content_unchanged = existing is not None and existing.fingerprint() == new.fingerprint()

    if wants_approval:
        same_approval = existing is not None and all(existing.get(f) == new.get(f) for f in APPROVAL_FIELDS)
        if not (existing is not None and existing.is_approved and content_unchanged and same_approval):
            print(
                "ERROR: this tool never records an approval. Set Status to draft or in_review and leave "
                "Approved_By/Approved_On empty; the approving person sets them in Excel."
            )
            return 1
        print("Content unchanged; existing approval by {0} kept.".format(existing.get("Approved_By")))
    else:
        status = new.status or "draft"
        if status not in AI_WRITABLE_STATUSES:
            print("ERROR: Status must be one of {0}.".format(", ".join(AI_WRITABLE_STATUSES)))
            return 1
        new.fields["Status"] = status
        if existing is not None and existing.is_approved:
            if content_unchanged:
                print(
                    "NOTE: content is unchanged but Status was set to {0}; the approval by {1} "
                    "is withdrawn.".format(status, existing.get("Approved_By"))
                )
            else:
                print(
                    "Content changed, so the approval by {0} on {1} is dropped: Status is now {2}. "
                    "A named person must approve the new content again.".format(
                        existing.get("Approved_By"), existing.get("Approved_On"), status
                    )
                )

    write_mapping(new, path)
    print("wrote {0} (status: {1}, fingerprint {2})".format(_rel(path), new.status, new.fingerprint()))
    _report(new)
    return 0


def _load(arg: str) -> Mapping:
    path = resolve_mapping_path(arg)
    if not os.path.exists(path):
        raise SystemExit("ERROR: no workbook at {0}".format(_rel(path)))
    return read_mapping(path)


def render_text(mapping: Mapping) -> str:
    out = ["# {0}  ({1})".format(mapping.mapping_id, _rel(mapping.path) if mapping.path else "")]
    out.append("")
    out.append("## Mapping")
    for spec in MAPPING_FIELDS:
        value = mapping.get(spec.name)
        if "\n" in value:
            out.append("{0}:".format(spec.name))
            out.extend("    " + line for line in value.splitlines())
        else:
            out.append("{0}: {1}".format(spec.name, value))
    for title, attr, headers in (
        ("Columns", "columns", COLUMN_HEADERS),
        ("Item_Columns", "item_columns", ITEM_COLUMN_HEADERS),
        ("Joins", "joins", JOIN_HEADERS),
        ("Acceptance_Criteria", "criteria", CRITERIA_HEADERS),
        ("Sources", "sources", SOURCE_HEADERS),
        ("Decisions", "decisions", DECISION_HEADERS),
    ):
        rows = getattr(mapping, attr)
        if attr == "item_columns" and not rows:
            continue  # optional sheet: keep the text of mappings without it as before
        out.append("")
        out.append("## {0} ({1})".format(title, len(rows)))
        for index, row in enumerate(rows, start=1):
            values = list(vars(row).values())
            parts = ["{0}={1}".format(h, v.replace("\n", " / ")) for h, v in zip(headers, values) if v]
            out.append("{0:>3}. {1}".format(index, " | ".join(parts)))
    out.append("")
    out.append("fingerprint: {0}".format(mapping.fingerprint()))
    return "\n".join(out)


def cmd_show(args) -> int:
    mapping = _load(args.mapping)
    if args.json:
        print(json.dumps(mapping_to_dict(mapping), indent=2, ensure_ascii=False))
    else:
        print(render_text(mapping))
    return 0


def cmd_fingerprint(args) -> int:
    print(_load(args.mapping).fingerprint())
    return 0


def cmd_textconv(args) -> int:
    """Readable text for git diff. Never fails: a diff must always render."""
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(args.path, data_only=True)
    except Exception as exc:  # noqa: BLE001
        print("<unreadable workbook: {0}>".format(exc))
        return 0
    if is_mapping_workbook(workbook):
        try:
            mapping = read_mapping(args.path)
            mapping.path = ""
            print(render_text(mapping))
            return 0
        except Exception:  # noqa: BLE001 - fall through to the generic dump
            pass
    for sheet in workbook.worksheets:
        print("## {0}".format(sheet.title))
        for row in sheet.iter_rows(values_only=True):
            if any(cell not in (None, "") for cell in row):
                print(" | ".join("" if cell is None else str(cell).replace("\n", " / ") for cell in row).rstrip(" |"))
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="create an empty draft workbook")
    new.add_argument("mapping_id")
    new.add_argument("--out", help="path instead of specs/<folder>/<ID>.xlsx")

    sub.add_parser("schema", help="print the JSON shape `write` accepts")

    write = sub.add_parser("write", help="create or replace a workbook from JSON")
    write.add_argument("json_file", help="JSON file, or - for stdin")
    write.add_argument("--out", help="path instead of specs/<folder>/<Mapping_ID>.xlsx")

    show = sub.add_parser("show", help="print a workbook as text")
    show.add_argument("mapping", help="Mapping_ID or path")
    show.add_argument("--json", action="store_true")

    fingerprint = sub.add_parser("fingerprint", help="print the content fingerprint")
    fingerprint.add_argument("mapping", help="Mapping_ID or path")

    textconv = sub.add_parser("textconv", help="text rendering of any xlsx, for git diff")
    textconv.add_argument("path")

    args = parser.parse_args(argv)
    handlers = {
        "new": cmd_new,
        "schema": cmd_schema,
        "write": cmd_write,
        "show": cmd_show,
        "fingerprint": cmd_fingerprint,
        "textconv": cmd_textconv,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
