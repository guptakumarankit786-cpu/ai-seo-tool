"""Brand vs non-brand query classification.

A query is "brand" if, after lower-casing and removing spaces/punctuation, it contains any of
the property's brand terms (normalised the same way). So the term "acme co" matches
"acmeco", "Acme-Co shoes" and "acme co store".
"""

import re
from urllib.parse import urlsplit

from sqlalchemy import ColumnElement, false, or_

MAX_TERMS = 50
MAX_TERM_LENGTH = 100

# Hosting/marketing words that make poor brand terms on their own.
_GENERIC_LABELS = {"www", "shop", "store", "blog", "m", "app", "en", "in"}


def normalize(text: str) -> str:
    """Lower-case and strip whitespace/punctuation — mirrors gsc_query_metrics.query_norm."""
    return re.sub(r"[\s\W_]+", "", text.lower())


def clean_terms(terms: list[str]) -> list[str]:
    """Trim, drop blanks/duplicates (by normalised form), cap count and length."""
    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        term = term.strip()[:MAX_TERM_LENGTH]
        key = normalize(term)
        if key and key not in seen:
            seen.add(key)
            out.append(term)
    return out[:MAX_TERMS]


def suggest_terms(site_url: str) -> list[str]:
    """Best-guess brand term from the domain, e.g. 'sc-domain:my-brand.co.in' -> ['my-brand']."""
    if site_url.startswith("sc-domain:"):
        host = site_url.removeprefix("sc-domain:")
    else:
        host = urlsplit(site_url).hostname or ""
    labels = [label for label in host.lower().split(".") if label and label not in _GENERIC_LABELS]
    # The registrable name is the first remaining label ("brand" in brand.co.in / shop.brand.com).
    return [labels[0]] if len(labels) >= 2 else labels[:1]


def brand_condition(norm_column, terms: list[str]) -> ColumnElement[bool]:
    """SQL condition: an already-normalised query column (query_norm) matches any brand term."""
    keys = [normalize(t) for t in terms if normalize(t)]
    if not keys:
        return false()
    return or_(*(norm_column.contains(key, autoescape=True) for key in keys))


def effective_terms(brand_terms: list[str] | None, site_url: str) -> list[str]:
    """Saved terms, or the domain-based suggestion when the user hasn't set any yet."""
    return brand_terms if brand_terms is not None else suggest_terms(site_url)


def is_brand(query: str, terms: list[str]) -> bool:
    norm = normalize(query)
    return any(key in norm for key in (normalize(t) for t in terms) if key)
