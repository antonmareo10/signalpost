# Evaluation (local, 21 Oct 2026)

Builderr's official score pools verified findings from every entrant and its own crawlers, so it cannot be reproduced
locally. These are the measurements we can make, all with the committed code and **no API keys** unless stated.

## Contract and evidence

| Check | Result |
|---|---|
| 100-company smoke test (`samples/smoke-100.jsonl`, the starter kit's seed 20260823) | 100/100 envelopes, input order kept, all states terminal, every claim has evidence with URL + time + SHA-256 — see `docs/smoke/run-report.json` |
| Refresh idempotency (same batch run twice) | 0 changes, 0 carried-forward claims on the second run (`docs/smoke/` is the second run) |
| Independent evidence audit (`eval/audit_evidence.py`) on the Builderr-sample run | 10,509 / 10,509 stored excerpts re-found in their snapshots (100%); 4 NAV ads verified against the stored projection (raw ads with contact persons are deliberately not kept) |
| Synthesis gate | sentences whose numbers are not cited values or declared computations are dropped (0 dropped in the smoke run) |
| Unit tests | 24 offline tests: `python -m unittest discover -s tests` (Python 3.11 and 3.14) |
| Runtime (24 workers) | 100 companies ≈ 75 s; 300 ≈ 3.6 min; **1,000 ≈ 9.6 min** (5,859 requests, p95 per company 16 s, US$0) |
| Scale test, 1,000 random companies (seed 1000, fresh cache) | 1,000/1,000 envelopes, validation passed, 1 company with a source error (Regnskapsregisteret HTTP 500, reported as `failed` for that section); evidence audit 81,782 / 81,782 excerpts re-found (100%) |

## Coverage on random companies (keyless)

| Batch | Verified website | Social profiles | Job ads / careers page | Dated posts | Accounts | Roles | Workplaces |
|---|---|---|---|---|---|---|---|
| smoke-100 (seed 20260823) | 8 | 3 cos / 5 | 1 | 0 | 100 | 100 | 74 |
| validation-100 (seed 77) | 14 | 10 cos / 19 | 4 | 0 | 100 | 100 | 80 |
| dev-300 (seed 2026) | 44 | 25 cos / 46 | 7 | 1 | 299 | 300 | 228 |
| scale-1000 (seed 1000) | 105 | 70 cos / 142 | 27 cos / 38 | 7 cos / 32 | 998 | 999 | 765 |

Most companies in the 2025-filer universe are holding, property and dormant companies: only 10.9% have a website in the
register and 85% report no employees, so external families are sparse by nature; the agent reports them as
`not_available` with a reason rather than guessing.

## Recall against Builderr's own crawl

`eval/builderr_reference.py` extracts the 100 profiles embedded in https://builderr.ai/signalpost (Builderr's reference
crawler, August 2026, website-rich companies); `eval/score.py` computes the challenge's family formula
(70% company recall + 30% claim recall).

| Family | Keyless | With search (Tavily) |
|---|---|---|
| Verified website (97 companies in reference) | 78.4% | 81.4% |
| Company-owned social profiles (43 companies) | 78.7% | 78.7% |
| Proxy recall points over 4 families, pooled with our extra finds | 45.3 / 50 | 45.9 / 50 |

Most remaining website misses are deliberate: the reference accepts parent/franchise/group sites (storebrand.no for
Storebrand Bank, kitchn.no for a franchise, vestbo.no for managed housing) and sites that refuse automated access; this
agent labels those `related`/`blocked` instead of publishing them as the company's own website.

## Precision review

Every external claim (website, brand, profile, job, careers page, post) in smoke-100 and validation-100 was reviewed by
hand, plus the dev-300 website list. Issues found during development and fixed in code (each now has a regression test):
directory pages (e.g. omsorgsguiden.no) accepted from search results, group/manager websites sharing only contact
details, parent-group social handles (`lindbak-gruppen-as`, `wyssen-avalanche-control-ag`), owners' personal profiles,
person names or other legal names used as "brand", SEO plugins' pseudo-articles as dated news, and the `twitter.com`
→ `x.com` canonicalisation that failed the evidence check. Known grey zone kept: a subsidiary's verified Norwegian page on
its group's domain (e.g. wyssenavalanche.com/nb for Wyssen Norge AS, where the site prints the exact legal name).
