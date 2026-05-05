import dateparser
import requests
import datetime
import re

def llm_analyze(text: str, model_name: str, ollama_url: str) -> tuple[datetime.datetime, str, float]:
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
        date = datetime.datetime.now()
        summary = "No summary available"
        amount = 0.0

        response = requests.post(ollama_url, json=payload)
        response.raise_for_status()
        result = response.json().get("response", "")

        # Simple parsing logic
        for line in result.split('\n'):
            if line.startswith("Summary:"):
                summary = line.replace("Summary:", "").strip()
            elif line.startswith("Date:"):
                date_str = line.replace("Date:", "").strip().replace("$", "").replace(",", "")
                try:
                    date = dateparser.parse(date_str)
                    if date == None:
                        raise Exception(f"Could not parse date: {date_str}")
                except Exception as e:
                    date = datetime.datetime.now()
            elif line.startswith("Amount:"):
                amount_str = line.replace("Amount:", "").strip().replace("$", "").replace(",", "")
                amount_str = re.sub("[^0-9^.]", "", amount_str)
                try:
                    amount = float(amount_str)
                except ValueError as e:
                    print(f"Could not parse amount: {amount_str}: {e}")
                    amount = 0.0

        return date, summary, amount

    except Exception as e:
        print(f"Error during LLM analysis: {e}")
        raise e
