-- ===========================================================================
-- GENERATED for CR-ECB-001 from the delivery agreement CRM_SIM v1.1
--   (change-requests/CR-ECB-001/UBB_Delivery_Agreement_CRM_SIM_v1.1.docx), entity PARTNER, file CRM_SIM_PARTNER_YYYYMMDD.csv
--   by tools/codegen/generate_staging.py on 2026-11-27
--   agreement fingerprint 871d4214328dedaf, approved by Emil Angelov on 2026-11-26
--   asked for by change-requests/CR-ECB-001/UBB_Delivery_Agreement_CRM_SIM_v1.1.docx
-- Change the delivery agreement and regenerate - do not hand-edit this file.
-- ===========================================================================
--
-- Brings the existing UBB_STAGING2.STG_PARTNER in line with the agreement. Written by
-- comparing the agreement with the table script in sql/ on 2026-11-27.
-- New columns are nullable: the rows already loaded have no value for them.

ALTER TABLE UBB_STAGING2.STG_PARTNER ADD (
    INDUSTRY_NACE_CODE         VARCHAR2(8 CHAR),
    CONNECTED_CLIENT_GROUP_REF VARCHAR2(80 CHAR)
);
COMMENT ON COLUMN UBB_STAGING2.STG_PARTNER.INDUSTRY_NACE_CODE IS 'Economic activity classification of the partner. Confirm the NACE revision, delivered code format/domain, and nullability.';
COMMENT ON COLUMN UBB_STAGING2.STG_PARTNER.CONNECTED_CLIENT_GROUP_REF IS 'Identifier of connected-client group for concentration reporting. Confirm the identifier namespace/format and how no group membership is represented, including whether NULL is allowed.';
