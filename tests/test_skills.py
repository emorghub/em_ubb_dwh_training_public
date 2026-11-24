"""Guards for the assistant skills and the "never touch a database" rule.

* `.github/skills/` (Copilot) must stay a copy of `.claude/skills/` (Claude
  Code). The only allowed difference is a paragraph that starts with
  "**Running as GitHub Copilot:**". The `.claude/` folder is not shipped to
  every team, so the comparison is skipped when it is absent and every other
  check runs against `.github/skills/`.
* Every repo path or `python <script>` command a skill names must exist.
* No tool, hook or requirement may bring a database driver or client, and
  every skill must say that a database is never used.

None of these tests needs a database.
"""

from __future__ import annotations

import ast
import glob
import os
import re

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CLAUDE_SKILLS = os.path.join(ROOT, ".claude", "skills")
GITHUB_SKILLS = os.path.join(ROOT, ".github", "skills")

COPILOT_ONLY = re.compile(r"\*\*Running as GitHub Copilot:\*\*.*?(?:\n\s*\n|\Z)", re.DOTALL)
CODE_SPAN = re.compile(r"`([^`\n]+)`")
PYTHON_COMMAND = re.compile(r"python\s+([\w./-]+\.py)")
REPO_PATH = re.compile(r"^(?:tools|docs|specs|sql|tests|\.claude|\.github)/[\w./-]*[\w]$")
BARE_FILE = re.compile(r"^[\w-]+\.(?:md|txt|json)$")

# Anything that can open a database session or run a database client.
DATABASE_MODULES = {
    "oracledb", "cx_oracle", "pyodbc", "jaydebeapi", "jpype", "ibm_db", "sqlalchemy",
    "psycopg2", "psycopg", "pymysql", "mysql", "sqlite3", "pymssql", "peewee", "records",
}
DATABASE_CLIENTS = {"sqlplus", "sqlcl", "sql.exe", "tnsping", "impdp", "expdp"}


def read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read().replace("\r\n", "\n")


def skill_files(base: str) -> list:
    return sorted(
        os.path.relpath(p, base).replace(os.sep, "/")
        for p in glob.glob(os.path.join(base, "**", "*.md"), recursive=True)
    )


def python_files() -> list:
    found = []
    for pattern in ("tools/**/*.py", ".claude/hooks/*.py", ".github/hooks/*.py"):
        found += glob.glob(os.path.join(ROOT, pattern), recursive=True)
    return sorted(found)


needs_claude_folder = pytest.mark.skipif(
    not os.path.isdir(CLAUDE_SKILLS), reason=".claude/ is not part of this checkout"
)


@needs_claude_folder
def test_both_skill_folders_hold_the_same_files():
    assert skill_files(CLAUDE_SKILLS) == skill_files(GITHUB_SKILLS)


@pytest.mark.parametrize("name", [n for n in skill_files(GITHUB_SKILLS) if n.endswith("SKILL.md")])
def test_skill_name_matches_its_folder(name):
    # Claude Code and Copilot both find a skill by its folder; a `name:` that
    # differs makes the slash command and the documents disagree.
    folder = name.split("/")[0]
    header = re.search(r"\A---\n(.*?)\n---\n", read(os.path.join(GITHUB_SKILLS, name)), re.DOTALL)
    assert header, "{0} has no front matter".format(name)
    declared = re.search(r"^name:\s*(\S+)\s*$", header.group(1), re.MULTILINE)
    assert declared and declared.group(1) == folder, (
        "{0}: front matter name must be '{1}'".format(name, folder)
    )


@needs_claude_folder
@pytest.mark.parametrize("name", skill_files(CLAUDE_SKILLS))
def test_github_skill_is_a_copy_of_the_claude_skill(name):
    claude = read(os.path.join(CLAUDE_SKILLS, name))
    github = COPILOT_ONLY.sub("", read(os.path.join(GITHUB_SKILLS, name)))
    assert github == claude, (
        "{0} differs between .claude/skills and .github/skills; change both "
        "(only a '**Running as GitHub Copilot:**' paragraph may differ)".format(name)
    )


def referenced_paths(text: str) -> set:
    paths = set(PYTHON_COMMAND.findall(text))
    for span in CODE_SPAN.findall(text):
        span = span.strip().rstrip(".,:;)")
        if "<" in span or "*" in span or " " in span:
            continue
        if REPO_PATH.match(span) or BARE_FILE.match(span):
            paths.add(span)
    return paths


@pytest.mark.parametrize("name", skill_files(GITHUB_SKILLS))
def test_paths_named_in_a_skill_exist(name):
    base = os.path.dirname(os.path.join(GITHUB_SKILLS, name))
    missing = [
        path
        for path in sorted(referenced_paths(read(os.path.join(GITHUB_SKILLS, name))))
        if not os.path.exists(os.path.join(ROOT, path))
        and not os.path.exists(os.path.join(base, path))
        and not glob.glob(os.path.join(ROOT, "**", path), recursive=True)
    ]
    assert not missing, "{0} names files that do not exist: {1}".format(name, ", ".join(missing))


@pytest.mark.parametrize("path", python_files())
def test_tools_and_hooks_never_import_a_database_library(path):
    tree = ast.parse(read(path), filename=path)
    imported = set()
    strings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0].lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0].lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.add(node.value.strip().lower())
    rel = os.path.relpath(path, ROOT)
    assert not imported & DATABASE_MODULES, "{0} imports a database library".format(rel)
    assert not strings & DATABASE_CLIENTS, "{0} runs a database client".format(rel)


def test_requirements_hold_no_database_driver():
    names = set()
    for line in read(os.path.join(ROOT, "requirements.txt")).splitlines():
        line = line.split("#")[0].strip()
        if line:
            names.add(re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0].lower().replace("-", "_"))
    assert not names & DATABASE_MODULES, "requirements.txt lists a database driver"


def test_no_database_connection_package_or_credentials_file_is_left():
    leftovers = [
        "db/__init__.py", "db/config.py", "db/connection.py", "db/env.py", ".env.example",
        "check_oracle.py", "list_procedures.py", "start_dev_services.ps1", "tools/db_export",
    ]
    present = [name for name in leftovers if os.path.exists(os.path.join(ROOT, name))]
    assert not present, "belongs to the removed live-database access: {0}".format(", ".join(present))


@pytest.mark.parametrize("name", [n for n in skill_files(GITHUB_SKILLS) if n.endswith("SKILL.md")])
def test_every_skill_says_a_database_is_never_used(name):
    text = read(os.path.join(GITHUB_SKILLS, name)).lower()
    assert re.search(r"never (?:connect to )?a database|no database|never from a database", text), (
        "{0} must state that no database is ever used".format(name)
    )
