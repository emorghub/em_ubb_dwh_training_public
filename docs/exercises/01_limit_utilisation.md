# Exercise 1: Credit limit utilisation

## The request

> **From:** Credit Risk Monitoring
> **Subject:** New daily table - how much of each credit limit is used
>
> Hi,
>
> We need a new daily table that shows, for every credit limit, how much of
> it is used and whether the limit is breached.
>
> The limits are already loaded into core every day from the core banking
> system (`LIMIT_HIST`), including the utilised amount CBS reports. We want
> that figure turned into something we can monitor, next to who the limit
> belongs to.
>
> What we would like to see per limit:
>
> - The main limit details (reference, type, status, currency, approved
>   amount) and the utilised amount CBS reports.
> - The headroom and the utilisation in percent.
> - A breach flag.
> - Who the limit belongs to: partner name, segment and risk rating. We
>   already have this in core (`PARTNER_HIST`).
>
> Rules:
>
> - One line per limit per day, no duplicates.
> - Amounts can never be negative.
> - The breach flag must always be filled.
> - We probably only need active limits.
>
> Later we also want to calculate the drawn amount ourselves from the loans
> and compare it with the CBS figure, but that is not part of this request.
>
> Thanks,
> Credit Risk Monitoring
