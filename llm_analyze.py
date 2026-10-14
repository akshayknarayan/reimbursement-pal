import dateparser
import requests
import datetime
import re

def llm_analyze(text: str, model_name: str, ollama_url: str) -> tuple[datetime.datetime, str, float, str, datetime.datetime | None, datetime.datetime | None]:
    """
    Invokes an Ollama-hosted model to summarize text, extract the amount, categorize the expense, and extract any travel dates.
    """
    prompt = f"""
    Analyze the following text from a receipt.
    Provide the date, a brief summary (between 4-8 words) of the receipt, and extract the total amount to reimburse.
    Also categorize the expense as exactly one of: food, lodging, transportation, other.
    Use "food" for restaurants, groceries, coffee, and any other meals or snacks.
    Also provide the travel dates the receipt covers, if any, which may differ from the purchase date:
    for example, a flight's departure and return dates, or a hotel's check-in and check-out dates.
    If the receipt covers a single day of travel, give that date as both start and end.
    If the receipt does not show any travel dates, write "none".
    Return the result in the following format:
    Date: <date>
    Summary: <summary>
    Amount: <amount>
    Category: <category>
    Travel dates: <start date> to <end date>

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
        category = "other"
        travel_start, travel_end = None, None

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
            elif line.startswith("Category:"):
                category = line.replace("Category:", "").strip().lower()
            elif line.startswith("Travel dates:"):
                travel_str = line.replace("Travel dates:", "").strip()
                if travel_str.lower() != "none":
                    start_str, _, end_str = travel_str.partition(" to ")
                    travel_start = dateparser.parse(start_str.strip())
                    travel_end = dateparser.parse(end_str.strip()) if end_str else travel_start
                    if travel_start is None or travel_end is None:
                        print(f"Could not parse travel dates: {travel_str}")
                        travel_start, travel_end = None, None

        return date, summary, amount, category, travel_start, travel_end

    except Exception as e:
        print(f"Error during LLM analysis: {e}")
        raise e
