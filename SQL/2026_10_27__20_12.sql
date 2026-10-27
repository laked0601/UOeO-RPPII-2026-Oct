CREATE TABLE companies_house_accounts (
    id                BIGINT NOT NULL AUTO_INCREMENT,
    created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    filing_history_id BIGINT NOT NULL,
    text_file_path    VARCHAR(1000) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT fk_ch_accounts_filing_history
        FOREIGN KEY (filing_history_id) REFERENCES filing_history (id)
);