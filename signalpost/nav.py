"""Active job ads from NAV's public job-vacancy feed (arbeidsplassen.nav.no).

Terms: "Alle kan bruke tenesta" and consumers may republish the ads (https://arbeidsplassen.nav.no/vilkar-api).
The feed uses NAV's published public token (https://pam-stilling-feed.nav.no/api/publicToken), so no personal
credential is involved. Each ad carries the employer's organisation number, which makes the company match exact:
an ad is attributed only when ``employer.orgnr`` equals the company or one of its registered subunits.
Contact persons in ads are never stored or published.
"""
from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any

from .ledger import Document, Ledger, canonical_json, tokens
from .net import Fetcher

BASE = "https://pam-stilling-feed.nav.no"
TOKEN_URL = BASE + "/api/publicToken"
FEED_URL = BASE + "/api/v1/feed"
AD_PUBLIC_URL = "https://arbeidsplassen.nav.no/stillinger/stilling/{uuid}"
GENERIC_EMPLOYER = {"as", "asa", "sa", "avd", "avdeling", "og", "i", "the", "kommune", "norge", "anonym", "arbeidsgiver", "da", "ans"}


def _name_key(name: str) -> frozenset[str]:
    return frozenset(t for t in tokens(name) if t not in GENERIC_EMPLOYER and len(t) > 1)


