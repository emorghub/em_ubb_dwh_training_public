# How the `/dev-2-implement-mapping` skill works

A short, plain-language explanation (about a 5 minute read) of what happens
when a developer types `/dev-2-implement-mapping <MAPPING_ID>` in the AI assistant,
and which small programs the assistant runs along the way.

## What the skill is for

`/ba-4-create-mapping-spec` ends with an Excel file that a person has approved. This
skill is the next step: it turns that approved Excel file into the database
code that actually moves the data. It produces three kinds of files:

- the **table script**: the SQL that creates the target table, or changes it if
  it already exists;
- the **load package**: the PL/SQL procedure that reads the source tables and
  fills the target table;
- the **tests**: automatic checks, written for utPLSQL (a testing tool for
  Oracle), that prove the load does what the Excel file says.

The assistant does not write this code by hand. A program creates it from the
Excel file, so the same file always gives the same code. The assistant's job
is to check that the Excel file still holds, run the program, write realistic
test data, and review the result. **It never installs anything in the
database.** The developer reviews the files and installs them by hand.

The checklist the assistant follows is in
[.claude/skills/dev-2-implement-mapping/SKILL.md](../.claude/skills/dev-2-implement-mapping/SKILL.md).

## The six steps

### Step 1 - Is the mapping ready?

The assistant first checks that the Excel file exists, is **approved** by a
person, and is filled in correctly:

- `python tools/mapping_spec/validate_spec.py status` - lists all mappings
  with their state and target table. Checked: the mapping exists and is
  `approved`, and who approved it.
- `python tools/mapping_spec/validate_spec.py validate` - checks all Excel
  files in the mapping folders `specs/*/` (it takes no file name) for required
  fields, allowed values, and file and folder name matching the mapping ID. The required fields
  are listed in `tools/mapping_spec/mapping_validation.py`. Checked: this
  mapping has no errors.
- `python tools/mapping_spec/mapping_workbook.py show <MAPPING_ID>` - opens
  the Excel file for that mapping ID and prints all its sheets as plain text.
  Nothing is checked; the assistant reads the full mapping it will build the
  code from.

If the mapping is not approved, the assistant stops and says who must approve
it. It never approves it itself and never changes the Excel file. Two guards
make sure of this even if the assistant tried: the code program refuses to run
for an unapproved mapping, and a guard in Claude Code (a "hook", a small
script that runs before every file change),
[.claude/hooks/sql_gate.py](../.claude/hooks/sql_gate.py), blocks writing code
files for it. GitHub Copilot runs its own identical copy,
[.github/hooks/sql_gate.py](../.github/hooks/sql_gate.py), from
[.github/hooks/sql_gate.json](../.github/hooks/sql_gate.json).

### Step 2 - Check it again against the real tables

The analyst already checked the mapping, but the table definitions in `sql/`
may have been copied out of the database again since then. So the assistant
checks once more, with the same program the analyst used:

```
python tools/codegen/verify_mapping.py <MAPPING_ID>
```

It confirms that every source table and column still exists, that values fit
their target columns, that joins cannot create duplicate rows, and that no
other procedure already fills the same target table. The assistant also looks
through the existing mappings for one that loads the same table.

If anything fails, the assistant **stops** and sends the mapping back to the
analyst. A developer never quietly "fixes" an approved mapping: any change
needs a new approval anyway.

### Step 3 - Create the code

```
python tools/codegen/generate.py <MAPPING_ID>
```

This writes the files into the mapping's own folder, next to the Excel file
(for example `specs/limit_monitor_daily/`):

| File | What it is |
|---|---|
| `<TABLE>.sql` | creates the target table, with its key and column descriptions |
| `<TABLE>_LOAD_LOG.sql` | only for a history (`scd2`) load: a small table listing every date loaded, so a late date can rebuild the history after it |
| `<MAPPING_ID>.sql` | only if the table already exists: the changes to make to it |
| `<PACKAGE>.sql` | the load procedure |
| `UT_<TABLE>.sql` | one automatic test per acceptance criterion in the Excel file |
| `UT_<TABLE>_DATA.sql` | the test data, a starting point the assistant completes in Step 4 |

The wording of the SQL comes from templates (fill-in-the-blanks text files) in
[tools/codegen/templates/](../tools/codegen/templates/). A team that wants
another coding style changes the templates once, not every generated file.

Changes that could lose data, such as making a column shorter, are never done
automatically. They are listed in a **MANUAL DECISIONS** block for the
developer to decide.

If the generated code is wrong, it is never edited by hand, because the next
run would overwrite the edit. The fix goes into the Excel file (back to the
analyst) or into a template (a deliberate team decision).

### Step 4 - Write realistic test data

The test data file is the only file the assistant edits by hand. The program
gives it a simple starting point; the assistant makes it realistic:

- it uses test dates far in the past (for example 1 January 2000), so the
  tests never mix with real data;
- it uses real-looking values that the table definitions allow (for example,
  partner type `PERSON` or `COMPANY`), with test IDs starting with `UT` so they
  can never clash with real ones;
- it adds rows for the tricky cases: a row the filter must skip, a row with no
  match in a joined table, and data that each business check would catch if
  the load were wrong. A test that can never fail proves nothing.

It never looks at the database to pick values.

### Step 5 - Review

The assistant walks through a fixed review checklist
([review-checklist.md](../.claude/skills/dev-2-implement-mapping/references/review-checklist.md)),
comparing the code with the Excel file line by line. For example: is every
column there with the right type, is the key correct, does the load use the
right joins and filter, and is there no `COMMIT` in the procedure (the caller
decides when to save, which also lets the tests undo their own changes).

Then a final check:

```
python tools/codegen/generate.py <MAPPING_ID> --check
```

Every generated file carries a **fingerprint**, a short code calculated from
the Excel file's content. This check confirms that the code still matches the
approved Excel file exactly, and that the test data has no unfinished `TODO`
left.

### Step 6 - Hand over and stop

The assistant gives the developer:

1. the results of the checks, and every manual decision;
2. the database permissions (grants) the load needs, for example read access
   to the source tables;
3. the order to install the files: table (or change) script, load package,
   test data, tests;
4. how to run the tests and the load by hand, in SQL Developer or SQL*Plus;
5. a reminder to copy the new table and package definitions into `sql/`
   once the new table is installed and its definition is copied into `sql/`.

Then it **stops**. It does not install anything, run SQL, or connect to the
database, even if asked. Installing the code is always the developer's job,
after they have reviewed the files.
