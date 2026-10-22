"""Company website discovery, exact-entity verification and extraction.

A website is only published when code finds proof that it belongs to the exact legal entity:
the organisation number on the site, or the full legal name together with a registered contact
detail (phone, e-mail, street address) or a matching domain. The required proof gets stricter as
the candidate's origin gets weaker (registry-listed > registry e-mail domain > guessed/search).
"""
from __future__ import annotations

import re
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any

from .html import Page, parse_html
from .ledger import Document, Ledger, excerpt_around, fold, tokens
from .net import Fetcher, FetchResult

LEGAL_FORMS = {"as", "asa", "sa", "da", "ans", "nuf", "ba", "ks", "enk", "sti", "iks", "kf", "hf", "bl", "ab", "ltd", "limited",
               "inc", "gmbh", "aps", "oy", "brl", "sti", "fli", "esek", "stiftelsen", "stiftelse", "stiftinga", "borettslag",
               "borettslaget", "sameie", "sameiet", "eierseksjonssameie", "eierseksjonssameiet", "andelslag", "samvirkelag"}
CONNECTORS = {"og", "and", "the", "i", "av", "for", "paa", "pa", "&"}
LEGAL_SUFFIXES = {"as", "asa", "sa", "da", "ans", "nuf", "ba", "ks", "enk", "sti", "iks", "kf", "hf", "bl", "ab", "ltd", "limited",
                  "inc", "gmbh", "aps", "oy", "og", "and", "the", "i", "av", "for", "på", "pa", "&"}
GENERIC = {"norge", "norway", "norsk", "norske", "service", "services", "eiendom", "holding", "invest", "consult", "consulting",
           "bygg", "transport", "drift", "utvikling", "gruppen", "group", "company", "selskap", "handel", "regnskap", "kapital",
           "partner", "partners", "solutions", "system", "systems", "teknikk", "entreprenor", "entreprenør", "maskin", "auto",
           "nord", "sor", "vest", "ost", "west", "north", "south", "east", "senter", "center", "tjenester", "media", "design",
           "data", "energi", "eiendommer", "investering", "management", "property", "properties", "capital", "trading",
           "import", "export", "agentur", "ventures", "venture", "industri", "industrier", "verksted", "salg", "produksjon",
           "bil", "elektro", "ror", "rør", "mat", "helse", "omsorg", "klinikk", "tannlege", "lege", "advokat", "advokatfirma",
           "landbruk", "gard", "garden", "fiske", "shipping", "marine", "maritime", "offshore", "olje", "oil", "gas", "it"}
FREEMAIL = {"gmail.com", "googlemail.com", "hotmail.com", "hotmail.no", "outlook.com", "outlook.no", "live.com", "live.no", "msn.com",
            "yahoo.com", "yahoo.no", "icloud.com", "me.com", "mac.com", "online.no", "start.no", "frisurf.no", "broadpark.no",
            "c2i.net", "getmail.no", "lyse.net", "altibox.no", "epost.no", "mail.com", "aol.com", "protonmail.com", "proton.me",
            "gmx.com", "gmx.net", "ebnett.no", "chello.no", "netcom.no", "bluezone.no", "hotmail.co.uk", "telia.no", "tele2.no",
            "loqal.no", "haugnett.no", "enivest.net", "tussa.com", "nordnet.no", "nextgentel.com", "vikenfiber.no", "sensewave.com",
            "online.com", "post.com", "email.com", "yandex.com", "mail.ru", "outlook.dk", "hotmail.se", "live.se", "live.dk",
            "privat.no", "ymail.com", "rocketmail.com", "skynet.be", "web.de", "t-online.de", "eniro.no", "kpnmail.nl"}
SHARED_HOSTS = {"facebook.com", "instagram.com", "linkedin.com", "google.com", "sites.google.com", "wix.com", "wixsite.com",
                "squarespace.com", "weebly.com", "wordpress.com", "blogspot.com", "proff.no", "gulesider.no", "1881.no",
                "finn.no", "mittanbud.no", "brreg.no", "purehelp.no", "firmaer.no", "youtube.com", "x.com", "twitter.com",
                "tiktok.com", "github.io", "netlify.app", "vercel.app", "business.site", "123hjemmeside.no", "hjemmeside.no",
                "linktr.ee", "kommune.no", "uniweb.no", "jimdosite.com", "mamutweb.com", "onepage.website"}
PUBLIC_SUFFIX_2 = {"co.uk", "org.uk", "com.au", "co.nz", "com.br", "priv.no", "kommune.no", "herad.no", "fylkeskommune.no", "museum.no",
                   "vgs.no", "co.za", "com.tr", "com.cn"}
PARKED = ("is parked", "has expired", "parkedweb", "does not have an active website", "domain is for sale", "domain for sale", "domenet er til salgs", "this domain may be for sale", "kjøp dette domenet",
          "hugedomains", "parked at", "parkert", "domeneshop.no/park", "her flytter snart en ny gjest", "is parked free",
          "buy this domain", "denne domenen er parkert", "domain parking", "sedo.com", "dan.com", "afternic",
          "under construction", "kommer snart", "coming soon", "website is under construction", "nettsiden er under arbeid",
          "default web site page", "welcome to nginx", "apache2 default page", "index of /", "this site can't be reached",
          "account suspended", "website expired", "the website you were trying to reach is temporarily unavailable",
          "web hosting by one.com", "one.com website builder", "domeneshop - norsk domeneregistrar", "dette domenet er registrert")
AGENCY_HINTS = ("levert av", "utviklet av", "laget av", "design av", "designet av", "designed by", "developed by", "powered by",
                "webdesign", "nettside av", "nettsider fra", "hjemmeside av", "produsert av", "made by", "website by", "drevet av")
# A careers page is matched on whole path segments (so "utstillinger" or "bestillinger" never match) and never on dated
# news paths such as /2022/05/23/ledig-stilling/.
CAREER_SEGMENT = re.compile(r"^(karriere|karrierer|career|careers|jobb|jobber|jobs?|ledige[-_]?stillinger|ledig[-_]?stilling|stillinger|"
                            r"jobb[-_]?hos[-_\w]*|jobbe[-_]?(hos|i|med)[-_\w]*|join[-_]?us|bli[-_]?med[-_]?oss|rekruttering|"
                            r"vi[-_]?ansetter|work[-_]?with[-_]?us|jobbmuligheter|arbeid[-_]?hos[-_]?oss)$", re.I)
CAREER_TEXT = re.compile(r"^(karriere|ledige stillinger|stillinger|jobb hos oss|jobbe hos oss|jobb|jobs|careers?|join us|bli med oss|"
                         r"vi ansetter|ledig stilling|jobbmuligheter|work with us|jobbe i [\w ]+)$", re.I)


def career_path(path: str) -> bool:
    segments = [s for s in urllib.parse.unquote(path).lower().split("/") if s]
    if not segments or re.search(r"/20\d\d/", path) or any(s in {"product", "produkt", "produkter", "shop", "nettbutikk"} for s in segments):
        return False
    return any(CAREER_SEGMENT.match(s) for s in segments[:3])
