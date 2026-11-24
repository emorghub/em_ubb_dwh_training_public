# Exercises: from a business request to tested code

Each exercise is a realistic request that a business analyst receives as
plain text. The analyst pastes it into `/ba-4-create-mapping-spec`, answers the
interview, and a named person approves the workbook in Excel. The developer
then runs `/dev-2-implement-mapping` on the approved workbook.

| # | Request | New core table | Sources | Runs today? |
|---|---|---|---|---|
| 1 | [Credit limit utilisation](01_limit_utilisation.md) | `UBB_CORE2.LIMIT_UTILISATION_HIST` | `UBB_CORE2.LIMIT_HIST`, `CTRL_LOAD`, `CREDIT_LIMIT`, `PARTNER_HIST` | Yes |
| 2 | [Overdue loan watch list](02_overdue_loan_watchlist.md) | `UBB_CORE2.LOAN_OVERDUE_WATCH_HIST` | `STG_LOAN`, `STG_PARTNER`, `UBB_CORE2.FX_RATE` | No, see below |

`later/` holds exercises that need tool or `sql/` changes first; each one
says what is missing at the top.

Every exercise file has two parts:

1. **The request** - the text exactly as the analyst receives it. Paste only
   this part into the chat.
2. **Notes for the person running the session** - what the assistant should
   find on its own, the traps it should catch, and suggested answers for the
   interview questions it cannot answer from the `sql/` folder. Do not paste
   this part; it is the trainer's answer sheet.

## Before you run an exercise

Exercise 1 reads only core tables that have a full table script in
`sql/UBB_CORE2.schema/`, and it stays within what the code generator
supports (one driving table, each other table joined once, no `GROUP BY`).
Its expected answer was run through the workbook writer, `verify_mapping.py`
and the generator before it was published.

The staging schema now has exported `CREATE TABLE` scripts in
`sql/UBB_Staging2.schema/`. Use those scripts as the source of truth for
staging column names, types, and nullability.

The remaining generator limitation is that loans and partners come from
separate loads, so this exercise needs `CTRL_LOAD` joined twice. The current
code generator does not support that pattern.
