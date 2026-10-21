"""Batch orchestration: one terminal envelope per input organisation number, always."""
from __future__ import annotations

import gzip
import json
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .ledger import Ledger
from .nav import NavJobs
from .net import Fetcher, resolve, utc_now
from .refresh import diff
from .registry import (account_claims, entity_claims, fetch_accounts, fetch_entity, fetch_group, fetch_roles, fetch_subunits,
                       group_claims, role_claims, subunit_claims)
from .search import SearchProvider
from .synth import build_summary
from .web import (FREEMAIL, Candidate, Company, SiteResearcher, candidate_slugs, extract_site, feed_posts, handle_matches, host_of,
                  jsonld_posts, name_tokens, normalize_site_url, phone_digits, registrable)

SECTIONS = ("identity", "accounts", "people", "website", "hiring", "activity")
STATES = {"available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"}


@dataclass
class Work:
    org: str
    ledger: Ledger
    started: float = field(default_factory=time.monotonic)
    states: dict[str, str] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    entity: dict[str, Any] = field(default_factory=dict)
    accounts: list[dict[str, Any]] = field(default_factory=list)
    people: list[dict[str, Any]] = field(default_factory=list)
    subunits: list[dict[str, Any]] = field(default_factory=list)
    company: Company | None = None
    site: dict[str, Any] | None = None
    discovery: list[dict[str, Any]] = field(default_factory=list)
    jobs: list[dict[str, Any]] = field(default_factory=list)
    posts: list[dict[str, Any]] = field(default_factory=list)
    requests_before: int = 0
    search_cost: float = 0.0


