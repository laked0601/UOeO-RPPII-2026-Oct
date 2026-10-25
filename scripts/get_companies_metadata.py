from mysql.connector.abstracts import MySQLCursorAbstract
from mysql.connector.connection import MySQLConnection
import requests
import re
import time
import datetime
import os
from helpers import CONNECTION_POOL
from tempfile import NamedTemporaryFile


CSV_URL = "https://find-and-update.company-information.service.gov.uk/advanced-search/csv"


def extract_from_csv(filepath: str):
    headers = []
    rows = []
    save_file = False
    line_re = re.compile(r"^([\W\w\s]+?),((?:[A-Z]{2}|\d{2}|[A-Z]\d)\d{6}),([^,]*?),([^,]*?),([^,]*?),([^,]*?),([^,]*?),([^,]*?),([^,]*?),(\[.*?\])?,(.*?)$")
    with open(filepath,'r', encoding="utf-8", newline='') as rf:
        headers = rf.readline().strip().split(',')
        if len(headers) != 11:
            print(f"Warning: expected 11 columns in csv file and received {len(headers)}. Please investigate...")
            save_file = True
        else:
            for line in rf.readlines():
                if line == '':
                    continue
                res = line_re.search(line.strip())
                if res is None or len(res.groups()) != 11:
                    print(f"Warning: failed to extract 11 columns from '{line}'. Please investigate...")
                    save_file = True
                    continue
                rows.append(tuple(res.groups()))


    if save_file:
        if not os.path.exists("error_csv_files"):
            os.mkdir("error_csv_files")
        i = 1
        fname = os.path.join("error_csv_files", f"output-{i}.csv")
        while os.path.exists(fname):
            i += 1
            fname = os.path.join("error_csv_files", f"output-{i}.csv")

        with open(fname, 'wb') as wf:
            with open(filepath, 'rb') as rf:
                wf.write(rf.read())

    return headers, rows


def retried_request(session: requests.Session, url: str, params, error_message_id: str):
    no_results_timeout = 7
    for i in (10, 60):
        try:
            r = session.get(url, params=params, timeout=no_results_timeout)
            if r.status_code == 504:
                return None, 'no results'
            r.raise_for_status()
            break
        except requests.exceptions.Timeout:
            # Timeout means the server didn't respond in time,
            # which we interpret as the server having no results.
            print(f"Request timed out for {error_message_id}. Treating as no results.")
            return None, 'no results'
        except Exception as e:
            print(f"Received {type(e)} {e} for {error_message_id}. Sleeping {i} seconds and retrying...")
            time.sleep(i)
    else:
        try:
            r = session.get(url, params=params, timeout=no_results_timeout)
            r.raise_for_status()
        except requests.exceptions.Timeout:
            print(f"Final attempt timed out for {error_message_id}. Treating as no results.")
            return None, 'no results'
        except Exception as e:
            print(f"Received {type(e)} {e} for {error_message_id}. Breaking requests...")
            return None, 'failed'

    return r, 'success'


def add_rows_to_database(connection: MySQLConnection, cursor: MySQLCursorAbstract, source_headers: list[str], rows: list[list[str]]):
    nature_of_business_re = re.compile(r"(\d+)")
    source_assumed_headers = (
        "company_number",
        "company_name",
        "registered_office_address",
        "company_type",
        "company_status",
        "incorporation_date",
        "nature_of_business"
    )
    header_map = []
    for target_i, head in enumerate(source_assumed_headers):
        for source_i, source_header in enumerate(source_headers):
            if source_header == head:
                header_map.append(source_i)
                break
        else:
            raise Exception(f"Could not find {head} in {source_headers}")

    company_rows = []
    nature_of_business_rows = []

    for row in rows:
        company_number = row[header_map[0]]
        company_name = row[header_map[1]]
        registered_address = row[header_map[2]]
        company_type = row[header_map[3]]
        company_status = row[header_map[4]]
        incorporation_date = row[header_map[5]]
        nature_of_business = row[header_map[6]]
        try:
            dt = datetime.date.fromisoformat(incorporation_date)
        except Exception as e:
            print(f"Unable to convert '{incorporation_date}' to date")
            dt = None

        res = nature_of_business_re.findall(nature_of_business)
        for match in res:
            nature_of_business_rows.append((company_number, int(match)))

        company_rows.append(
            (
                company_number,
                company_name,
                registered_address,
                company_type,
                company_status,
                dt
            )
        )

    cursor.executemany(
        "INSERT INTO companies_staging (company_number, company_name, registered_address, type, status, incorporated_on) " +
        "VALUES (%s, %s, %s, %s, %s, %s)",
        company_rows
    )
    cursor.executemany(
        "INSERT INTO sic_codes_staging (company_number, sic_code) VALUES (%s, %s)",
        nature_of_business_rows
    )
    cursor.callproc("ProcessCompanyStaging")
    connection.commit()
    print(f"Processed {len(rows)} rows...")


