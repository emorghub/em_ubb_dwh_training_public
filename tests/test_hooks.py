"""The generated-code gate hook, as Claude Code and GitHub Copilot call it.

Each tool runs its own copy of the same script: Claude Code runs
.claude/hooks/sql_gate.py from .claude/settings.json, Copilot runs
.github/hooks/sql_gate.py from .github/hooks/sql_gate.json. The two folders
are shipped separately, so neither may depend on the other; the copies must
stay identical. The tests run against the .github copy, and the checks that
involve .claude/ are skipped when that folder is not part of the checkout. The tools send the pending tool call in different shapes;
every shape must reach the gate.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, ".github", "hooks"))

import _hooklib  # noqa: E402

TARGET = "specs/t_out/T_OUT.sql"


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_name": "Edit", "tool_input": {"file_path": TARGET}},  # Claude Code
        {"tool_name": "MultiEdit", "tool_input": {"edits": [{"file_path": TARGET}]}},  # Claude Code
        {"tool_name": "Edit", "tool_input": {"filePath": TARGET}},  # Copilot, PascalCase PreToolUse
        {"toolName": "edit", "toolArgs": json.dumps({"path": TARGET})},  # Copilot, camelCase preToolUse
        {"tool_name": "Edit", "tool_input": {"input": "*** Begin Patch\n*** Update File: " + TARGET + "\n*** End Patch"}},
    ],
)
def test_every_payload_shape_yields_the_file(payload):
    assert _hooklib.collect_paths(payload) == [TARGET]


@pytest.mark.skipif(os.name != "nt", reason="drive letters exist only on Windows")
def test_drive_letter_case_does_not_open_the_gate():
    absolute = os.path.join(_hooklib.REPO_ROOT, TARGET)
    for spelled in (absolute[0].upper() + absolute[1:], absolute[0].lower() + absolute[1:]):
        assert _hooklib.under(spelled, "specs")


needs_claude_folder = pytest.mark.skipif(
    not os.path.isdir(os.path.join(ROOT, ".claude")), reason=".claude/ is not part of this checkout"
)


def _copilot_entry():
    with open(os.path.join(ROOT, ".github", "hooks", "sql_gate.json"), encoding="utf-8") as handle:
        copilot = json.load(handle)["hooks"]["PreToolUse"]
    return next(e for e in copilot if "sql_gate.py" in e.get("powershell", ""))


def test_copilot_runs_its_own_copy_of_the_gate():
    entry = _copilot_entry()
    assert "Edit" in entry["matcher"] and "Write" in entry["matcher"]
    for shell in ("bash", "powershell"):
        assert entry[shell].endswith(".github/hooks/sql_gate.py")


@needs_claude_folder
def test_claude_and_copilot_run_the_same_gate():
    with open(os.path.join(ROOT, ".claude", "settings.json"), encoding="utf-8") as handle:
        claude = json.load(handle)["hooks"]["PreToolUse"]
    claude_entry = next(e for e in claude if "sql_gate.py" in e["hooks"][0]["command"])
    assert _copilot_entry()["matcher"] == claude_entry["matcher"]
    assert claude_entry["hooks"][0]["command"].endswith(".claude/hooks/sql_gate.py")


@needs_claude_folder
@pytest.mark.parametrize("name", ["sql_gate.py", "_hooklib.py"])
def test_each_assistant_folder_holds_an_identical_copy_of_the_hook(name):
    def read(folder):
        with open(os.path.join(ROOT, folder, "hooks", name), "rb") as handle:
            return handle.read().replace(b"\r\n", b"\n")

    assert read(".claude") == read(".github"), (
        "{0} differs between .claude/hooks and .github/hooks; change both".format(name)
    )


def _text_files(folder):
    for base, dirs, files in os.walk(os.path.join(ROOT, folder)):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for file_name in files:
            if file_name.lower().endswith((".py", ".md", ".json", ".yml", ".yaml", ".txt")):
                yield os.path.join(base, file_name)


@pytest.mark.parametrize("folder, other", [(".claude", ".github"), (".github", ".claude")])
def test_neither_assistant_folder_names_the_other(folder, other):
    if not os.path.isdir(os.path.join(ROOT, folder)):
        pytest.skip("{0}/ is not part of this checkout".format(folder))
    offenders = []
    for path in _text_files(folder):
        with open(path, encoding="utf-8") as handle:
            if other in handle.read():
                offenders.append(os.path.relpath(path, ROOT))
    assert not offenders, "{0} is shipped without {1} but names it: {2}".format(folder, other, ", ".join(offenders))


def test_generated_staging_scripts_are_never_hand_edited(capsys):
    import validate_spec

    assert validate_spec.main(["sql-gate", "change-requests/CR-ECB-001/staging/STG_LOAN.sql"]) == 1
    assert "BLOCKED" in capsys.readouterr().out
    # other files of a change request, and SQL elsewhere, are not this gate's business
    assert validate_spec.main(["sql-gate", "change-requests/CR-ECB-001/notes.sql"]) == 0
    assert validate_spec.main(["sql-gate", "docs/example.sql"]) == 0
