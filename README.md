# Companies House accounts extractor

Two commands:

| Command | What it does |
|---|---|
| `python main.py <pdf or folder>` | Reads accounts PDFs (text layer or OCR) and writes figures as JSON and flat CSV facts to `output/`, with a run log. |
| `python upload_filings.py` | Takes the filings listed in the database, downloads each PDF, OCRs it to a `.txt`, uploads both to the IONOS bucket and logs a row in `companies_house_accounts`. `--dry-run` stops before any upload. |

## Layout

```
main.py, upload_filings.py     the two commands (command line only)
extract_data/
  pipeline.py one PDF start to finish (read, parse, write files) and the results log entries
  reading/    ocr.py (text layer / OCR / cache), gpu.py (GPU switch)
  parsing/    document.py runs the steps: rows -> tables -> company -> finalise -> totals check
              (figures, rows, tables, columns, finalise, totals, labels, company)
  rescan.py   re-reads pages whose totals did not add up, at a higher resolution
  results/    standardise.py (fixed headings), flatten.py (SQL-ready facts)
  storage/    ionos.py (bucket), database.py (MySQL), accounts.py (one filing, start to finish)
tests/        pytest; fixtures in tests/fixtures
```

## Environment variables

| Variable | Used by |
|---|---|
| `RPP2_CONNSTR` | database connection, as JSON |
| `IONOS_BUCKET_ACCESS_KEY`, `IONOS_BUCKET_SECRET_KEY` | the bucket |

## Checks

`python -m pytest` and `python -m pyflakes main.py upload_filings.py extract_data tests`
