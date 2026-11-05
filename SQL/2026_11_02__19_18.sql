CREATE TABLE companies_house_accounts_pages (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    filing_history_id BIGINT NOT NULL,
    page_number SMALLINT NOT NULL,
    CONSTRAINT fk_chap_filing_history
        FOREIGN KEY (filing_history_id) REFERENCES filing_history(id)
);
/**/
CREATE TABLE companies_house_accounts_lines_staging(
	id BIGINT PRIMARY KEY AUTO_INCREMENT,
	filing_history_id BIGINT NOT NULL REFERENCES companies_house_accounts.filing_history_id,
	record_date DATE,
	currency VARCHAR(10),
	intangible_assets DECIMAL(14,2),
	tangible_assets DECIMAL(14,2),
	investments DECIMAL(14,2),
	fixed_assets DECIMAL(14,2),
	stocks DECIMAL(14,2),
	debtors DECIMAL(14,2),
	cash DECIMAL(14,2),
	current_assets DECIMAL(14,2),
	total_assets DECIMAL(14,2),
	creditors_within_one_year DECIMAL(14,2),
	creditors_after_one_year DECIMAL(14,2),
	provisions DECIMAL(14,2),
	net_current_assets DECIMAL(14,2),
	total_assets_less_current_liabilities DECIMAL(14,2),
	net_assets DECIMAL(14,2),
	share_capital DECIMAL(14,2),
	other_reserves DECIMAL(14,2),
	retained_earnings DECIMAL(14,2),
	turnover DECIMAL(14,2),
	gross_profit DECIMAL(14,2),
	operating_profit DECIMAL(14,2),
	profit_before_tax DECIMAL(14,2),
	profit_for_period DECIMAL(14,2),
	asset_depreciation DECIMAL(14,2),
	net_book_value DECIMAL(14,2),
	average_employees INT
);

ALTER TABLE companies_house_accounts
	ADD COLUMN record_date DATE,
	ADD COLUMN currency VARCHAR(10),
	ADD COLUMN intangible_assets DECIMAL(14,2),
	ADD COLUMN tangible_assets DECIMAL(14,2),
	ADD COLUMN investments DECIMAL(14,2),
	ADD COLUMN fixed_assets DECIMAL(14,2),
	ADD COLUMN stocks DECIMAL(14,2),
	ADD COLUMN debtors DECIMAL(14,2),
	ADD COLUMN cash DECIMAL(14,2),
	ADD COLUMN current_assets DECIMAL(14,2),
	ADD COLUMN total_assets DECIMAL(14,2),
	ADD COLUMN creditors_within_one_year DECIMAL(14,2),
	ADD COLUMN creditors_after_one_year DECIMAL(14,2),
	ADD COLUMN provisions DECIMAL(14,2),
	ADD COLUMN net_current_assets DECIMAL(14,2),
	ADD COLUMN total_assets_less_current_liabilities DECIMAL(14,2),
	ADD COLUMN net_assets DECIMAL(14,2),
	ADD COLUMN share_capital DECIMAL(14,2),
	ADD COLUMN other_reserves DECIMAL(14,2),
	ADD COLUMN retained_earnings DECIMAL(14,2),
	ADD COLUMN turnover DECIMAL(14,2),
	ADD COLUMN gross_profit DECIMAL(14,2),
	ADD COLUMN operating_profit DECIMAL(14,2),
	ADD COLUMN profit_before_tax DECIMAL(14,2),
	ADD COLUMN profit_for_period DECIMAL(14,2),
	ADD COLUMN asset_depreciation DECIMAL(14,2),
	ADD COLUMN net_book_value DECIMAL(14,2),
	ADD COLUMN average_employees INT
;

DELIMITER $$

DROP PROCEDURE IF EXISTS ProcessCompaniesHouseAccountsLinesStaging$$

CREATE PROCEDURE ProcessCompaniesHouseAccountsLinesStaging()
BEGIN
	DECLARE EXIT HANDLER FOR SQLEXCEPTION
	BEGIN
		ROLLBACK;
		RESIGNAL;
	END;

	START TRANSACTION;

	-- 2a. Update rows that already exist for this filing_history_id
	UPDATE companies_house_accounts AS a
	INNER JOIN companies_house_accounts_lines_staging AS s
		ON s.filing_history_id = a.filing_history_id
	SET
		a.record_date   = s.record_date,
		a.currency      = s.currency,
		a.intangible_assets   = s.intangible_assets,
		a.tangible_assets     = s.tangible_assets,
		a.investments         = s.investments,
		a.fixed_assets        = s.fixed_assets,
		a.stocks              = s.stocks,
		a.debtors             = s.debtors,
		a.cash                = s.cash,
		a.current_assets      = s.current_assets,
		a.total_assets        = s.total_assets,
		a.creditors_within_one_year = s.creditors_within_one_year,
		a.creditors_after_one_year  = s.creditors_after_one_year,
		a.provisions          = s.provisions,
		a.net_current_assets  = s.net_current_assets,
		a.total_assets_less_current_liabilities = s.total_assets_less_current_liabilities,
		a.net_assets          = s.net_assets,
		a.share_capital       = s.share_capital,
		a.other_reserves      = s.other_reserves,
		a.retained_earnings   = s.retained_earnings,
		a.turnover            = s.turnover,
		a.gross_profit        = s.gross_profit,
		a.operating_profit    = s.operating_profit,
		a.profit_before_tax   = s.profit_before_tax,
		a.profit_for_period   = s.profit_for_period,
		a.asset_depreciation   = s.asset_depreciation,
		a.net_book_value      = s.net_book_value,
		a.average_employees    = s.average_employees;

	COMMIT;

	-- 2c. Clear the staging table (implicit commit; safe because the
	-- data is now fully merged)
	TRUNCATE TABLE companies_house_accounts_lines_staging;
END$$

DELIMITER ;