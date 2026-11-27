-- ===========================================================================
-- GENERATED from mapping M_COLLATERAL (specs/collateral/M_COLLATERAL.xlsx)
--   by tools/codegen/generate.py on 2026-11-27
--   mapping fingerprint 35a96c007d483467, approved by Emil Angelov on 2026-11-27
-- Change the mapping workbook and regenerate - do not hand-edit this file.
-- ===========================================================================
--
-- Creates UBB_CORE2.COLLATERAL_HIST as the mapping describes it: one column per row of the
-- workbook's Columns sheet, in that order, primary key = Business_Key.
-- This is the full, current definition of the table. For a table that already
-- exists, deploy the change script <MAPPING_ID>.sql instead of this one.

CREATE TABLE UBB_CORE2.COLLATERAL_HIST (
    COLLATERAL_ID           NUMBER(18,0) NOT NULL,
    LOAD_ID                 NUMBER(18,0) NOT NULL,
    LOAN_ID                 NUMBER(18,0),
    COLLATERAL_TYPE         VARCHAR2(30 CHAR),
    COLLATERAL_STATUS       VARCHAR2(20 CHAR),
    CURRENCY_CODE           CHAR(3 CHAR) NOT NULL,
    MARKET_VALUE_AMT        NUMBER(20,2),
    ELIGIBLE_VALUE_AMT      NUMBER(20,2),
    VALUATION_DATE          DATE,
    CREATED_AT              TIMESTAMP(6) NOT NULL,
    VALUATION_CURRENCY_CODE VARCHAR2(3 CHAR),
    ELIGIBILITY_FLAG        CHAR(1 CHAR),
    ELIGIBILITY_REASON_CODE VARCHAR2(30 CHAR),
    REGULATORY_HAIRCUT_PCT  NUMBER(9,6),
    CONSTRAINT PK_COLLATERAL_HIST PRIMARY KEY (COLLATERAL_ID, LOAD_ID)
);

COMMENT ON TABLE UBB_CORE2.COLLATERAL_HIST IS 'Full daily collateral snapshot: one row per collateral item per source load; the reporting date is the business date of the load in CTRL_LOAD.';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.COLLATERAL_ID IS 'Collateral identifier: Warehouse identifier of the collateral item.';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.LOAD_ID IS 'Source load identifier: Identifier of the daily CBS collateral extract; links to the reporting date in the load register.';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.LOAN_ID IS 'Direct loan link (not used): Not loaded. Q-16: the authoritative loan relationship is LOAN_COLLATERAL_REL_HIST.';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.COLLATERAL_TYPE IS 'Collateral type: Category of the collateral item (collateral category, DIM-07).';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.COLLATERAL_STATUS IS 'Collateral status: Status of the collateral item in the extract.';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.CURRENCY_CODE IS 'Collateral currency: ISO currency code delivered with the collateral.';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.MARKET_VALUE_AMT IS 'Market value: Valuation amount used as the unadjusted collateral value (Q-14).';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.ELIGIBLE_VALUE_AMT IS 'Eligible value (as delivered): Eligible value delivered by the source; not used by the KPI (Q-14).';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.VALUATION_DATE IS 'Valuation date: Date of the valuation.';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.CREATED_AT IS 'Snapshot creation time: Warehouse timestamp when the row was written.';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.VALUATION_CURRENCY_CODE IS 'Valuation currency: Currency of the latest valuation (IN-11); the currency the market value is converted from.';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.ELIGIBILITY_FLAG IS 'Eligibility flag: Y if the source decided the item is eligible as protection (Q-06).';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.ELIGIBILITY_REASON_CODE IS 'Eligibility reason: Reason code of the source eligibility decision.';
COMMENT ON COLUMN UBB_CORE2.COLLATERAL_HIST.REGULATORY_HAIRCUT_PCT IS 'Regulatory haircut (%): Haircut applicable to the item, as delivered; one haircut per item (Q-04).';
