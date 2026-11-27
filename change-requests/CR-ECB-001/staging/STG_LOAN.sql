-- ===========================================================================
-- GENERATED for CR-ECB-001 from the delivery agreement CBS_SIM v1.1
--   (change-requests/CR-ECB-001/UBB_Delivery_Agreement_CBS_SIM_v1.1.docx), entity LOAN, file CBS_SIM_LOAN_YYYYMMDD.csv
--   by tools/codegen/generate_staging.py on 2026-11-27
--   agreement fingerprint c649ec5248294414, approved by Emil Angelov on 2026-11-26
--   asked for by change-requests/CR-ECB-001/UBB_Delivery_Agreement_CBS_SIM_v1.1.docx
-- Change the delivery agreement and regenerate - do not hand-edit this file.
-- ===========================================================================
--
-- Brings the existing UBB_STAGING2.STG_LOAN in line with the agreement. Written by
-- comparing the agreement with the table script in sql/ on 2026-11-27.
-- New columns are nullable: the rows already loaded have no value for them.

ALTER TABLE UBB_STAGING2.STG_LOAN ADD (
    CREDIT_CONVERSION_FACTOR NUMBER(9,6)
);
COMMENT ON COLUMN UBB_STAGING2.STG_LOAN.CREDIT_CONVERSION_FACTOR IS 'Factor used for converting undrawn commitments to an exposure equivalent. Confirm the numeric scale (fraction or percentage points), permitted range, and nullability.';
