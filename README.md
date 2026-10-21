# Signalpost agent — evidence-first company research for Norwegian organisation numbers

Give it a batch of Norwegian organisation numbers; it returns **exactly one terminal envelope per input** with
company facts from official registers, the company's verified website, NAV's job feed and the company's own dated
activity. **Every published fact cites the exact source excerpt, URL, retrieval time and content hash, and code checks
that the cited text really contains the value before the fact is published.** Anything that cannot be tied to the exact
legal entity is left out and reported as `not_available` / `ambiguous` / `blocked` instead of guessed.

Built for the Builderr *Signalpost* challenge. Standard library only (Python ≥ 3.11), no model calls, no API keys required.

## Run it

```bash
git clone <repo> signalpost && cd signalpost
python -m venv .venv && . .venv/bin/activate        # optional: there are no dependencies to install
python -m signalpost run --organisations batch.jsonl --output out/envelopes.jsonl
```

That one command writes:

| File | What it is |
|---|---|
| `out/envelopes.jsonl` | one envelope per input organisation number, same order as the input |
| `out/run-report.json` | counts, section states, coverage per field family, requests, p50/p95, cost, contract validation |
| `out/site/index.html` | self-contained viewer: search, filters, side-by-side compare, click-through evidence (desktop + mobile) |
| `out/snapshots/` | immutable gzip snapshots of every fetched source, named by SHA-256 |
| `out/history/<run_id>.jsonl` | every run is kept; the next run diffs against the latest one |

Input may be JSONL (`{"organisation_number": "..."}` per line), a JSON list, or plain text/CSV with one number per line.
Useful options: `--bulk <brreg snapshot .csv|.jsonl[.gz]>` (identity fallback + registered website),
`--previous <envelopes.jsonl>` (explicit refresh baseline), `--expected-count N`, `--workers 24`,
`--time-budget-minutes 55` (also `SIGNALPOST_TIME_BUDGET_MINUTES`), `--run-id`, `--no-site`.
Rebuild the viewer from any envelopes file: `python -m signalpost site --envelopes out/envelopes.jsonl --site out/site`.

Tests (offline): `python -m unittest discover -s tests`.

### Optional search provider
Website discovery works without any key (registry website, registry e-mail domain, NAV employer homepage, workplace
websites, name-derived domains). If the evaluator supplies `BRAVE_API_KEY` or `TAVILY_API_KEY`, the agent also asks the
search API for website *candidates* for operating companies that still have no verified site. Search results are never
evidence: every candidate goes through the same identity gate on the independently fetched site. Cost ≈ US$0.005–0.008
per query; capped by `--max-search` (default 400 per run).

## What an envelope contains

```jsonc
{
  "schema": "signalpost.envelope/1",
  "organisation_number": "810034882",
  "status": "available",                      // available | not_available | blocked | not_applicable | ambiguous | failed
  "legal_name": "SANDNES ELEKTRISKE AS", "public_brand": "…",
  "run": {"run_id": "…", "started_at": "…", "completed_at": "…", "terminal_status": "completed", "previous_run_id": "…"},
  "sections": {                               // the brief's required sections, each with an explicit state
    "identity": {"state": "available", "claims": 31, "note": null},
    "accounts": {…}, "people": {…}, "website": {…}, "hiring": {…}, "activity": {…}
  },
  "summary": {"text": "…", "sentences": [{"text": "…", "claim_ids": ["c-…"]}], "unknowns": ["active job ads", …]},
  "claims": [{"id": "c-…", "section": "accounts", "field": "revenue", "key": "revenue|2025:SELSKAP", "value": 10021242.0,
              "display": "Revenue 2025: NOK 10,021,242", "reporting_period": "2025-01-01..2025-12-31",
              "evidence_ids": ["ev-…"], "availability": "available", "confidence": 1.0}],
  "evidence": [{"id": "ev-…", "source_url": "https://data.brreg.no/regnskapsregisteret/regnskap/810034882",
                "source_class": "official_annual_accounts", "retrieved_at": "…Z", "content_sha256": "…",
                "locator": "/0/resultatregnskapResultat/driftsresultat/driftsinntekter/sumDriftsinntekter",
                "claim_span": "10021242.0", "extraction_method": "json_pointer"}],
  "changes": [{"type": "new_role", "materiality": "high", "description": "…", "previous": {…}, "current": {…}}],
  "refresh": {"previous_run_id": "…", "material_changes": 0, "carried_forward_claims": 0, "policy": "…"},
  "discovery": [{"url": "…", "source": "registry_email_domain", "outcome": "verified|rejected|related|parked|blocked", "reason": "…"}],
  "rejected_claims": [...], "errors": [...],
  "operations": {"runtime_ms": 4120, "third_party_cost_usd": 0, "claims": 96, "evidence": 96}
}
```

