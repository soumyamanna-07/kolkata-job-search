"""Automatic spam / scam check for jobs that employers post.

It never publishes or rejects anything by itself: it gives each post a 0-100 score
and the reasons, and the admin review queue shows the riskiest posts first.
Version "v1-rules". A trained classifier can replace it later (model_versions).
"""
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

SPAM_VERSION = "v1-rules"

FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com", "live.com", "rediffmail.com",
    "ymail.com", "aol.com", "icloud.com", "proton.me", "protonmail.com", "zoho.com", "mail.com",
}
LINK_SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "cutt.ly", "rb.gy", "is.gd", "shorturl.at", "tiny.cc"}
# well-known job boards / hiring tools, so an apply link there is not "a different website"
TRUSTED_APPLY_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "smartrecruiters.com", "workable.com",
                       "naukri.com", "linkedin.com", "indeed.com", "zohorecruit.com", "keka.com",
                       "darwinbox.in", "freshteam.com", "myworkdayjobs.com", "forms.gle", "docs.google.com")

FEE = re.compile(r"\b(registration|joining|security|processing|training|application|interview|kit)\s+"
                 r"(fee|fees|charge|charges|deposit)\b|\brefundable\s+deposit\b|\bpay\s+(a\s+)?(small\s+)?"
                 r"(fee|amount|deposit)\b", re.I)
EASY_MONEY = re.compile(r"\b(earn|income)\s+(rs\.?|inr|\u20b9)?\s?\d[\d,]*\s*(\+\s*)?(per|a|/)\s*(day|hour)\b|"
                        r"\bdaily\s+payment\b|\bno\s+target\b.*\bearn\b|\bwork\s+from\s+home\b.*\bearn\b", re.I)
CHAT_ONLY = re.compile(r"\b(whatsapp|telegram)\b", re.I)
SHOUTING = re.compile(r"[A-Z]{6,}")


@dataclass
class SpamResult:
    score: int
    reasons: list[str] = field(default_factory=list)


def _host(url: Optional[str]) -> str:
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _same_site(a: str, b: str) -> bool:
    """careers.abc.com and abc.com count as the same site."""
    return bool(a and b) and (a == b or a.endswith("." + b) or b.endswith("." + a))


def check(title: str, description: str, apply_url: str, official_email: str, website: Optional[str],
          salary_max: Optional[int] = None, experience_max: Optional[float] = None) -> SpamResult:
    text = f"{title}\n{description}"
    points: dict[str, int] = {}

    if FEE.search(text):
        points["asks_for_fee"] = 50                     # genuine employers never charge candidates
    if EASY_MONEY.search(text):
        points["easy_money_promise"] = 25
    apply_host = _host(apply_url)
    site_host = _host(website)
    email_domain = (official_email or "").rsplit("@", 1)[-1].lower()
    if apply_host in LINK_SHORTENERS:
        points["link_shortener"] = 25
    elif apply_host and not any(_same_site(apply_host, h) for h in (site_host, email_domain)) \
            and not any(apply_host == t or apply_host.endswith("." + t) for t in TRUSTED_APPLY_HOSTS):
        points["apply_link_on_other_site"] = 10
    if email_domain in FREE_EMAIL_DOMAINS:
        points["free_email_domain"] = 15
    if CHAT_ONLY.search(text):
        points["chat_app_contact"] = 15
    if salary_max and salary_max > 3_000_000 and (experience_max is not None and experience_max <= 1):
        points["unrealistic_salary"] = 25                # over Rs 30 lakh a year for a fresher
    if len(description.strip()) < 150:
        points["very_short_description"] = 10
    if len(SHOUTING.findall(text)) >= 3 or text.count("!!") >= 2:
        points["shouting_text"] = 10

    reasons = sorted(points, key=lambda r: -points[r])
    return SpamResult(score=min(100, sum(points.values())), reasons=reasons)
