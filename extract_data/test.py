from extract_data.ocr import ocr_pdf, rows_to_lines

pages = ocr_pdf("11508952_aa_2025-09-23.pdf")

for number, page in enumerate(pages, start=1):
    print(f"Page {number}:")
    lines = rows_to_lines(page)
    for line in lines:
        print(line)
