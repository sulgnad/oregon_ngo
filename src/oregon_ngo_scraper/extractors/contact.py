"""Extraction of street address, phone and email from HTML.

Like :mod:`.mission`, this module performs no I/O — it operates on HTML
strings supplied by the caller, so unit tests exercise it directly against
fixture pages.

Strategies are tried in descending order of confidence:

1. **JSON-LD** — ``PostalAddress`` / ``telephone`` / ``email`` on an
   ``Organization``-like node. This is structured data the site author
   published deliberately, so it is trusted over anything inferred.
2. **Markup affordances** — ``<address>`` elements, and ``tel:`` / ``mailto:``
   link hrefs. Still explicit, but not typed.
3. **Free-text regex** — a US phone number, and a street line terminating in
   an Oregon ZIP. Lowest confidence: a page footer may carry a mailing
   address for a different office, so results are treated as provisional.

Output is normalized to the conventions of the target dataset: phone as
``(541) 555-1234`` and address as a single comma-separated line such as
``123 SE Main St, Madras, OR 97741``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable

from bs4 import BeautifulSoup

from ..models import FetchedPage


@dataclass
class ContactResult:
    """Outcome of running :class:`ContactExtractor` over a set of pages."""

    address: str | None = None
    phone: str | None = None
    email: str | None = None
    source_url: str | None = None
    strategies: list[str] = field(default_factory=list)


@dataclass
class _Candidate:
    """One extracted value, with context for ranking against rivals."""

    value: str
    strategy: str
    source_url: str
    explicit: bool
    context: str = ""


# --- patterns ---------------------------------------------------------------

#: US phone numbers: "(541) 555-1234", "541-555-1234", "541.555.1234",
#: optionally with a leading +1. Word boundaries keep us from slicing digits
#: out of a longer number such as an EIN or a ZIP+4.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]*)?\(?([2-9]\d{2})\)?[\s.-]*(\d{3})[\s.-]*(\d{4})(?!\d)"
)

#: A street line ending in an Oregon ZIP. Oregon ZIPs are 97xxx.
#: Example: "123 SE Main St Suite 4, Madras, OR 97741".
#:
#: Street and city are matched as one non-greedy blob rather than as separate
#: groups: real pages punctuate them inconsistently ("1130 SW Hwy 97 Madras OR
#: 97741" has no commas at all), and the trailing state + ZIP is a strong
#: enough anchor on its own. ``_tidy_address`` re-inserts the missing comma.
_ADDRESS_RE = re.compile(
    r"\d{1,6}\s+"                  # street number
    r"[A-Za-z0-9.,'#\-/ ]{3,100}?"  # street + unit + city, non-greedy
    r",?\s*"                       # optional comma before the state
    r"(?:OR|Oregon)\s*"            # state
    r"(97\d{3})(?:-\d{4})?",       # ZIP
    re.IGNORECASE,
)

#: A real street line names a street type, a directional, a highway or a PO
#: box. Requiring one rejects fragments where the regex latched onto a bare
#: number followed by the city ("489 Tillamook, OR 97141").
_STREET_TOKEN_RE = re.compile(
    r"(?i)(?<!\w)(?:"
    r"st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|way|ct"
    r"|court|pl|place|hwy|highway|loop|ter|terrace|cir|circle|pkwy|parkway"
    r"|box|suite|ste|apt|unit|bldg|building"
    r"|ne|nw|se|sw"
    r")(?!\w)"
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_WS_RE = re.compile(r"\s+")

#: Emails that belong to the site vendor / CMS rather than the organization.
_EMAIL_NOISE = (
    "example.com",
    "sentry.io",
    "wixpress.com",
    "squarespace.com",
    "wordpress.com",
    "godaddy.com",
    "@2x",
)

#: Role mailboxes that reach whoever runs the website or mail server, not the
#: organization's programs. A county site's footer typically carries
#: ``webmaster@`` on every page, which would otherwise win as "the" email for
#: a department that has no published address of its own. Matched on the
#: whole local part, so ``info@`` and ``admin@`` (often the real contact for
#: small orgs) are still accepted.
_EMAIL_ROLE_LOCALPARTS = frozenset(
    {
        "webmaster",
        "postmaster",
        "hostmaster",
        "abuse",
        "noreply",
        "no-reply",
        "donotreply",
        "do-not-reply",
        "mailer-daemon",
    }
)

#: Free-mail providers. Small nonprofits sometimes use them, so these are
#: accepted even when they don't match the org's own domain.
_FREEMAIL_DOMAINS = frozenset(
    {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com"}
)

#: Numbers that are never a usable contact line.
_PHONE_NOISE = ("000", "111", "123")

_OREGON_AREA_CODES = frozenset({"458", "503", "541", "971"})

_ORG_JSONLD_TYPES = {
    "Organization",
    "NGO",
    "LocalBusiness",
    "NonprofitOrganization",
    "CharitableOrganization",
    "GovernmentOrganization",
    "MedicalOrganization",
    "Place",
}


class ContactExtractor:
    """Pull address / phone / email from a list of fetched pages.

    Rather than taking the first match, every candidate across every page is
    collected and then ranked. This matters because a regional agency's site
    may lead with its headquarters, while the county row should represent a
    local office.

    ``cities``, when given, is a hard filter for addresses: a row in a county
    dataset exists to say where to go in that county, so recording a regional
    agency's out-of-county headquarters is worse than recording nothing.
    Phones are only ranked by it, not filtered — a central intake line is
    useful regardless of which office answers it.

    ``domain`` rejects third-party emails from partner footers and embedded
    widgets.
    """

    def extract(
        self,
        pages: Iterable[FetchedPage],
        *,
        cities: Iterable[str] = (),
        domain: str | None = None,
    ) -> ContactResult:
        preferred = {c.strip().lower() for c in cities if c and c.strip()}
        addresses: list[_Candidate] = []
        phones: list[_Candidate] = []
        emails: list[_Candidate] = []

        for page in pages:
            try:
                soup = BeautifulSoup(page.html, "lxml")
            except Exception:  # pragma: no cover - defensive
                continue
            page_text = _collapse(soup.get_text(" ", strip=True))
            self._collect_jsonld(soup, page, page_text, addresses, phones, emails)
            self._collect_markup(soup, page, page_text, addresses, phones, emails)
            self._collect_text(page_text, page, addresses, phones)

        address_candidates = [
            c for c in addresses if not preferred or _names_city(c.value, preferred)
        ]
        best_address = _best(
            address_candidates, key=lambda c: _address_score(c, preferred)
        )
        best_phone = _best(phones, key=lambda c: _phone_score(c, preferred))
        best_email = _best(
            [c for c in emails if _email_allowed(c.value, domain)],
            key=lambda c: _email_score(c, domain),
        )

        result = ContactResult(
            address=best_address.value if best_address else None,
            phone=best_phone.value if best_phone else None,
            email=best_email.value if best_email else None,
        )
        for chosen in (best_address, best_phone, best_email):
            if chosen is not None:
                result.source_url = result.source_url or chosen.source_url
                if chosen.strategy not in result.strategies:
                    result.strategies.append(chosen.strategy)
        return result

    # -- strategy 1: JSON-LD -------------------------------------------------

    def _collect_jsonld(
        self,
        soup: BeautifulSoup,
        page: FetchedPage,
        page_text: str,
        addresses: list[_Candidate],
        phones: list[_Candidate],
        emails: list[_Candidate],
    ) -> None:
        for node in _iter_org_jsonld_nodes(soup):
            address = _format_postal_address(node.get("address"))
            if address:
                addresses.append(
                    _Candidate(address, "jsonld_address", page.url, True, page_text)
                )
            phone = _normalize_phone(node.get("telephone"))
            if phone:
                phones.append(
                    _Candidate(phone, "jsonld_phone", page.url, True, page_text)
                )
            email = _clean_email(node.get("email"))
            if email:
                emails.append(
                    _Candidate(email, "jsonld_email", page.url, True, page_text)
                )

    # -- strategy 2: markup affordances --------------------------------------

    def _collect_markup(
        self,
        soup: BeautifulSoup,
        page: FetchedPage,
        page_text: str,
        addresses: list[_Candidate],
        phones: list[_Candidate],
        emails: list[_Candidate],
    ) -> None:
        for link in soup.find_all("a", href=True):
            href = link["href"].strip()
            lowered = href.lower()
            if lowered.startswith("tel:"):
                phone = _normalize_phone(href[4:])
                if phone:
                    context = _collapse(link.parent.get_text(" ", strip=True))
                    phones.append(
                        _Candidate(phone, "tel_link_phone", page.url, True, context)
                    )
            elif lowered.startswith("mailto:"):
                email = _clean_email(href[7:].split("?")[0])
                if email:
                    context = _collapse(link.parent.get_text(" ", strip=True))
                    emails.append(
                        _Candidate(email, "mailto_link_email", page.url, True, context)
                    )
        for tag in soup.find_all("address"):
            text = _collapse(tag.get_text(" ", strip=True))
            address = _find_address(text) or (
                text if _looks_like_address(text) else None
            )
            if address:
                addresses.append(
                    _Candidate(address, "address_tag", page.url, True, text)
                )

    # -- strategy 3: free text -----------------------------------------------

    def _collect_text(
        self,
        text: str,
        page: FetchedPage,
        addresses: list[_Candidate],
        phones: list[_Candidate],
    ) -> None:
        for address in _find_addresses(text):
            addresses.append(_Candidate(address, "text_address", page.url, False, text))
        for phone in _find_phones(text):
            phones.append(_Candidate(phone, "text_phone", page.url, False, text))


# --- ranking ----------------------------------------------------------------


def _best(candidates: list[_Candidate], *, key) -> _Candidate | None:
    """Highest-scoring candidate, ties broken by discovery order."""
    best: _Candidate | None = None
    best_score = float("-inf")
    for candidate in candidates:
        score = key(candidate)
        if score > best_score:
            best = candidate
            best_score = score
    return best


def _address_score(candidate: _Candidate, preferred: set[str]) -> int:
    score = 0
    if preferred and _names_city(candidate.value, preferred):
        score += 10
    if candidate.explicit:
        score += 2
    if _STREET_TOKEN_RE.search(candidate.value):
        score += 1
    return score


def _phone_score(candidate: _Candidate, preferred: set[str]) -> int:
    score = 2 if candidate.explicit else 0
    if preferred and _names_city(candidate.context, preferred):
        score += 10
    area = candidate.value[1:4]
    if area in _OREGON_AREA_CODES:
        score += 1
    return score


def _email_score(candidate: _Candidate, domain: str | None) -> int:
    score = 2 if candidate.explicit else 0
    if domain and candidate.value.rsplit("@", 1)[-1].endswith(domain):
        score += 5
    return score


def _names_city(text: str, preferred: set[str]) -> bool:
    lowered = text.lower()
    return any(
        re.search(rf"(?<!\w){re.escape(city)}(?!\w)", lowered) for city in preferred
    )


def _email_allowed(email: str, domain: str | None) -> bool:
    """Reject third-party addresses when we know the org's own domain."""
    if not domain:
        return True
    host = email.rsplit("@", 1)[-1]
    return host.endswith(domain) or host in _FREEMAIL_DOMAINS