class NavJobs:
    def __init__(self, fetcher: Fetcher, cache_dir: str | Path | None = None, since_days: int = 100,
                 max_pages: int = 400, mode: str = "names") -> None:
        self.fetcher = fetcher
        self.cache_dir = Path(cache_dir) / "nav" if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.since_days = since_days
        self.max_pages = max_pages
        self.mode = mode
        self.token: str | None = None
        self.active: dict[str, dict[str, Any]] = {}
        self.state = "not_started"
        self.error: str | None = None
        self.feed_pages = 0
        self.details: dict[str, tuple[Any, Document]] = {}
        self.by_org: dict[str, list[str]] = {}
        self.lock = threading.Lock()

    # -- feed --------------------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def load_feed(self) -> None:
        token_result = self.fetcher.get(TOKEN_URL, accept="text/plain", retries=2, snapshot=False)
        lines = [l.strip() for l in token_result.text.splitlines() if l.strip()] if token_result.ok else []
        token = lines[-1] if lines else ""
        if not re.fullmatch(r"[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", token):
            self.state, self.error = "failed", f"public token unavailable ({token_result.error or token_result.status})"
            return
        self.token = token
        since = datetime.now(timezone.utc) - timedelta(days=self.since_days)
        latest: dict[str, dict[str, Any]] = {}
        url = FEED_URL
        headers = {**self._headers(), "If-Modified-Since": format_datetime(since, usegmt=True)}
        pages = 0
        while url and pages < self.max_pages:
            result = self.fetcher.get(url, accept="application/json", headers=headers, retries=2, snapshot=False, timeout=60,
                                      max_bytes=8_000_000)
            if not result.ok:
                self.error = f"feed page failed: {result.error or result.status}"
                break
            pages += 1
            body = result.json() or {}
            for item in body.get("items") or []:
                entry = item.get("_feed_entry") or {}
                latest[item.get("id")] = {"uuid": item.get("id"), "status": entry.get("status"), "businessName": entry.get("businessName") or "",
                                          "title": entry.get("title") or item.get("title"), "municipal": entry.get("municipal"),
                                          "modified": entry.get("sistEndret") or item.get("date_modified"), "url": item.get("url")}
            next_url = body.get("next_url")
            if not next_url or not body.get("items"):
                break
            url = BASE + next_url
            headers = self._headers()
        self.feed_pages = pages
        self.active = {k: v for k, v in latest.items() if v.get("status") == "ACTIVE"}
        self.state = "available" if pages else "failed"

    # -- matching ------------------------------------------------------------------------------
    def candidate_ads(self, names: list[str]) -> list[str]:
        keys = [k for k in (_name_key(n) for n in names) if k]
        if not keys:
            return []
        out = []
        for uuid, ad in self.active.items():
            ad_key = _name_key(ad["businessName"])
            if not ad_key:
                continue
            for key in keys:
                if key <= ad_key or (ad_key <= key and sum(len(t) for t in ad_key) >= 5):
                    out.append(uuid)
                    break
        return out

    def _detail(self, uuid: str, modified: str | None) -> tuple[Any, Document] | None:
        with self.lock:
            if uuid in self.details:
                return self.details[uuid]
        cache_file = self.cache_dir / f"{uuid}.json" if self.cache_dir else None
        payload = None
        if cache_file and cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                if cached.get("modified") == modified:
                    payload = cached
            except (OSError, ValueError):
                payload = None
        if payload is None:
            result = self.fetcher.get(f"{BASE}/api/v1/feedentry/{uuid}", accept="application/json", headers=self._headers(),
                                      retries=2, snapshot=False, timeout=30)
            if not result.ok:
                return None
            body = result.json() or {}
            content = body.get("ad_content") or {}
            # keep only non-personal fields; contact persons are dropped
            projection = {k: content.get(k) for k in ("uuid", "published", "expires", "updated", "title", "jobtitle", "applicationDue",
                                                         "engagementtype", "extent", "positioncount", "sector", "sourceurl", "source", "link")}
            projection["employer"] = {k: (content.get("employer") or {}).get(k) for k in ("name", "orgnr", "homepage")}
            projection["workLocations"] = [{k: loc.get(k) for k in ("city", "municipal", "county", "postalCode", "country")}
                                           for loc in content.get("workLocations") or []]
            projection["status"] = body.get("status")
            payload = {"modified": modified, "retrieved_at": result.retrieved_at, "sha256": result.sha256, "projection": projection}
            if cache_file:
                cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        projection = payload["projection"]
        doc = Document(url=f"{BASE}/api/v1/feedentry/{uuid}", source_class="official_job_vacancy_feed",
                       retrieved_at=payload["retrieved_at"], sha256=payload["sha256"], text=canonical_json(projection),
                       data={"ad_content": projection}, transform="contact persons and free-text description removed")
        with self.lock:
            self.details[uuid] = (projection, doc)
        return projection, doc

    def resolve(self, companies: dict[str, dict[str, Any]], workers: int = 8) -> None:
        """``companies``: org -> {"names": [...], "orgs": {org, subunit orgs...}}. Fills ``by_org``."""
        if self.state != "available":
            return
        wanted: dict[str, set[str]] = {}
        if self.mode == "full":
            for uuid in self.active:
                wanted[uuid] = set()
        else:
            for org, info in companies.items():
                for uuid in self.candidate_ads(info["names"]):
                    wanted.setdefault(uuid, set()).add(org)
        owner = {sub: org for org, info in companies.items() for sub in info["orgs"]}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda u: (u, self._detail(u, self.active[u].get("modified"))), list(wanted)))
        for uuid, detail in results:
            if not detail:
                continue
            projection, _ = detail
            employer_org = re.sub(r"\D", "", str((projection.get("employer") or {}).get("orgnr") or ""))
            if employer_org in owner and projection.get("status") == "ACTIVE":
                self.by_org.setdefault(owner[employer_org], []).append(uuid)

    def homepages(self, org: str) -> list[str]:
        out = []
        for uuid in self.by_org.get(org, []):
            projection, _ = self.details[uuid]
            homepage = (projection.get("employer") or {}).get("homepage")
            if homepage:
                out.append(homepage)
        return out

    def claims(self, ledger: Ledger, org: str, today: str) -> list[dict[str, Any]]:
        jobs = []
        for uuid in self.by_org.get(org, []):
            projection, doc = self.details[uuid]
            expires = (projection.get("expires") or "")[:10]
            if expires and expires < today:
                continue
            published = (projection.get("published") or "")[:10] or None
            locations = ", ".join(sorted({(l.get("city") or l.get("municipal") or "").title() for l in projection.get("workLocations") or []
                                          if l.get("city") or l.get("municipal")}))
            claim = ledger.json_claim(doc, "/ad_content", "hiring", "job_posting",
                                      value={"title": projection.get("title"), "employer_orgnr": projection["employer"].get("orgnr")},
                                      qualifier=uuid, effective_at=published, span_keys=("title", "employer", "published", "expires"),
                                      display=f"{projection.get('title')}" + (f" — {locations}" if locations else ""),
                                      method="nav_feed_exact_orgnr",
                                      extra={"event_date": published, "expires": expires or None, "location": locations or None,
                                             "employer_name": projection["employer"].get("name"), "url": AD_PUBLIC_URL.format(uuid=uuid),
                                             "positions": projection.get("positioncount"), "extent": projection.get("extent"),
                                             "engagement": projection.get("engagementtype"), "job_title": projection.get("jobtitle")})
            if claim:
                jobs.append({"uuid": uuid, "title": projection.get("title"), "published": published, "expires": expires or None,
                             "location": locations or None, "url": AD_PUBLIC_URL.format(uuid=uuid), "claim_id": claim["id"]})
        jobs.sort(key=lambda j: j.get("published") or "", reverse=True)
        return jobs
