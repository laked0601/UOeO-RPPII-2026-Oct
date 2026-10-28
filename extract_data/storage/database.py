"""
The MySQL database: which filings still need their PDF saved, and the log of those that are done.

The connection settings are read from the environment variable RPP2_CONNSTR, a JSON object
(the same one the rest of the project uses):
    {"host": "...", "port": 3306, "user": "...", "password": "...", "database": "...",
     "ssl_verify_cert": true, "ssl_ca": "/path/to/ca.crt"}
"""

import json
import mysql.connector
import os

CONNSTR_VAR = "RPP2_CONNSTR"
ACCOUNT_TYPES = ("AA", "AA01", "AA03", "AAMD")  # filing types that hold annual accounts

# Accounts filings with a PDF that have no row in companies_house_accounts yet (`%s` is the limit).
PENDING_FILINGS = """
    SELECT fh.id, fh.pdf_url
    FROM filing_history fh
    JOIN filing_types ft ON fh.filing_type = ft.id
    LEFT JOIN companies_house_accounts cha ON cha.filing_history_id = fh.id
    WHERE ft.name IN ({types})
      AND fh.pdf_url LIKE '%format=pdf%'
      AND cha.id IS NULL
    ORDER BY fh.id
    LIMIT %s
""".format(types=", ".join(["%s"] * len(ACCOUNT_TYPES)))


def connect():
    """Open a connection using the settings in RPP2_CONNSTR."""
    try:
        settings = json.loads(os.environ.get(CONNSTR_VAR, ""))
    except json.JSONDecodeError:
        raise RuntimeError(f"Set the environment variable {CONNSTR_VAR} to the database settings as JSON "
                           '(host, port, user, password, database, ssl_verify_cert, ssl_ca).') from None
    return mysql.connector.connect(**settings)


def pending_filings(connection, limit):
    """Up to `limit` (filing id, pdf url) pairs that have not been saved yet."""
    cursor = connection.cursor()
    cursor.execute(PENDING_FILINGS, (*ACCOUNT_TYPES, limit))
    rows = cursor.fetchall()
    cursor.close()
    return rows