class Agent:
    def __init__(self, *, run_id: str, snapshot_dir: str | None, cache_dir: str | None, workers: int = 16,
                 time_budget_s: float = 3000, guess_domains: bool = True, nav_mode: str = "names", use_search: bool = True,
                 search_min_revenue: float = 5_000_000, max_search: int = 400, log=print) -> None:
        self.run_id = run_id
        self.fetcher = Fetcher(snapshot_dir=snapshot_dir)
        self.cache_dir = cache_dir
        self.workers = workers
        self.deadline = time.monotonic() + time_budget_s
        self.guess_domains = guess_domains
        self.nav = NavJobs(self.fetcher, cache_dir=cache_dir, mode=nav_mode)
        self.search = SearchProvider.from_env(self.fetcher, max_calls=max_search) if use_search else None
        self.search_min_revenue = search_min_revenue
        self.sites = SiteResearcher(self.fetcher)
        self.log = log
        self.started_at = utc_now()
        self.today = datetime.now(timezone.utc).date().isoformat()
        self._errors: dict[str, list[dict[str, Any]]] = {}
        self._elapsed: dict[str, float] = {}
        self._errors_lock = threading.Lock()

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    # -- phase A: official registers --------------------------------------------------------------
    def official(self, work: Work, bulk_row: dict[str, Any] | None) -> None:
        org, ledger = work.org, work.ledger
        result = fetch_entity(self.fetcher, org)
        state, entity = entity_claims(ledger, result)
        if state != "available":
            work.errors.append({"section": "identity", "source": result.url, "error": result.error or f"HTTP {result.status}"})
            if bulk_row:
                work.notes["identity"] = "live register unavailable; identity anchored on the supplied registry snapshot only"
        work.states["identity"] = state if not (state != "available" and bulk_row) else "available"
        work.entity = entity or {}
        name = entity.get("navn") or (bulk_row or {}).get("name") or (bulk_row or {}).get("navn") or ""
        if result.status == 410 or entity.get("slettedato"):
            work.notes["identity"] = "entity deleted from the register"
        acc = fetch_accounts(self.fetcher, org)
        work.states["accounts"], work.accounts = account_claims(ledger, acc)
        if work.states["accounts"] != "available" and acc.status not in (404, 410):
            work.errors.append({"section": "accounts", "source": acc.url, "error": acc.error or f"HTTP {acc.status}"})
        roles = fetch_roles(self.fetcher, org)
        roles_state, work.people = role_claims(ledger, roles, self.fetcher)
        subs = fetch_subunits(self.fetcher, org)
        subs_state, work.subunits = subunit_claims(ledger, subs)
        if "failed" in (roles_state, subs_state):
            work.errors.append({"section": "people", "source": roles.url if roles_state == "failed" else subs.url,
                                "error": "role or subunit lookup failed"})
        work.states["people"] = "available" if (work.people or work.subunits) else ("failed" if "failed" in (roles_state, subs_state) else "not_available")
        if entity.get("erIKonsern"):
            group = fetch_group(self.fetcher, org)
            group_claims(ledger, group, org)
        phones = {p for p in (phone_digits(entity.get("telefon")), phone_digits(entity.get("mobil"))) if p}
        for unit in work.subunits:
            phones |= {p for p in (phone_digits(x) for x in unit.get("phones", [])) if p}
        emails = {e.lower() for e in [entity.get("epostadresse")] + [u.get("email") for u in work.subunits] if e}
        address = entity.get("forretningsadresse") or {}
        revenue = None
        company_years = [y for y in work.accounts if y.get("account_type") == "SELSKAP"] or work.accounts
        if company_years and "revenue" in company_years[0]:
            revenue = company_years[0]["revenue"]["value"]
        work.company = Company(org=org, name=name, legal_form=(entity.get("organisasjonsform") or {}).get("kode", ""),
                               phones=phones, emails=emails, street=" ".join(address.get("adresse") or []),
                               postcode=address.get("postnummer") or "", city=address.get("poststed") or "",
                               aliases=[h.get("navn") for h in entity.get("historiskeNavn") or [] if h.get("navn")],
                               other_addresses=[(u["street"], u["postcode"]) for u in work.subunits if u.get("street") and u.get("postcode")],
                               brands=self._subunit_brands(name, work.subunits),
                               employees=entity.get("antallAnsatte"), revenue=revenue,
                               industry=(entity.get("naeringskode1") or {}).get("kode", ""))

    # -- phase C: website and footprint -------------------------------------------------------------
    def candidates(self, work: Work) -> list[Candidate]:
        company, entity = work.company, work.entity
        assert company is not None
        out: list[Candidate] = []
        seen: set[str] = set()

        def add(url: str | None, source: str, strength: str, note: str = "") -> None:
            normalized = normalize_site_url(url)
            if not normalized:
                return
            key = registrable(host_of(normalized))
            if key in seen:
                return
            seen.add(key)
            out.append(Candidate(normalized, source, strength, note))

        def email_domain(email: str | None) -> str | None:
            domain = (email or "").split("@")[-1].strip().lower()
            if domain and domain not in FREEMAIL and not any(domain.endswith("." + f) for f in FREEMAIL):
                return domain
            return None

        add(entity.get("hjemmeside"), "registry_website", "strong")
        add(email_domain(entity.get("epostadresse")), "registry_email_domain", "medium", entity.get("epostadresse") or "")
        for homepage in self.nav.homepages(work.org):
            add(homepage, "nav_job_ad_employer_homepage", "medium")
        for unit in work.subunits:
            add(unit.get("website"), "registry_subunit_website", "strong")
        for unit in work.subunits:
            add(email_domain(unit.get("email")), "registry_subunit_email_domain", "medium", unit.get("email") or "")
        if self.guess_domains and self._operating(company):
            slugs = candidate_slugs(company)
            for brand in company.brands[:2]:
                slugs += candidate_slugs(Company(org=company.org, name=brand))[:1]
            for slug in slugs:
                for tld in (".no", ".com"):
                    host = slug + tld
                    if registrable(host) in seen:
                        continue
                    if resolve(host) or resolve("www." + host):
                        add("https://" + host, "domain_guess_from_legal_name", "weak")
        return out

    @staticmethod
    def _subunit_brands(legal_name: str, subunits: list[dict[str, Any]]) -> list[str]:
        """Workplace names that are distinct trading names (not 'LEGAL NAME AVD X')."""
        legal = set(name_tokens(legal_name))
        out = []
        for unit in subunits:
            unit_name = unit.get("name") or ""
            toks = set(name_tokens(unit_name))
            if not toks or toks & legal or len("".join(toks)) < 5:
                continue
            if re.search(r"\b(avd|avdeling|filial|kontor)\b", unit_name.lower()):
                continue
            out.append(unit_name)
        return out[:5]

    def _operating(self, company: Company) -> bool:
        name = company.name.lower()
        if re.search(r"\b(holding|invest|investering|eiendom|eiendommer|property|kapital|capital)\b", name):
            return False
        if company.industry.startswith(("64.2", "64.3", "68.2", "70.1")):
            return False
        return bool((company.employees or 0) >= 1 or (company.revenue or 0) >= 1_000_000)

    def footprint(self, work: Work) -> None:
        company = work.company
        assert company is not None
        ledger = work.ledger
        verified = None
        extra_sites: list[Any] = []
        related = None
        blocked = False
        candidates = self.candidates(work)
        tried_search = False
        index = 0
        while index < len(candidates) or (verified is None and not tried_search):
            if index >= len(candidates):
                tried_search = True
                if self.search and self.remaining() > 120 and self._search_worthy(company):
                    found = self.search.find_sites(company)
                    work.search_cost += self.search.last_cost
                    known = {registrable(host_of(c.url)) for c in candidates}
                    for url in found:
                        normalized = normalize_site_url(url)
                        if normalized and registrable(host_of(normalized)) not in known:
                            known.add(registrable(host_of(normalized)))
                            candidates.append(Candidate(normalized, f"search:{self.search.name}", "weak"))
                if index >= len(candidates):
                    break
            candidate = candidates[index]
            index += 1
            if self.remaining() < 30:
                work.errors.append({"section": "website", "error": "time budget exhausted before website research"})
                break
            result = self.sites.research(company, candidate)
            work.discovery.append({"url": candidate.url, "source": candidate.source, "outcome": result.state, "reason": result.reason,
                                   "final_url": result.home_url or None})
            if result.state == "verified":
                if verified is None:
                    verified = result
                    if not self._more_sites_worthwhile(candidates, index):
                        break
                    continue
                if registrable(host_of(result.home_url)) != registrable(host_of(verified.home_url)):
                    extra_sites.append(result)
                if len(extra_sites) >= 2:
                    break
                continue
            if result.state == "related" and related is None:
                related = result
            if result.state == "blocked":
                blocked = True
        if verified:
            work.site = extract_site(ledger, company, verified)
            for extra in extra_sites:
                extra_info = extract_site(ledger, company, extra, primary=False)
                work.site.setdefault("additional", []).append({"url": extra_info["url"], "claim_id": extra_info.get("claim_id")})
            if self.remaining() > 20:
                work.posts = feed_posts(self.fetcher, ledger, verified) + jsonld_posts(ledger, verified)
            work.states["website"] = "available" if work.site.get("claim_id") else "failed"
        elif related:
            work.states["website"] = "ambiguous"
            work.notes["website"] = f"{related.home_url}: {related.reason}"
        elif blocked:
            work.states["website"] = "blocked"
            work.notes["website"] = "candidate website refused automated access (robots.txt)"
        else:
            work.states["website"] = "not_available"
            if not candidates:
                work.notes["website"] = "no website listed in the register and no verifiable candidate"
            else:
                work.notes["website"] = "candidates checked but none could be tied to this exact legal entity"
        # hiring
        work.jobs = self.nav.claims(ledger, work.org, self.today)
        careers = ledger.by_field("careers_page")
        if work.jobs or careers:
            work.states["hiring"] = "available"
        elif self.nav.state == "available":
            work.states["hiring"] = "not_available"
            work.notes["hiring"] = "no active ad with this organisation number (or its workplaces) in NAV's job feed"
        else:
            work.states["hiring"] = "failed"
            work.notes["hiring"] = f"NAV job feed unavailable: {self.nav.error}"
        activity = ledger.section_claims("activity")
        work.states["activity"] = "available" if activity else "not_available"

    @staticmethod
    def _more_sites_worthwhile(candidates: list[Candidate], index: int) -> bool:
        """After the primary site is verified, keep checking remaining registry-sourced candidates (brand sites of workplaces)."""
        return any(c.source.startswith("registry") for c in candidates[index:])

    def _search_worthy(self, company: Company) -> bool:
        if re.search(r"\b(holding|invest|eiendom|eiendommer)\b", company.name.lower()):
            return False
        return (company.employees or 0) >= 5 or (company.revenue or 0) >= self.search_min_revenue

    # -- batch ------------------------------------------------------------------------------------------
    def run(self, orgs: list[str], bulk: dict[str, dict[str, Any]] | None = None,
            previous: dict[str, dict[str, Any]] | None = None, previous_run_id: str | None = None) -> list[dict[str, Any]]:
        works = {org: Work(org, Ledger(org)) for org in orgs}
        nav_thread = threading.Thread(target=self._load_nav, daemon=True)
        nav_thread.start()
        self.log(f"[phase A] official registers for {len(orgs)} companies")
        self._parallel(orgs, lambda org: self.official(works[org], (bulk or {}).get(org)), "official")
        nav_thread.join(timeout=max(5, self.remaining() - 600))
        if self.nav.state == "available":
            names = {}
            for org, work in works.items():
                if work.company is None:
                    continue
                labels = [work.company.name] + work.company.aliases + [u["name"] for u in work.subunits if u.get("name")]
                names[org] = {"names": labels, "orgs": {org} | {u["organisation_number"] for u in work.subunits if u.get("organisation_number")}}
            self.nav.resolve(names)
            self.log(f"[phase B] NAV feed: {len(self.nav.active)} active ads, matched {sum(len(v) for v in self.nav.by_org.values())} ads "
                     f"to {len(self.nav.by_org)} companies")
        else:
            self.log(f"[phase B] NAV feed unavailable: {self.nav.error}")
        self.log("[phase C] websites, profiles, jobs and activity")
        self._parallel([o for o in orgs if works[o].company], lambda org: self.footprint(works[org]), "footprint")
        self._dedupe_shared_profiles(works)
        envelopes = []
        for org in orgs:
            envelopes.append(self.envelope(works[org], (previous or {}).get(org), previous_run_id))
        return envelopes

    def _load_nav(self) -> None:
        try:
            self.nav.load_feed()
        except Exception as exc:  # never let the jobs source break the batch
            self.nav.state, self.nav.error = "failed", f"{type(exc).__name__}: {exc}"

    def _parallel(self, orgs: list[str], fn, label: str) -> None:
        done = 0
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(self._guard, fn, org, label): org for org in orgs}
            for future in as_completed(futures):
                done += 1
                if done % 50 == 0 or done == len(orgs):
                    self.log(f"  {label}: {done}/{len(orgs)} (requests so far {self.fetcher.stats.requests})")

    def _guard(self, fn, org: str, label: str) -> None:
        started = time.monotonic()
        try:
            fn(org)
        except Exception as exc:
            with self._errors_lock:
                self._errors.setdefault(org, []).append({"stage": label, "error": f"{type(exc).__name__}: {exc}",
                                                         "trace": traceback.format_exc(limit=3)[-600:]})
        finally:
            with self._errors_lock:
                self._elapsed[org] = self._elapsed.get(org, 0.0) + time.monotonic() - started

    def _dedupe_shared_profiles(self, works: dict[str, Work]) -> None:
        """A social URL attributed to two different companies in one batch is an agency/parent link unless its handle names the company."""
        owners: dict[str, set[str]] = {}
        for org, work in works.items():
            for claim in work.ledger.by_field("social_profile"):
                owners.setdefault(claim.get("normalized_url") or claim["value"], set()).add(org)
        for url, orgs in owners.items():
            if len(orgs) < 2:
                continue
            for org in orgs:
                work = works[org]
                for claim in list(work.ledger.by_field("social_profile")):
                    if (claim.get("normalized_url") or claim["value"]) == url and not claim.get("handle_matches_name"):
                        work.ledger.claims.remove(claim)
                        work.ledger.rejected.append({"field": "social_profile", "value": url,
                                                     "reason": "same profile linked from several companies' sites in this batch"})
                        if work.site:
                            work.site["profiles"] = [p for p in work.site["profiles"] if p["url"] != url]

    # -- envelope ----------------------------------------------------------------------------------------
    def envelope(self, work: Work, previous: dict[str, Any] | None, previous_run_id: str | None) -> dict[str, Any]:
        ledger = work.ledger
        errors = work.errors + self._errors.get(work.org, [])
        for section in SECTIONS:
            work.states.setdefault(section, "failed" if errors else "not_available")
        failed_sections = {s for s, st in work.states.items() if st in ("failed", "blocked")}
        changes, carried = diff({"claims": ledger.claims}, previous, failed_sections)
        if carried:
            prev_evidence = {e["id"]: e for e in (previous or {}).get("evidence", [])}
            for claim in carried:
                ledger.claims.append(claim)
                for ev_id in claim.get("evidence_ids", []):
                    if ev_id in prev_evidence and ev_id not in ledger.evidence:
                        ledger.evidence[ev_id] = prev_evidence[ev_id]
        missing = []
        if work.states.get("website") != "available":
            missing.append("website")
        if not ledger.by_field("social_profile"):
            missing.append("profiles")
        if work.states.get("hiring") != "available":
            missing.append("hiring")
        if not ledger.by_field("website_post"):
            missing.append("activity")
        if work.states.get("accounts") != "available":
            missing.append("accounts")
        summary = build_summary(ledger, {"accounts": work.accounts, "changes": changes, "previous_run_id": (previous or {}).get("run", {}).get("run_id"),
                                         "missing": missing})
        sections = {}
        for section in SECTIONS:
            claim_ids = [c["id"] for c in ledger.claims if c["section"] == section]
            state = work.states.get(section, "not_available")
            if state not in STATES:
                state = "failed"
            sections[section] = {"state": state, "claims": len(claim_ids), "note": work.notes.get(section)}
        status = "available" if ledger.claims else ("failed" if errors else "not_available")
        legal_name = (ledger.first("legal_name") or {}).get("value")
        brand = (ledger.first("public_brand") or {}).get("value")
        now = utc_now()
        envelope = {
            "schema": "signalpost.envelope/1",
            "organisation_number": work.org,
            "status": status,
            "legal_name": legal_name,
            "public_brand": brand,
            "run": {"run_id": self.run_id, "agent_version": __version__, "started_at": self.started_at, "completed_at": now,
                    "terminal_status": "completed" if status != "failed" else "failed",
                    "previous_run_id": (previous or {}).get("run", {}).get("run_id")},
            "sections": sections,
            "summary": summary,
            "claims": ledger.claims,
            "evidence": list(ledger.evidence.values()),
            "changes": changes,
            "refresh": {"previous_run_id": (previous or {}).get("run", {}).get("run_id"),
                        "previous_completed_at": (previous or {}).get("run", {}).get("completed_at"),
                        "material_changes": sum(1 for c in changes if c["materiality"] in ("high", "medium")),
                        "carried_forward_claims": len(carried),
                        "policy": "stable claim keys; failed/blocked sections keep the last supported value; prior envelopes preserved in history/"},
            "discovery": work.discovery,
            "rejected_claims": ledger.rejected[:50],
            "errors": errors,
            "operations": {"runtime_ms": int(self._elapsed.get(work.org, 0.0) * 1000), "third_party_cost_usd": round(work.search_cost, 4),
                           "claims": len(ledger.claims), "evidence": len(ledger.evidence)},
        }
        return envelope
