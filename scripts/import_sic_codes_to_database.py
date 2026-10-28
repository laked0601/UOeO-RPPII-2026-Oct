import re

import requests

import helpers

# Call this script to load in the SIC codes from the UK government website


SIC_CODES_TABLE_RE = re.compile(r"<table .*? id=\"sic-codes\">(.*?)<\/table>", re.DOTALL)
SIC_CODE_ROW_RE = re.compile(r"<tr>.*?<td>(\d+?)</td>.*?<td>(.*?)</td>.*?</tr>", re.DOTALL)


def main():
    response = requests.get("https://resources.companieshouse.gov.uk/sic/")
    response.raise_for_status()
    table = SIC_CODES_TABLE_RE.search(response.text)
    if table is None:
        raise Exception(
            f"Could not find table with pattern '{SIC_CODES_TABLE_RE.pattern}' in response beginning " +
            f"'{response.text[:50]}'. Please investigate."
        )
    rows = SIC_CODE_ROW_RE.findall(table.group(1))
    if not rows:
        raise Exception(
            f"Could not rows with pattern '{SIC_CODE_ROW_RE.pattern}' in table beginning " +
            f"'{table.group(1)[:50]}'. Please investigate."
        )
    with helpers.CONNECTION_POOL.get_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(
            "INSERT INTO sic_codes_staging_with_description (sic_code, description) VALUES (%s, %s)",
            [[int(str(x[0]).strip()), str(x[1]).strip()] for x in rows]
        )
        cursor.callproc("ProcessSicCodesWithDescriptionStaging")
        conn.commit()


if __name__ == "__main__":
    main()
