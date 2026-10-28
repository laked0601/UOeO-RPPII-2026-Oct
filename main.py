"""
Main entry point for the extract_data package.

For every PDF this runs the pipeline  text layer or OCR -> parse and writes
into the output folder:
    <name>.json      parsed data (statements and notes as rows x columns),
                      including a "standardised" block
    <name>.standard.json  just the standardised block: the same fixed headings for every
                      filing (assets, creditors, net assets, capital and reserves,
                      income, costs, profit and loss, depreciation), null where a
                      figure does not exist
    <name>.facts.csv  one row per figure, ready to load into SQL

Working files go in output/cache/ (the cached OCR result, re-used on later runs, and a note of
which pages were re-read).  With `--text`, <name>.txt is also written: the raw text, page by
page, for checking against the scan.

A log of what each extraction found (company number, period end, figure count and every
warning) is added to output/extract_log.txt, or the file given with `--log`.
"""

import argparse
import sys
from pathlib import Path

from extract_data.cli import add_ocr_options
from extract_data.pipeline import DEFAULT_LOG_NAME, append_log, failure_entry, process_pdf, result_entry
from extract_data.reading import gpu
from extract_data.rescan import DEFAULT_RESCAN_DPI

DEFAULT_OUT_DIR = Path("output")  # where the results go
DEFAULT_PDF_PATH = Path("extract_data/pdf_files")  # where to look for PDFs


def build_parser():
    """
    The command line parser.
    """
    ap = argparse.ArgumentParser(description="Extract Companies House accounts PDFs.")
    ap.add_argument("path", nargs="?", default=DEFAULT_PDF_PATH, help="a PDF file, or a folder of PDFs")
    ap.add_argument("--out", default=DEFAULT_OUT_DIR, help="output folder (default: output)")
    add_ocr_options(ap)
    ap.add_argument("--no-cache", action="store_true", help="ignore current stored OCR and re-run it")
    ap.add_argument("--rescan-dpi", type=int, default=DEFAULT_RESCAN_DPI,
                    help="re-read pages whose totals do not add up at this resolution; 0 turns it off "
                         "(default: %(default)s)")
    ap.add_argument("--text", action="store_true", help="also write <name>.txt, the raw text of each page")
    ap.add_argument("--force-ocr", action="store_true",
                    help="OCR every page even if the PDF has a text layer")
    ap.add_argument("--log", help=f"text file the results are logged to (default: <out>/{DEFAULT_LOG_NAME})")
    return ap


def report(pdf, json_path, parsed, facts):
    """Print where a PDF's results went, and its warnings."""
    print(f"{pdf.name} -> {json_path} "
          f"({len(facts)} figures, {len(parsed['warnings'])} warnings)")
    for warning in parsed["warnings"]:
        print(f" - {warning}")


def main(argv=None):
    """
    Command line entry point: read the command line, find the PDFs, and process each one.
    """
    args = build_parser().parse_args(argv)
    if 0 < args.rescan_dpi <= args.dpi:
        print(f"Note: --rescan-dpi {args.rescan_dpi} is not above --dpi {args.dpi}, so pages are not re-read.")

    # The target is either one PDF or a folder of PDFs.
    target = Path(args.path)
    pdfs = sorted(target.glob("*.pdf")) if target.is_dir() else [target]

    if not pdfs:
        sys.exit(f"No PDF files found at {target}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Process each PDF, report where the parsed JSON was saved, and log what was found.
    log_path = Path(args.log) if args.log else out_dir / DEFAULT_LOG_NAME
    failed = []
    with gpu.setting(not args.cpu):
        for pdf in pdfs:
            try:
                json_path, parsed, facts = process_pdf(
                    pdf, out_dir, args.dpi, not args.no_cache, use_text_layer=not args.force_ocr,
                    rescan_dpi=args.rescan_dpi, write_text=args.text)
            except Exception as error:  # one unreadable PDF must not stop the rest
                print(f"{pdf.name} FAILED: {type(error).__name__}: {error}")
                append_log(log_path, failure_entry(pdf.name, error))
                failed.append(pdf.name)
                continue
            report(pdf, json_path, parsed, facts)
            append_log(log_path, result_entry(pdf.name, parsed, facts))

    if failed:
        sys.exit(f"\n{len(failed)} of {len(pdfs)} PDFs failed: {', '.join(failed)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
