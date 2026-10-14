import pymupdf
from ocr_utils import extract_text_from_file
from pdf_locate import find_text_in_pdf, find_text_in_pdf_page
from llm_analyze import llm_analyze
from per_diem import compute_per_diem

from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, FloatPrompt
from rich import print

import argparse
import datetime
import dateparser
import os
import subprocess
import pickle
import sys
from collections import Counter

CATEGORIES = ["food", "lodging", "transportation", "other"]


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
    table.add_column("#", justify="right")
    table.add_column("File", max_width=20)
    table.add_column("Date")
    table.add_column("Summary", max_width=40)
    table.add_column("Category")
    table.add_column("Amount", justify="right")
    return table

def add_receipt_row(table: Table, i: int, r: dict):
    table.add_row(str(i), os.path.basename(r['path']), r['date'].strftime("%d %b %Y"), r['summary'], r.get('category', '?'), f"${r['amount']:>4.2f}")

def print_receipts(receipt_data: list[dict]):
    table = receipt_table()
    for i, r in enumerate(receipt_data, 1):
        add_receipt_row(table, i, r)
    print(table)

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
                date, summary, amount, category, travel_start, travel_end, location = llm_analyze(text, model_name, ollama_url)

            receipt_data.append({
                "path": path,
                "date": date,
                "summary": summary,
                "amount": amount,
                "amount_coords": None,
                "category": category,
                "travel_start": travel_start,
                "travel_end": travel_end,
                "location": location,
            })

            # Find amount coordinates for this receipt
            try:
                receipt_data[-1]["amount_coords"] = find_text_in_pdf(path, str(amount))
            except Exception as e:
                print(f"Warning: Could not find coordinates for amount ${amount:.2f} in {path}: {e}")

            # print table row
            add_receipt_row(table, len(receipt_data), receipt_data[-1])
            table_live.refresh()

    print(table)
    receipt_data.sort(key=lambda x: x['date'])
    return receipt_data

def has_food(receipt_data: list[dict]) -> bool:
    return any(r.get("category") == "food" for r in receipt_data)

def default_trip_dates(receipt_data: list[dict]) -> tuple[datetime.date, datetime.date]:
    """
    The range of travel dates on the receipts (e.g., flight or hotel dates),
    falling back to the receipts' transaction dates if no receipt shows travel dates.
    """
    travel = [r for r in receipt_data if r.get("travel_start") and r.get("travel_end")]
    if travel:
        return min(r["travel_start"] for r in travel).date(), max(r["travel_end"] for r in travel).date()
    return min(r["date"] for r in receipt_data).date(), max(r["date"] for r in receipt_data).date()

def default_trip_city(receipt_data: list[dict]) -> str | None:
    """
    The most common location on the receipts, preferring lodging receipts since those best indicate where the trip was.
    """
    lodging = [r["location"] for r in receipt_data if r.get("location") and r.get("category") == "lodging"]
    locations = lodging or [r["location"] for r in receipt_data if r.get("location")]
    if not locations:
        return None
    return Counter(locations).most_common(1)[0][0]

def trip_settings(receipt_data: list[dict], trip: dict) -> tuple[str | None, datetime.date, datetime.date, bool]:
    """
    Resolve the trip city, start, end, and whether to include per diem. Unset (None) values in `trip` are derived from the receipts.
    """
    city = trip["city"] or default_trip_city(receipt_data)
    default_start, default_end = default_trip_dates(receipt_data)
    start = trip["start"] or default_start
    end = trip["end"] or default_end
    include = trip["per_diem"] if trip["per_diem"] is not None else (not has_food(receipt_data) and bool(city))
    return city, start, end, include

def per_diem_preview(receipt_data: list[dict], trip: dict) -> tuple[dict | None, str | None]:
    """
    Compute the per diem entry for the trip (whether or not it's included). Returns (entry, error message).
    """
    city, start, end, _ = trip_settings(receipt_data, trip)
    if not city:
        return None, None
    try:
        return compute_per_diem(city, start, end), None
    except Exception as e:
        return None, str(e)

def print_trip(receipt_data: list[dict], trip: dict, per_diem: dict | None, per_diem_error: str | None):
    city, start, end, include = trip_settings(receipt_data, trip)
    auto = lambda key: "" if trip[key] is not None else " [dim](auto)[/dim]"
    if trip["per_diem"] is None:
        why = "food receipts found" if has_food(receipt_data) else ("no food receipts" if city else "no city set")
        include_str = f"{'yes' if include else 'no'} [dim](auto: {why})[/dim]"
    else:
        include_str = "yes" if include else "no"

    if per_diem_error:
        amount_str = f"[red]{per_diem_error}[/red]"
    elif per_diem:
        amount_str = f"${per_diem['amount']:,.2f} [dim]({per_diem['summary']})[/dim]"
        if not include:
            amount_str += " [dim](not included)[/dim]"
    else:
        amount_str = "[dim](set a city)[/dim]"

    receipts_total = sum(r["amount"] for r in receipt_data)
    if include and per_diem:
        total_str = f"${receipts_total:,.2f} receipts + ${per_diem['amount']:,.2f} per diem = [bold]${receipts_total + per_diem['amount']:,.2f}[/bold]"
    else:
        total_str = f"[bold]${receipts_total:,.2f}[/bold]"

    print(Panel(
        f"City:     {(city + auto('city')) if city else '[dim](not set)[/dim]'}\n"
        f"Start:    {start.strftime('%d %b %Y')}{auto('start')}\n"
        f"End:      {end.strftime('%d %b %Y')}{auto('end')}\n"
        f"Per diem: {include_str}\n"
        f"Amount:   {amount_str}\n"
        f"Total:    {total_str}",
        title="Trip", expand=False))

