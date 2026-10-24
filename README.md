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
| `out/site/index.html` (+ `out/site/data/`) | the viewer: find, compare and verify on desktop and mobile, no server, no external requests (see below; live smoke-test copy: https://antonmareo10.github.io/signalpost/smoke/site/) |
| `out/snapshots/` | immutable gzip snapshots of every fetched source, named by SHA-256 |
| `out/history/<run_id>.jsonl` | every run is kept; the next run diffs against the latest one |

Input may be JSONL (`{"organisation_number": "..."}` per line), a JSON list, or plain text/CSV with one number per line.
Useful options: `--bulk <brreg snapshot .csv|.jsonl[.gz]>` (identity fallback + registered website),
`--previous <envelopes.jsonl>` (explicit refresh baseline), `--expected-count N`, `--workers 24`,
`--time-budget-minutes 55` (also `SIGNALPOST_TIME_BUDGET_MINUTES`), `--run-id`, `--no-site`.
Rebuild the viewer from any envelopes file: `python -m signalpost site --envelopes out/envelopes.jsonl --site out/site`.

Tests (offline): `python -m unittest discover -s tests`.

### The viewer (find, compare, verify)
- **Find**: one search box over name, organisation number (with or without spaces), brand, place, person, industry and
  former names, folded for æ/ø/å, ranked by best match; Enter on an exact organisation number opens that profile; `/` or
  Ctrl/⌘+K focuses the search; filters for verified website, hiring, social profiles, dated posts, filed accounts, signals
  and changes; sort by best match, data found, name, revenue or employees.
- **Compare**: tick two to four companies, or press "Compare with…" on a profile; similar companies in the run (same
  industry code, then same place) are offered as one-click additions. A comparison has its own link
  (`#/compare/<org>,<org>`) that opens the same table on another device. Rows: the "In brief" overview, what was found,
  industry, place, founding year, employees, latest revenue and its change, results, equity, leaders, workplaces,
  website, profiles, job ads, latest post, signals, changes and gaps; shaded rows differ; every value has its source
  button. The first column stays fixed on phones.
- **Verify**: every statement carries a numbered source button. The numbers are the profile's list of sources (the same
  numbers as the summary's `sources` in the envelope); hovering shows the source and its retrieval date, and a click opens
  the exact excerpt, the source named in plain English, the URL, the retrieval time, the SHA-256 of the stored copy and
  the JSON pointer or locator, with "Open source" and "Copy citation". Each profile can be downloaded as JSON.
- **States**: every section shows found, not found, blocked, ambiguous, failed or not applicable with an icon and a word,
  never colour alone, and a legend explains each one. Missing values read "not found", never zero.
- Each profile opens with "In brief" (three to five cited sentences: what the company is, how its latest accounts look,
  its online presence, what changed recently and what was not found), then the five labelled parts, the accounts table
  with the official PDF of every filed year, identity, leadership, website and profiles, hiring, a dated timeline,
  changes since our previous run, what could not be found with the reason, the numbered sources and every fact.
- **Fast at batch scale**: the page carries a compact index of every company (about 0.6 MB for 1,000); each profile
  (about 37 KB) is written to `site/data/<org>.js` and loaded when it is opened, so the 1,000-company viewer shows its
  list in 0.2 s on a laptop and 1.2 s on a phone emulated with a 4× slower CPU (1.3.0's single 50 MB page: 1.9 s and 21 s). Small batches stay a single file. Profiles load through a `<script>` tag, so the
  viewer works from disk (file://) as well as from any static host; keep `data/` next to `index.html`.
- Accessibility: keyboard only (skip link, focus trap and Escape in the evidence panel, focus returns to the button),
  labelled landmarks and controls, light and dark themes; axe-core 4.14 (WCAG 2.2 AA and best practice) reports no
  violations on the list, a profile, the evidence panel and a comparison, at 1440 px and at 390 px.

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
  "summary": {"overview": "WYSSEN NORGE AS (trading as Wyssen Avalanche) is a Sogndal-based private limited company in …",
              "text": "In brief: … What it does: … Money: … People and presence: … What changed: … Not found: …",
              "sentences": [{"text": "…", "claim_ids": ["c-…"], "sources": [1, 3], "part": "what_changed"}],
              "parts": {"overview": […], "what_it_does": […], "money": […], "people_and_presence": […], "what_changed": […], "unknown": […]},
              "sources": [{"n": 1, "url": "https://data.brreg.no/enhetsregisteret/api/enheter/916340257",
                           "source": "Brønnøysund Register Centre: entity record (live API)", "retrieved_at": "…Z"}],
              "markdown": "### In brief
… [1] [2]
…
### Sources
[1] …",
              "signals": [{"text": "Revenue grew 107.4% in 2025.", "claim_ids": […], "tone": "up", "sources": [3]}],
              "unknowns": ["active job ads", …], "unknown_detail": [{"item": "…", "state": "not_available", "reason": "…"}]},
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
registered contact details, official English industry label), annual accounts for every year the register returns
(company and group accounts, 20 line items) plus the official PDF copy of every filed year, roles (CEO, chair, board,
deputies, auditor, accountant), registered workplaces, verified official website and identity proof, public brand, site
description, company-owned social profiles, careers pages, active NAV job ads, dated posts/news from the company's own
site, and the dated register history (what the register changed and when: employee count, filed accounts, addresses,
industry code, contact details, roles).

## How it decides what belongs to the company

1. **Official anchor** – Brønnøysund Enhetsregisteret (entity, roles, subunits, group structure) and Regnskapsregisteret
   (accounts). Claims are JSON pointers into the stored response; person birth dates are stripped before storage.
2. **Website candidates**, strongest first: website registered in Brreg (entity or workplace, or in the supplied
   snapshot) → domain of the e-mail address registered in Brreg (free-mail excluded) → employer homepage in a NAV ad that
   carries this organisation number → domains derived from the legal name or a workplace brand → optional search.
   Name-derived domains are tried for operating companies (registered employees or NOK 1M+ revenue) and, since 1.2.0,
   for small active ones (no employees, NOK 100k–1M revenue; holding, property and investment companies excluded). If a
   candidate fails for a reason that says nothing about the site (DNS, connection, TLS, timeout, a dead deep link), the
   same registrable domain is tried once more with or without `www` and at its root; a refusal (robots.txt, HTTP
   401/403/429) is never retried under another spelling.
3. **Identity gate** on the fetched site (home page plus contact/about/terms pages, robots.txt respected):
   organisation number printed on the site; or the legal name in the site's identity text together with a registered
   phone/e-mail/street address; or the full legal name *with its legal suffix* (unique in the Register of Business
   Enterprises) on a domain named after the company; or name + domain + Brreg name search proving no other registered
   entity carries that name. Discovered domains must be named after the company (directories print names and phone
   numbers too); a site printing another organisation number is rejected; a registered website that only shares
   contact details is marked `related` (group/manager site), not published. For small active companies the name-search
   route is not enough: fewer of them have a site at all, so their sites need the organisation number, the exact legal
   name or the legal name plus a registered contact detail.
   Since 1.3.0, a website the company itself lists in the register that answers but refuses automated access
   (robots.txt or HTTP 401/403/429) is published from the register listing when its domain is named after the company
   (for the domain of the registered e-mail address, only when it spells the whole legal name). Its pages are not read,
   so no brand, profile, careers page or post comes from it, and the profile says so. A domain that does not resolve
   with or without `www` is reported as gone (`not_available`), not as `blocked`.
4. **Profiles and pages from a verified site** – social links must name the company/brand/domain (opaque numeric ids only
   when single), parent-group handles (`-gruppen-as`, `-ag`) and owners' personal pages are excluded, and a profile linked
   from several companies' sites in one batch (web-agency footers) is dropped. Since 1.3.0, when the verified page sits on
   someone else's site (a chain's dealer page, a group's or a manager's site: the page is a sub-page, or the site prints
   another organisation number, or its domain carries none of the company's current names, and the site does not print
   this company's organisation number), only the page itself is published, labelled `site_scope: shared_site`; the
   brand, description, profiles, careers page and posts on that site belong to the chain, the group or the manager.
5. **Jobs** – NAV's public job-vacancy feed (public token, republishing permitted by NAV's API terms). An ad is attributed
   only when `employer.orgnr` is the company or one of its registered workplaces. Contact persons are never stored.
   Ads are looked up by the names of the company and its workplaces, without store numbers ("NARVESEN BUTIKKEN 600"
   advertises as "Narvesen Harstad Sykehus"); the organisation number alone decides the match.
6. **Dated activity** – the verified site's RSS/Atom feed (up to 10 items, nothing dated in the future), its WordPress
   REST API (`/wp-json/wp/v2/posts`, robots.txt honoured) when a WordPress site advertises no feed, dated JSON-LD articles,
   and dated news teasers (the date must be in the teaser or the only date on the adjacent line). Posts dated before the
   company was founded, lorem-ipsum excerpts, WordPress's install-time sample post and the theme demo posts dated up to two
   months after it are skipped, and `utm_*` parameters are removed from post links; plus dated register
   events: role changes, and Enhetsregisteret's update log filtered to this organisation number (only entries that state
   which fields changed; the last 24 months).
