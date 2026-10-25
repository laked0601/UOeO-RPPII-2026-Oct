DROP PROCEDURE IF EXISTS ProcessCompanyStaging;
 
ALTER TABLE company_nature_of_business DROP FOREIGN KEY fk_nob_company;
ALTER TABLE filing_history             DROP FOREIGN KEY fk_filing_company;
 
ALTER TABLE companies
    DROP PRIMARY KEY,
    ADD COLUMN id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    ADD UNIQUE KEY uq_companies_company_number (company_number);

ALTER TABLE company_nature_of_business
    ADD COLUMN company_id BIGINT NULL FIRST;
 
UPDATE company_nature_of_business cnb
INNER JOIN companies c ON c.company_number = cnb.company_number
SET cnb.company_id = c.id;
 
ALTER TABLE company_nature_of_business
    DROP PRIMARY KEY,
    DROP COLUMN company_number,
    MODIFY COLUMN company_id BIGINT NOT NULL,
    ADD PRIMARY KEY (company_id, sic_code);
 
ALTER TABLE company_nature_of_business
    ADD CONSTRAINT fk_nob_company
        FOREIGN KEY (company_id) REFERENCES companies (id);
 
ALTER TABLE filing_history
    ADD COLUMN company_id BIGINT NULL AFTER created_at;
 
UPDATE filing_history fh
INNER JOIN companies c ON c.company_number = fh.company_number
SET fh.company_id = c.id;
 
ALTER TABLE filing_history
    DROP COLUMN company_number,
    MODIFY COLUMN company_id BIGINT NOT NULL;
 
ALTER TABLE filing_history
    ADD CONSTRAINT fk_filing_company
        FOREIGN KEY (company_id) REFERENCES companies (id);


ALTER TABLE companies
    MODIFY COLUMN company_number VARCHAR(15) NOT NULL;

ALTER TABLE companies_staging
    MODIFY COLUMN company_number VARCHAR(15) NOT NULL,
    ADD INDEX idx_cs_company_number (company_number);
 
ALTER TABLE sic_codes_staging
    MODIFY COLUMN company_number VARCHAR(15) NOT NULL,
    ADD INDEX idx_scs_company_number (company_number);
 

DELIMITER $$
 
CREATE PROCEDURE ProcessCompanyStaging()
BEGIN
    START TRANSACTION;
 
    -- 1. Resolve / create company types and statuses
    INSERT INTO company_types (`name`)
    SELECT DISTINCT s.`type`
    FROM companies_staging s
    WHERE s.`type` IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM company_types t WHERE t.`name` = s.`type`);
 
    INSERT INTO company_status (`name`)
    SELECT DISTINCT s.`status`
    FROM companies_staging s
    WHERE s.`status` IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM company_status st WHERE st.`name` = s.`status`);
 
    -- 2. SIC codes: insert only unknown codes (no description available here);
    --    existing codes and descriptions are preserved
    INSERT INTO sic_codes (code)
    SELECT DISTINCT s.sic_code
    FROM sic_codes_staging s
    WHERE NOT EXISTS (
        SELECT 1 FROM sic_codes sc WHERE sc.code = s.sic_code
    );
 
    -- 3. Upsert companies (matched on the unique company_number)
    INSERT INTO companies (
        company_number, company_name, registered_address,
        `type`, `status`, incorporated_on,
        next_accounts_made_up_to, accounts_due_by, last_accounts_made_up_to,
        next_statement_date, next_statement_due_by, last_statement_dated
    )
    SELECT
        s.company_number, s.company_name, s.registered_address,
        t.id, st.id, s.incorporated_on,
        s.next_accounts_made_up_to, s.accounts_due_by, s.last_accounts_made_up_to,
        s.next_statement_date, s.next_statement_due_by, s.last_statement_dated
    FROM companies_staging s
    LEFT JOIN company_types   t  ON t.`name`  = s.`type`
    LEFT JOIN company_status  st ON st.`name` = s.`status`
    ON DUPLICATE KEY UPDATE
        company_name             = VALUES(company_name),
        registered_address       = VALUES(registered_address),
        `type`                   = VALUES(`type`),
        `status`                 = VALUES(`status`),
        incorporated_on          = VALUES(incorporated_on),
        next_accounts_made_up_to = VALUES(next_accounts_made_up_to),
        accounts_due_by          = VALUES(accounts_due_by),
        last_accounts_made_up_to = VALUES(last_accounts_made_up_to),
        next_statement_date      = VALUES(next_statement_date),
        next_statement_due_by    = VALUES(next_statement_due_by),
        last_statement_dated     = VALUES(last_statement_dated);
 
    -- 4. Refresh nature of business links for staged companies
    DELETE cnb
    FROM company_nature_of_business cnb
    INNER JOIN companies c ON c.id = cnb.company_id
    INNER JOIN (SELECT DISTINCT company_number FROM companies_staging) s
        ON s.company_number = c.company_number;
 
    INSERT INTO company_nature_of_business (company_id, sic_code)
    SELECT DISTINCT c.id, s.sic_code
    FROM sic_codes_staging s
    INNER JOIN companies c ON c.company_number = s.company_number;
 
    COMMIT;
 
    -- 5. Clear both staging tables
    DELETE FROM companies_staging;
    DELETE FROM sic_codes_staging;
END$$
 
DELIMITER ;