def prompt_date(label: str, current: datetime.date | None) -> datetime.date | None:
    """
    Prompt for a date; an empty answer keeps the current value, and "auto" resets to automatic (None).
    """
    while True:
        answer = Prompt.ask(f"{label} ('auto' to derive from receipts)", default=current.isoformat() if current else "auto")
        if answer.strip().lower() == "auto":
            return None
        parsed = dateparser.parse(answer)
        if parsed:
            return parsed.date()
        print(f"[red]Could not parse date: {answer}[/red]")

def edit_receipt(receipt: dict):
    receipt["summary"] = Prompt.ask("Summary", default=receipt["summary"])
    receipt["category"] = Prompt.ask("Category", choices=CATEGORIES, default=receipt.get("category") if receipt.get("category") in CATEGORIES else "other")
    amount = FloatPrompt.ask("Amount", default=receipt["amount"])
    if amount != receipt["amount"]:
        receipt["amount"] = amount
        # the old coordinates point at the old amount
        try:
            receipt["amount_coords"] = find_text_in_pdf(receipt["path"], str(amount))
        except Exception:
            receipt["amount_coords"] = None

def review(receipt_data: list[dict], trip: dict) -> bool:
    """
    Interactively edit receipts and trip settings. Returns False if the user quits.
    """
    help_text = "[bold]<n>[/bold] edit receipt n, [bold]c[/bold] city, [bold]s[/bold] start, [bold]e[/bold] end, [bold]p[/bold] toggle per diem, [bold]d[/bold] done, [bold]q[/bold] quit"
    while True:
        per_diem, per_diem_error = per_diem_preview(receipt_data, trip)
        print_receipts(receipt_data)
        print_trip(receipt_data, trip, per_diem, per_diem_error)
        print(help_text)
        cmd = Prompt.ask("Command", default="d").strip().lower()
        if cmd.isdigit() and 1 <= int(cmd) <= len(receipt_data):
            edit_receipt(receipt_data[int(cmd) - 1])
        elif cmd == "c":
            city = Prompt.ask("City ('City, ST' or ZIP code, 'auto' to guess from receipts)", default=trip["city"] or "auto").strip()
            trip["city"] = None if city.lower() in ("", "auto") else city
        elif cmd == "s":
            trip["start"] = prompt_date("Trip start", trip["start"])
        elif cmd == "e":
            trip["end"] = prompt_date("Trip end", trip["end"])
        elif cmd == "p":
            trip["per_diem"] = not trip_settings(receipt_data, trip)[3]
        elif cmd == "d":
            _, _, _, include = trip_settings(receipt_data, trip)
            if include and not per_diem:
                print(f"[red]Can't compute per diem: {per_diem_error or 'set a city (c)'}. Fix it or turn off per diem (p).[/red]")
                continue
            return True
        elif cmd == "q":
            return False
        else:
            print(f"[red]Unknown command: {cmd}[/red]")

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

    args = parser.parse_args()

    if not args.receipts:
        print("No PDF files provided.")
        return

    # trip settings; None means derive from the receipts
    trip = {"city": None, "start": None, "end": None, "per_diem": None}
    if not args.resume or not os.path.exists(args.resume):
        receipts = process_receipts(args.receipts, args.model, args.url)
    else:
        with open(args.resume, 'rb') as f:
            saved = pickle.load(f)
        # older saves are just the list of receipts
        receipts, trip = (saved["receipts"], saved["trip"]) if isinstance(saved, dict) else (saved, trip)
        receipts.sort(key=lambda x: x['date'])
        if any("category" not in r for r in receipts):
            print("[yellow]Warning: some receipts have no category (saved by an older version?); re-run without --resume to check for food receipts.[/yellow]")

    if sys.stdin.isatty():
        done = review(receipts, trip)
    else:
        print_receipts(receipts)
        done = True

    if args.resume:
        with open(args.resume, 'wb') as f:
            pickle.dump({"receipts": receipts, "trip": trip}, f)
    if not done:
        return

    output = list(receipts)
    city, start, end, include = trip_settings(receipts, trip)
    if include:
        per_diem = compute_per_diem(city, start, end)
        print(f"Adding {per_diem['summary']} (${per_diem['amount']:,.2f})")
        output.append(per_diem)

    output.sort(key=lambda x: x['date'])
    grand_total = sum(item["amount"] for item in output)
    print(f"Grand Total: ${grand_total:.2f}")

    write_combined_pdf(output, args.output)

if __name__ == "__main__":
   main()