def get_companies_csv_data(session: requests.Session, url: str, params, error_message_id: str):
    r, is_success = retried_request(
        session=session,
        url=url,
        params=params,
        error_message_id=error_message_id
    )
    if is_success != 'success':
        return None, None, r, is_success
    temp_file = NamedTemporaryFile('wb', delete_on_close=False)
    temp_file.write(r.content)
    temp_file.close()
    try:
        headers, rows = extract_from_csv(temp_file.name)
    except Exception as e:
        print(f"Received {type(e)} {e} for csv file with {error_message_id}.")
        return None, None, None, None
    rows_len = len(rows)
    print(f"{rows_len} rows for {error_message_id}. ")
    os.remove(temp_file.name)
    return headers, rows, None, None


def get_companies():
    with CONNECTION_POOL.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT code FROM sic_codes")
        sic_codes: list[int] = [x[0] for x in cursor.fetchall()]
        with requests.session() as s:
            for code in sic_codes:
                padded_code = str(code).zfill(5)
                res = get_companies_csv_data(
                    session=s,
                    url=CSV_URL,
                    params={
                        "sicCodes": padded_code
                    },
                    error_message_id=f"sic code {padded_code}"
                )
                if res[0] is None:
                    print("continuing...")
                    continue
                headers, rows, _, _ = res
                rows_len = len(rows)
                print(f"{rows_len} rows for sic code {padded_code}. ", end="")
                if rows_len > 4999:
                    print("Splitting requests by incorporation year")
                    this_year = datetime.datetime.today().year
                    start_year = 1800
                    end_year = start_year + (this_year - start_year) // 2
                    while start_year <= this_year:
                        res = get_companies_csv_data(
                            session=s,
                            url=CSV_URL,
                            params={
                                "incorporationFromDay": 1,
                                "incorporationFromMonth": 1,
                                "incorporationFromYear": start_year,
                                "incorporationToDay": 31,
                                "incorporationToMonth": 12,
                                "incorporationToYear": end_year,
                                "sicCodes": padded_code
                            },
                            error_message_id=f"sic code {padded_code} from {start_year} to {end_year}"
                        )
                        if res[3] == 'no results':
                            print("continuing...")
                            diff = end_year - start_year
                            if diff == 0:
                                start_year += 1
                                end_year += 1
                            else:
                                start_year = end_year
                                end_year = min(start_year + max(diff, 1), this_year)
                            continue
                        headers, rows, _, _ = res
                        rows_len = len(rows)
                        if rows_len > 4999:
                            if start_year == end_year:
                                for end_day, month in (
                                    (31, 1), (28, 2), (31, 3), (30, 4), (31, 5), (30, 6), (31, 7), (31, 8),
                                    (30, 9), (31, 10), (30, 11), (31, 12)
                                ):
                                    if start_year == this_year:
                                        start_date = datetime.date(start_year, month, 1)
                                        if start_date >= datetime.date.today():
                                            break

                                    res = get_companies_csv_data(
                                        session=s,
                                        url=CSV_URL,
                                        params={
                                            "incorporationFromDay": 1,
                                            "incorporationFromMonth": month,
                                            "incorporationFromYear": start_year,
                                            "incorporationToDay": end_day,
                                            "incorporationToMonth": month,
                                            "incorporationToYear": end_year,
                                            "sicCodes": padded_code
                                        },
                                        error_message_id=f"sic code {padded_code} for {start_year}-{str(month).zfill(2)}"
                                    )
                                    if res[0] is None:
                                        print("continuing...")
                                        continue
                                    headers, rows, _, _ = res
                                    add_rows_to_database(conn, cursor, headers, rows)
                                start_year += 1
                                end_year += 1
                            else:
                                end_year = start_year + (end_year - start_year) // 2
                        else:
                            add_rows_to_database(conn, cursor, headers, rows)
                            if end_year >= this_year:
                                break
                            diff = end_year - start_year
                            if diff == 0:
                                start_year += 1
                                end_year += 1
                            else:
                                start_year = end_year
                                end_year = min(start_year + max(diff, 1), this_year)

                else:
                    add_rows_to_database(conn, cursor, headers, rows)
                

if __name__ == "__main__":
    get_companies()
