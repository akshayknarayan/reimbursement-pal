import pdfplumber
import requests
from pypdf import PdfReader, PdfWriter

import argparse
import subprocess
import os

def llm_analyze(text: str, model_name: str, ollama_url: str):
    """
    Invokes an Ollama-hosted model to summarize text and extract the amount.
    """
    prompt = f"""
    Analyze the following text from a receipt.
    Provide a brief summary of the receipt and extract the total amount.
    Return the result in the following format:
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

        summary = "No summary available"
        amount = 0.0

        # Simple parsing logic
        for line in result.split('\n'):
            if line.startswith("Summary:"):
                summary = line.replace("Summary:", "").strip()
            elif line.startswith("Amount:"):
                amount_str = line.replace("Amount:", "").strip().replace("$", "").replace(",", "")
                try:
                    amount = float(amount_str)
                except ValueError:
                    amount = 0.0

        return summary, amount

    except Exception as e:
        print(f"Error during LLM analysis: {e}")
        return "Error analyzing receipt", 0.0

def extract_text_from_pdf(pdf_path: str) -> str:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"
    return text

def make_cover_page(receipt_data: list[dict], filename: str = "./coverpage.pdf") -> str:
    """
    Creates a Markdown file containing a table of receipts.
    """
    lines = [
        "# Receipt Summary",
        "",
        "| Description | Amount |",
        "| :--- | :--- |"
    ]

    for receipt in receipt_data:
        # Note: process_receipts uses 'summary' and 'amount' in its dictionary
        description = receipt.get("summary", "No Description")
        amount = receipt.get("amount", 0.0)
        lines.append(f"| {description} | ${amount:,.2f} |")

    grand_total = sum(item["amount"] for item in receipt_data)
    lines.append(f"| **Grand Total** | **${grand_total:,.2f}** |")

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

    for path in pdf_paths:
        print(f"Processing {path}...")
        text = extract_text_from_pdf(path)
        summary, amount = llm_analyze(text, model_name, ollama_url)
        receipt_data.append({
            "path": path,
            "summary": summary,
            "amount": amount
        })
        print(f"Processed {path}. Summary: {summary}, Amount: {amount}")

        # Add the receipt pages to the writer
        reader = PdfReader(path)
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
