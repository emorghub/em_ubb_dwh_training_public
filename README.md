# UBB DWH training

Welcome. This folder is a small, simulated bank data warehouse for a bank
called UBB. You use it to try out how an AI assistant (Claude Code or GitHub
Copilot) helps business analysts and developers with their daily work: from
a change request written by the business, all the way to tested database
code.

You do not need a database. Everything the assistant needs to know about the
database is stored as files in this folder.

## What you will do with it

A **change request** is a document in which the business asks for something
new, for example a new risk report. You take one change request through six
steps. In each step you type a command (a "skill") in the assistant, it does
the work together with you, and writes a document. A person (you, in the
workshop) reviews and approves that document in Excel or Word before the next
step can start.

| Step | Command | Who | What comes out |
|---|---|---|---|
| 1 | `/ba-1-analyse-requirement` | analyst | The requirements, as an Excel workbook |
| 2 | `/ba-2-analyse-data-gaps` | analyst | For every piece of data needed: where it comes from, or that it is missing; plus the load plan |
| 3 | `/ba-3-specify-baseline-changes` | analyst | New versions of the delivery agreements (what a source system must deliver) and the business glossary, as Word and Excel |
| 4 | `/ba-4-create-mapping-spec` | analyst | One mapping workbook per target table: which source column goes into which target column, and how |
| 5 | `/dev-1-implement-staging-change` | developer | SQL scripts for the new staging columns and tables |
| 6 | `/dev-2-implement-mapping` | developer | SQL for the target table, the PL/SQL load package and its automated tests |
| 7 | `/dev-3-prepare-deployment` | developer | A deployment runbook, read-only preflight scripts and a deployment package (zip) for deploying from another machine |

The assistant never approves a document and never deploys code. Those are
always a person's decisions.

The full process, with what each step reads and writes:
[docs/WORKFLOW.md](docs/WORKFLOW.md).

## Install

You need:

- **Python 3** (we test with 3.14). On Windows, tick "Add python.exe to PATH"
  in the installer, so that the command `python` works in a terminal.
- **VS Code** with the **Claude Code** extension (or GitHub Copilot).
- **Excel and Word**, to read and approve the documents.

Then:

1. **Unzip** the folder to a short local path, for example `C:\workshop\`.
   Avoid folders synced by OneDrive (such as Desktop or Documents): syncing
   can lock the Excel files while the tools write them.
2. In VS Code, choose **File > Open Folder** and select the
   `ubb_dwh_training` folder itself, the one that contains this `README.md`
   and `CLAUDE.md`. If you open a folder above it, the assistant does not
   find the six commands.
3. When VS Code asks whether you trust the authors, choose **Yes**.
4. Open a terminal (**Terminal > New Terminal**) and run:

```bash
pip install -r requirements.txt            # the three Python libraries the tools need
python -m pytest -q                        # all tests pass: your setup works
python tools/change_request/cr.py status   # on a fresh copy: "No change requests yet"
```

If all three run without errors, you are ready. Open the Claude Code panel
and type `/ba-1-analyse-requirement` to start.

## What is in which folder

| Folder | What you find there |
|---|---|
| `business-documents/` | The bank's existing, approved documents: the change request you work on (`UBB_CR_ECB_001_...docx`), the business glossary (the agreed meaning of every business term), the delivery agreements (what each source system delivers), the catalog of source systems and their data, and the existing source-to-target overview. These are never changed; a change is always a new version in your change request's folder. |
| `change-requests/` | Created when you start step 1. One folder per change request (for example `change-requests/CR-ECB-001/`) holding everything you produce in steps 1 to 3 and 5: the requirements, the gap analysis, the new document versions and the staging SQL. |
| `specs/` | Created in step 4. One folder per target table (for example `specs/loan_hist/`) holding its mapping workbook and, after step 6, the SQL generated from it. |
| `sql/` | The database, as files: the scripts that create every table and package, exported from the bank's Oracle database. This is the assistant's only source for table and column names. Two schemas: `UBB_Staging2` (data as delivered by the source systems) and `UBB_CORE2` (the cleaned-up core tables). See [sql/README.md](sql/README.md). |
| `docs/` | Explanations: [WORKFLOW.md](docs/WORKFLOW.md) (the process), [skills-overview.md](docs/skills-overview.md) (the six commands), detailed explanations of steps 4 and 6, diagrams, and [TEST_PLAN.md](docs/TEST_PLAN.md) (how to test the whole process). |
| `docs/exercises/` | The workshop exercises. |
| `tools/` | The Python programs the assistant calls: they read the `sql/` scripts, write and check the Excel and Word documents, and generate the SQL code. You do not need to run them yourself. |
| `tests/` | Automated tests of the tools (`python -m pytest -q`). |
| `.claude/` | The six commands for Claude Code (`skills/`), and a safety check (`hooks/`) that stops the assistant from changing SQL that has not been approved. |
| `.github/` | The same six commands and safety check for GitHub Copilot. |
| `CLAUDE.md`, `AGENT_BRIEFING.md` | The rules and background the assistant reads before it starts. Worth a look if you want to see how the assistant is guided. |

## If something does not work

- **`python` is not found:** Python is not on the PATH. Reinstall it with the
  "Add python.exe to PATH" box ticked, then open a new terminal.
- **`pip install` fails with a network error:** your company network may
  block it. Ask the trainer for the offline package folder.
- **The `/ba-...` commands do not appear:** VS Code has the wrong folder open.
  See step 2 of the install.

## For maintainers

Checks to run after changing the tools, skills or mappings:

```bash
python -m pytest -q
python tools/mapping_spec/validate_spec.py validate
python tools/change_request/cr.py validate
```
