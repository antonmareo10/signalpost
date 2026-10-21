"""Optional search providers for website *candidates* (never evidence).

Enabled only when a key is supplied through an environment variable (TAVILY_API_KEY or BRAVE_API_KEY).
Results are kept in memory only: the provider's titles/snippets are discarded and every candidate must
pass the same exact-entity gate on the independently fetched website before anything is published.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.parse
from typing import Any

from .net import Fetcher
from .web import SHARED_HOSTS, Company, host_of

DIRECTORY_HOSTS = SHARED_HOSTS | {"proff.no", "purehelp.no", "gulesider.no", "1881.no", "finn.no", "firmasjekk.no", "regnskapstall.no",
                                  "bedriftsdatabasen.no", "allabolag.se", "dnb.com", "kompass.com", "opencorporates.com", "infobel.com",
                                  "northdata.com", "wikipedia.org", "linkedin.com", "facebook.com", "instagram.com", "youtube.com",
                                  "enirocdn.com", "nettavisen.no", "vg.no", "dn.no", "e24.no", "nrk.no", "tv2.no", "aftenposten.no",
                                  "mittanbud.no", "anbud365.no", "bygg.no", "legelisten.no", "tripadvisor.com", "tripadvisor.no",
                                  "trustpilot.com", "yelp.com", "google.com", "apple.com", "bing.com", "brreg.no", "nav.no", "stortinget.no",
                                  "lovdata.no", "forvalt.no", "virksomhetsdatabasen.no", "kartverket.no", "seeiendom.no", "boligmappa.no",
                                  "startsiden.no", "120.no", "kvasir.no", "hitta.se", "eniro.no", "norgesnettet.no", "norskeskog.no",
                                  "kredittsjekk.no", "1850.no", "byndle.no", "forretningsflyt.no", "firmadatabasen.no", "firmabasen.no",
                                  "vexter.no", "fagfolkguiden.no", "vilbli.no", "utdanning.no", "dibk.no", "verkstedregisteret.no",
                                  "bilmappa.no", "skademeldinger.no", "byggsikt.no", "bhgplass.no", "barnehagelisten.no",
                                  "barnehagefakta.no", "felleskatalogen.no", "kulturrom.no", "fiskeriportalen.no", "skipsrevyen.no",
                                  "graveplassen.no", "snekkersentralen.no", "bestillerorlegger.no", "sjekkpunkt.no", "helsenorge.no",
                                  "legelisten.no", "finnbedrift.no", "bedrift.no", "nordicnet.no", "advokatforeningen.no",
                                  "regnskapnorge.no", "revisorforeningen.no", "ifinnmark.no", "lokalavisen.no", "bizzdo.no",
                                  "norskeansatte.no", "proffnett.no", "bedriftskatalogen.no", "gulex.no", "firmanett.no",
                                  "infobel.no", "europages.com", "opplysningen1881.no", "rorleggerlisten.no", "xn--rrleggerlisten-qqb.no",
                                  "smartepenger.no", "kundeklubb.no", "hjemmesnekker.no", "bygghjemme.no", "anbudstorget.no",
                                  "glassdoor.com", "indeed.com", "jobbsafari.no", "karriere.no", "stepstone.no", "talentech.no",
                                  "facebook.no", "wikidata.org", "slideshare.net", "issuu.com", "scribd.com", "yumpu.com",
                                  "regjeringen.no", "ssb.no", "doffin.no", "mercell.com", "tenderned.nl", "bloomberg.com",
                                  "crunchbase.com", "zoominfo.com", "rocketreach.co", "apollo.io", "lusha.com", "signalhire.com"}


# Tavily accepts a bounded exclude list; the biggest directory/aggregator hosts seen in Norwegian results.
EXCLUDE_FOR_PROVIDER = {"proff.no", "purehelp.no", "gulesider.no", "1881.no", "finn.no", "kredittsjekk.no", "1850.no", "byndle.no",
                        "forretningsflyt.no", "firmadatabasen.no", "vexter.no", "fagfolkguiden.no", "vilbli.no", "utdanning.no",
                        "linkedin.com", "facebook.com", "instagram.com", "regnskapstall.no", "firmasjekk.no", "brreg.no",
                        "bedriftsdatabasen.no", "mittanbud.no", "legelisten.no", "dnb.com", "northdata.com", "opencorporates.com",
                        "barnehagefakta.no", "verkstedregisteret.no", "byggsikt.no", "forvalt.no"}


class SearchProvider:
    name = "none"
    cost_per_call = 0.0

    def __init__(self, fetcher: Fetcher, key: str, max_calls: int) -> None:
        self.fetcher = fetcher
        self.key = key
        self.max_calls = max_calls
        self.calls = 0
        self.cost = 0.0
        self.lock = threading.Lock()
        self.last_cost = 0.0

    @staticmethod
    def from_env(fetcher: Fetcher, max_calls: int = 400) -> "SearchProvider | None":
        if os.environ.get("TAVILY_API_KEY"):
            return Tavily(fetcher, os.environ["TAVILY_API_KEY"], max_calls)
        if os.environ.get("BRAVE_API_KEY"):
            return Brave(fetcher, os.environ["BRAVE_API_KEY"], max_calls)
        return None

    def _reserve(self) -> bool:
        with self.lock:
            if self.calls >= self.max_calls:
                return False
            self.calls += 1
            self.cost += self.cost_per_call
            return True

    def query_for(self, company: Company) -> str:
        city = company.city.title() if company.city else ""
        name = company.name
        return f"\"{name}\" {city}".strip()

    def find_sites(self, company: Company) -> list[str]:
        self.last_cost = 0.0
        if not self._reserve():
            return []
        self.last_cost = self.cost_per_call
        urls = self._search(self.query_for(company))
        out: list[str] = []
        for url in urls:
            host = host_of(url)
            if not host or any(host == d or host.endswith("." + d) for d in DIRECTORY_HOSTS):
                continue
            root = f"https://{urllib.parse.urlsplit(url).hostname}"
            if root not in out:
                out.append(root)
        return out[:3]

    def _search(self, query: str) -> list[str]:
        raise NotImplementedError


class Tavily(SearchProvider):
    name = "tavily"
    cost_per_call = 0.008  # one basic-search credit

    def _search(self, query: str) -> list[str]:
        body = json.dumps({"query": query, "search_depth": "basic", "max_results": 8, "include_answer": False,
                           "include_raw_content": False, "country": "norway",
                           "exclude_domains": sorted(EXCLUDE_FOR_PROVIDER)}).encode("utf-8")
        result = self.fetcher.get("https://api.tavily.com/search", accept="application/json", data=body, snapshot=False,
                                  headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"}, timeout=25)
        if not result.ok:
            return []
        try:
            data: Any = result.json()
        except ValueError:
            return []
        return [item.get("url", "") for item in (data or {}).get("results", []) if item.get("url")]


class Brave(SearchProvider):
    name = "brave"
    cost_per_call = 0.005

    def _search(self, query: str) -> list[str]:
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({"q": query, "country": "NO", "count": 8})
        result = self.fetcher.get(url, accept="application/json", snapshot=False, headers={"X-Subscription-Token": self.key}, timeout=20)
        if not result.ok:
            return []
        try:
            data: Any = result.json()
        except ValueError:
            return []
        return [item.get("url", "") for item in ((data or {}).get("web") or {}).get("results", []) if item.get("url")]
