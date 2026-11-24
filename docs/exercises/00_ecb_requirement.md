## 1.
 /ba-1-analyse-requirement PASTE THE ECB REQ
## 2.
/ba-1-analyse-requirement CR-ECB-001

Change the existing requirements. I am the business for this dry run and answer
every open question below. Record each answer, set Decided_By = <your name>,
Decided_On = 2026-11-17, Status = decided, and update the affected KPIs, rules and
dimensions so no TODO is left. Do not ask further questions unless an answer
contradicts the CR. Mark rules that come from these answers as interpretation.

Q-01 Gross exposure = outstanding principal + overdue amount + undrawn amount x CCF
     (CCF from CBS_SIM; missing CCF = 100%). EAD for expected loss = this gross exposure.
Q-02 Eligible = eligibility flag 'Y'. A valuation older than 365 days at the
     reporting date, or missing, is not recognised (value 0) and logged as an
     exception; the loan is still reported.
Q-03 Allocation share = the allocation % valid at the reporting date. If the shares
     of one collateral item add up to more than 100%, that item is not recognised
     and is logged.
Q-04 Order: convert to EUR, apply haircut, apply allocation share, sum per loan,
     cap at the loan's gross exposure.
Q-05 Reporting currency EUR. FX rate from FX_SIM, valid on the reporting date.
     Missing rate: the load fails, no snapshot is written.
Q-06 Missing or ambiguous borrower reference: the load fails, no partial snapshot;
     log the loan reference and the reason.
Q-07 Simplified Expected Loss = PD x LGD x EAD, approved for this training measure
     only. PD and LGD from RISK_ENGINE_SIM, valid on the reporting date. A missing
     parameter: the load fails, no partial snapshot.
Q-08 Every input is taken as valid on the reporting date. A reported snapshot is
     never changed afterwards.
Q-09 KPI grain: loan x reporting date. Dimensions are attached as valid on the
     reporting date. Collateral category: Eligible Allocated Collateral Value is
     also kept per loan x collateral item, so it can be split by category.
Q-10 Economic sector = NACE Rev. 2 section from CRM_SIM, valid on the reporting date.
Q-11 Connected-client group = the group reference from CRM_SIM, membership valid
     on the reporting date; group totals are the sum over its borrowers.
Q-12 2 decimals, round half up, only on the final stored value. All three KPIs
     add up across loans, borrowers, sectors and groups.
Q-13 Per loan: Eligible Allocated Collateral Value + Net Unsecured Exposure =
     gross exposure. Totals per reporting date equal the sum of the loan
     positions. Tolerance 0.01 EUR.
Q-14 Errors are written to the job log with reporting date, loan reference,
     missing input and reason; the whole load is rolled back.