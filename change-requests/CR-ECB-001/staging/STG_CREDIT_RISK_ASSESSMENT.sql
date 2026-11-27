-- ===========================================================================
-- GENERATED for CR-ECB-001 from the delivery agreement RISK_ENGINE_SIM v1.0
--   (change-requests/CR-ECB-001/UBB_Delivery_Agreement_RISK_ENGINE_SIM_v1.0.docx), entity CREDIT_RISK_ASSESSMENT, file RISK_ENGINE_SIM_CREDIT_RISK_ASSESSMENT_YYYYMMDD.csv
--   by tools/codegen/generate_staging.py on 2026-11-27
--   agreement fingerprint a028d77b5c2cb3e7, approved by Emil Angelov on 2026-11-26
--   asked for by change-requests/CR-ECB-001/UBB_Delivery_Agreement_RISK_ENGINE_SIM_v1.0.docx
-- Change the delivery agreement and regenerate - do not hand-edit this file.
-- ===========================================================================
--
-- Creates UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT, which receives the delivered file RISK_ENGINE_SIM_CREDIT_RISK_ASSESSMENT_YYYYMMDD.csv: one
-- column per attribute of the agreement, plus the warehouse columns every
-- staging table has (LOAD_ID first, STAGED_AT last). One partition per load.

CREATE TABLE UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT (
    LOAD_ID                NUMBER(18,0) NOT NULL,
    ASSESSMENT_REF         VARCHAR2(80 CHAR) NOT NULL,
    ASSESSMENT_DATE        DATE,
    PROBABILITY_OF_DEFAULT NUMBER(9,6),
    LOSS_GIVEN_DEFAULT     NUMBER(9,6),
    EXPOSURE_AT_DEFAULT    NUMBER(20,2),
    MODEL_VERSION          VARCHAR2(40 CHAR),
    PARAMETER_VALID_FROM   DATE,
    PARAMETER_VALID_TO     DATE,
    STAGED_AT              TIMESTAMP(6) DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT PK_STG_CREDIT_RISK_ASSESSMENT PRIMARY KEY (LOAD_ID, ASSESSMENT_REF),
    CONSTRAINT FK_STG_CREDIT_RISK_ASSESSMENT_LOAD FOREIGN KEY (LOAD_ID) REFERENCES UBB_CORE2.CTRL_LOAD (LOAD_ID)
)
PARTITION BY LIST (LOAD_ID) AUTOMATIC (PARTITION P_LOAD_0 VALUES (0));

COMMENT ON TABLE UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT IS 'RISK_ENGINE_SIM CREDIT_RISK_ASSESSMENT daily delivery (RISK_ENGINE_SIM_CREDIT_RISK_ASSESSMENT_YYYYMMDD.csv), delivery agreement v1.0; business key ASSESSMENT_REF.';
COMMENT ON COLUMN UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT.ASSESSMENT_REF IS 'Unique identifier for the risk assessment record. Confirm identifier format and uniqueness scope; as the file business key it must not be null.';
COMMENT ON COLUMN UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT.ASSESSMENT_DATE IS 'Effective date of the risk parameter assessment. Confirm whether the assessment date is mandatory for every delivered record.';
COMMENT ON COLUMN UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT.PROBABILITY_OF_DEFAULT IS 'Estimated probability of default over the applicable risk horizon. Confirm numeric scale, allowed range, nullability, and the applicable risk horizon with risk methodology.';
COMMENT ON COLUMN UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT.LOSS_GIVEN_DEFAULT IS 'Estimated proportion of exposure lost conditional on default. Confirm numeric scale, allowed range, and nullability.';
COMMENT ON COLUMN UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT.EXPOSURE_AT_DEFAULT IS 'Estimated exposure amount at the point of default. Confirm the allowed amount range, nullability, and the currency basis with risk methodology; the assessment currency is not scoped as a delivery field.';
COMMENT ON COLUMN UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT.MODEL_VERSION IS 'Identifier of the risk model version used for the assessment. Confirm version format/domain and nullability. With risk methodology, identify the source approval indicator or the governed approved-model registry and join key (IN-21/Q-17). MODEL_VERSION alone is not approval evidence.';
COMMENT ON COLUMN UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT.PARAMETER_VALID_FROM IS 'Start date of risk parameter validity. Confirm whether the validity start date is mandatory.';
COMMENT ON COLUMN UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT.PARAMETER_VALID_TO IS 'End date of risk parameter validity. Confirm whether open-ended validity is permitted and, if so, its representation and nullability.';

GRANT SELECT ON UBB_STAGING2.STG_CREDIT_RISK_ASSESSMENT TO UBB_CORE2;