7. **Filed-accounts documents** – Regnskapsregisteret's list of annual-account copies for this organisation number; each
   year becomes a claim with the official PDF URL. The endpoint publishes a small request budget, so calls are paced
   (≈4/s) and a refusal is reported as `blocked`, never as "no documents".
8. **English industry label** – Statistics Norway's classification API (KLASS), fetched once per run, gives the official
   English name of each SN/NACE code the register uses, so the profile says what the company does in plain English.

## Synthesis and refresh

The summary is generated from verified claims only (no language model, nothing to reproduce with private keys). Each
sentence lists the claim ids it rests on and the numbers of its sources, and `check_sentence` rejects any sentence
containing a number that is not a cited value or a declared computation (revenue change, operating margin, equity
ratio, counts). Ratios that would mislead (a margin beyond ±300 % on tiny revenue, an equity ratio when negative equity
exceeds total assets) are left out. The summary opens with an overview and then has five parts that answer the brief:

- **In brief** (`summary.overview`) – three to five sentences: what the company is (form, place, English industry label,
  founding year, registered employees), how the latest filed accounts look (revenue and its change, and whether it has
  moved the same way for two or more years running; operating profit or loss; equity), its verified online presence and
  hiring, the most notable recent change, and what was not found.
- **What it does** – legal form, place, founding year, the official English industry label next to the Norwegian one,
  the company's own description (or statutory purpose), registered employees and group parent.
