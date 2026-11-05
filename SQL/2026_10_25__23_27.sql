ALTER TABLE filing_history
    MODIFY COLUMN pdf_url VARCHAR(8192),
	MODIFY COLUMN description VARCHAR(1024),
	MODIFY COLUMN filing_type SMALLINT,
	ADD COLUMN document_page_count INT;

CREATE TABLE filing_types (
	id SMALLINT PRIMARY KEY NOT NULL AUTO_INCREMENT,
	`name` VARCHAR(100) NOT NULL UNIQUE
);

ALTER TABLE filing_history
    ADD CONSTRAINT fk_filing_type
        FOREIGN KEY (filing_type) REFERENCES filing_types (id);

CREATE TABLE filing_history_staging (
	company_number VARCHAR(8) NOT NULL,
	filing_type VARCHAR(100),
	date DATE,
	description VARCHAR(1024),
	pdf_url VARCHAR(8192),
	document_page_count INT
);

DELIMITER $$

CREATE PROCEDURE ProcessFilingHistoryStaging()
BEGIN
    START TRANSACTION;

    -- 1. Resolve / create filing types
    INSERT INTO filing_types (`name`)
    SELECT DISTINCT s.filing_type
    FROM filing_history_staging s
    WHERE s.filing_type IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM filing_types ft WHERE ft.`name` = s.filing_type);

    -- 2. Replace filing history rows for staged companies.
    --    filing_history has no natural unique key to upsert on,
    --    so we mirror the refresh pattern used for company_nature_of_business:
    --    delete existing rows for the staged companies, then insert afresh.
    DELETE fh
    FROM filing_history fh
    INNER JOIN companies c ON c.id = fh.company_id
    INNER JOIN (SELECT DISTINCT company_number FROM filing_history_staging) s
        ON s.company_number = c.company_number;

    -- 3. Insert staged filing history, resolving type names to ids
    INSERT INTO filing_history (company_id, `date`, filing_type, description, pdf_url, document_page_count)
    SELECT DISTINCT
        c.id, s.`date`, ft.id, s.description, s.pdf_url, s.document_page_count
    FROM filing_history_staging s
    INNER JOIN companies c ON c.company_number = s.company_number
    LEFT JOIN filing_types ft ON ft.`name` = s.filing_type;

    COMMIT;
END$$

DELIMITER ;