"""
The MySQL database: which filings still need their PDF saved, and the log of those that are done.

The connection settings are read from the environment variable RPP2_CONNSTR, a JSON object
(the same one the rest of the project uses):
    {"host": "...", "port": 3306, "user": "...", "password": "...", "database": "...",
     "ssl_verify_cert": true, "ssl_ca": "/path/to/ca.crt"}
"""

import json
import os

import mysql.connector

CONNSTR_VAR = "RPP2_CONNSTR"
ACCOUNT_TYPES = ("AA", "AA01", "AA03", "AAMD")  # filing types that hold annual accounts
MIN_PAGES = 2  # shorter filings are skipped
MAX_PER_RUN = 100000  # the most filings one run takes, whatever --limit says

# Accounts filings with a PDF that have no row in companies_house_accounts yet, and enough pages to hold
# accounts (a 1-page filing is a notice or form with no figures).  A filing whose page count is not known is
# kept.  The `%s` placeholders are the filing types, the fewest pages, and (from build_query) the earliest
# date if wanted and the limit.
PENDING_FILINGS = """
    SELECT fh.id, fh.pdf_url
    FROM filing_history fh
    JOIN filing_types ft ON fh.filing_type = ft.id
    LEFT JOIN companies_house_accounts cha ON cha.filing_history_id = fh.id
    WHERE ft.name IN ({types})
      AND fh.pdf_url LIKE '%format=pdf%'
      AND cha.id IS NULL
      AND (fh.document_page_count IS NULL OR fh.document_page_count >= %s)
""".format(types=", ".join(["%s"] * len(ACCOUNT_TYPES)))

SINCE_CLAUSE = "      AND (fh.`date` IS NULL OR fh.`date` >= %s)\n"  # a filing with no date is kept
ORDER_BY_ID = "    ORDER BY fh.id"
ORDER_NEWEST_FIRST = "    ORDER BY fh.`date` DESC, fh.id DESC"
LIMIT_CLAUSE = "\n    LIMIT %s"


def build_query(since_year=None, newest_first=False):
    """
    The query for the filings still to save: from `since_year` on if given, newest first if asked.
    """
    query = PENDING_FILINGS

    if since_year:
        query += SINCE_CLAUSE

    return query + (ORDER_NEWEST_FIRST if newest_first else ORDER_BY_ID) + LIMIT_CLAUSE


def connect():
    """
    Open a connection using the settings in RPP2_CONNSTR.
    """
    try:
        settings = json.loads(os.environ.get(CONNSTR_VAR, ""))

    except json.JSONDecodeError:
        raise RuntimeError(f"Set the environment variable {CONNSTR_VAR} to the database settings as JSON "
                           '(host, port, user, password, database, ssl_verify_cert, ssl_ca).') from None

    return mysql.connector.connect(**settings)


def pending_filings(connection, limit=None, min_pages=MIN_PAGES, since_year=None, newest_first=False):
    """
    The (filing id, pdf url) pairs that have not been saved yet and have `min_pages` or more, filed in
    `since_year` or later if that is given, newest first if `newest_first`.  There are at most `limit` of
    them, and never more than MAX_PER_RUN, which is also the number when no limit is given.
    """
    parameters = [*ACCOUNT_TYPES, min_pages]

    if since_year:
        parameters.append(f"{since_year}-01-01")

    parameters.append(min(limit or MAX_PER_RUN, MAX_PER_RUN))
    cursor = connection.cursor()
    cursor.execute(build_query(since_year, newest_first), tuple(parameters))
    rows = cursor.fetchall()
    cursor.close()

    return rows
