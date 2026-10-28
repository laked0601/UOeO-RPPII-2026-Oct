# Companies House accounts extractor

Reads Companies House annual accounts PDFs, scanned or digital, and works with them in two ways:

| Command                          | What it does                                                                                                                                                      |
|----------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `python main.py <pdf or folder>` | Reads the PDFs (text layer, or OCR for scans) and writes the figures as JSON and flat CSV facts to `output/`, with a run log.                                     |
| `python upload_filings.py`       | Takes the filings listed in the database, downloads each PDF, OCRs it to a `.txt`, uploads both to the IONOS bucket and logs a row in `companies_house_accounts`. |

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

OCR runs on the CPU by default. For an NVIDIA GPU, follow the GPU note at the bottom of `requirements.txt`.
It is used automatically when it works; `--cpu` turns it off.

## Environment variables

| Variable                                             | Used by                                                                                                                                                                     |
|------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `RPP2_CONNSTR`                                       | the database connection, as JSON: `{"host": "...", "port": 3306, "user": "...", "password": "...", "database": "...", "ssl_verify_cert": true, "ssl_ca": "path/to/ca.crt"}` |
| `IONOS_BUCKET_ACCESS_KEY`, `IONOS_BUCKET_SECRET_KEY` | the bucket (not needed with `--dry-run`)                                                                                                                                    |

In PowerShell, `$env:IONOS_BUCKET_ACCESS_KEY = "..."` sets one for that window only.
`setx IONOS_BUCKET_ACCESS_KEY "..."` keeps it for new windows. In PyCharm, add them to the run configuration.
The keys are never kept in the code.

## Reading PDFs: main.py

```
python main.py extract_data/pdf_files                one folder of PDFs
python main.py "some file.pdf" --out results         one PDF, results in another folder
python main.py extract_data/pdf_files --text         also write the raw text of each page
```

Each PDF gives `<name>.json` (the figures as tables), `<name>.standard.json` (the same figures under fixed
headings) and `<name>.facts.csv` (one row per figure, ready for SQL). What each PDF found, with every warning,
is added to `output/extract_log.txt`. The OCR result is kept in `output/cache/`, so a second run is fast;
`--no-cache` reads the PDFs again. Pages whose totals do not add up are read again at a higher resolution
(`--rescan-dpi 0` turns that off). `--force-ocr` OCRs pages that have a text layer.

## Saving filings: upload_filings.py

```
python upload_filings.py --dry-run --limit 3         download and OCR three filings, upload nothing
python upload_filings.py --limit 50                  the first 50 filings not saved yet
python upload_filings.py --since 2020 --newest-first  filed in 2020 or later, newest first
python upload_filings.py                             up to 100,000 filings not saved yet
```

One run does at most 100,000 filings, whatever `--limit` says; run it again for the rest.

Filings with fewer than 2 pages are skipped (`--min-pages`). Each filing goes to the bucket as
`accounts/pdf/<filing id>.pdf` and `accounts/txt/<filing id>.txt`, and its row in `companies_house_accounts`
is written last. So a filing that fails, or a run stopped with Ctrl+C, is simply done again next time, and a
saved filing is never done twice. Local copies are kept in `downloads/`.

Each run prints a line per filing with the time taken and an estimate of the time left, and writes the same
to `logs/`, in a file named by the start time and number of filings, for example
`logs/2026-10-28_14-05-33_50-filings.txt`.

## Layout

```
main.py, upload_filings.py     the two commands (command line only)
extract_data/
  cli.py      options both commands share
  pipeline.py one PDF start to finish (read, parse, write files) and the results log entries
  jsonio.py   writes JSON files
  runlog.py   progress lines and log file of upload_filings.py
  reading/    ocr.py (text layer / OCR / cache), gpu.py (GPU switch)
  parsing/    document.py runs the steps: rows -> tables -> company -> finalise -> totals check
              (figures, rows, tables, columns, finalise, totals, labels, company)
  rescan.py   re-reads pages whose totals did not add up, at a higher resolution
  results/    standardise.py (fixed headings), flatten.py (SQL-ready facts)
  storage/    ionos.py (bucket), database.py (MySQL), accounts.py (one filing, start to finish)
tests/        pytest; fixtures in tests/fixtures
```

`helpers.py`, `scripts/` and `SQL/` belong to the rest of the project.

## Tests

```
python -m pytest
```
