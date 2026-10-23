CREATE TABLE companies_staging (
    company_number             BIGINT       NOT NULL,
    company_name               VARCHAR(1024),
    registered_address         VARCHAR(1024),
    `type`                     VARCHAR(50),
    `status`                   VARCHAR(50),
    incorporated_on            DATE,
    next_accounts_made_up_to   DATE,
    accounts_due_by            DATE,
    last_accounts_made_up_to   DATE,
    next_statement_date        DATE,
    next_statement_due_by      DATE,
    last_statement_dated       DATE,
    INDEX idx_cs_type (`type`),
    INDEX idx_cs_status (`status`)
);

CREATE TABLE sic_codes_staging (
    company_number  BIGINT      NOT NULL,
    sic_code        INT         NOT NULL,
    description     VARCHAR(255),
    INDEX idx_scs_code (sic_code)
);

DELIMITER $$

CREATE PROCEDURE ProcessStaging()
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

    -- 2. SIC codes: overwrite descriptions wholesale
    INSERT INTO sic_codes (code, description)
    SELECT DISTINCT s.sic_code, s.description
    FROM sic_codes_staging s
    ON DUPLICATE KEY UPDATE description = VALUES(description);

    -- 3. Upsert companies
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
        `type`                  = VALUES(`type`),
        `status`                = VALUES(`status`),
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
    INNER JOIN (SELECT DISTINCT company_number FROM companies_staging) s
        ON cnb.company_number = s.company_number;

    INSERT INTO company_nature_of_business (company_number, sic_code)
    SELECT DISTINCT s.company_number, s.sic_code
    FROM sic_codes_staging s;

    COMMIT;

    -- 5. Clear both staging tables
    DELETE FROM companies_staging;
    DELETE FROM sic_codes_staging;
END$$

DELIMITER ;