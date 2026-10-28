-- One row per filing in companies_house_accounts.
-- Without this, two runs of upload_filings.py at the same time could both insert the same filing.
-- upload_filings.py treats the "duplicate entry" error as "already recorded".

-- 1. Check for duplicates first.  This should return no rows; if it does, delete the extra ones
--    (keep the lowest id of each filing) before step 2, or the ALTER fails.
SELECT filing_history_id, COUNT(*) AS rows_for_filing, MIN(id) AS keep_id
FROM companies_house_accounts
GROUP BY filing_history_id
HAVING COUNT(*) > 1;

-- 2. Make the filing id unique.
ALTER TABLE companies_house_accounts
    ADD CONSTRAINT uq_ch_accounts_filing_history UNIQUE (filing_history_id);
