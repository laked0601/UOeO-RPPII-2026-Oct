"""
Main entry point for the extract_data package.

For every PDF this runs the pipeline  OCR -> parse and writes
into the output folder:
    <name>.ocr.json   cached OCR result (re-used on later runs)
    <name>.txt        raw OCR text, page by page, for auditing
    <name>.json       parsed data
"""

import argparse
import json
import sys
from pathlib import Path

from extract_data.ocr import ocr_pdf, rows_to_lines
from extract_data.parse import parse_accounts

# Defaults
default_dpi = 300  # default render resolution for OCR
default_out_dir = Path("output")  # default output folder
default_pdf_path = Path("extract_data/pdf_files")  # default path to look for PDFs


def process_pdf(pdf_path, out_dir, dpi, use_cache):
    """Run the full pipeline for one PDF and return the parsed result."""
    pages = ocr_pdf(pdf_path, out_dir, dpi=dpi, use_cache=use_cache)
    pages_lines = [rows_to_lines(p) for p in pages]

    # Raw text dump so a human can compare against the original scan.
    raw = "\n".join(f"PAGE {i}\n" + "\n".join(lines)
                    for i, lines in enumerate(pages_lines, 1))
    (out_dir / f"{pdf_path.stem}.txt").write_text(raw, encoding="utf-8")

    # Parse the OCR results and save them as JSON
    parsed = parse_accounts(pages_lines, source_file=pdf_path.name)
    json_path = out_dir / f"{pdf_path.stem}.json"
    json_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
    return json_path, parsed


def main():
    """
    Command line Entry point: read the command line, find the PDFs, and process each one.
    """
    # Build the command line parser and read the arguments.
    ap = argparse.ArgumentParser(description="Extract Companies House accounts PDFs.")
    ap.add_argument("path", nargs="?", default=default_pdf_path, help="a PDF file, or a folder of PDFs")
    ap.add_argument("--out", default=default_out_dir, help="output folder (default: output)")
    ap.add_argument("--dpi", type=int, default=default_dpi, help="render resolution for OCR")
    ap.add_argument("--no-cache", action="store_true", help="ignore current stored OCR and re-run it")
    # Read the command line arguments.
    args = ap.parse_args()

    # Find the PDFs to process, either a single file or all PDFs in a folder.
    target = Path(args.path)

    # If the target is a directory, find all PDFs in it; if it's a file, just use that one.
    pdfs = sorted(target.glob("*.pdf")) if target.is_dir() else [target]

    # If no PDFs were found, exit with an error message.
    if not pdfs:
        sys.exit(f"No PDF files found at {target}")

    # Create the output directory if it doesn't exist, and process each PDF.
    out_dir = Path(args.out)
    # Create the output directory if it doesn't exist
    out_dir.mkdir(parents=True, exist_ok=True)
    # Process each PDF and report where the parsed JSON was saved.
    for pdf in pdfs:
        json_path, parsed = process_pdf(pdf, out_dir, args.dpi, not args.no_cache)
        print(f"{pdf.name} -> {json_path} ({len(parsed['warnings'])}) warnings)")
        for warning in parsed["warnings"]:
            print(f" - {warning}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
