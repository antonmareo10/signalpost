# Evaluation (local, 21–22 Oct 2026)

Builderr's official score pools verified findings from every entrant and its own crawlers, so it cannot be reproduced
locally. These are the measurements we can make, all with the committed code and **no API keys** unless stated.

## Version 1.2.0 (22 Oct): more websites, and three wrong-site cases closed

Same 1,000 random companies as the scale test below (seed 1000), 1.1.0 and 1.2.0 run back to back on 22 Oct, keyless,
24 workers:

| Family | 1.1.0: companies / facts | 1.2.0: companies / facts |
|---|---|---|
| Verified website | 104 / 106 | **117 / 119** |
| Company-owned social profiles | 69 / 139 | **77 / 153** |
| Careers page or job ads | 21 / 23 | **23 / 25** |
| Dated own-channel posts | 7 / 32 | 7 / 32 |
| Wall clock | 1,940 s (this run; 775 s an hour earlier) | 964 s (877 s an hour earlier) |

Validation passed on both. 15 websites gained and 2 removed, all reviewed by hand:
- **Gained (15):** all 15 are small active companies that were never guessed before (no registered employees, NOK
  100k–1M revenue). Proof on the site: the organisation number for 11, the legal name with the registered address or
  phone for 3, the exact legal name for 1 (Spellplassen AS, whose site prints its organisation number with two digits
  swapped). The `www`/apex retry reached three more sites in this batch (bartho.no, volvomaskinservice.no,
  kriss-consulting.com); none of them proves it belongs to the company, so none is published.