ATS_HOSTS = ("webcruiter.no", "webcruiter.com", "jobbnorge.no", "recman.no", "recman.io", "teamtailor.com", "jobylon.com",
             "easycruit.com", "reachmee.com", "hrmanager.no", "varbi.com", "smartrecruiters.com", "workable.com", "lever.co",
             "greenhouse.io", "talentech.com", "simployer.com", "jobsite.no", "hr-manager.net", "candidate.hr-manager.net",
             "emply.com", "jobandtalent.com", "personio.de", "personio.com", "career.hireserve", "cvpartner.com", "tellent.com")
PRIORITY_PATH = re.compile(r"(kontakt|contact|om-oss|om_oss|omoss|about|personvern|privacy|vilkar|vilkår|terms|salgsbetingelser|"
                           r"kjopsvilkar|kjøpsvilkår|impressum|firma|selskapet|company|ledelse|hvem-er-vi|om-[a-z]+)", re.I)
SOCIAL_HOSTS = {"facebook.com": "facebook", "fb.com": "facebook", "instagram.com": "instagram", "linkedin.com": "linkedin",
                "youtube.com": "youtube", "x.com": "x", "twitter.com": "x", "tiktok.com": "tiktok", "pinterest.com": "pinterest",
                "vimeo.com": "vimeo", "snapchat.com": "snapchat", "threads.net": "threads"}
ORG_RE = re.compile(r"(?<![\d])(\d{3})[ . -]?(\d{3})[ . -]?(\d{3})(?![\d])")
PHONE_RE = re.compile(r"(?<![\d+])(?:\+47[ . -]?|0047[ . -]?)?(\d{2}[ . -]?\d{2}[ . -]?\d{2}[ . -]?\d{2}|\d{3}[ . -]?\d{2}[ . -]?\d{3})(?![\d])")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
WORD_RE = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
DATE_DOTTED = re.compile(r"(?<!\d)([0-3]?\d)\.([01]?\d)\.(20\d\d)(?!\d)")


def valid_orgnr(number: str) -> bool:
    if not re.fullmatch(r"[89]\d{8}", number):
        return False
    weights = [3, 2, 7, 6, 5, 4, 3, 2]
    total = sum(int(d) * w for d, w in zip(number[:8], weights))
    check = 11 - total % 11
    check = 0 if check == 11 else check
    return check != 10 and check == int(number[8])


def host_of(url: str) -> str:
    host = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def registrable(host: str) -> str:
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in PUBLIC_SUFFIX_2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def normalize_site_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().strip("/").replace("\\", "/")
    if not value or " " in value or "@" in value.split("/")[0]:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    host = host_of(value)
    if not host or "." not in host or host.endswith(tuple(SHARED_HOSTS)) or host in SHARED_HOSTS:
        return None
    return value


def _strip_forms(toks: list[str]) -> list[str]:
    toks = list(toks)
    changed = True
    while changed and toks:
        changed = False
        if toks[-3:] == ["a", "s", "a"]:  # "A.S.A." written with separators
            toks, changed = toks[:-3], True
        elif toks[-2:] == ["a", "s"]:  # "A/S"
            toks, changed = toks[:-2], True
        elif toks[-1] in LEGAL_FORMS:
            toks, changed = toks[:-1], True
    while toks[:2] == ["a", "s"] or (toks and toks[0] in LEGAL_FORMS):
        toks = toks[2:] if toks[:2] == ["a", "s"] else toks[1:]
    return toks


def name_tokens(name: str) -> list[str]:
    """Legal-name tokens without the legal-form suffix/prefix (only at the ends) and connector words."""
    return [t for t in _strip_forms(tokens(name)) if t not in CONNECTORS]


def name_tokens_with_connectors(name: str) -> list[str]:
    """Like name_tokens but keeps inner connector words ("Nesset og Eidem" is often nessetogeidem.no)."""
    return [t for t in _strip_forms(tokens(name)) if t != "&"]


def domain_key(text: str) -> str:
    """Compare names with domain labels: å may be written a or aa in domains."""
    return re.sub(r"[^a-z0-9]", "", fold(text)).replace("aa", "a")


def distinctive(name_toks: list[str]) -> list[str]:
    return [t for t in name_toks if len(t) >= 4 and t not in GENERIC and not t.isdigit()]


