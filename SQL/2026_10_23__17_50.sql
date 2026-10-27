ALTER TABLE sic_codes_staging DROP COLUMN description;

CREATE TABLE sic_codes_staging_with_description (
	sic_code INT,
	description VARCHAR(255)
);

DELIMITER $$

CREATE PROCEDURE ProcessSicCodesWithDescriptionStaging()
BEGIN
    START TRANSACTION;

	INSERT INTO sic_codes (code, description)
	SELECT DISTINCT s.sic_code, s.description
	FROM sic_codes_staging_with_description s
	ON DUPLICATE KEY UPDATE description = VALUES(description);
	
	DELETE FROM TABLE sic_codes_staging_with_description;

    COMMIT;
END$$

DELIMITER ;