- **Removed (2), now `not_available`:** legentic.com for LEGENTIC SERVICES AS (the domain only matches "Legentic", which
  five other registered companies share: a group site) and lekeplassmontorene.no (the web host's default page, "This
  domain is hosted by NordkappNett AS").
- **Never published:** kriss-consulting.com for KRISS CONSULTING AS. 1.1.0 could not reach it; reaching it via `www`
  showed "Kriss Consulting Inc", an IT company, while the Norwegian company is a carpentry consultancy in Kristiansand.
  Its page carried `lang="no"` only because Google Sites follows the visitor's Accept-Language. 1.2.0 rejects a site
  that names the company with a foreign legal form its own name lacks, and counts `lang="no"` as Norwegian context only
  when the visible text is Norwegian.

The other five websites verified by the name-search route in this batch (kokooo.no, rigelmap.no, tjuvgods.no,
bjornsen-advokatfirma.no, supermercado.no in smoke-100) were re-checked by hand under the new rules and stay verified.

Smoke test (`samples/smoke-100.jsonl`, three passes, 22 Oct): 100/100 envelopes, validation passed on every pass,
verified websites 8 → 10 (brandmaker.no prints the registered Bergen address and phone; novooi.com prints the
organisation number), third pass 0 changes and 0 carried-forward claims, evidence audit 9,353 / 9,353 excerpts
re-found. 53 offline unit tests.

Measured and **not** added (details in the submission notes): Wikidata (no new own websites in 500 companies); Norid
whois/RDAP (whois gives no holder and restricts use; anonymous RDAP gives no holder and allows 300 lookups a day);
a registered officer's name on a name-matching site as proof (1 extra website in 1,000, and 2 of 3 matches were the
officer's other company).

## Version 1.1.0 (22 Oct): what changed, measured on the same 100 companies the same day

Both versions were run on `samples/smoke-100.jsonl` on 22 Oct 2026, keyless.

| Family | v1.0.0: companies / facts | v1.1.0: companies / facts |
|---|---|---|
| Verified website | 8 / 8 | 8 / 8 |
| Company-owned social profiles | 3 / 5 | 3 / 5 |
| Job ads or careers page | 1 / 1 | 1 / 1 |
| Accounts figures (revenue, net result, equity) | 100 / 753 | 100 / 753 |
| Roles / workplaces | 100 / 383 · 74 / 77 | 100 / 383 · 74 / 77 |
| **Official PDF copy of each filed year (new)** | 0 / 0 | **100 / 909** |
| **Dated register history events (new)** | 0 / 0 | **100 / 187** |
| **Register employee-count history (new)** | 0 / 0 | **9 / 39** |
| **Official English industry label (new)** | 0 / 0 | **91 / 91** (the other 9 are registered as "00.000 unspecified") |
| Summary sentences per company (mean) | 8.1 | 13.2, in five labelled parts; 0 dropped by the number check |
| Companies with a dated "what changed" statement beyond the role-change date | 0 | 100 |
| Companies with at least one cited signal | 0 | 73 |

Evidence audit (`eval/audit_evidence.py`) on the v1.1.0 smoke run: 9,344 / 9,344 excerpts re-found in their stored
snapshots. A second run on the same day: 0 changes, 0 carried-forward claims (idempotent refresh holds for the new
families too). Unit tests: 35 offline tests.

Scale, same 1,000 random companies as below (seed 1000), 22 Oct, keyless, 24 workers:

| Run | Wall clock | Validation | Copies lists | p50 / p95 per company | Notes |
|---|---|---|---|---|---|
| v1.1.0 draft, copies called at ≈4/s inside the website phase | 802 s | passed | 900 / 1,000 | 11.2 s / 36.8 s | 98 refusals (HTTP 429), reported as `blocked` |
| v1.1.0, one paced copies thread, waiting for every list | 1,012 s | passed | 1,000 / 1,000 | 5.7 s / 15.0 s | 0 refusals left; 1 Regnskapsregisteret HTTP 500 (accounts) |

The copies endpoint sustains less than one request per second (260 calls alone at 2/s still drew 10 refusals), so
the released default waits at most 300 s for it after the other phases (`SIGNALPOST_COPIES_WAIT_SECONDS`); a company not
reached in time carries an explicit error and no "no documents" claim. Expected wall clock for 1,000 companies: about
16 minutes, inside the 55-minute default budget. Other families on that batch: register history 997, English industry
label 888 (the rest are registered as "00.000 unspecified"), employee-count history 142, verified websites 102–104
(the same-day difference is a closed connection and a robots.txt refusal, both reported, not guessed).

Website discovery: "A/S" and "A.S.A." are now stripped as legal forms, and names with a connector word are also tried
with it ("Nesset og Eidem" → nessetogeidem.no). On the 27 such companies of the 1,000-company batch this found one more
verified website (organisation number printed on the site) and changed no rejection. A Wikidata lookup by
organisation number (property P2333) was measured and not added: 8 of 500 sample companies have an item, and the
agent already finds 5 of the 7 websites listed there; the other two are a group site and a municipality page.

## Contract and evidence

| Check | Result |
|---|---|
| 100-company smoke test (`samples/smoke-100.jsonl`, the starter kit's seed 20260823) | 100/100 envelopes, input order kept, all states terminal, every claim has evidence with URL + time + SHA-256 — see `docs/smoke/run-report.json` |
| Refresh idempotency (same batch run twice) | 0 changes, 0 carried-forward claims on the second run (`docs/smoke/` is the second run) |
| Independent evidence audit (`eval/audit_evidence.py`) | smoke-100: 8,018 / 8,018 excerpts re-found in their stored snapshots; Builderr sample: 10,509 / 10,509; NAV ads are verified against a stored projection (raw ads with contact persons are deliberately not kept) |
| Synthesis gate | sentences whose numbers are not cited values or declared computations are dropped (0 dropped in the smoke run) |
| Unit tests | 24 offline tests: `python -m unittest discover -s tests` (Python 3.11 and 3.14) |
| Runtime (24 workers) | v1.0.0: 100 companies ≈ 75 s; 300 ≈ 3.6 min; 1,000 ≈ 9.6 min (5,859 requests, p95 per company 16 s, US$0). v1.1.0: 100 ≈ 76–112 s; 1,000 ≈ 13–17 min (paced annual-account copies, see the top of this file) |
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
