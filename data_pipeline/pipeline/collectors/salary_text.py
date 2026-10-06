"""Read a salary written as text, e.g. "Rs 3,00,000 - 5,00,000 a year", "15k-20k per month", "6-8 LPA"."""
import re
from typing import Optional

NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k|lakhs?|lacs?|lpa|l)?(?![a-z])", re.I)
MULTIPLIER = {"k": 1_000, "l": 100_000, "lpa": 100_000, "lakh": 100_000, "lakhs": 100_000,
              "lac": 100_000, "lacs": 100_000}
LAKH_WORDS = re.compile(r"\b(lpa|lakhs?|lacs?)\b")
INR_WORDS = re.compile(r"\b(rs|inr)\b|\u20b9|\blpa\b|\blakhs?\b|\blacs?\b")


def parse_salary(text: Optional[str]) -> dict:
    """{min, max, currency, period}, or {} when no salary is given."""
    lower = (text or "").strip().lower()
    found = NUMBER.findall(lower)[:2]                       # "6-8 LPA": the unit after 8 counts for 6 too
    shared_unit = next((unit for _, unit in reversed(found) if unit), "")
    values = [float(number.replace(",", "")) * MULTIPLIER.get((unit or shared_unit).lower(), 1)
              for number, unit in found]
    values = [v for v in values if v >= 1000]               # skip "2 years", "5 days" etc.
    if not values:
        return {}
    if LAKH_WORDS.search(lower):
        period = "year"
    else:
        period = "month" if "month" in lower else "hour" if "hour" in lower else "year"
    currency = "INR" if INR_WORDS.search(lower) else ("USD" if "$" in lower else "INR")
    return {"min": min(values), "max": max(values), "currency": currency, "period": period}
