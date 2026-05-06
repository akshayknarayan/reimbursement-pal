import pymupdf

class PdfLocation:
    def __init__(self, page_num, tot_pages, x0, y0, x1, y1) -> None:
        self.page_num = page_num
        self.tot_pages = tot_pages
        # Store bounding box on page_num
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1

def find_text_in_pdf(receipt_pdf_path, text) -> PdfLocation:
    """
    Given a path to a PDF receipt, find the position of text on the page.

    Returns PdfLocation, containing (page_num, x0, y0, x1, y1).
    """
    with pymupdf.open(receipt_pdf_path) as pdf:
        tot_pages = len(pdf)
        for page_num, page in enumerate(pdf):
            return find_text_in_pdf_page(page, text, page_num=page_num, tot_pages=tot_pages)

    raise Exception(f"{text} not found in {receipt_pdf_path}")

def find_text_in_pdf_page(page: pymupdf.Page, text, page_num = 0, tot_pages=1) -> PdfLocation:
    """
    Given a PDF object, find the position of text on the page.

    Returns PdfLocation, containing (page_num, x0, y0, x1, y1).
    """
    text_instances = page.search_for(text)
    for inst in text_instances:
        return PdfLocation(page_num, tot_pages, inst.x0, inst.y0, inst.x1, inst.y1)
    raise Exception(f"{text} not found in {page}")

if __name__ == '__main__':
    import sys
    pdf_loc = find_text_in_pdf(sys.argv[1], sys.argv[2])
    print(f"found {sys.argv[2]} on page {pdf_loc.page_num}/{pdf_loc.tot_pages} at ({pdf_loc.x0}, {pdf_loc.y0}) -> ({pdf_loc.x1}, {pdf_loc.y1}) of {sys.argv[1]}")
