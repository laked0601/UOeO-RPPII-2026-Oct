import datetime
import re

import bs4
import requests

from helpers import CONNECTION_POOL, retried_request

PAGES_RE = re.compile(r"\((\d+?) pages?\)")


def is_covid_unavailable(row: bs4.Tag) -> bool:
    return row.find(
        string=lambda s: isinstance(s, bs4.Comment) and "unable to offer the document ordering service" in s
    ) is not None


def is_available_later(row: bs4.Tag) -> bool:
    hint = row.find("div", class_="form-hint")
    if hint is None:
        return False
    return "will be available in" in hint.get_text()


def is_zip_file(cell: bs4.Tag) -> bool:
    return "Download ZIP" in cell.get_text()


def extract_filings(response: requests.Response, error_message_id: str):
    soup = bs4.BeautifulSoup(response.text, "html.parser")
    filings_table = soup.find("table", {"id": "fhTable"})
    if filings_table is None:
        print(f"Could not find table with id 'fhTable' in html source for {error_message_id}. Please investigate.")
        return
    tbody = filings_table
    rows = tbody.find_all("tr")[1:]
    return_rows = []
    for r in rows:
        cells = r.find_all("td")
        if not len(cells) == 4:
            print(
                f"Expected at most 4 cells in each row for {error_message_id} but found {len(cells)}. Please investigate.")
            return
        filing_date_str = cells[0].get_text().strip()
        try:
            dt = datetime.datetime.strptime(filing_date_str, "%d %b %Y").date()
        except Exception as e:
            print(f"Failed to parse date string '{filing_date_str}' for {error_message_id}.")
            return
        filing_type = cells[1].get_text().strip()
        description = cells[2].get_text().strip()
        pdf_component = cells[3].find("div", {"class": "govuk-!-padding-bottom-2"})
        if pdf_component is None:
            pdf_url = None
            page_count = None
            request_pdf_component = cells[3].find("a", {"data-event-id": "Request Document"})
            if request_pdf_component is None:
                if not (is_covid_unavailable(r) or is_available_later(r)):
                    if is_zip_file(cells[3]):
                        pdf_url = cells[3].find("a").get("href")
                    else:
                        print(f"Could not find pdf component or request pdf component on cell for {error_message_id}")
                        return
        else:
            pages_text = text = "".join(pdf_component.find_all(string=True, recursive=False)).strip()
            res = PAGES_RE.search(pages_text)
            if res is None:
                print(f"Could not find pages count on cell for {error_message_id}")
                return
            page_count = int(res.group(1))
            pdf_a_tag = pdf_component.find("a")
            if pdf_a_tag is None:
                print(f"Could not find pdf a tag on cell for {error_message_id}")
                return
            pdf_url = pdf_a_tag.get("href")
        return_rows.append((filing_type, dt, description, pdf_url, page_count))

    return return_rows


def main(first_page_only=True):
    batch_size = 100000
    sql_quer = f"""
        SELECT 
            c.id, c.company_number
        FROM companies c
        LEFT JOIN company_status cs on c.status = cs.id
        LEFT JOIN (
            SELECT DISTINCT company_id
            FROM filing_history
        ) res ON c.id = res.company_id
        WHERE
            cs.name = 'active' 
            AND res.company_id IS NULL
        ORDER BY RAND() * c.id
        LIMIT {batch_size}
    """
    with CONNECTION_POOL.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql_quer)
        rows = cursor.fetchall()
        with requests.session() as s:
            while rows != []:
                company_id = None
                for company_id, company_number in rows:
                    page_number = 1
                    all_filings = []
                    error_message_id = f"company id {company_id} number '{company_number}'"
                    while True:
                        response, message = retried_request(
                            session=s,
                            url=f"https://find-and-update.company-information.service.gov.uk/company/{company_number}/filing-history",
                            params={
                                "page": page_number
                            },
                            error_message_id=error_message_id
                        )
                        if message == "failed":
                            return
                        elif message == "no results":
                            break
                        elif response is not None:
                            filings = extract_filings(response, error_message_id)
                            if filings is None or len(filings) == 0:
                                break
                            else:
                                for r in filings:
                                    all_filings.append(
                                        [company_number] + list(r)
                                    )
                                if first_page_only:
                                    break
                        page_number += 1
                    cursor.executemany(
                        """
                        INSERT INTO filing_history_staging (company_number, filing_type, date, description,
                                                            pdf_url, document_page_count)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        all_filings
                    )
                    cursor.callproc("ProcessFilingHistoryStaging")
                    cursor.execute("DELETE FROM filing_history_staging")
                    conn.commit()
                    print(f"Added {len(all_filings)} filings for {error_message_id}")

                if company_id is None:
                    break
                cursor.execute(sql_quer)
                rows = cursor.fetchall()
                print(len(rows))


if __name__ == "__main__":
    main()
