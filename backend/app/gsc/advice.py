"""Is a "why not indexed" reason worth fixing, or a waste of time?

Verdicts:
  fix    — real problem that costs traffic; prioritise it.
  review — depends on which pages are affected; check the list.
  ignore — expected behaviour; spending time here won't move rankings.
"""

from dataclasses import dataclass
from typing import Literal

Verdict = Literal["fix", "review", "ignore"]
VERDICT_ORDER: dict[str, int] = {"fix": 0, "review": 1, "ignore": 2}


@dataclass(frozen=True)
class Advice:
    verdict: Verdict
    summary: str  # one line: what's going on
    action: str  # what to do about it
    # This reason on a URL that's in the sitemap means the sitemap lists a URL that shouldn't be there.
    sitemap_cleanup: bool = False


_RULES: dict[str, Advice] = {
    "server error (5xx)": Advice(
        "fix",
        "Google tried to crawl these pages and your server failed.",
        "Check hosting/server logs and uptime for these URLs, fix the errors, then click Validate Fix in Search Console.",
    ),
    "redirect error": Advice(
        "fix",
        "Redirect loops, chains that are too long, or redirects to a bad URL.",
        "Point each URL straight to its final destination with a single 301 redirect.",
    ),
    "soft 404": Advice(
        "fix",
        "Pages return 200 OK but look empty or 'not found' to Google (e.g. out-of-stock or thin pages).",
        "Add real content, or return a proper 404/410, or 301 to the closest relevant page.",
    ),
    "duplicate without user-selected canonical": Advice(
        "fix",
        "Google sees these as duplicates and you haven't said which version is the main one.",
        "Add a rel=canonical tag pointing to the preferred URL on every duplicate.",
    ),
    "crawled - currently not indexed": Advice(
        "fix",
        "Google crawled these pages and decided they aren't worth indexing — usually a quality or uniqueness signal.",
        "For pages you want ranking: improve content depth/uniqueness and add internal links from strong pages. "
        "Low-value pages (tags, filters, thin pages) can be noindexed or removed instead.",
    ),
    "blocked due to access forbidden (403)": Advice(
        "fix",
        "Googlebot is being refused access (403) — often a firewall, CDN or bot-protection rule.",
        "If these pages are public, allow Googlebot in your firewall/CDN settings. If private, remove them from the sitemap.",
        sitemap_cleanup=True,
    ),
    "url is unknown to google": Advice(
        "review",
        "Google has no record of these URLs in its web index. Pages that only appear in Shopping results "
        "often show up here.",
        "Product, category and blog pages here should be indexed: link to them internally, keep them in the sitemap "
        "and request indexing in URL Inspection. Test, draft or campaign pages should be taken out of the sitemap instead.",
    ),
    "discovered - currently not indexed": Advice(
        "review",
        "Google knows the URLs but hasn't crawled them yet — often crawl budget or weak internal linking.",
        "For important pages, add internal links and keep them in the sitemap. For large sets of low-value URLs, it's usually fine to wait.",
    ),
    "excluded by 'noindex' tag": Advice(
        "review",
        "These pages tell Google not to index them.",
        "Fine for cart, account, thank-you and filter pages. If any page here should rank, remove the noindex tag. "
        "Noindexed pages shouldn't be in the sitemap.",
        sitemap_cleanup=True,
    ),
    "blocked by robots.txt": Advice(
        "review",
        "robots.txt stops Google from crawling these URLs.",
        "Fine for admin, search and cart URLs. If a page should rank, allow it in robots.txt.",
        sitemap_cleanup=True,
    ),
    "not found (404)": Advice(
        "review",
        "These URLs return 404.",
        "Ignore deleted pages nobody links to. 301-redirect ones that still get internal links, backlinks or traffic, "
        "and fix internal links pointing to them.",
        sitemap_cleanup=True,
    ),
    "duplicate, google chose different canonical than user": Advice(
        "review",
        "You set a canonical, but Google picked a different URL as the main version.",
        "Check the Google canonical for each page. If Google's choice is wrong, make the content more distinct "
        "and make internal links and the sitemap point to your preferred URL.",
    ),
    "blocked due to other 4xx issue": Advice(
        "review",
        "These URLs return a 4xx error other than 404/401/403.",
        "Check what each URL returns; fix the public ones, remove the rest from the sitemap.",
        sitemap_cleanup=True,
    ),
    "indexed, though blocked by robots.txt": Advice(
        "review",
        "Indexed without being crawled because robots.txt blocks it — Google shows it without a description.",
        "If it should rank, unblock it in robots.txt. If not, unblock it and add noindex so Google can see the tag.",
    ),
    "page with redirect": Advice(
        "ignore",
        "These URLs redirect elsewhere — Google indexes the destination instead. This is normal.",
        "No fix needed. Just update internal links and the sitemap to use the final URLs.",
        sitemap_cleanup=True,
    ),
    "alternate page with proper canonical tag": Advice(
        "ignore",
        "Duplicates correctly pointing to their main version — canonicals working as intended.",
        "Nothing to fix.",
        sitemap_cleanup=True,
    ),
    "blocked due to unauthorized request (401)": Advice(
        "ignore",
        "Password-protected pages; Google can't and shouldn't index them.",
        "Nothing to fix. Remove them from the sitemap if they're listed.",
        sitemap_cleanup=True,
    ),
}

_FALLBACK = Advice(
    "review",
    "Search Console reported this reason for these pages.",
    "Open a few of the URLs in Search Console's URL Inspection to see details.",
)


def normalize_reason(reason: str) -> str:
    """Match Search Console's wording regardless of quote/dash style, case or British spelling
    (UK/Indian-English accounts say "Alternative page…" and "unauthorised")."""
    return (
        reason.strip()
        .lower()
        .replace("‘", "'")
        .replace("’", "'")
        .replace("–", "-")
        .replace("—", "-")
        .replace("alternative page", "alternate page")
        .replace("unauthorised", "unauthorized")
    )


def advice_for(reason: str) -> Advice:
    return _RULES.get(normalize_reason(reason), _FALLBACK)
