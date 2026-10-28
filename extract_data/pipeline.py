"""
The extraction of one PDF, start to finish, and the log of what each extraction found.

`process_pdf` runs text layer or OCR -> parse -> standardise -> flat facts and writes the
results into the output folder (see main.py for the files).
The log functions at the end, with the entry added to the results log for each PDF.
"""

from datetime import datetime

from extract_data.jsonio import write_json
from extract_data.reading.ocr import ocr_pdf, re_ocr_pages, save_cache, write_text_dump
from extract_data.rescan import load_tried, rescan_flagged_pages, save_tried, tried_path
from extract_data.results.flatten import to_facts, write_facts
from extract_data.results.standardise import standardise

DEFAULT_LOG_NAME = "extract_log.txt"  # the log of results, inside the output folder


def read_pdf(pdf_path, out_dir, dpi, use_cache, use_text_layer, rescan_dpi):
    """
    Get the text of a PDF (text layer or OCR) and parse it; returns the pages and the parsed result.

    extract_document reads any layout.  It is given the OCR fragments, with their positions, so it
    knows where each figure sits and can place it under the right column when neighbouring cells
    are blank.  Pages whose totals do not add up are first read again at a higher resolution
    (once per page).
    """
    pages = ocr_pdf(pdf_path, out_dir, dpi=dpi, use_cache=use_cache, use_text_layer=use_text_layer)
    tried_file = tried_path(pdf_path, out_dir)
    tried = load_tried(tried_file, rescan_dpi) if use_cache else set()
    can_rescan = rescan_dpi > dpi

    def rescan(numbers):
        return re_ocr_pages(pdf_path, numbers, rescan_dpi) if can_rescan else {}

    pages, parsed, rescanned, improved = rescan_flagged_pages(pages, pdf_path.name, rescan, tried)

    if rescanned and can_rescan:
        print(f"  Re-read pages {rescanned} at {rescan_dpi} dpi; improved: {improved or 'none'}")
        save_tried(tried_file, rescan_dpi, tried | set(rescanned))

        if improved:
            save_cache(pdf_path, out_dir, pages)  # later runs start from the better reading

    return pages, parsed


def process_pdf(pdf_path, out_dir, dpi, use_cache, use_text_layer=True, rescan_dpi=0, write_text=False):
    """
    Run the full pipeline for one PDF; return the JSON path, the parsed result and the flat facts.
    """
    pages, parsed = read_pdf(pdf_path, out_dir, dpi, use_cache, use_text_layer, rescan_dpi)

    if write_text:
        write_text_dump(pages, out_dir / f"{pdf_path.stem}.txt")

    # The same figures under fixed, common headings (null where the filing has none).
    parsed["standardised"] = standardise(parsed)
    company = parsed["company"]
    write_json(out_dir / f"{pdf_path.stem}.standard.json",
               {"source_file": parsed["source_file"], "company_number": company.get("registration_number"),
                "period_end": company.get("period_end"), **parsed["standardised"]})

    json_path = out_dir / f"{pdf_path.stem}.json"
    write_json(json_path, parsed)

    # The same figures again as flat rows (one per figure) for loading into SQL.
    facts = to_facts(parsed)
    write_facts(facts, out_dir, pdf_path.stem)

    return json_path, parsed, facts


# Results Log
# One entry is appended per PDF (and one for a PDF that failed)


def result_entry(pdf_name, parsed, facts, now=None):
    """
    The log text for one PDF that was extracted.
    """
    company = parsed.get("company", {})
    tables = len(parsed.get("statements", [])) + len(parsed.get("note_tables", []))
    warnings = parsed.get("warnings", [])

    lines = [
        f"{(now or datetime.now()):%Y-%m-%d %H:%M:%S}  {pdf_name}",
        f"  company number : {company.get('registration_number') or 'not found'}",
        f"  period end     : {company.get('period_end') or 'not found'}",
        f"  currency       : {company.get('currency') or 'not found'} x{company.get('unit_multiplier') or '?'}"
        + ("  (ASSUMED: no currency found in the document)" if company.get("currency_assumed") else ""),
        f"  extracted      : {tables} tables, {len(facts)} figures",
        f"  warnings       : {len(warnings)}" + ("" if warnings else "  (none)")]

    lines += [f"    - {warning}" for warning in warnings]

    return "\n".join(lines) + "\n\n"


def failure_entry(pdf_name, error, now=None):
    """
    The log text for one PDF that could not be extracted.
    """
    return (f"{(now or datetime.now()):%Y-%m-%d %H:%M:%S}  {pdf_name}\n"
            f"  FAILED         : {type(error).__name__}: {error}\n\n")


def append_log(path, entry):
    """
    Add an entry to the end of the log file (created if need be).
    """
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(entry)
