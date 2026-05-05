import pymupdf

def find_text_in_pdf(receipt_pdf_path, text) -> tuple:
    """
    Given a PDF receipt, find the position of a numeric amount on the page.

    Returns (page_num, x0, y0, x1, y1).
    """
    with pymupdf.open(receipt_pdf_path) as pdf:
        for page_num, page in enumerate(pdf):
            text_instances = page.search_for(text)
            for inst in text_instances:
                x0 = inst.x0
                y0 = inst.y0
                x1 = inst.x1
                y1 = inst.y1
                # Store bounding box for the current page
                return (page_num + 1, x0, y0, x1, y1)  # page numbers + 1 to count cover page

    raise Exception(f"{text} not found in {receipt_pdf_path}")

if __name__ == '__main__':
    import sys
    page, x0,y0,x1,y1 = find_text_in_pdf(sys.argv[1], sys.argv[2])
    print(f"found {sys.argv[2]} on page {page} at ({x0}, {y0}) -> ({x1}, {y1}) of {sys.argv[1]}")
