from ocr_utils import extract_text_from_file
from pdf_locate import find_text_in_pdf
from llm_analyze import llm_analyze

from pypdf import PdfReader, PdfWriter

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
    Creates a Markdown file containing a table of receipts with links to amounts in the original PDFs.
    """
    lines = [
        "# Receipt Summary",
        "",
        "| Receipt Date |  Description | Amount |",
        "| :--- | :--- | :--- |"
    ]

    for receipt in receipt_data:
        # Note: process_receipts uses 'date, 'summary', and 'amount' in its dictionary
        date = receipt.get("date", datetime.date.today()).strftime("%d %b %Y")
        description = receipt.get("summary", "No Description")
        amount = receipt.get("amount", 0.0)
        coords = receipt.get("amount_coords", None)

        # Add PDF link only if coordinates were found
        if coords:
            page, x0, y0, x1, y1 = coords
            file_link = f"#page={page}&view=FitH&top={y0}&left={x0}"
            formatted_amount = f"[${amount:,.2f}]({file_link})"
        else:
            formatted_amount = f"${amount:,.2f}"

        lines.append(f"| {date} | {description} | {formatted_amount} |")

    grand_total = sum(item["amount"] for item in receipt_data)
    lines.append(f"| | **Grand Total** | **${grand_total:,.2f}** |")

    # We'll use a markdown file as intermediate, but the caller expects a pdf path
    # In a real scenario, you'd convert md to pdf here.
    # For now, we follow the prompt's structure of returning a path.
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
    return filename

def process_receipts(pdf_paths: list[str], model_name: str, ollama_url: str):
    receipt_data = []

    # print the table incrementally
    table = Table(title = "Receipts", expand=True)
    table.add_column("File", max_width=20)
    table.add_column("Date")
    table.add_column("Summary", max_width=40)
    table.add_column("Amount", justify="right")

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
                page_num_result, x0, y0, x1, y1 = find_text_in_pdf(path, str(amount))
                amount_coord = (page_num_result, x0, y0, x1, y1)
                receipt_data[-1]["amount_coords"] = amount_coord
            except Exception as e:
                print(f"Warning: Could not find coordinates for amount ${amount:.2f} in {path}: {e}")

            # print table row
            table.add_row(os.path.basename(path), date.strftime("%d %b %Y"), summary, f"${amount:>4.2f}")
            table_live.refresh()

    print(table)

    receipt_data.sort(key=lambda x: x['date'])

    return receipt_data

def write_combined_pdf(receipt_data: list[dict], output_pdf: str):
    writer = PdfWriter()

    for receipt in receipt_data:
        # Add the receipt pages to the writer
        reader = PdfReader(receipt['path'])
        for page in reader.pages:
            writer.add_page(page)

    grand_total = sum(item["amount"] for item in receipt_data)
    print(f"Grand Total: ${grand_total:.2f}")

    coverpage_fn = "./coverpage.pdf"
    make_cover_page(receipt_data, filename=coverpage_fn)
    reader = PdfReader(coverpage_fn)
    for page in reader.pages:
        writer.insert_page(page, index=0)

    # Save the concatenated PDF
    with open(output_pdf, "wb") as f:
        writer.write(f)
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

    write_combined_pdf(receipts, args.output)

if __name__ == "__main__":
   main()
