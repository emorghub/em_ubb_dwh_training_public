"""PreToolUse hook: block hand-edits to generated code whose mapping is not
approved.

Every .sql file in a mapping folder, specs/<folder>/ (table DDL, change
scripts, load packages, utPLSQL tests), is generated from the mapping
workbook in that same folder by
tools/codegen/generate.py, which itself refuses to run for an unapproved
mapping. This hook closes the other path: an assistant editing those files
directly - for example filling in test fixture data - is only allowed
while the owning mapping is valid and approved. How a file is matched to
its mapping is described in `validate_spec.py sql-gate`.

The staging scripts a change request needs, change-requests/<CR_ID>/staging/
*.sql, are generated from approved delivery agreements by
tools/codegen/generate_staging.py and are never edited by hand: the gate
blocks every edit to them.

Wired up against Edit, Write and MultiEdit by the hook configuration of the
assistant (Claude Code, or GitHub Copilot: VS Code agent, Copilot CLI and the
cloud coding agent). Each assistant's folder holds its own copy of this script
and of _hooklib; _hooklib reads both tools' payload shapes, and
tests/test_hooks.py keeps the copies identical.
"""

from __future__ import annotations

import sys

from _hooklib import run_gate, use_utf8_streams

if __name__ == "__main__":
    use_utf8_streams()
    sys.exit(run_gate("sql-gate", ("specs", "change-requests"), "sql_gate"))