- **Money** – latest filed figures with the year-on-year change, margin and equity ratio, revenue by filed year,
  negative equity and unaudited accounts, and how many official PDF copies exist.
- **People and presence** – leadership, workplaces, verified website and profiles, hiring, latest own-channel post.
- **What changed** – first, the diff against our previous run with its date ("Since our previous run on 2026-10-23,
  nothing material has changed", or the changes) or a plain statement that this is our first run; then the accounts year
  on year (revenue, the operating result turning from profit to loss or back, equity turning negative), the register's
  employee-count history, when the latest accounts were filed, other register changes in the last 12 months, the last
  role change and which entry it was, and former names.
- **Not found** – one sentence per missing family with its state (not found, blocked, ambiguous, could not be checked)
  and the reason, including how many candidate websites were checked and of which kind. A candidate that belongs to
  another company is never named.

`summary.sources` numbers every distinct source behind the summary (source name, URL, retrieval time), each sentence
carries `sources: [n, …]`, and `summary.markdown` renders the whole summary with `[n]` markers and the numbered list,
so the conclusions can be checked without the viewer. `summary.text` is the same summary as plain text with the part
labels ("In brief: … What changed: … Not found: …").

`signals` lists up to six short, cited flags a reader acts on (revenue up/down ≥25 %, employee count change, negative
equity, register flags, recent address/name/industry change, recent leadership change, young company, hiring now).

Refresh is a diff on stable claim keys (`field|qualifier`), so re-running the same snapshot yields no changes. Sections
that fail or are blocked keep the previous supported value (`carried_forward_from`) instead of producing false
removals. Every run's envelopes are preserved in `history/`.

## Sources, rights and safety

| Source | Use | Terms |
|---|---|---|
| data.brreg.no Enhetsregisteret + Regnskapsregisteret | identity, roles, workplaces, group, accounts, name-uniqueness check | NLOD 2.0 open data |
| data.brreg.no Enhetsregisteret update log (`oppdateringer/enheter?organisasjonsnummer=…`) | dated register history | NLOD 2.0 open data |
| data.brreg.no Regnskapsregisteret annual-account copies (`aarsregnskap/kopi/{org}/aar`) | list of filed years with the official PDF URL | NLOD 2.0 open data; paced to the published request budget |
| data.ssb.no KLASS (classification 6, SN2025 with SN2007 fallback) | official English industry labels | Statistics Norway open data (attribution: Statistics Norway) |
| pam-stilling-feed.nav.no (public token) | active job ads by employer organisation number | NAV API terms: anyone may use and republish ads |
| The company's own website (only after the identity gate) | website, description, brand, social links, careers page, posts (RSS/Atom feed, or the site's own WordPress REST API) | robots.txt honoured; honest User-Agent; ≤2 concurrent requests per host |
| Brave / Tavily (only if a key is supplied) | website candidates only, never evidence | provider terms; results kept in memory/cache only |

Not used: LinkedIn, Facebook, Instagram, Glassdoor, Indeed or Google scraping; Brreg's `w2.brreg.no/kunngjoring`
(disallowed by robots.txt); Norid WHOIS. Outbound requests allow only http/https on ports 80/443 to public IP addresses
(every redirect hop is re-checked), bodies are size-capped, and secrets are read only from environment variables.

## Measured locally

See [EVAL.md](EVAL.md). The committed 100-company smoke test lives in [`docs/smoke/`](docs/smoke/)
(`run-report.json`, `envelopes.jsonl`, viewer `site/index.html` with its profiles in `site/data/`), and the viewer is
published at https://antonmareo10.github.io/signalpost/smoke/site/.
