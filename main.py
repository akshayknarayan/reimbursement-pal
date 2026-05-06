import pymupdf
from ocr_utils import extract_text_from_file
from pdf_locate import find_text_in_pdf, find_text_in_pdf_page
from llm_analyze import llm_analyze

from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich import print

import argparse
import datetime
import os
import subprocess
import pickle


def make_cover_page(receipt_data: list[dict], filename: str = "./coverpage.pdf") -> str:
    """
    Creates a Markdown file containing a table of receipts.
    This function only creates the cover page, so it cannot generate links from the coverpage to the receipts - must do this later.
    """
    lines = [
        "# Receipt Summary",
        "",
        "| Receipt Date |  Description | Amount |",
        "| :--- | :--- | :--- |"
    ]

    # First pass: create table without links
    for receipt in receipt_data:
        date = receipt.get("date", datetime.date.today()).strftime("%d %b %Y")
        description = receipt.get("summary", "No Description")
        amount = receipt.get("amount", 0.0)

        # Don't add PDF link yet - will be added in post-processing
        formatted_amount = f"${amount:,.2f}"
        lines.append(f"| {date} | {description} | {formatted_amount} |")

    grand_total = sum(item["amount"] for item in receipt_data)
    lines.append(f"| | **Grand Total** | **${grand_total:,.2f}** |")

    md_path = filename.replace(".pdf", ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # now convert the md to pdf with pandoc
    subprocess.check_call([
        "pandoc",
        "--pdf-engine", "tectonic",
        "-V", "colorlinks=true", "-V", "linkcolor=blue",
        "-o", filename,
        md_path])
    os.unlink(md_path)

    # Return pdf_path. Need to post-process later to add the links
    return filename

def add_links(receipt_data: list[dict], doc: pymupdf.Document):
    """
    Add links to the PDF in `writer` according to `amount_coords` in `receipt_data`.
    """
    # Get the first page (coverpage) which is where we'll add the links
    coverpage = doc[0]

    # First pass: determine all receipt positions
    curr_page_num = 1
    for receipt in receipt_data:
        # Skip if no amount coordinates
        if "amount_coords" not in receipt or receipt["amount_coords"] is None:
            continue

        amount_text = receipt["amount"]
        coverpage_loc = find_text_in_pdf_page(coverpage, str(amount_text))
        pdf_loc = receipt["amount_coords"]
        # Find the actual page number in our writer (excluding coverpage)
        target_page_num = curr_page_num + pdf_loc.page_num

        # Create the link annotation
        coverpage.insert_link({
            "kind": pymupdf.LINK_GOTO,
            "page": target_page_num,
            "from": pymupdf.Rect(coverpage_loc.x0, coverpage_loc.y0, coverpage_loc.x1, coverpage_loc.y1),
            "to": pymupdf.Point(pdf_loc.x0, pdf_loc.y0)
        })
        curr_page_num += pdf_loc.tot_pages

    print(f"Added links to coverpage")

def receipt_table():
    table = Table(title = "Receipts", expand=True)
    table.add_column("File", max_width=20)
    table.add_column("Date")
    table.add_column("Summary", max_width=40)
    table.add_column("Amount", justify="right")
    return table

def process_receipts(pdf_paths: list[str], model_name: str, ollama_url: str):
    receipt_data = []

    # print the table incrementally
    table = receipt_table()

    for path in pdf_paths:
        text = extract_text_from_file(path)
        num_bytes = len(text)
        if num_bytes > 10000:
            text = text[:10000]
            num_bytes = 10000
        text_lines = text.split('\n')
        num_lines = len(text_lines)

        # Use rich.Live to display text being processed
        with Live(table, transient=True, auto_refresh=False) as table_live:
            with Live(transient=True, refresh_per_second=1) as row_live:
                row_live.update(Panel(text, title=f"Processing {os.path.basename(path)[:15]} ({num_bytes} B, {num_lines} lines)", height=20, expand=False))
                date, summary, amount = llm_analyze(text, model_name, ollama_url)

            receipt_data.append({
                "path": path,
                "date": date,
                "summary": summary,
                "amount": amount,
                "amount_coords": None,
            })

            # Find amount coordinates for this receipt
            try:
                receipt_data[-1]["amount_coords"] = find_text_in_pdf(path, str(amount))
            except Exception as e:
                print(f"Warning: Could not find coordinates for amount ${amount:.2f} in {path}: {e}")

            # print table row
            table.add_row(os.path.basename(path), date.strftime("%d %b %Y"), summary, f"${amount:>4.2f}")
            table_live.refresh()

    print(table)

    receipt_data.sort(key=lambda x: x['date'])

    grand_total = sum(item["amount"] for item in receipt_data)
    print(f"Grand Total: ${grand_total:.2f}")

    return receipt_data

def write_combined_pdf(receipt_data: list[dict], output_pdf: str):
    doc = pymupdf.Document()

    # Make the initial coverpage
    coverpage_fn = "./coverpage.pdf"
    make_cover_page(receipt_data, filename=coverpage_fn)
    # Add the coverpage first
    doc.insert_pdf(pymupdf.open(coverpage_fn))

    # Add all the receipt pages to the writer
    for receipt in receipt_data:
        with pymupdf.open(receipt['path']) as pages:
            doc.insert_pdf(pages)

    # add links into the pdf
    add_links(receipt_data, doc)

    # Save the concatenated PDF
    doc.save(output_pdf)
    doc.close()

    # remove the temporary coverpage pdf
    os.unlink(coverpage_fn)
    print(f"\nConcatenated PDF saved to: {output_pdf}")

def main():
    parser = argparse.ArgumentParser(description="Process receipts for reimbursement.")
    parser.add_argument("--receipts", nargs="+", help="List of receipts to process")
    parser.add_argument("--resume", nargs="?", const="./rpal.pckl", default=None, help="Previous run to resume (save this run if previous not found)")
    parser.add_argument("--model", "-m", default="gemma4:e4b", help="Name of model to use")
    parser.add_argument("--url", "-u", default="http://localhost:11434/api/generate", help="URL serving model")
    parser.add_argument("--output", "-o", default="merged_receipts.pdf", help="Output PDF filename")

    args = parser.parse_args()

    if not args.receipts:
        print("No PDF files provided.")
        return

    if not args.resume or not os.path.exists(args.resume):
        receipts = process_receipts(args.receipts, args.model, args.url)
        with open(args.resume, 'wb') as f:
            pickle.dump(receipts, f)
    else:
        with open(args.resume, 'rb') as f:
            receipts = pickle.load(f)
        table = receipt_table()
        for r in receipts:
            table.add_row(os.path.basename(r['path']), r['date'].strftime("%d %b %Y"), r['summary'], f"${r['amount']:>4.2f}")
        print(table)

    write_combined_pdf(receipts, args.output)

if __name__ == "__main__":
   main()