def phone_digits(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("0047"):
        digits = digits[4:]
    elif digits.startswith("47") and len(digits) == 10:
        digits = digits[2:]
    return digits if len(digits) == 8 else None


@dataclass
class Company:
    org: str
    name: str
    legal_form: str = ""
    phones: set[str] = field(default_factory=set)
    emails: set[str] = field(default_factory=set)
    street: str = ""
    postcode: str = ""
    other_addresses: list[tuple[str, str]] = field(default_factory=list)
    brands: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    city: str = ""
    aliases: list[str] = field(default_factory=list)
    employees: int | None = None
    revenue: float | None = None
    industry: str = ""

    @property
    def core(self) -> list[str]:
        return name_tokens(self.name)


@dataclass
class Candidate:
    url: str
    source: str
    strength: str  # strong | medium | weak
    note: str = ""


@dataclass
class SiteResult:
    candidate: Candidate
    state: str  # verified | rejected | unreachable | blocked | parked | related
    reason: str = ""
    home_url: str = ""
    pages: list[tuple[FetchResult, Page]] = field(default_factory=list)
    proof: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


def candidate_slugs(company: Company) -> list[str]:
    toks = company.core
    if not toks or len(toks) > 4:
        return []
    joined = "".join(toks)
    out = []
    full = name_tokens_with_connectors(company.name)
    if full != toks and 2 <= len(full) <= 5 and any(t in CONNECTORS for t in full[1:-1]):
        with_connectors = "".join(full).replace("aa", "a")
        if 6 <= len(with_connectors) <= 40:
            out += [with_connectors, "-".join(t.replace("aa", "a") for t in full)]
    if 4 <= len(joined) <= 40:
        variants = [joined.replace("aa", "a"), joined] if "aa" in joined else [joined]
        for variant in variants:
            out.append(variant)
        if len(toks) > 1:
            out.append("-".join(t.replace("aa", "a") for t in toks))
    # "LISLEGÅRD MASKIN AS" often lives at lislegard.no: try the distinctive first word when the rest is generic
    if len(toks) >= 2 and len(toks[0]) >= 6 and toks[0] not in GENERIC and not toks[0].isdigit() \
            and all(t in GENERIC for t in toks[1:]):
        out.append(toks[0].replace("aa", "a"))
    return out


def page_documents(pages: list[tuple[FetchResult, Page]], source_class: str) -> list[tuple[Document, Page]]:
    docs = []
    for result, page in pages:
        docs.append((Document(url=result.url, source_class=source_class, retrieved_at=result.retrieved_at, sha256=result.sha256,
                              text=page.evidence_text(), raw="", final_url=result.final_url, status=result.status), page))
    return docs


class SiteResearcher:
    def __init__(self, fetcher: Fetcher, max_pages: int = 4) -> None:
        self.fetcher = fetcher
        self.max_pages = max_pages
        self._unique_cache: dict[str, bool] = {}
        self._unique_lock = threading.Lock()

    # -- fetching ----------------------------------------------------------------------------
    def _fetch_page(self, url: str, retries: int = 0) -> tuple[FetchResult, Page | None]:
        result = self.fetcher.get(url, respect_robots=True, max_bytes=2_500_000, timeout=12, retries=retries)
        if result.status is None and url.startswith("https://") and not result.blocked:
            alt = self.fetcher.get("http://" + url[len("https://"):], respect_robots=True, max_bytes=2_500_000, timeout=12, retries=0)
            if alt.status is not None:
                result = alt
        if not result.ok or "html" not in (result.content_type or "html").lower():
            return result, None
        return result, parse_html(result.text, result.final_url or url)

    def research(self, company: Company, candidate: Candidate) -> SiteResult:
        result, home = self._fetch_page(candidate.url, retries=1 if candidate.strength in ("strong", "medium") else 0)
        if result.blocked:
            return SiteResult(candidate, "blocked", result.error or "blocked")
        if result.status in (401, 403, 429):
            return SiteResult(candidate, "blocked", f"site refused automated access (HTTP {result.status})")
        if home is None:
            return SiteResult(candidate, "unreachable", result.error or f"HTTP {result.status}")
        final_host = host_of(result.final_url or candidate.url)
        if final_host in SHARED_HOSTS or final_host.endswith(tuple("." + h for h in SHARED_HOSTS)):
            return SiteResult(candidate, "rejected", f"redirects to shared platform {final_host}")
        pages = [(result, home)]
        lowered = fold(home.title + " " + home.text[:4000])
        if any(marker in lowered for marker in PARKED) or len(home.text) < 40 and not home.jsonld:
            if len(home.text) < 600 or any(marker in lowered for marker in PARKED[:16]):
                return SiteResult(candidate, "parked", "placeholder, parked or empty page", home_url=result.final_url, pages=pages)
        proof = self._proof(company, pages)
        if not proof["orgnr"]:
            # look at contact/about/terms pages where Norwegian sites usually print the organisation number
            for url in self._priority_links(home, final_host)[: self.max_pages - 1]:
                extra_result, extra_page = self._fetch_page(url)
                if extra_page is not None and host_of(extra_result.final_url or url).endswith(registrable(final_host)):
                    pages.append((extra_result, extra_page))
                    proof = self._proof(company, pages)
                    if proof["orgnr"]:
                        break
        decision, confidence, reason = self._decide(company, candidate, proof, final_host)
        return SiteResult(candidate, decision, reason, home_url=result.final_url or candidate.url, pages=pages, proof=proof,
                          confidence=confidence)

    def _priority_links(self, page: Page, host: str) -> list[str]:
        seen: set[str] = set()
        ranked: list[tuple[int, str]] = []
        for link in page.links:
            if host_of(link.url) != host or link.url.split("#")[0] in seen:
                continue
            path = urllib.parse.urlsplit(link.url).path.lower()
            text = fold(link.text)
            if re.search(r"\.(pdf|jpe?g|png|gif|zip|docx?|xlsx?)$", path):
                continue
            score = 0
            if re.search(r"kontakt|contact", path + " " + text):
                score = 3
            elif re.search(r"om-oss|om oss|about|hvem er vi|selskapet|firma", path + " " + text):
                score = 2
            elif re.search(r"personvern|privacy|vilkar|terms|betingelser|impressum", path + " " + text):
                score = 1
            if score:
                seen.add(link.url.split("#")[0])
                ranked.append((score, link.url.split("#")[0]))
        ranked.sort(key=lambda item: -item[0])
        return [url for _, url in ranked]

    # -- identity proof -------------------------------------------------------------------------
    def _proof(self, company: Company, pages: list[tuple[FetchResult, Page]]) -> dict[str, Any]:
        proof: dict[str, Any] = {"orgnr": None, "other_orgnrs": [], "phone": None, "email": None, "address": None,
                                 "name_identity": None, "name_anywhere": None, "domain_name": None}
        core = set(company.core)
        alias_sets = [set(name_tokens(a)) for a in company.aliases + company.brands if name_tokens(a)]
        others: set[str] = set()
        for result, page in pages:
            text = page.text
            raw_text = text + "\n" + "\n".join(f"{k}: {v}" for k, v in page.meta.items())
            for match in ORG_RE.finditer(raw_text):
                number = "".join(match.groups())
                if number == company.org and not proof["orgnr"]:
                    proof["orgnr"] = {"url": result.url, "excerpt": excerpt_around(raw_text, match.group(0))}
                elif valid_orgnr(number) and number != company.org:
                    window = raw_text[max(0, match.start() - 40):match.start()].lower()
                    if re.search(r"org|foretak|mva|vat|reg", window):
                        others.add(number)
            if not proof["phone"] and company.phones:
                for match in PHONE_RE.finditer(text):
                    digits = phone_digits(match.group(0))
                    if digits and digits in company.phones:
                        proof["phone"] = {"url": result.url, "excerpt": excerpt_around(text, match.group(0).strip()),
                                          "value": match.group(0).strip(), "digits": digits}
                        break
            if not proof["email"] and company.emails:
                lowered = text.lower() + " " + " ".join(l.url.lower() for l in page.links if l.url.lower().startswith("mailto:"))
                for email in company.emails:
                    if email in lowered:
                        excerpt = excerpt_around(text, email) or excerpt_around(page.evidence_text(), email)
                        proof["email"] = {"url": result.url, "excerpt": excerpt, "value": email}
                        break
            if not proof["address"] and company.street and company.postcode:
                found_address = address_on_page(company.street, company.postcode, text)
                for street, postcode in company.other_addresses:
                    if found_address:
                        break
                    found_address = address_on_page(street, postcode, text)
                if found_address:
                    proof["address"] = {"url": result.url, "excerpt": excerpt_around(text, found_address), "value": found_address}
            identity_text = " ".join([page.title, page.meta.get("og:site_name", ""), page.meta.get("og:title", ""),
                                      page.meta.get("application-name", ""), " ".join(page.headings[:6]), page.header_text[:1500],
                                      page.footer_text[:3000], text[-1500:]]
                                     + [str(item.get("name", "")) + " " + str(item.get("legalName", "")) for item in page.jsonld_flat()
                                        if str(item.get("@type", "")).lower() in {"organization", "localbusiness", "corporation", "store",
                                                                                   "restaurant", "website", "professionalservice"}
                                        or "business" in str(item.get("@type", "")).lower()])
            ident = set(tokens(identity_text))
            anywhere = set(tokens(text + " " + page.title))
            if not proof.get("legal_name_exact"):
                hit = legal_name_hit(company.name, text) or legal_name_hit(company.name, page.title)
                if hit:
                    proof["legal_name_exact"] = {"url": result.url, "excerpt": excerpt_around(text, hit) or f"[title] {page.title}",
                                                 "value": hit}
            if core and not proof["name_identity"] and (core <= ident or any(a and a <= ident for a in alias_sets)):
                proof["name_identity"] = {"url": result.url}
            if core and not proof["name_anywhere"] and (core <= anywhere or any(a and a <= anywhere for a in alias_sets)):
                excerpt = None
                for line in text.split("\n"):
                    if core <= set(tokens(line)):
                        excerpt = line[:300]
                        break
                proof["name_anywhere"] = {"url": result.url, "excerpt": excerpt}
        proof["other_orgnrs"] = sorted(others)
        home = pages[0][1]
        lang = (home.lang or "").lower()[:2]
        all_text = " ".join(p.text for _, p in pages)
        proof["norwegian_context"] = bool(host_of(pages[0][0].final_url or "").endswith(".no") or lang in ("no", "nb", "nn")
                                          or (company.postcode and company.postcode in all_text)
                                          or (company.city and company.city.lower() in all_text.lower())
                                          or re.search(r"\b(norge|norway|org\.? ?nr)\b", all_text, re.I))
        return proof

    def _name_unique(self, company: Company) -> bool:
        """True when no other registered entity or workplace (besides this company's own) carries all legal-name words.

        Uses Brønnøysund's name search (relevance-ranked), so a namesake would appear among the first results."""
        core = set(company.core)
        if not core or len("".join(core)) < 6:
            return False
        key = " ".join(sorted(core))
        with self._unique_lock:
            if key in self._unique_cache:
                return self._unique_cache[key]
        query = urllib.parse.quote(" ".join(company.core))
        unique = True
        for kind, url in (("enheter", f"https://data.brreg.no/enhetsregisteret/api/enheter?navn={query}&size=50"),
                          ("underenheter", f"https://data.brreg.no/enhetsregisteret/api/underenheter?navn={query}&size=50")):
            result = self.fetcher.get(url, accept="application/json", retries=1, snapshot=False)
            if not result.ok:
                unique = False
                break
            for item in ((result.json() or {}).get("_embedded") or {}).get(kind, []):
                owner = item.get("overordnetEnhet") or item.get("organisasjonsnummer")
                if owner == company.org or item.get("organisasjonsnummer") == company.org:
                    continue
                other = name_tokens(item.get("navn") or "")
                if core <= set(other) or "".join(company.core) in "".join(other):
                    unique = False
                    break
            if not unique:
                break
        with self._unique_lock:
            self._unique_cache[key] = unique
        return unique

    def _decide(self, company: Company, candidate: Candidate, proof: dict[str, Any], final_host: str) -> tuple[str, float, str]:
        label = domain_key(registrable(final_host).split(".")[0])
        core = company.core
        joined = domain_key("".join(core))
        joined_full = domain_key("".join(name_tokens_with_connectors(company.name)))
        dist = [domain_key(t) for t in distinctive(core)]
        domain_name = bool(joined and (label == joined or (len(joined) >= 6 and joined in label))) or \
            bool(joined_full and len(joined_full) >= 6 and label == joined_full) or \
            bool(dist and all(t in label for t in dist) and sum(len(t) for t in dist) >= 5)
        proof["domain_name"] = domain_name
        contact = proof["phone"] or proof["email"] or proof["address"]
        foreign = bool(proof["other_orgnrs"]) and not proof["orgnr"]
        if proof["orgnr"]:
            return "verified", 0.99, "organisation number shown on the site"
        if candidate.strength != "strong" and not contact and not foreign and proof["name_identity"] and domain_name:
            proof["name_unique_in_register"] = self._name_unique(company)

        if candidate.strength == "strong":
            if foreign and not proof["name_identity"]:
                return "related", 0.5, f"site shows another organisation number ({', '.join(proof['other_orgnrs'][:2])})"
            if proof["name_identity"] and (contact or domain_name):
                return "verified", 0.97, "registered website shows the legal name and a registered contact detail or matching domain"
            if proof["name_identity"] or (proof["name_anywhere"] and (domain_name or contact)) or (contact and domain_name):
                return "verified", 0.93, "registered website shows the legal name, or a registered contact detail on a matching domain"
            if domain_name:
                return "verified", 0.9, "registered website domain matches the legal name"
            if contact:
                return "related", 0.6, "registered website shares the company's contact details but names another business (group/manager site)"
            return "rejected", 0.3, "registered website lacks exact-entity evidence"
        if foreign:
            return "rejected", 0.2, f"site shows another organisation number ({', '.join(proof['other_orgnrs'][:2])})"
        exact_name = proof.get("legal_name_exact")
        if candidate.strength == "medium":
            if proof["name_identity"] and (contact or domain_name):
                return "verified", 0.95, "legal name on the site plus registered contact detail or matching domain"
            if exact_name and final_host.endswith(".no"):
                return "verified", 0.95, "the full registered legal name (unique in Norway) is printed on the site"
            if proof["name_anywhere"] and contact and domain_name:
                return "verified", 0.93, "legal name, registered contact detail and matching domain"
            return "rejected", 0.4, "insufficient exact-entity evidence"
        # Discovered (guessed/searched) domains must also *be named after* the company: directories and
        # aggregators print a company's name and phone number too, but on their own domain.
        if not domain_name:
            return "rejected", 0.3, "discovered domain is not named after the company (directory/aggregator risk)"
        if proof["name_identity"] and contact:
            return "verified", 0.95, "legal name and a registered contact detail on a site named after the company"
        if exact_name:
            return "verified", 0.94, "the full registered legal name (unique in Norway) is printed on a site named after the company"
        if proof["name_identity"] and proof.get("name_unique_in_register") and proof.get("norwegian_context"):
            return "verified", 0.92, "on-site name and domain match the legal name, and no other registered entity carries that name"
        return "rejected", 0.3, "insufficient exact-entity evidence for a discovered domain"


STREET_SUFFIX = re.compile(r"(veien|vegen|veg|vei|vn|v|gata|gaten|gate|gt|g|plassen|plass|alle|allee|alleen|bakken|brygga|bryggen|"
                           r"stien|sti|torget|tunet|lia|kaia|kaien|haugen|ringen|myra|svingen)$")


def _street_stem(token: str) -> str:
    stem = STREET_SUFFIX.sub("", token)
    return stem if len(stem) >= 3 else token


def address_on_page(street: str, postcode: str, text: str) -> str | None:
    """Find the registered business address on the page, tolerant to veien/vegen-style spelling variants.

    Requires the postcode, the house number and the street-name stem within one short window."""
    if not postcode or postcode not in text:
        return None
    street_tokens = tokens(street)
    numbers = [t for t in street_tokens if t.isdigit() or re.fullmatch(r"\d+[a-z]", t)]
    words = [t for t in street_tokens if not t.isdigit() and not re.fullmatch(r"\d+[a-z]", t) and len(t) > 1]
    if not words:
        return None
    stems = [_street_stem(w) for w in words]
    for match in re.finditer(re.escape(postcode), text):
        window = text[max(0, match.start() - 120): match.end() + 40]
        window_tokens = tokens(window)
        if numbers and not any(n in window_tokens for n in numbers):
            continue
        if all(any(t.startswith(stem) for t in window_tokens) for stem in stems):
            return window.strip()[-160:] if len(window) > 160 else window.strip()
    return None


def legal_name_hit(legal_name: str, text: str) -> str | None:
    """Return the original text span when the complete legal name *including its legal-form suffix* appears on the page.

    Names of Norwegian AS/ASA companies are unique in the Register of Business Enterprises, so the
    verbatim legal name is a strong identity signal."""
    wanted = tokens(legal_name)
    if len(wanted) < 2 or wanted[-1] not in {"as", "asa", "sa", "da", "ans", "ba", "ks"}:
        return None
    if len("".join(wanted[:-1])) < 4:
        return None
    words = [(m.start(), m.end(), tokens(m.group(0))) for m in WORD_RE.finditer(text)]
    flat: list[tuple[int, int, str]] = [(start, end, tok) for start, end, toks in words for tok in toks]
    n = len(wanted)
    for index in range(len(flat) - n + 1):
        if all(flat[index + k][2] == wanted[k] for k in range(n)):
            before = flat[index - 1][2] if index else ""
            after = flat[index + n][2] if index + n < len(flat) else ""
            if before.isalpha() and before not in {"av", "fra", "til", "hos", "og", "i", "c", "copyright", "ved", "for", "drives",
                                                     "levert", "eies", "eiet", "eier", "med"} and len(before) > 2 and not text[flat[index - 1][1]:flat[index][0]].strip():
                continue  # part of a longer company name such as "Nord Lislegard Maskin AS"
            return text[flat[index][0]:flat[index + n - 1][1]]
    return None


# -- extraction from a verified site ----------------------------------------------------------------

def normalize_social(url: str) -> tuple[str, str] | None:
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    host = re.sub(r"^(m|mobile|no|nb-no|nb|web|business|l)\.", "", host)
    platform = SOCIAL_HOSTS.get(host)
    if not platform:
        return None
    path = urllib.parse.unquote(parts.path or "").rstrip("/")
    segs = [s for s in path.split("/") if s]
    query = urllib.parse.parse_qs(parts.query)
    if platform == "facebook":
        if not segs:
            return None
        if segs[0] in {"sharer", "sharer.php", "share", "share.php", "dialog", "plugins", "tr", "login", "help", "policies", "privacy",
                       "groups", "events", "photo.php", "photo", "watch", "hashtag", "search", "story.php", "permalink.php", "l.php",
                       "media", "notes", "business", "ads", "legal", "about", "home.php", "gaming", "marketplace", "fundraisers"}:
            return None
        if segs[0] == "profile.php" and query.get("id"):
            return platform, f"https://www.facebook.com/profile.php?id={query['id'][0]}"
        if segs[0] == "pages" and len(segs) >= 3:
            return platform, f"https://www.facebook.com/pages/{segs[1]}/{segs[2]}"
        if segs[0] == "p" and len(segs) >= 2:
            return platform, f"https://www.facebook.com/p/{segs[1]}"
        handle = segs[0]
        if not re.fullmatch(r"[\w.\-%]{2,100}", handle) or handle.lower() in {"pg", "people", "public"}:
            return None
        return platform, f"https://www.facebook.com/{handle}"
    if platform == "instagram":
        if not segs or segs[0] in {"p", "reel", "reels", "explore", "accounts", "stories", "tv", "direct", "about", "developer", "legal"}:
            return None
        return platform, f"https://www.instagram.com/{segs[0]}"
    if platform == "linkedin":
        if len(segs) >= 2 and segs[0] in {"company", "school", "showcase"}:
            return platform, f"https://www.linkedin.com/{segs[0]}/{segs[1]}"
        return None
    if platform == "youtube":
        if not segs:
            return None
        if segs[0].startswith("@"):
            return platform, f"https://www.youtube.com/{segs[0]}"
        if segs[0] in {"channel", "c", "user"} and len(segs) >= 2:
            return platform, f"https://www.youtube.com/{segs[0]}/{segs[1]}"
        return None
    if platform == "x":
        if not segs or segs[0] in {"intent", "share", "home", "hashtag", "search", "i", "login", "explore", "settings", "tos", "privacy"}:
            return None
        return platform, f"https://x.com/{segs[0]}"
    if platform == "tiktok":
        if segs and segs[0].startswith("@"):
            return platform, f"https://www.tiktok.com/{segs[0]}"
        return None
    if platform in {"pinterest", "vimeo", "snapchat", "threads"}:
        if not segs or segs[0] in {"pin", "share", "video", "watch", "add", "search"} or segs[0].isdigit():
            return None
        return platform, f"https://www.{host}/{segs[0]}"
    return None


OPAQUE_HANDLE = re.compile(r"(profile\.php\?id=\d+|/channel/uc[\w-]{10,}|/company/\d+|/pages/[^/]+/\d+|/p/[^/]*\d{6,})", re.I)


def _initials(text: str) -> str:
    words = [w for w in re.split(r"[^a-z0-9]+|(?<=[a-z])(?=[A-Z])", text) if w]
    return "".join(w[0] for w in words).lower() if len(words) >= 2 else ""


FOREIGN_FORMS = {"ag", "gmbh", "ab", "oy", "oyj", "aps", "ltd", "limited", "inc", "llc", "plc", "bv", "nv", "sarl", "srl", "as", "asa"}
GROUP_WORDS = {"group", "gruppen", "konsern", "konsernet", "holding"}


def acceptable_brand(brand: str, company: Company, site_host: str) -> bool:
    """A public brand must be short, not the legal name itself, not a domain, not a person registered in a role,
    and must not name a *different* legal entity (e.g. 'Knut Hovet AS' on the site of 'KNUT HOVET INSTALLASJONAR AS')."""
    text = brand.strip()
    folded = fold(text)
    if not (2 <= len(text) <= 40) or folded == fold(company.name) or re.search(r"(www\.|https?:|\.(no|com|net|org)\b|scroll|meny|menu|cookie)",
                                                                             folded):
        return False
    toks = tokens(text)
    if toks and toks[-1] in {"as", "asa", "sa", "da", "ans", "ag", "gmbh", "ab", "ltd", "inc"} and toks != tokens(company.name):
        return False
    brand_tokens = set(tokens(text))
    if any(brand_tokens and brand_tokens <= set(tokens(person)) for person in company.people):
        return False  # a registered person's name (e.g. the owner) is not a company brand
    label = domain_key(registrable(site_host).split(".")[0])
    shared = set(distinctive(name_tokens(text))) & (set(distinctive(company.core)) | {t for t in [label] if len(t) >= 3})
    return bool(shared) or domain_key(text) in label or label in domain_key(text)


def foreign_entity_handle(company: Company, url: str) -> bool:
    """Handles such as 'wyssen-avalanche-control-ag' or 'lindbak-gruppen-as' name another legal entity (parent/group)."""
    segment = urllib.parse.unquote(urllib.parse.urlsplit(url).path).strip("/").split("/")[-1]
    parts = [p for p in re.split(r"[-_.]+", fold(segment)) if p]
    if len(parts) < 2:
        return False
    if parts[-1] in FOREIGN_FORMS - {"as", "asa"}:
        return True
    stem = set(parts[:-1] if parts[-1] in {"as", "asa"} else parts)
    own_names = [set(company.core)] + [set(name_tokens(n)) for n in company.aliases + company.brands if name_tokens(n)]
    if parts[-1] in {"as", "asa"} and not any(names and names <= stem for names in own_names):
        return True
    return bool((stem & GROUP_WORDS) - set().union(*own_names))


def handle_matches(company: Company, url: str, brand: str | None, site_host: str) -> bool:
    """Does the profile handle name the company (legal name, former names, brand, workplace brands, domain, initials)?"""
    parts = urllib.parse.urlsplit(url)
    raw_path = urllib.parse.unquote(parts.path + "?" + parts.query)
    compact = domain_key(raw_path)
    names = [company.name, *company.aliases, *company.brands] + ([brand] if brand else [])
    candidates: set[str] = set()
    for name in names:
        toks = name_tokens(name)
        candidates |= {domain_key(t) for t in distinctive(toks)}
        joined = domain_key("".join(toks))
        if len(joined) >= 4:
            candidates.add(joined)
        initials = "".join(t[0] for t in toks if t)
        if len(initials) >= 3:
            candidates.add(initials)
    label = domain_key(registrable(site_host).split(".")[0])
    if len(label) >= 3:
        candidates.add(label)
    if any(token and token in compact for token in candidates):
        return True
    segment = raw_path.strip("/").split("/")[-1].split("?")[0]
    initials = _initials(segment)
    return bool(initials and len(initials) >= 3 and (initials == label or initials in candidates))


def opaque_handle(url: str) -> bool:
    """Numeric/channel identifiers cannot carry a name, so name matching cannot be applied to them."""
    return bool(OPAQUE_HANDLE.search(url))


def extract_site(ledger: Ledger, company: Company, site: SiteResult, primary: bool = True) -> dict[str, Any]:
    """Publish website facts from a verified site. Returns a summary used by synthesis and the UI.

    The primary site becomes ``official_website``; further verified sites (e.g. a workplace's brand site listed in the
    register) become ``additional_website``. Both cite the identity-proof excerpts the gate found.
    """
    docs = page_documents(site.pages, "company_owned_website")
    home_doc, home = docs[0]
    site_host = host_of(site.home_url)
    out: dict[str, Any] = {"url": site.home_url, "host": site_host, "profiles": [], "careers": [], "posts": [], "brand": None,
                           "description": None}
    proof_ids = []
    for kind in ("orgnr", "phone", "email", "address"):
        bit = site.proof.get(kind)
        if not bit or not bit.get("excerpt"):
            continue
        doc = next((d for d, _ in docs if d.url == bit["url"]), home_doc)
        value = company.org if kind == "orgnr" else bit.get("value")
        label = {"orgnr": "organisation number", "phone": "phone number", "email": "e-mail address", "address": "business address"}[kind]
        claim = ledger.text_claim(doc, bit["excerpt"], "website", "website_identity_proof", value, qualifier=f"{site_host}:{kind}",
                                  display=f"{site_host} shows the company's registered {label}", confidence=site.confidence,
                                  method=f"identity_gate:{kind}", extra={"proof_kind": kind, "site": site_host})
        if claim:
            proof_ids.append(claim["id"])
    # The website claim cites the fetch record of the page that passed the gate (URL, time, hash).
    home_doc.text = home_doc.text + f"\n[fetched] {site.home_url}"
    home_doc._norm_text = None
    field_name = "official_website" if primary else "additional_website"
    official = ledger.text_claim(home_doc, f"[fetched] {site.home_url}", "website", field_name, site.home_url, qualifier=site_host,
                                 display=site.home_url, confidence=site.confidence, method="identity_gate", locator="final_url",
                                 extra={"discovery": site.candidate.source, "verification": site.reason, "proof_claim_ids": proof_ids})
    if official:
        out["claim_id"] = official["id"]
    if not primary:
        return out
    # public brand: og:site_name, Organization name in JSON-LD, or the title segment that matches the domain
    brand, span = None, None
    if home.meta.get("og:site_name"):
        brand, span = home.meta["og:site_name"], f"[meta og:site_name] {home.meta['og:site_name']}"
    elif home.title:
        label = domain_key(registrable(site_host).split(".")[0])
        for piece in (p.strip() for p in re.split(r"\s[|\-–—:·]\s", home.title) if p.strip()):
            compact = domain_key(piece)
            if compact and len(compact) >= 3 and (compact in label or label in compact) and len(piece) <= 60:
                brand, span = piece, f"[title] {home.title}"
                break
    if brand and span and acceptable_brand(brand, company, site_host):
        claim = ledger.text_claim(home_doc, span, "identity", "public_brand", brand, confidence=0.9, method="site_metadata")
        if claim:
            out["brand"] = brand
    description = home.meta.get("description") or home.meta.get("og:description")
    if description and 20 <= len(description) <= 600:
        key = "description" if home.meta.get("description") == description else "og:description"
        claim = ledger.text_claim(home_doc, f"[meta {key}] {description}", "website", "website_description", description,
                                  confidence=0.9, method="site_metadata")
        if claim:
            out["description"] = description
            out["description_claim"] = claim["id"]
    # social profiles linked from the verified site (company-owned outbound links + JSON-LD sameAs)
    found: dict[str, dict[str, Any]] = {}
    for doc, page in docs:
        for link in page.links:
            normalized = normalize_social(link.url)
            if not normalized:
                continue
            if any(hint in fold(link.text) for hint in AGENCY_HINTS):
                continue
            platform, url = normalized
            found.setdefault(url, {"platform": platform, "url": url, "raw": link.url, "doc": doc, "text": link.text,
                                   "footer": link.in_footer or link.in_header})
        for item in page.jsonld_flat():
            same = item.get("sameAs")
            for raw in ([same] if isinstance(same, str) else same if isinstance(same, list) else []):
                normalized = normalize_social(str(raw))
                if normalized and normalized[1] not in found:
                    found[normalized[1]] = {"platform": normalized[0], "url": normalized[1], "raw": str(raw), "doc": doc,
                                            "text": "json-ld sameAs", "footer": True, "jsonld": True}
    by_platform: dict[str, list[dict[str, Any]]] = {}
    for item in found.values():
        by_platform.setdefault(item["platform"], []).append(item)
    for platform, items in by_platform.items():
        # A readable handle must name the company (or its brand/domain); opaque numeric/channel ids are accepted only
        # when they are the site's single link for that platform. Owners' personal pages and parent-group profiles fail this.
        matching = [i for i in items if handle_matches(company, i["url"], out["brand"], site_host)
                    and not foreign_entity_handle(company, i["url"])]
        opaque = [i for i in items if opaque_handle(i["url"]) and i not in matching]
        keep = matching[:2] if matching else (opaque[:1] if len(items) == 1 else [])
        for item in keep:
            doc = item["doc"]
            span = (f"[link] {item['raw']} {item['text']}".strip() if not item.get("jsonld") else None)
            if span is None:
                raw_json = next((line for line in doc.text.split("\n") if line.startswith("[json-ld]") and item["raw"] in line), None)
                span = raw_json[:500] if raw_json and item["raw"] in raw_json[:500] else None
            if not span:
                continue
            named = handle_matches(company, item["url"], out["brand"], site_host)
            # value = the link exactly as printed on the verified site; the canonical form is kept for matching/dedupe
            claim = ledger.text_claim(doc, span, "website", "social_profile", item["raw"].strip(), qualifier=f"{platform}:{item['url']}",
                                      display=f"{platform.title() if platform != 'x' else 'X'}: {item['url']}", confidence=0.93 if named else 0.85,
                                      method="verified_site_outbound_link",
                                      extra={"platform": platform, "normalized_url": item["url"], "handle_matches_name": named})
            if claim:
                out["profiles"].append({"platform": platform, "url": item["url"], "claim_id": claim["id"]})
    # careers pages and applicant-tracking portals linked from the site
    seen_career: set[str] = set()
    for doc, page in docs:
        for link in page.links:
            host = host_of(link.url)
            path = urllib.parse.urlsplit(link.url).path
            is_ats = any(host == ats or host.endswith("." + ats) for ats in ATS_HOSTS)
            own = host.endswith(registrable(site_host))
            if not (is_ats or (own and (career_path(path) or (CAREER_TEXT.match(fold(link.text).strip()) and not re.search(r"/20\d\d/", path))))):
                continue
            url = link.url.split("#")[0]
            if url in seen_career or len(seen_career) >= 2:
                continue
            seen_career.add(url)
            claim = ledger.text_claim(doc, f"[link] {link.url} {link.text}".strip(), "hiring", "careers_page", url,
                                      display=f"Careers page: {url}", confidence=0.85, method="verified_site_outbound_link",
                                      extra={"portal": host if is_ats else None})
            if claim:
                out["careers"].append({"url": url, "claim_id": claim["id"], "portal": host if is_ats else None})
    # contact details published on the site itself
    emails_seen: set[str] = set()
    for doc, page in docs:
        for link in page.links:
            if link.url.lower().startswith("mailto:"):
                email = urllib.parse.unquote(link.url[7:].split("?")[0]).strip().lower()
                local = email.split("@")[0]
                generic = re.fullmatch(r"(post|postmottak|info|kontakt|contact|firmapost|mail|epost|salg|sales|kundeservice|service|"
                                       r"booking|bestilling|ordre|order|resepsjon|office|kontor|admin|hello|hei|support|faktura|"
                                       r"regnskap|jobb|jobs|karriere|career|presse|press|media)[0-9]*", local)
                if generic and EMAIL_RE.fullmatch(email) and registrable(email.split("@")[1]) == registrable(site_host) \
                        and email not in emails_seen and len(emails_seen) < 2:
                    emails_seen.add(email)
                    ledger.text_claim(doc, f"[link] {link.url} {link.text}".strip(), "website", "website_email", email,
                                      confidence=0.9, method="verified_site_mailto")
    return out


def feed_posts(fetcher: Fetcher, ledger: Ledger, site: SiteResult, limit: int = 8) -> list[dict[str, Any]]:
    """Dated company-owned activity from the verified site's RSS/Atom feed (or WordPress /feed/)."""
    home_page = site.pages[0][1]
    site_host = host_of(site.home_url)
    feeds = [f for f in home_page.feeds if "comment" not in f.lower() and host_of(f).endswith(registrable(site_host))]
    generator = home_page.meta.get("generator", "").lower()
    if not feeds and "wordpress" in generator:
        feeds = [urllib.parse.urljoin(site.home_url, "/feed/")]
    posts: list[dict[str, Any]] = []
    for feed_url in feeds[:1]:
        result = fetcher.get(feed_url, accept="application/rss+xml, application/atom+xml, application/xml, text/xml",
                             respect_robots=True, max_bytes=2_000_000, timeout=12)
        if not result.ok or not result.text.lstrip().startswith(("<?xml", "<rss", "<feed", "<rdf")):
            continue
        try:
            root = ET.fromstring(result.text.encode("utf-8") if isinstance(result.text, str) else result.text)
        except ET.ParseError:
            continue
        items = []
        for node in root.iter():
            tag = node.tag.split("}")[-1]
            if tag not in {"item", "entry"}:
                continue
            fields = {child.tag.split("}")[-1]: child for child in node}
            title = (fields.get("title").text or "").strip() if fields.get("title") is not None else ""
            link_node = fields.get("link")
            link = ""
            if link_node is not None:
                link = (link_node.text or "").strip() or link_node.attrib.get("href", "")
            date_node = fields.get("pubDate") or fields.get("published") or fields.get("updated") or fields.get("date")
            raw_date = (date_node.text or "").strip() if date_node is not None else ""
            iso = None
            try:
                iso = parsedate_to_datetime(raw_date).date().isoformat()
            except (TypeError, ValueError, IndexError):
                match = re.match(r"(\d{4}-\d{2}-\d{2})", raw_date)
                iso = match.group(1) if match else None
            if title and link and iso and host_of(link).endswith(registrable(site_host)):
                items.append((iso, title, link, raw_date))
        items.sort(reverse=True)
        lines = []
        for iso, title, link, raw_date in items:
            lines.append(f"[feed item] {title} | {link} | {raw_date}")
        doc = Document(url=feed_url, source_class="company_owned_feed", retrieved_at=result.retrieved_at, sha256=result.sha256,
                       text="\n".join(lines), final_url=result.final_url)
        for iso, title, link, raw_date in items[:limit]:
            claim = ledger.text_claim(doc, f"[feed item] {title} | {link} | {raw_date}", "activity", "website_post",
                                      {"title": title, "url": link, "published": raw_date}, qualifier=link,
                                      display=f"{iso} — {title}", effective_at=iso, confidence=0.95, method="rss_atom_feed",
                                      extra={"event_date": iso, "url": link})
            if claim:
                posts.append({"date": iso, "title": title, "url": link, "claim_id": claim["id"]})
    return posts


def jsonld_posts(ledger: Ledger, site: SiteResult) -> list[dict[str, Any]]:
    """Dated articles declared in JSON-LD on crawled pages (NewsArticle/BlogPosting/Article/Event)."""
    posts = []
    docs = page_documents(site.pages, "company_owned_website")
    for doc, page in docs:
        for item in page.jsonld_flat():
            kind = str(item.get("@type", "")).lower()
            if kind not in {"newsarticle", "blogposting", "article", "pressrelease", "event"}:
                continue
            item_url = str(item.get("url") or item.get("@id") or "")
            if str(item.get("@id", "")).endswith("#richSnippet"):
                continue
            if kind not in {"newsarticle", "pressrelease"} and not NEWS_PATH.search(urllib.parse.urlsplit(item_url or doc.url).path):
                continue  # SEO plugins label ordinary pages as Article/BlogPosting
            title = str(item.get("headline") or item.get("name") or "").strip()
            date = str(item.get("datePublished") or item.get("startDate") or "")[:10]
            main_entity = item.get("mainEntityOfPage")
            url = str(item.get("url") or (main_entity.get("@id", "") if isinstance(main_entity, dict) else main_entity or ""))
            if url and not host_of(url).endswith(registrable(host_of(site.home_url))):
                continue
            if not (title and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)):
                continue
            line = next((l for l in doc.text.split("\n") if l.startswith("[json-ld]") and title[:40] in l and date in l), None)
            if not line:
                continue
            claim = ledger.text_claim(doc, line[:500], "activity", "website_post", {"title": title, "published": date},
                                      qualifier=url or title, display=f"{date} — {title}", effective_at=date, confidence=0.9,
                                      method="json_ld_article", extra={"event_date": date, "url": url or doc.url})
            if claim:
                posts.append({"date": date, "title": title, "url": url or doc.url, "claim_id": claim["id"]})
    return posts


