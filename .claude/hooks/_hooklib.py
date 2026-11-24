"""Shared plumbing for this repo's Claude Code hooks.

Claude Code passes the pending (PreToolUse) or completed (PostToolUse) tool
call as JSON on stdin. A PreToolUse hook denies the call by exiting with
code 2; whatever it wrote to stderr is shown to the model.
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys

# This file lives in <repo>/<assistant folder>/hooks/, so the root is two levels up.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
VALIDATOR = os.path.join(REPO_ROOT, "tools", "mapping_spec", "validate_spec.py")


def use_utf8_streams() -> None:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - older or redirected streams
        pass


def read_payload():
    raw = sys.stdin.read()
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _as_dict(value):
    """Tool arguments arrive as a dict in Claude Code but as a JSON string
    in GitHub Copilot (key `toolArgs`). Normalise both to a dict."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {"input": value}  # raw text, e.g. an apply_patch body
    return value if isinstance(value, dict) else {}


_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$", re.MULTILINE)


def collect_paths(payload) -> list:
    """Every file path a tool call writes to (Edit, Write, MultiEdit shapes,
    plus the Copilot variants: `toolArgs` as a JSON string, apply_patch text)."""
    payload = payload if isinstance(payload, dict) else {}
    tool_input = _as_dict(payload.get("tool_input") or payload.get("toolArgs") or payload.get("toolInput"))
    paths = []
    for key in ("file_path", "filePath", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    for key in ("edits", "files"):
        items = tool_input.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    value = item.get("file_path") or item.get("filePath") or item.get("path")
                    if isinstance(value, str) and value:
                        paths.append(value)
                elif isinstance(item, str) and item:
                    paths.append(item)
    for key, value in tool_input.items():
        if isinstance(value, str) and "*** " in value:
            paths.extend(_PATCH_FILE.findall(value))
    return paths


def under(path: str, relative_dir: str) -> bool:
    # normcase: on Windows "C:\x" and "c:/x" are the same file; Claude Code and
    # Copilot differ in how they spell the drive letter, and a mismatch would
    # silently let the edit through.
    candidate = os.path.normcase(os.path.abspath(path))
    directory = os.path.normcase(os.path.abspath(os.path.join(REPO_ROOT, relative_dir)))
    try:
        return os.path.commonpath([candidate, directory]) == directory
    except ValueError:
        return False  # different drives on Windows - definitely not under it


def run_gate(subcommand: str, relative_dirs, hook_name: str) -> int:
    """Run `validate_spec.py <subcommand>` on the touched files under
    relative_dirs (one folder or several). Returns the hook exit code: 0
    allow, 2 deny.

    Fails open, loudly: if the validator itself crashes (as opposed to
    deliberately blocking, which it signals by printing BLOCKED), the edit
    is allowed and a warning says the gate is not protecting anything. A
    broken validator must never lock every edit in the repository -
    including the edit that would fix it.
    """
    payload = read_payload()
    if isinstance(relative_dirs, str):
        relative_dirs = (relative_dirs,)
    paths = [p for p in collect_paths(payload) if any(under(p, d) for d in relative_dirs)]
    if not paths:
        return 0

    if not os.path.isfile(VALIDATOR):
        sys.stderr.write("{0}: validator not found; allowing, but this gate is off.\n".format(hook_name))
        return 0

    try:
        result = subprocess.run(
            [sys.executable, VALIDATOR, subcommand] + paths,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("{0}: validator failed to run ({1}); allowing.\n".format(hook_name, exc))
        return 0

    if result.returncode == 0:
        return 0
    output = (result.stdout or "") + (result.stderr or "")
    if "BLOCKED" not in output:
        sys.stderr.write(
            "{0}: the validator crashed instead of answering; allowing the edit, but "
            "this gate is NOT protecting anything until it is fixed:\n{1}\n".format(hook_name, output.strip())
        )
        return 0
    sys.stderr.write(output.strip() + "\n")
    return 2
