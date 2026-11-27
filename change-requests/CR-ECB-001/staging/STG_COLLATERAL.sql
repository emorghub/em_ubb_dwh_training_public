-- ===========================================================================
-- GENERATED for CR-ECB-001 from the delivery agreement CBS_SIM v1.1
--   (change-requests/CR-ECB-001/UBB_Delivery_Agreement_CBS_SIM_v1.1.docx), entity COLLATERAL, file CBS_SIM_COLLATERAL_YYYYMMDD.csv
--   by tools/codegen/generate_staging.py on 2026-11-27
--   agreement fingerprint c649ec5248294414, approved by Emil Angelov on 2026-11-26
--   asked for by change-requests/CR-ECB-001/UBB_Delivery_Agreement_CBS_SIM_v1.1.docx
-- Change the delivery agreement and regenerate - do not hand-edit this file.
-- ===========================================================================
--
-- Brings the existing UBB_STAGING2.STG_COLLATERAL in line with the agreement. Written by
-- comparing the agreement with the table script in sql/ on 2026-11-27.
-- New columns are nullable: the rows already loaded have no value for them.

ALTER TABLE UBB_STAGING2.STG_COLLATERAL ADD (
    VALUATION_CURRENCY_CODE VARCHAR2(3 CHAR),
    ELIGIBILITY_FLAG        CHAR(1 CHAR),
    ELIGIBILITY_REASON_CODE VARCHAR2(30 CHAR),
    REGULATORY_HAIRCUT_PCT  NUMBER(9,6)
);
COMMENT ON COLUMN UBB_STAGING2.STG_COLLATERAL.VALUATION_CURRENCY_CODE IS 'Currency of the latest collateral valuation. Confirm the allowed ISO currency-code domain and nullability, including when no valuation is present.';
COMMENT ON COLUMN UBB_STAGING2.STG_COLLATERAL.ELIGIBILITY_FLAG IS 'Whether collateral meets internal eligibility criteria. Confirm all allowed values other than Y (eligible, per Q-06), their meanings, and nullability.';
COMMENT ON COLUMN UBB_STAGING2.STG_COLLATERAL.ELIGIBILITY_REASON_CODE IS 'Reason for collateral eligibility determination. Confirm the reason-code list and when a reason is mandatory or may be null.';
COMMENT ON COLUMN UBB_STAGING2.STG_COLLATERAL.REGULATORY_HAIRCUT_PCT IS 'Haircut percentage applicable to recognized collateral value. Confirm the numeric scale (fraction or percentage points), permitted range, and nullability.';
