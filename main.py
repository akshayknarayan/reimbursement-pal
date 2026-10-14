import pymupdf
from ocr_utils import extract_text_from_file
from pdf_locate import find_text_in_pdf, find_text_in_pdf_page
from llm_analyze import llm_analyze
from per_diem import compute_per_diem

from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich import print

import argparse
import datetime
import dateparser
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
        # Entries without a receipt file (e.g., per diem) have nothing to link to
        if receipt.get("path") is None:
            continue

        # First link from coverpage summary to receipt start
        summary = receipt["summary"]
        coverpage_loc = find_text_in_pdf_page(coverpage, summary)
        coverpage_summary_rect = pymupdf.Rect(coverpage_loc.x0, coverpage_loc.y0, coverpage_loc.x1, coverpage_loc.y1)
        annot = coverpage.add_rect_annot(coverpage_summary_rect)
        annot.set_colors(stroke=(0.2,0.8,0.2))
        annot.update()
        coverpage.insert_link({
            "kind": pymupdf.LINK_GOTO,
            "page": curr_page_num,
            "from": coverpage_summary_rect,
            "to": pymupdf.Point(0, 0)
        })

        # Second link the amount coordinates
        if "amount_coords" not in receipt or receipt["amount_coords"] is None:
            continue

        amount_text = receipt["amount"]
        coverpage_loc = find_text_in_pdf_page(coverpage, str(amount_text))
        pdf_loc = receipt["amount_coords"]
        # Find the actual page number in our writer (excluding coverpage)
        target_page_num = curr_page_num + pdf_loc.page_num

        # Create the link annotation
        link_rect = pymupdf.Rect(coverpage_loc.x0, coverpage_loc.y0, coverpage_loc.x1, coverpage_loc.y1)
        annot = coverpage.add_rect_annot(link_rect)
        annot.set_colors(stroke=(0.2,0.8,0.2))
        annot.update()
        coverpage.insert_link({
            "kind": pymupdf.LINK_GOTO,
            "page": target_page_num,
            "from": link_rect,
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
                date, summary, amount, category, travel_start, travel_end = llm_analyze(text, model_name, ollama_url)

            receipt_data.append({
                "path": path,
                "date": date,
                "summary": summary,
                "amount": amount,
                "amount_coords": None,
                "category": category,
                "travel_start": travel_start,
                "travel_end": travel_end,
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
    return receipt_data

def add_per_diem(receipt_data: list[dict], location: str, trip_start: str | None, trip_end: str | None):
    """
    If none of the receipts are for food, add a GSA M&IE per diem entry for the trip.
    Trip dates default to the range of travel dates on the receipts (e.g., flight or hotel dates),
    falling back to the receipts' transaction dates if no receipt shows travel dates.
    """
    if any("category" not in r for r in receipt_data):
        print("[yellow]Warning: some receipts have no category (saved by an older version?); re-run without --resume to check for food receipts.[/yellow]")
    food = [r for r in receipt_data if r.get("category") == "food"]
    if food:
        print(f"Found {len(food)} food receipt(s); not adding per diem.")
        return

    travel = [r for r in receipt_data if r.get("travel_start") and r.get("travel_end")]
    if not travel and not (trip_start and trip_end):
        print("[yellow]Warning: no receipts show travel dates; using receipt transaction dates for the per diem. Pass --trip-start/--trip-end to override.[/yellow]")
    start = dateparser.parse(trip_start).date() if trip_start else \
        min(r["travel_start"] for r in travel).date() if travel else min(r["date"] for r in receipt_data).date()
    end = dateparser.parse(trip_end).date() if trip_end else \
        max(r["travel_end"] for r in travel).date() if travel else max(r["date"] for r in receipt_data).date()
    per_diem = compute_per_diem(location, start, end)
    print(f"No food receipts found; adding {per_diem['summary']} (${per_diem['amount']:,.2f})")
    receipt_data.append(per_diem)

def write_combined_pdf(receipt_data: list[dict], output_pdf: str):
    doc = pymupdf.Document()

    # Make the initial coverpage
    coverpage_fn = "./coverpage.pdf"
    make_cover_page(receipt_data, filename=coverpage_fn)
    # Add the coverpage first
    doc.insert_pdf(pymupdf.open(coverpage_fn))

    # Add all the receipt pages to the writer
    for receipt in receipt_data:
        if receipt.get("path") is None:
            continue
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
    parser.add_argument("--per-diem-location", help="Trip destination ('City, ST' or ZIP code). If given and no food receipts are found, adds a GSA M&IE per diem")
    parser.add_argument("--trip-start", help="First day of travel, for per diem (default: earliest travel date on the receipts)")
    parser.add_argument("--trip-end", help="Last day of travel, for per diem (default: latest travel date on the receipts)")

    args = parser.parse_args()

    if not args.receipts:
        print("No PDF files provided.")
        return

    if not args.resume or not os.path.exists(args.resume):
        receipts = process_receipts(args.receipts, args.model, args.url)
        if args.resume:
            with open(args.resume, 'wb') as f:
                pickle.dump(receipts, f)
    else:
        with open(args.resume, 'rb') as f:
            receipts = pickle.load(f)
        table = receipt_table()
        for r in receipts:
            table.add_row(os.path.basename(r['path']), r['date'].strftime("%d %b %Y"), r['summary'], f"${r['amount']:>4.2f}")
        print(table)

    if args.per_diem_location:
        add_per_diem(receipts, args.per_diem_location, args.trip_start, args.trip_end)

    receipts.sort(key=lambda x: x['date'])
    grand_total = sum(item["amount"] for item in receipts)
    print(f"Grand Total: ${grand_total:.2f}")

    write_combined_pdf(receipts, args.output)

if __name__ == "__main__":
   main()