MONTHS = {"januar": 1, "january": 1, "jan": 1, "februar": 2, "february": 2, "feb": 2, "mars": 3, "march": 3, "mar": 3, "april": 4,
          "apr": 4, "mai": 5, "may": 5, "juni": 6, "june": 6, "jun": 6, "juli": 7, "july": 7, "jul": 7, "august": 8, "aug": 8,
          "september": 9, "sep": 9, "sept": 9, "oktober": 10, "october": 10, "okt": 10, "oct": 10, "november": 11, "nov": 11,
          "desember": 12, "december": 12, "des": 12, "dec": 12}
DATE_PATTERNS = (
    re.compile(r"(?<!\d)(?P<d>[0-3]?\d)\.(?P<m>[01]?\d)\.(?P<y>20\d\d)(?!\d)"),
    re.compile(r"(?<!\d)(?P<y>20\d\d)-(?P<m>[01]\d)-(?P<d>[0-3]\d)(?!\d)"),
    re.compile(r"(?<!\d)(?P<d>[0-3]?\d)\.?\s+(?P<mon>[A-Za-zæøåÆØÅ]{3,9})\.?\s+(?P<y>20\d\d)(?!\d)"),
)


def find_date(text: str, today: str) -> tuple[str, str] | None:
    """First plausible publication date in ``text`` as (iso, matched text); never in the future, not older than 4 years."""
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(text):
            parts = match.groupdict()
            month = int(parts["m"]) if parts.get("m") else MONTHS.get((parts.get("mon") or "").lower().rstrip("."))
            if not month:
                continue
            try:
                iso = f"{int(parts['y']):04d}-{month:02d}-{int(parts['d']):02d}"
                import datetime as _dt
                _dt.date.fromisoformat(iso)
            except ValueError:
                continue
            if iso <= today and iso >= f"{int(today[:4]) - 4}{today[4:]}":
                return iso, match.group(0)
    return None


