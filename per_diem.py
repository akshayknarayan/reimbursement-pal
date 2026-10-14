import requests
import datetime
import functools
import os

GSA_API_BASE = "https://api.gsa.gov/travel/perdiem/v2/rates"

def fiscal_year(date: datetime.date) -> int:
    """
    GSA rates are published per federal fiscal year, which starts on Oct 1.
    """
    return date.year + 1 if date.month >= 10 else date.year

# cached so that previewing the per diem while editing doesn't repeat requests
@functools.cache
def lookup_mie_rate(location: str, year: int, api_key: str) -> tuple[float, str]:
    """
    Look up the daily M&IE (meals and incidental expenses) rate from GSA for a CONUS location.
    `location` is either a ZIP code or "City, ST".

    Returns (daily rate, name of the per diem locality).
    """
    location = location.strip()
    if location.isdigit():
        url = f"{GSA_API_BASE}/zip/{location}/year/{year}"
    else:
        city, _, state = location.rpartition(",")
        if not city:
            raise ValueError(f"Per diem location must be a ZIP code or 'City, ST': {location}")
        url = f"{GSA_API_BASE}/city/{city.strip()}/state/{state.strip()}/year/{year}"

    response = requests.get(url, params={"api_key": api_key}, timeout=30)
    if response.status_code == 429:
        raise Exception("GSA API rate limit exceeded; get a free API key at https://open.gsa.gov/api/perdiem/ and set GSA_API_KEY")
    response.raise_for_status()
    rates = [r for entry in response.json().get("rates", []) for r in entry.get("rate", [])]
    if not rates:
        raise Exception(f"No GSA per diem rate found for {location} in FY{year}")

    # A city search can match multiple localities; prefer the one named after the city searched for.
    rate = rates[0]
    for r in rates:
        if location.split(",")[0].strip().lower() in (r.get("city") or "").lower():
            rate = r
            break

    return float(rate["meals"]), rate.get("city") or location

@functools.cache
def first_last_day_rate(mie_rate: float, year: int, api_key: str) -> float:
    """
    The rate for the first and last day of travel is 75% of the full M&IE rate.
    GSA publishes this (rounded) in its M&IE breakdown table, so use that if possible.
    """
    try:
        response = requests.get(f"{GSA_API_BASE}/conus/mie/{year}", params={"api_key": api_key}, timeout=30)
        response.raise_for_status()
        for tier in response.json():
            if float(tier["total"]) == mie_rate:
                return float(tier["FirstLastDay"])
    except Exception as e:
        print(f"Warning: could not fetch GSA M&IE breakdown for FY{year}, computing 75% directly: {e}")
    return mie_rate * 0.75

def compute_per_diem(location: str, start: datetime.date, end: datetime.date, api_key: str | None = None) -> dict:
    """
    Compute the M&IE per diem for a trip to `location` from `start` to `end` (inclusive).
    The first and last days of travel are reimbursed at 75%.

    Returns a receipt-like dict (with no `path`, since there is no receipt to attach).
    """
    api_key = api_key or os.environ.get("GSA_API_KEY", "DEMO_KEY")
    if end < start:
        raise ValueError(f"Trip end {end} is before trip start {start}")

    rates = {}  # fiscal year -> (full rate, first/last day rate, locality)
    total = 0.0
    num_days = (end - start).days + 1
    for i in range(num_days):
        day = start + datetime.timedelta(days=i)
        fy = fiscal_year(day)
        if fy not in rates:
            full, locality = lookup_mie_rate(location, fy, api_key)
            rates[fy] = (full, first_last_day_rate(full, fy, api_key), locality)

        full, partial, _ = rates[fy]
        total += partial if (day == start or day == end) else full

    locality = next(iter(rates.values()))[2]
    full_rates = "/".join(f"${r[0]:,.0f}" for r in rates.values())
    days = "1 day" if num_days == 1 else f"{num_days} days"
    return {
        "path": None,
        "date": datetime.datetime.combine(start, datetime.time()),
        "summary": f"M&IE per diem: {locality}, {days} at {full_rates}/day",
        "amount": round(total, 2),
        "amount_coords": None,
        "category": "per diem",
    }

if __name__ == '__main__':
    import sys
    import dateparser
    print(compute_per_diem(sys.argv[1], dateparser.parse(sys.argv[2]).date(), dateparser.parse(sys.argv[3]).date()))
