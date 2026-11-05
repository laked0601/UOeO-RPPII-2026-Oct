ALTER TABLE companies
    MODIFY COLUMN company_number VARCHAR(8) NOT NULL;

ALTER TABLE companies_staging
    MODIFY COLUMN company_number VARCHAR(8) NOT NULL;