Field families published: legal identity (name, form, addresses, industry codes, founding/registration dates, registered
employees, share capital, statutory purpose, VAT/business-register status, former names, group parent/subsidiaries,
registered contact details), annual accounts for every year the register returns (company and group accounts, 20 line
items), roles (CEO, chair, board, deputies, auditor, accountant), registered workplaces, verified official website and
identity proof, public brand, site description, company-owned social profiles, careers pages, active NAV job ads, dated
posts/news from the company's own site and dated register events.

## How it decides what belongs to the company

1. **Official anchor** – Brønnøysund Enhetsregisteret (entity, roles, subunits, group structure) and Regnskapsregisteret
   (accounts). Claims are JSON pointers into the stored response; person birth dates are stripped before storage.
2. **Website candidates**, strongest first: website registered in Brreg (entity or workplace, or in the supplied
   snapshot) → domain of the e-mail address registered in Brreg (free-mail excluded) → employer homepage in a NAV ad that
   carries this organisation number → domains derived from the legal name or a workplace brand → optional search.
3. **Identity gate** on the fetched site (home page plus contact/about/terms pages, robots.txt respected):
   organisation number printed on the site; or the legal name in the site's identity text together with a registered
   phone/e-mail/street address; or the full legal name *with its legal suffix* (unique in the Register of Business
   Enterprises) on a domain named after the company; or name + domain + Brreg name search proving no other registered
   entity carries that name. Discovered domains must be named after the company (directories print names and phone
   numbers too); a site printing another organisation number is rejected; a registered website that only shares
   contact details is marked `related` (group/manager site), not published.
4. **Profiles and pages from a verified site** – social links must name the company/brand/domain (opaque numeric ids only
   when single), parent-group handles (`-gruppen-as`, `-ag`) and owners' personal pages are excluded, and a profile linked
   from several companies' sites in one batch (web-agency footers) is dropped.
5. **Jobs** – NAV's public job-vacancy feed (public token, republishing permitted by NAV's API terms). An ad is attributed
   only when `employer.orgnr` is the company or one of its registered workplaces. Contact persons are never stored.
6. **Dated activity** – RSS/Atom feeds and dated news teasers on the verified site (the date must be in the teaser or the
   only date on the adjacent line), plus dated register events (role changes).

## Synthesis and refresh

The summary is generated from verified claims only (no language model). Each sentence lists the claim ids it rests on,
and `check_sentence` rejects any sentence containing a number that is not a cited value or a declared computation
(revenue change, operating margin, equity ratio). It covers what the company does, size and latest filed figures,
leadership, footprint, website and profiles, hiring, latest dated activity, changes since the previous run and what could
not be found.

Refresh is a diff on stable claim keys (`field|qualifier`), so re-running the same snapshot yields no changes. Sections
that fail or are blocked keep the previous supported value (`carried_forward_from`) instead of producing false
removals. Every run's envelopes are preserved in `history/`.

## Sources, rights and safety

| Source | Use | Terms |
|---|---|---|
| data.brreg.no Enhetsregisteret + Regnskapsregisteret | identity, roles, workplaces, group, accounts, name-uniqueness check | NLOD 2.0 open data |
| pam-stilling-feed.nav.no (public token) | active job ads by employer organisation number | NAV API terms: anyone may use and republish ads |
| The company's own website (only after the identity gate) | website, description, brand, social links, careers page, posts | robots.txt honoured; honest User-Agent; ≤2 concurrent requests per host |
| Brave / Tavily (only if a key is supplied) | website candidates only, never evidence | provider terms; results kept in memory/cache only |

Not used: LinkedIn, Facebook, Instagram, Glassdoor, Indeed or Google scraping; Brreg's `w2.brreg.no/kunngjoring`
(disallowed by robots.txt); Norid WHOIS. Outbound requests allow only http/https on ports 80/443 to public IP addresses
(every redirect hop is re-checked), bodies are size-capped, and secrets are read only from environment variables.

## Measured locally

See [EVAL.md](EVAL.md). The committed 100-company smoke test lives in [`docs/smoke/`](docs/smoke/)
(`run-report.json`, `envelopes.jsonl`, viewer `site/index.html`).
