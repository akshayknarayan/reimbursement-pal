import argparse
import pdfplumber
import requests
from pypdf import PdfReader, PdfWriter

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