# --- helpers ----------------------------------------------------------------


def _collapse(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()


def _iter_org_jsonld_nodes(soup: BeautifulSoup) -> Iterable[dict]:
    """Yield JSON-LD dicts that describe an organization or place."""
    for script in soup.find_all("script", type="application/ld+json"):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for node in _walk(payload):
            if not isinstance(node, dict):
                continue
            node_type = node.get("@type")
            types = [node_type] if isinstance(node_type, str) else (node_type or [])
            if any(t in _ORG_JSONLD_TYPES for t in types):
                yield node


def _walk(node: object) -> Iterable[object]:
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _format_postal_address(value: object) -> str | None:
    """Render a schema.org ``PostalAddress`` as a single comma-separated line."""
    if isinstance(value, str):
        collapsed = _collapse(value)
        return _find_address(collapsed) or (
            collapsed if _looks_like_address(collapsed) else None
        )
    if isinstance(value, list):
        for item in value:
            rendered = _format_postal_address(item)
            if rendered:
                return rendered
        return None
    if not isinstance(value, dict):
        return None
    street = _collapse(str(value.get("streetAddress") or ""))
    city = _collapse(str(value.get("addressLocality") or ""))
    region = _collapse(str(value.get("addressRegion") or ""))
    postal = _collapse(str(value.get("postalCode") or ""))
    if not street:
        return None
    tail = " ".join(p for p in (region, postal) if p)
    parts = [p for p in (street, city, tail) if p]
    if len(parts) <= 1:
        return None
    rendered = ", ".join(parts)
    return rendered if _looks_like_address(rendered) else None


def _looks_like_address(text: str) -> bool:
    """True for a short line that starts with a number and names a state/ZIP."""
    if not text or len(text) > 180:
        return False
    if not re.match(r"^\d{1,6}\s", text):
        return False
    if not _STREET_TOKEN_RE.search(text):
        return False
    return bool(re.search(r"(?i)\b(?:OR|Oregon)\b|\b97\d{3}\b", text))


def _find_addresses(text: str) -> list[str]:
    """Find every address-ish Oregon street line in free text."""
    out: list[str] = []
    seen: set[str] = set()
    for match in _ADDRESS_RE.finditer(text or ""):
        address = _tidy_address(match.group(0))
        if not _looks_like_address(address):
            continue
        if address not in seen:
            seen.add(address)
            out.append(address)
    return out


def _find_address(text: str) -> str | None:
    addresses = _find_addresses(text)
    return addresses[0] if addresses else None


def _tidy_address(raw: str) -> str:
    """Normalize whitespace and comma spacing on a matched address line."""
    out = _collapse(raw)
    # The regex anchors on the leftmost number, which may be a suite number,
    # a year or a price sitting just before the real street number
    # ("1870 906 Main Ave" -> "906 Main Ave"). Two bare numbers in a row are
    # never a street line, so drop the first.
    out = re.sub(r"^\d{1,6}\s+(?=\d{1,6}\s)", "", out)
    out = re.sub(r"\s*,\s*", ", ", out)
    out = re.sub(r",\s*,", ",", out)
    # "Madras OR 97741" -> "Madras, OR 97741" when the comma is missing.
    out = re.sub(r"(?i)\s+(OR|Oregon)\s+(97\d{3})", r", \1 \2", out)
    out = re.sub(r"(?i)\boregon\b", "OR", out)
    out = re.sub(r",\s*,", ",", out)
    return _collapse(out).strip(" ,")


def _find_phones(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in _PHONE_RE.finditer(text or ""):
        phone = _normalize_phone(match.group(0))
        if phone and phone not in seen:
            seen.add(phone)
            out.append(phone)
    return out


def _find_phone(text: str) -> str | None:
    phones = _find_phones(text)
    return phones[0] if phones else None


def _normalize_phone(value: object) -> str | None:
    """Return ``(541) 555-1234`` for anything phone-shaped, else ``None``."""
    if not isinstance(value, str):
        return None
    match = _PHONE_RE.search(value)
    if not match:
        return None
    area, prefix, line = match.groups()
    if area in _PHONE_NOISE or prefix in _PHONE_NOISE:
        return None
    return f"({area}) {prefix}-{line}"


def _clean_email(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = _EMAIL_RE.search(value.strip())
    if not match:
        return None
    email = match.group(0).lower()
    if any(noise in email for noise in _EMAIL_NOISE):
        return None
    if email.split("@", 1)[0] in _EMAIL_ROLE_LOCALPARTS:
        return None
    return email
