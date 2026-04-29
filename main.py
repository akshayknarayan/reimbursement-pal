import argparse
import pdfplumber
from pypdf import PdfReader, PdfWriter

def llm_analyze(text: str):
    """
    Mock LLM function. In a real implementation, this would call an LLM API.
    """
    # Simple mock logic: just returning some dummy data
    # In a real scenario, this would use an LLM to summarize and extract the amount.
    return text[:10], 0.0

def extract_text_from_pdf(pdf_path: str) -> str:
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"
    return text

def process_receipts(pdf_paths: list[str], output_pdf: str):
    receipt_data = []
    writer = PdfWriter()

    for path in pdf_paths:
        print(f"Processing {path}...")
        text = extract_text_from_pdf(path)
        summary, amount = llm_analyze(text)
        receipt_data.append({
            "path": path,
            "summary": summary,
            "amount": amount
        })

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

    # Save the concatenated PDF
    with open(output_pdf, "wb") as f:
        writer.write(f)
    print(f"\nConcatenated PDF saved to: {output_pdf}")

    # Note: Creating a cover page with text would ideally require a library like reportlab.
    # For this initial implementation, we've focused on extraction and concatenation.

def main():
    parser = argparse.ArgumentParser(description="Process PDF receipts for reimbursement.")
    parser.add_argument("pdfs", nargs="+", help="List of PDF receipts to process")
    parser.add_argument("--output", "-o", default="merged_receipts.pdf", help="Output PDF filename")

    args = parser.parse_args()

    if not args.pdfs:
        print("No PDF files provided.")
        return

    process_receipts(args.pdfs, args.output)

if __name__ == "__main__":
   main()
