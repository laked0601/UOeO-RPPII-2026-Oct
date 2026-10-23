CREATE TABLE company_types (
    id SMALLINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `name` VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE company_status (
    id SMALLINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `name` VARCHAR(50) NOT NULL UNIQUE
);

CREATE TABLE companies (
    company_number BIGINT NOT NULL PRIMARY KEY,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    company_name VARCHAR(1024) NOT NULL,
    registered_address VARCHAR(1024),
    `type` SMALLINT,
    `status` SMALLINT,
    incorporated_on DATE,
    next_accounts_made_up_to DATE,
    accounts_due_by DATE,
    last_accounts_made_up_to DATE,
    next_statement_date DATE,
    next_statement_due_by DATE,
    last_statement_dated DATE,
    CONSTRAINT fk_companies_type
        FOREIGN KEY (`type`) REFERENCES company_types (id),
    CONSTRAINT fk_companies_status
        FOREIGN KEY (`status`) REFERENCES company_status (id)
);

CREATE TABLE sic_codes (
    code INT NOT NULL PRIMARY KEY,
    description VARCHAR(255)
);

CREATE TABLE company_nature_of_business (
    company_number BIGINT NOT NULL,
    sic_code INT NOT NULL,
    PRIMARY KEY (company_number, sic_code),
    CONSTRAINT fk_nob_company
        FOREIGN KEY (company_number) REFERENCES companies (company_number),
    CONSTRAINT fk_nob_sic
        FOREIGN KEY (sic_code) REFERENCES sic_codes (code)
);

CREATE TABLE filing_history (
    id BIGINT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    company_number BIGINT NOT NULL,
    `date` DATE,
    filing_type VARCHAR(20),
    description VARCHAR(255),
    pdf_url VARCHAR(1024),
    CONSTRAINT fk_filing_company
        FOREIGN KEY (company_number) REFERENCES companies (company_number)
);