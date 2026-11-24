# Exercise: Loan contract terms history (SCD2)

This exercise asks a trainee to turn a business request into a mapping
workbook with `/ba-4-create-mapping-spec`. The target is a new SCD2 table in
`UBB_CORE2`. SCD2 means a new row is added only when something changes, and
each row carries a "valid from / valid to" period.


---

## The business request

> **From:** Credit Restructuring & Workout department
> **Subject:** Request for a history of loan contract terms
>
> Hi DWH team,
>
> We are the team that handles loans in difficulty: restructurings, maturity
> extensions, interest rate reductions and status changes. Every quarter we
> report which loans were "forborne" (their terms were changed because the
> borrower was struggling), and we also have to show auditors what the terms
> were *before* and *after* each change.
>
> Today we do this by comparing the daily loan snapshots in the warehouse.
> That is painful. A loan's balance changes every day, so every snapshot
> looks different, and we have to dig through hundreds of rows per loan to
> find the one day the maturity date or the interest rate actually changed.
>
> **What we need:** a table that keeps the history of each loan's
> **contract terms**. A new version should appear only when one of the terms
> below actually changes. Days with no change in terms should not create a
> new row. Each version should say from which date it was valid, until which
> date, and whether it is the current one.
>
> **The terms we want to track** (any change in one of these is a new
> version):
>
> - Loan type
> - Loan status (for example, when a loan becomes restructured or defaulted)
> - Currency of the loan
> - Interest rate
> - Start date
> - Maturity date
> - The borrower (sometimes a loan is taken over by another customer, and we
>   must see that)
> - The credit limit the loan is booked under, as the core banking system
>   gives it
>
> **What we also need on every row:**
>
> - The loan's internal warehouse identifier and the loan reference from the
>   core banking system, so we can find it in both places
> - The borrower's internal warehouse identifier (not just the core-banking
>   reference), so we can link it to the customer data you already keep
> - Valid from, valid to, and a "current version" flag
> - Which daily load created the version, for audit
>
> **What we do NOT want:** principal, undrawn amount and overdue amount.
> Those change daily and would create a new version every day. We get them
> from the daily snapshot already.
>
> **Examples of what we expect:**
>
> 1. Loan L-1001 has its maturity extended from 2027-06-30 to 2028-06-30 on
>    business date 2026-03-15. We expect two versions: the old one valid
>    until 2026-03-15, and a new current one valid from 2026-03-15.
> 2. Loan L-1002 repays a bit of principal every day but nothing else
>    changes. We expect exactly one version.
> 3. Running the same day twice must not create duplicate versions.
>
> **Open points we'd like your help on:**
>
> - What should happen when a loan disappears from the daily file (repaid or
>   written off)? We think the last version should be closed, but we are
>   open to your advice.
> - The history only needs to start from the day the table goes live. We
>   don't need it rebuilt from the past.
> - We need it loaded daily, after the normal loan load.
>
> Thanks,
> Credit Restructuring & Workout

---

## Trainer notes (spoilers)

### Why this table

The request needs one staging table and two core tables:

| Role | Table | What it gives |
|---|---|---|
| Staging (the starting table) | `UBB_STAGING2.STG_LOAN` | The daily loan file from the core banking system: type, status, currency, interest rate, start and maturity date, borrower reference, limit reference |
| Core 1 | `UBB_CORE2.LOAN` | Turns `LOAN_REF` into the internal `LOAN_ID` |
| Core 2 | `UBB_CORE2.PARTNER_HIST` | Turns `CBS_PARTNER_REF` into the borrower's `PARTNER_ID`, using the partner version that was valid on the business date |

The existing load [PKG_ETL_LOAN_1.sql](sql/UBB_CORE2.schema/PKG_ETL_LOAN_1.sql)
already uses these same joins, so the trainee has a real example to
research.

Why it is clearly missing:

- `PARTNER_HIST` is the only SCD2 table in core. Its load,
  [PKG_ETL_PARTNER_1.sql](sql/UBB_CORE2.schema/PKG_ETL_PARTNER_1.sql), is
  the pattern to learn from.
- Loans exist only as `LOAN_HIST`, which stores a full copy of every loan
  every day. Balances change every day in that table, so you can't easily
  answer "when was this loan's maturity extended?" or "what was the interest
  rate before the restructuring?".
- Banks need exactly this to report forbearance, so the business reason is
  real.
- No mapping in `specs/mappings/` covers it. The existing mappings are
  about limits.

### What a good run should catch

1. **The tooling cannot express SCD2 yet. This is the biggest one.** The
   workbook only allows `Load_Strategy` values `full`, `delete_insert`,
   `merge` and `append`, and `SCD_Type` only allows `0` or `1` (see
   [workbook_format.py](tools/mapping_spec/workbook_format.py)).
   [generate.py](tools/codegen/generate.py) has no SCD2 template. A correct
   `/ba-4-create-mapping-spec` run should notice this, say so clearly and stop
   short of approval. It should not quietly downgrade the request to a
   `merge`. Taking the exercise all the way to generated code needs the
   tooling extended first, which makes a good follow-up exercise.
2. **LOAN is filled by another load.** `UBB_CORE2.LOAN` gets its rows from
   `UBB_CORE2.PKG_ETL_LOAN.LOAD_DAY`, so that load must run first. The
   request hints at this with "after the normal loan load". It belongs in
   `Preconditions`.
3. **Borrower lookup by validity date.** `PARTNER_HIST` must be joined on
   `CBS_PARTNER_REF` *and* the validity period
   (`VALID_FROM <= business date < VALID_TO`). The existing packages also
   join `PARTNER` to keep only `SOURCE_SYSTEM = 'CRM_SIM'`. Does the trainee
   notice this and decide whether it is needed? Also: what if no partner, or
   more than one, matches? The existing loads fail the run in that case.
4. **What happens when the borrower or currency is missing?**
   `STG_LOAN.CBS_PARTNER_REF` and `STG_LOAN.CURRENCY_CODE` are both nullable
   in the file. Does the run fail, keep the row with an empty value, or drop
   it? This should become an interview question, not a guess.
5. **"Why not build it from LOAN_HIST?"** `LOAN_HIST` already has the same
   terms plus `PARTNER_ID` and `LIMIT_ID`. A sharp analyst may propose
   building from core only. Both are defensible, so it makes a good design
   discussion.
6. **Comparing values when some are empty.** A change check written as
   `a <> b` misses changes from or to an empty value, because in SQL a
   comparison with NULL is never true. `PKG_ETL_PARTNER` uses
   `DECODE(a, b, 0, 1)` for exactly this reason.
7. **Same-day reruns and loading out of order.** Example 3 in the request
   asks for safe reruns. `PKG_ETL_PARTNER` also refuses to load a date
   earlier than versions that already exist (no backfill). The mapping
   should state the same rules.
8. **The disappearing-loan question** is left open on purpose, to test
   whether the skill asks about it instead of guessing.
9. **Which columns trigger a new version.** The request lists them
   explicitly and excludes the daily balances. Check that the mapping does
   not track principal, undrawn or overdue amount, and that the audit column
   (the load that created the version) does not trigger a new version on its
   own.
