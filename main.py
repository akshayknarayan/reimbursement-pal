from ocr_utils import extract_text_from_pdf_or_images
import dateparser
import pdfplumber
from pypdf import PdfReader, PdfWriter
import requests

import argparse
import datetime
import os
import subprocess

def llm_analyze(text: str, model_name: str, ollama_url: str):
    """
    Invokes an Ollama-hosted model to summarize text and extract the amount.
    """
    prompt = f"""
    Analyze the following text from a receipt.
    Provide the date, a brief summary (between 4-8 words) of the receipt, and extract the total amount.
    Return the result in the following format:
    Date: <date>
    Summary: <summary>
    Amount: <amount>

    Text:
    {text}
    """

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False
    }

    try:
        response = requests.post(ollama_url, json=payload)
        response.raise_for_status()
        result = response.json().get("response", "")

        date = datetime.date.today()
        summary = "No summary available"
        amount = 0.0

        # Simple parsing logic
        for line in result.split('\n'):
            if line.startswith("Summary:"):
                summary = line.replace("Summary:", "").strip()
            elif line.startswith("Date:"):
                date_str = line.replace("Date:", "").strip().replace("$", "").replace(",", "")
                try:
                    date = dateparser.parse(date_str)
                except:
                    date = datetime.date.today()
            elif line.startswith("Amount:"):
                amount_str = line.replace("Amount:", "").strip().replace("$", "").replace(",", "")
                try:
                    amount = float(amount_str)
                except ValueError:
                    amount = 0.0

        return date, summary, amount

    except Exception as e:
        print(f"Error during LLM analysis: {e}")
        raise e

def extract_text_from_file(file_path: str) -> str:
    """
    Extracts text from a PDF or image using both digital extraction and OCR if necessary.
    """
    is_pdf = file_path.lower().endswith(".pdf")
    try:
        # First attempt: Use pdfplumber for digital text extraction if it's a PDF
        text = ""
        if is_pdf:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"

        # If text is empty or very short, or if it's an image, try OCR
        if not text.strip() or not is_pdf:
            print(f"Low text density or image detected in {file_path}, attempting OCR...")
            text = extract_text_from_pdf_or_images(file_path, is_pdf=is_pdf)

        return text
    except Exception as e:
        print(f"Error extracting text from {file_path}: {e}")
        # Fallback to OCR if initial attempt fails
        try:
            return extract_text_from_pdf_or_images(file_path, is_pdf=is_pdf)
        except Exception as ocr_e:
            print(f"OCR fallback also failed: {ocr_e}")
            return ""

def make_cover_page(receipt_data: list[dict], filename: str = "./coverpage.pdf") -> str:
    """
    Creates a Markdown file containing a table of receipts.
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
        lines.append(f"| {date} | {description} | ${amount:,.2f} |")

    grand_total = sum(item["amount"] for item in receipt_data)
    lines.append(f"| | **Grand Total** | **${grand_total:,.2f}** |")

    # We'll use a markdown file as intermediate, but the caller expects a pdf path
    # In a real scenario, you'd convert md to pdf here.
    # For now, we follow the prompt's structure of returning a path.
    md_path = filename.replace(".pdf", ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # now convert the md to pdf with pandoc
    subprocess.check_call(["pandoc", "--pdf-engine", "tectonic", "-o", filename, md_path])
    os.unlink(md_path)
    return filename

def process_receipts(pdf_paths: list[str], output_pdf: str, model_name: str, ollama_url: str):
    receipt_data = []
    writer = PdfWriter()

    print(f"| {'File':<15} | {'Date':<10} | {'Summary':<40} | {'Amount':>6} |")

    for path in pdf_paths:
        print(f"| {os.path.basename(path)} ", end='|')
        text = extract_text_from_file(path)
        date, summary, amount = llm_analyze(text, model_name, ollama_url)
        receipt_data.append({
            "path": path,
            "date": date,
            "summary": summary,
            "amount": amount
        })
        print(f"{date:<10} | {summary:<40} | {amount:>6} |")

    receipt_data.sort(key=lambda x: x['date'])

    for receipt in receipt_data:
        # Add the receipt pages to the writer
        reader = PdfReader(receipt['path'])
        for page in reader.pages:
            writer.add_page(page)

    grand_total = sum(item["amount"] for item in receipt_data)

    # Print summary to console
    print("\n--- Reimbursement Summary ---")
    for item in receipt_data:
        print(f"Receipt: {item['path']} | Summary: {item['summary']} | Amount: ${item['amount']:.2f}")
    print(f"-----------------------------")
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
    parser = argparse.ArgumentParser(description="Process PDF receipts for reimbursement.")
    parser.add_argument("pdfs", nargs="+", help="List of PDF receipts to process")
    parser.add_argument("--model", "-m", default="gemma4:26b", help="Name of model to use")
    parser.add_argument("--url-ollama", "-u", default="http://localhost:11434/api/generate", help="Ollama URL serving model")
    parser.add_argument("--output", "-o", default="merged_receipts.pdf", help="Output PDF filename")

    args = parser.parse_args()

    if not args.pdfs:
        print("No PDF files provided.")
        return

    process_receipts(args.pdfs, args.output, args.model, args.url_ollama)

if __name__ == "__main__":
   main()
