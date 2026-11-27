-- ===========================================================================
-- GENERATED from mapping M_COLLATERAL (specs/collateral/M_COLLATERAL.xlsx)
--   by tools/codegen/generate.py on 2026-11-27
--   mapping fingerprint 35a96c007d483467, approved by Emil Angelov on 2026-11-27
-- Change the mapping workbook and regenerate - do not hand-edit this file.
-- ===========================================================================
--
-- Brings the existing UBB_CORE2.COLLATERAL_HIST in line with the mapping. Written by comparing
-- the mapping with the table script in sql/ on 2026-11-27; deploy it instead of
-- COLLATERAL_HIST.sql, which holds the full definition.
-- Only safe, additive changes are executed. Anything that could lose data or
-- fail on existing rows is listed at the bottom for a person to decide.

ALTER TABLE UBB_CORE2.COLLATERAL_HIST ADD (
    VALUATION_CURRENCY_CODE VARCHAR2(3 CHAR),
    ELIGIBILITY_FLAG        CHAR(1 CHAR),
    ELIGIBILITY_REASON_CODE VARCHAR2(30 CHAR),
    REGULATORY_HAIRCUT_PCT  NUMBER(9,6)
);
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.VALUATION_CURRENCY_CODE IS 'Valuation currency: Currency of the latest valuation (IN-11); the currency the market value is converted from.';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.ELIGIBILITY_FLAG IS 'Eligibility flag: Y if the source decided the item is eligible as protection (Q-06).';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.ELIGIBILITY_REASON_CODE IS 'Eligibility reason: Reason code of the source eligibility decision.';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.REGULATORY_HAIRCUT_PCT IS 'Regulatory haircut (%): Haircut applicable to the item, as delivered; one haircut per item (Q-04).';