NAV_TEXT = re.compile(r"(flere (saker|nyheter|artikler)|les mer|se (alle|flere)|alle (nyheter|saker|artikler)|arkiv|"
                      r"more news|all news|read more|view all|neste side|forrige side)")
NEWS_PATH = re.compile(r"(nyhet|aktuelt|news|blogg|blog|presse|artikl|article|innlegg|arkiv)", re.I)


def news_items(ledger: Ledger, site: SiteResult, today: str, extra_pages: list[tuple[FetchResult, Page]] | None = None,
               limit: int = 8) -> list[dict[str, Any]]:
    """Dated news teasers on the verified site.

    Conservative pairing: the date must be inside the link text, or be the only date on the line directly
    before/after the link text, and that date line must not be claimed by a second teaser."""
    posts: list[dict[str, Any]] = []
    seen: set[str] = set()
    site_root = registrable(host_of(site.home_url))
    for doc, page in page_documents(site.pages + (extra_pages or []), "company_owned_website"):
        lines = page.text.split("\n")
        index_of: dict[str, int] = {}
        for i, line in enumerate(lines):
            index_of.setdefault(line.strip(), i)
        candidates = []
        for link in page.links:
            url = link.url.split("#")[0]
            text = link.text.strip()
            if len(text) < 15 or url in seen or not host_of(url).endswith(site_root):
                continue
            if NAV_TEXT.search(fold(text)):
                continue
            path = urllib.parse.urlsplit(url).path.rstrip("/")
            if len(path) < 8 or url.rstrip("/") == site.home_url.rstrip("/"):
                continue
            if not (NEWS_PATH.search(path) or NEWS_PATH.search(urllib.parse.urlsplit(page.url).path)):
                continue
            found = find_date(text, today)
            if found:
                candidates.append((url, text, found, text, None))
                continue
            i = index_of.get(text)
            if i is None:
                continue
            near = []
            for j in (i - 1, i + 1):
                if 0 <= j < len(lines):
                    hit = find_date(lines[j], today)
                    if hit and len(lines[j]) <= 60:
                        near.append((j, hit))
            if len(near) != 1:
                continue
            j, hit = near[0]
            window = " ".join(lines[min(i, j): max(i, j) + 1])
            candidates.append((url, text, hit, window, j))
        used: dict[int, int] = {}
        for *_, j in candidates:
            if j is not None:
                used[j] = used.get(j, 0) + 1
        for url, text, (iso, raw_date), window, j in candidates:
            if j is not None and used.get(j, 0) > 1:
                continue
            title = re.sub(r"\s+", " ", text.replace(raw_date, " ")).strip(" -–|·,") if raw_date in text else text
            if len(title) < 10 or url in seen:
                continue
            seen.add(url)
            claim = ledger.text_claim(doc, window[:480], "activity", "website_post", {"title": title[:80], "published": raw_date},
                                      qualifier=url, display=f"{iso} — {title[:160]}", effective_at=iso, confidence=0.85,
                                      method="dated_teaser_on_verified_site", extra={"event_date": iso, "url": url})
            if claim:
                posts.append({"date": iso, "title": title, "url": url, "claim_id": claim["id"]})
            if len(posts) >= limit:
                return posts
    return posts


def news_page_url(site: SiteResult) -> str | None:
    home = site.pages[0][1]
    site_root = registrable(host_of(site.home_url))
    for link in home.links:
        path = urllib.parse.urlsplit(link.url).path.lower()
        if host_of(link.url).endswith(site_root) and re.fullmatch(r"/?(no/|nb/|en/)?(nyheter|aktuelt|news|blogg|blog|presse|artikler|"
                                                                    r"nyheiter|siste-nytt|pressemeldinger)/?", path):
            return link.url.split("#")[0]
    return None
