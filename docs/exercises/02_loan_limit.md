# Exercise 3: Loans with their credit limit (the easy one)

The simplest exercise: two staging feeds from the same source system, one
lookup join, no sums, no currency conversion, no partner history. Start here
to show the workflow before moving to exercises 1 and 2.

## The request

> **From:** Credit Operations
> **Subject:** See each loan together with its credit limit
>
> Hi,
>
> When we check a loan, we always have to look up the credit limit it is
> booked under in a second report. We would like one daily table that shows
> each loan together with its limit.
>
> Both come from the core banking system: loans from `STG_LOAN` and limits
> from `STG_LIMIT`.
>
> What we would like to see:
>
> - The main loan details (reference, type, status, currency, principal).
> - The limit the loan belongs to, with its main details (reference, type,
>   status, approved amount).
> - Whether the loan has a limit at all.
> - How big the loan is compared to its limit.
>
> Rules:
>
> - One row per loan per day.
> - The "has a limit" indicator must always be filled.
> - Amounts can never be negative.
>
> Thanks,
> Credit Operations
