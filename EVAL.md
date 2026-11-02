# Evaluation (local, 21 Oct – 2 Nov 2026)

Builderr's official score pools verified findings from every entrant and its own crawlers, so it cannot be reproduced
locally. These are the measurements we can make, all with the committed code and **no API keys** unless stated.

## Version 1.6.1 (2 Nov): a sister's or parent's site lends only the page

**How it was found.** 1.6.0 was run on another 1,000 companies never used before (the public universe, seed 20261102,
sampled the starter kit's way after removing the 3,596 companies of the seed-1000, seed-20261031 and seed-20261101
batches and of the smoke, dev, validation and Builderr samples; 0 overlap with each), from a clean checkout of 675d461,
keyless and with the defaults: 1,000 / 1,000 envelopes, validation passed, 964 s, 8,550 requests, 95,128 / 95,128
excerpts re-found. It published 137 websites (6 as a page on someone else's site), 135 social profiles (73 companies),
14 careers pages (13), 4 NAV ads (3), 183 posts (26), 72 brands, 94 descriptions, 62 site e-mail addresses (60) and 204
identity proofs (105). All 138 companies with anything external were read by hand against the register (website field,
roles, group structure) and the stored pages. No website belonged to another organisation. 15 items did:

| Company | What 1.6.0 published | Whose it is |
|---|---|---|
| GAUTE ROSTRUP EIENDOM AS (984399804), property | from gaute-rostrup.no, which the register lists for it, for the frame shop and for a gallery: the description "Gaute Rostrup AS er en spesial forretning for innramming…", instagram `gauterostrup`, post@gaute-rostrup.no and 10 posts of shop offers | the frame shop GAUTE ROSTRUP AS (945070781), its sister at the same address |
| PANTAENIUS NUF (914332516) | info@pantaenius.com and info@monaco.pantaenius.com, from the site's "Avdelinger" page listing the group's offices | Pantaenius GmbH (Hamburg) and the Monaco office |

1.5.1 (9e0489d) run right after on the same batch published the same websites, profiles, careers pages, posts,
descriptions and e-mail addresses; the only difference in those families was the brand "Vibbo - En tjeneste fra OBOS"
of a housing co-operative, which 1.6.0 rightly drops. 1.6.0 cites 204 identity proofs (128 in 1.5.1) and gives no
revenue percentage from a negative year (6 in 1.5.1).

**The fixes.** (1) A registered website that does not print the company's organisation number, whose domain spells the
whole name of another organisation that lists the same website in the register and only part of the company's name, is
that organisation's site: only the page is attributed (`site_scope: shared_site`). If the register does not answer,
the page alone is published as well. About 26 register requests per 1,000 companies. (2) A site whose domain is named
after the company's registered parent or ultimate parent and not after the company is the group's site: only the page.
(3) No e-mail address is taken from a sub-page that links addresses on three or more domains (a group's list of offices,
a centre's tenants). (4) A site name with a part that names another legal entity ("Langset AS - Forside" for LANGSET
GROUP AS, whose sister LANGSET AS shares its address) is not published as the brand.

**What it costs.** 1.6.0 and 1.6.1 back to back, keyless, on the companies with a website or a blocked, failed or
ambiguous one: on the 2 Nov batch (181 companies, 313 s each, validation passed, 20,543 / 20,543 excerpts re-found) the
fixes remove the 15 items above and the Langset brand, and lose nothing correct (the other two differences were the
network: one site down, one answering HTTP 429 to the first run). On the 1 Nov batch (195 companies, 22,365 / 22,365
excerpts) they remove 4 items of the Boreal group that 1.6.0 hung on BOREAL BANE AS (brand "Boreal", the group's
description, careers page and one post; boreal.no stays as a page) and lose nothing correct. On the seed-1000 and
seed-20261031 batches, checked without a rerun, they change one company: BACKE ROGALAND AS on backe.no loses the Backe
group's Facebook and LinkedIn pages, two careers pages, brand, description and two e-mail addresses.

**Money.** In 30 random envelopes of the 2 Nov batch, all 1,418 accounts claims equal the live Regnskapsregisteret
value; recomputing the 3,432 derived figures found 0 errors. NAV: 4 / 4 ads carry the company's or one of its
workplaces' organisation number.

Smoke test (`samples/smoke-100.jsonl`, three passes with the release code, 2 Nov, committed in `docs/smoke/`): 100/100
envelopes, validation passed on every pass, 118–123 s per pass, third pass 0 changes and 0 carried-forward claims,
evidence audit 9,394 / 9,394 excerpts re-found, 100/100 summaries with an overview, 1,463 / 1,463 sentences that cite
claims carry their sources, 0 dropped; the same figures for every field family as 1.6.0. The scripted browser check
(24 steps, 1440 px and 390 px) passes on the committed smoke viewer and axe-core 4.14 reports 0 violations on all 10
views. 178 offline unit tests (165 in 1.6.0). The default time budget stays 40 minutes from process start.

## Version 1.6.0 (1 Nov): nothing from another organisation's site, profile or group under the company

**How it was found.** 1.5.1 was run on 1,000 companies never used before (the public universe, seed 20261101, sampled
the starter kit's way after removing the 2,596 companies of the seed-1000 and seed-20261031 batches and of the smoke,
dev, validation and Builderr samples), keyless and with the defaults: 1,000 / 1,000 envelopes, validation passed,
929 s, 8,875 requests. Every published item was read by hand: 131 websites (130 companies, one additional site), 133
social profiles (68 companies), 24 careers pages (21), 8 NAV ads (4) and 228 posts (32), with the register's website
field for every published domain (`hjemmeside` search), the organisation numbers printed on the stored pages and the
group structure. No website belonged to another organisation. 23 items published from correct websites did:

| Company | What 1.5.1 published | Whose it is |
|---|---|---|
| BLÅ KORS BARNEHAGE ØVREBØ AS (930574643) | from its registered page blakors.no/barnehage-ovrebo/, which prints its number: blakors.no's Facebook, Instagram, LinkedIn and YouTube, careers page and 10 news posts | Blå Kors Norge (962323855) |
| VARANGER KRAFT AS (985188092) | facebook and instagram `varangerkraftmarked`, facebook and youtube `varangerkraftfiber` | its subsidiaries VARANGER KRAFTMARKED AS and VARANGER KRAFTFIBER AS |
| BAUTA CONSTRUCTION AS (956595924) | linkedin and instagram `bautagroup` | BAUTA GROUP AS, its ultimate parent |
| BROKKE ALPINSENTER AS (916538227) | facebook.com/p/Brokke-VVS-as-61552198067839 | BROKKE VVS AS (932149664) |
| BENTERUDJORDET BORETTSLAG (948616858) | brand "Vibbo - En tjeneste fra OBOS" from vibbo.no/benterudjordet/om | OBOS's housing platform |

**The fixes.** (1) A page under a path of a domain that is not named after the company is published as that page only
(`site_scope: shared_site`), even when it prints the company's organisation number: the number shows the page is
about the company, not that the site's brand, profiles, careers page and posts are its own. (2) A profile handle that
spells the name of another organisation in the company's registered group (parent, ultimate parent or subsidiary, from
the register's group structure) is that organisation's, unless the name is part of the company's own. (3) Facebook's
`/p/<Name>-<id>/` pages are read without the numeric id, so a name ending in another company's legal form is caught
like any other foreign-entity handle.

**What it costs.** The same 1,000 companies with the three rules, keyless, on 1 Nov: 1,000 / 1,000, validation passed,
1,020 s, 8,873 requests, 96,282 / 96,282 excerpts re-found. Websites lost to the rules: 0. Removed: the 23 items above
(11 profiles, 1 careers page, 10 posts, 1 brand). Lost: 4 correct items, the kindergarten's brand and description, the
housing co-operative's description and the description of MILANO PIZZA GRILL AS's ordering page on
pckassenettbutikk.no. Everything else that differed between the two runs was the network (scandec.no answered 429).
On the seed-1000 and seed-20261031 batches the rules change two companies: REKOM DRIFT KRISTIANSAND AS on
sedetpianobar.no/kristiansand loses the SE DET! chain's two profiles and, with them, the venue's brand and description;
GFH.NO AS's page on gfh.no/geosport/ only changes scope.

**Money.** In 30 random envelopes with accounts, all 1,490 accounts claims equal the live Regnskapsregisteret value at
the cited JSON pointer and the stored copy (same year, account type and currency). Recomputing the 2,757 derived
figures in the 1,000 summaries found 8 that were revenue percentages measured from a negative year, in 4 companies
(HTEK AS: "up 16796.2%" from NOK -11 k to NOK 1.9 m, also the signal "Revenue grew 16796.2%"). 1.6.0 gives no
percentage and no revenue signal when either year is negative; "What changed" states the two amounts ("revenue went
from NOK -11 k to NOK 1.9 m"). In the 1,000 summaries of the run above, 0 of 2,049 revenue percentages involve a
negative year and 0 sentences were dropped.

**Three smaller fixes from the same reading**, measured by running 1.5.1 and 1.6.0 back to back on the 370 companies
with a published website in the three batches (1.5.1: 421 s, 4,916 requests; 1.6.0: 408 s, 4,901 requests; both
validation passed):
- The domain of the registered e-mail address, published from the register listing when its site refuses the crawler,
  now goes through the same `hjemmeside` check as every other inferred site (another organisation lists it: `related`,
  nothing published; no answer: not checked, earlier values kept). The three such listings in the three batches
  (sommerlyst.no, albertvoldinterior.no, tungror.no) are listed for no other organisation and stay published; the check
  costs two register requests per listing.
- Published website and careers URLs carry no session id: vertshusetfrisor.no/c;jsessionid=…timebok?0 changed on every
  run and is now vertshusetfrisor.no/c?0 (the fetch record keeps the URL as served).
- The identity proof is cited when the registered address is printed over two lines (it was never found as an excerpt)
  or the organisation number is the last line of the page (its excerpt ran into the page's meta tags). Sites with a
  verified website but no cited proof: 136 of 362 in 1.5.1, 60 in 1.6.0 (1 Nov batch 44 → 12, seed 1000 47 → 25,
  seed 20261031 45 → 23); 212 address proofs and 34 more organisation-number proofs are now cited. Of the remaining 60,
  59 were verified by the legal name, the domain or the register listing (stated in the website claim), and for one
  (STRATAGENTIC AS) the excerpt around its number does not pass the claim check, so the proof is left out rather than
  cited loosely.
- Differences between the two A/B runs other than these and the rules above: REGN AS (regnstore.no) was refused with
  HTTP 429 in the 1.5.1 run and verified in the 1.6.0 run.

Smoke test (`samples/smoke-100.jsonl`, three passes with the release code, 1 Nov, committed in `docs/smoke/`): 100/100
envelopes, validation passed on every pass, 120–122 s per pass, third pass 0 changes and 0 carried-forward claims,
evidence audit 9,394 / 9,394 excerpts re-found, 100/100 summaries with an overview, 1,463 / 1,463 sentences that cite
claims carry their sources, 0 dropped. Verified websites 9, as in 1.5.0. The scripted browser check (24 steps, 1440 px
and 390 px) passes on the committed smoke viewer and axe-core 4.14 reports 0 violations on all 10 views. 165 offline
unit tests (132 in 1.5.1). The default time budget stays 40 minutes from process start.

## Version 1.5.1 (1 Nov): a 40-minute default time budget

Builderr's official runs get 45 minutes. The default budget is now 40 minutes instead of 55, and it counts from process
start (reading the inputs, the optional bulk snapshot and the previous run are part of it), so the envelopes and the
viewer are written inside the official limit. Nothing else changes from 1.5.0.

Checks on 1 Nov, keyless: the smoke-100 batch with the defaults gives 100/100 envelopes and passes validation in 129 s.
Cut-off test: dev-300 with `--time-budget-minutes 1.5` ended after 109 s including the viewer, with 300/300 envelopes and
validation passed; what was not reached says so per section (256 annual-account lists, 106 website sections, and 6
companies not researched at all, status failed with that reason). 132 offline tests pass.

## Version 1.5.0 (31 Oct): ask the register whose website it is, before publishing a site we inferred

**How it was found.** 1.4.0 was run on 1,000 companies never used in development (the public universe, seed
20261031) and every website it published was read by hand, together with what the register says about each domain.
Five of the 127 sites belonged to another organisation although they had passed the identity gate:

| Company | Site 1.4.0 published | Whose it is, per the register | What 1.4.0 attached |
|---|---|---|---|
| SALTEK HOLDING AS (formerly SALTEK AS) | saltek.no (from the shared e-mail domain) | SALTEK AS, 913207521, which now carries the old name | site, brand, 10 posts |
| STEINKJER TOMTESELSKAP AS | steinkjerbygg.no (shared e-mail domain; its name appears on the site) | STEINKJERBYGG KF, a municipal enterprise | site, brand, LinkedIn, Facebook, careers page |
| SAMEIET TINDEN APARTMENTS | tindenapartments.com (name-derived domain) | BYGG DET AS, the construction company | site, brand, description |
| TRIDENT OPERATIONS AS | tridentaquaservices.com (a workplace's e-mail domain) | FSV GROUP AS, FSV SERVICES AS and INTERSHIP AS | site, brand, careers page |
| VIKØYRI AS (property rental) | blixhotell.no (shared e-mail domain; already labelled `shared_site`) | BLIX HOTELL AS | the page only |

Each puts another organisation's site under this company; the first two also carried that organisation's brand,
profiles and posts, which is what the brief calls a material wrong-company publication.

**The fix.** Enhetsregisteret's search accepts the website field (`/enheter?hjemmeside=<domain>`, and the same for
`/underenheter`). When a site was inferred rather than registered (e-mail domain, NAV ad, name-derived domain, search)
and does not print this company's organisation number, 1.5.0 asks the register which organisations list that domain
(the redirect target and the candidate) as their website. If another organisation does (not this company, not one of
its own workplaces), the site is marked `related` and nothing from it is published; the summary's gap says "a candidate
site is listed in the register as another organisation's website" without naming it. If the register does not
answer, the site is reported as not checked (and a refresh keeps the previous value) rather than published. Sites the
company registered itself and sites that print its number are not affected. Cost: two register requests per domain
checked, about 100 per 1,000 companies (45 and 41 checks in the two batches below).

Also from the same reading: a profile handle that spells a registered role holder's first and last name is that
person's page (instagram.com/denniskiil on KIIL MGMT AS's site), unless the company is named after the person; posts
titled "Test" or "TEst 2 – hubspot" are not activity; `<title>` elements of inline SVG icons no longer leak into the page
title (the brand "TravelmateFacebook iconInstagram icon" is now "Travelmate"); an AS also gets the `<name>as.no` and
`<name>.as` guesses; and a parent with no revenue of its own that heads an operating group counts as operating (MEASURE IT AS:
NOK 158 m group revenue, no guesses in 1.4.0).

**Summary wording**, from linting the 2,000 summaries of the two batches below: "up 0.0%" (23 summaries) now reads
"almost unchanged" (and "unchanged" only when the two filed values are identical), "turned from a profit of NOK 0"
(8) and "went from NOK 0" (4) now say break-even, "revenue of NOK 0" (250) reads "no revenue (NOK 0)", "N.V.." has
one full stop, and an ambiguous website says why: of the 50 ambiguous websites in the two 1.5.0 runs, 10 are the
register check, 26 print another organisation number and 14 are group or manager sites sharing contact details, which
1.4.0 also described as "prints another organisation number". Re-running the summaries of both batches with 1.5.0:
none of those patterns left (three remaining hits are a space before a full stop inside verbatim register quotes),
0 sentences dropped, and the independent re-check of every overview against the envelope's claims finds no problem in
1,000 / 1,000.

**Refresh.** Two sources of false changes turned up on 31 Oct and are closed. The third smoke pass of an early 1.5.0
build showed 27 low-materiality "new" register events: Brønnøysund's update log answers "2025-09-01T22:05:37.005Z" on one
call and "2025-09-02T00:05:37.005+02:00" on the next for the same update (fetched four times in a row: one +02:00, three
Z), and the event date was the first ten characters. It is now the UTC date of the timestamp, which is also the date the
register's own fields give for the change; the evidence check accepts a date when the cited excerpt has a timestamp on
that UTC date. Second, Shopify storefronts answer this crawler "429, Retry-After: 60" for minutes (16 shops, one request
every 5 s after a 65 s pause: 5 of 30 answered), so a site could be verified in one run and gone in the next
(SUPERMERCADO AS: refused in passes 1 and 2, verified in pass 3). A 429 now makes the website section `blocked` for that
run, so the previous run's site is carried forward instead of reported as removed; a 429 with a `Retry-After` of 10 s
or less (or none) is retried twice, a longer one is not retried early.

**Fresh batch (seed 20261031), 1.4.0 and the 1.5.0 release candidate on 31 Oct, keyless, 24 workers.** Both runs:
1,000 / 1,000 envelopes, validation passed, the whole NAV feed (189 pages); 912 s and 1,005 s, 8,793 and 8,880 requests
(a `hjemmeside` search answers in about 0.5 s).

| Family | 1.4.0: companies / facts | 1.5.0: companies / facts | Why |
|---|---|---|---|
| Verified website | 127 / 127 | 122 / 122 | −5 register check (table above); Shopify 429 in one run or the other: −1 dekamund.com (refused in the 1.5.0 run), +1 smart4u.no (refused in the 1.4.0 run) |
| Company-owned social profiles | 67 / 133 | 66 / 132 | −2 Steinkjerbygg's, −1 personal Instagram, +2 smart4u |
| Careers page or job ads | 31 / 33 | 29 / 31 | −2 careers pages of Steinkjerbygg and the FSV group |
| Dated own-channel posts | 28 / 190 | 27 / 179 | −10 Saltek AS's, −1 "TEst 2 – hubspot" |
| Brand / description | 75 / 91 | 69 / 88 | the sites above |

Website states in the 1.5.0 run: 122 available, 824 not available, 24 ambiguous (5 of them the register check), 17
failed (registered site unreachable), 13 blocked (7 of them only because a candidate answered 429; 1.4.0 reported those
as not available). An intermediate 1.5.0 build run between the two took 1,258 s with every request slower (p50 1.25 s →
1.55 s): the network at that hour, not the code.

**Seed-1000 batch (the development batch of 1.2.0–1.4.0), 1.5.0 on 31 Oct against 1.4.0 on 24 Oct.** 1,000 / 1,000,
validation passed, 1,100 s, 8,645 requests, whole NAV feed (this run predates the NUF exception, the register-date fix
and the 429 change).

| Family | 1.4.0 (24 Oct) | 1.5.0 (31 Oct) |
|---|---|---|
| Verified website | 119 / 119 | 118 / 118 |
| Company-owned social profiles | 73 / 141 | 69 / 133 |
| Careers page or job ads | 21 / 25 | 20 / 24 |
| Dated own-channel posts | 29 / 211 | 27 / 205 |

Every difference, by cause. Register check (−5 sites): MANSOFT, TONEMAKERIET AS (tonemakeriet.no is registered to
the owner's sole proprietorship, still active), HOPPENSPRETT AKADEMIET AS (hoppensprett.no is registered to
HOPPENSPRETT AKADEMIET BRÅRUD AS), and two pages already labelled `shared_site` (drommekjokkenet.no, systemhus.no); with
them go 7 profiles, 9 posts and 2 careers pages. MANSOFT is a NUF, the Norwegian registration of MANSOFT A/S, which
the register lists separately (form UTLA) with mansoft.dk: one legal person, so the final 1.5.0 commit keeps that site
(a NUF whose foreign company has the same name owns its site; an AS sharing the domain does not). Re-run on its own
with the final commit: MANSOFT verified again; SALTEK HOLDING AS, STEINKJER TOMTESELSKAP AS, SAMEIET TINDEN APARTMENTS,
TRIDENT OPERATIONS AS, TONEMAKERIET AS and HOPPENSPRETT AKADEMIET AS ambiguous; MARINOR AS verified. New guesses (+3 sites):
marinoras.no (organisation number on the site) and proconsult.as (the full legal name), with 1 profile, 14 posts and a
careers page; measureit.no (group revenue now counts). The sites themselves changed during the week (−2 sites, −2
profiles, −12 posts): familierettadvokaten.no and brandiva.no now show a placeholder, and www.nordasa.no's certificate
no longer matches its name, so its feed could not be read (two other feeds rotated their latest items, +1 post). Network on 24 Oct (+3): ds-betong.no answered 403 then,
bikefixx.no 429 and aabergeplanteskule.no timed out.

Smoke test (`samples/smoke-100.jsonl`, three passes with the release commit, 31 Oct, committed in `docs/smoke/`):
100/100 envelopes, validation passed on every pass, 139–146 s per pass, third pass 0 changes and 0 carried-forward
claims, evidence audit 9,388 / 9,388 excerpts re-found, 100/100 summaries with an overview, 1,463 / 1,463 sentences
that cite claims carry their sources, 0 dropped. Verified websites 9, as in 1.4.0. The scripted browser check (24
steps, 1440 px and 390 px) passes on the committed smoke viewer and on the 1,000-company viewer of the release
candidate, and axe-core 4.14 reports 0 violations on all 10 views. 130 offline unit tests (93 in 1.4.0).

## Version 1.4.0 (24 Oct): an overview with numbered sources, and a viewer that opens a 1,000-company batch at once

This version changes how the profile is explained and shown, not what is collected (apart from the NAV feed limit
below).

**Synthesis.** Every summary now opens with "In brief" (`summary.overview`): what the company is, how its latest
filed accounts look (revenue, its change and whether it moved the same way two years running, operating profit or
loss, equity), its verified website, profiles and hiring, the most notable recent change and what was not found. Every
sentence carries `sources: [n]`, `summary.sources` numbers each distinct source with URL and retrieval time, and
`summary.markdown` renders the summary with `[n]` markers. "What changed" opens with the comparison against our previous
run and its date (or says it is the first run), then the accounts year on year. "Not found" has one sentence per gap
with its state and reason and the number and kind of candidate websites checked; a candidate that belongs to another
company is never named. Ratios that would mislead are left out (a margin beyond ±300 %, an equity ratio when negative
equity exceeds total assets: 1.3.0 printed "-28762200.0%" for one company), "Uoppgitt" (00.000) is not presented as an
industry, unchanged revenue reads "unchanged", and amounts that round alike get one more decimal.

Checked on 1,000 summaries from the 1,000-company run below and on the smoke test: every sentence that cites claims names its sources (14,858 / 14,858 on the
1,000; 1,461 / 1,461 on the smoke test), none was dropped as unsupported, and an independent re-check of each overview
against the envelope's own claims (revenue and its change, direction and streak, operating profit or loss, equity sign,
net result fallback, website host, profile platforms, job count, the gaps against the section states, no URL in a gap
sentence) found no problem in 1,000 / 1,000. About 25 summaries were also read in full; that reading is what found the
ratio, "Uoppgitt", flat-revenue and accountant-change wording fixed above.

**Viewer.** 1.3.0 embedded every profile in one page: 49.8 MB for the 1,000-company batch. 1.4.0 keeps a compact
index in the page and writes each profile to `site/data/<org>.js`, loaded when it is opened (it still works from disk).
Time until the list shows, headless Chromium from disk, both viewers measured back to back with nothing else running:

| 1,000 companies | 1.3.0 | 1.4.0 |
|---|---|---|
| `index.html` | 49.8 MB | 1.09 MB (index plus a plain-HTML list of every overview for readers without JavaScript) |
| List ready, laptop (1440 px) | 1.9 s | 0.2 s |
| List ready, phone emulation (390 px, 4× slower CPU) | 21.1 s | 1.2 s |
| JavaScript heap | 81 MB | 10 MB |
| A profile | in the page | about 37 KB, loaded on demand |

(With a crawl running on the same machine the phone figures were 12.9 s and 2.5–2.9 s.)

Also new: best-match search, counts on the filters, "Compare with…" and similar-company suggestions, comparison links
(`#/compare/<org>,<org>`) that open on another device, numbered source buttons that match the profile's source list and
show source and retrieval date on hover, a legend for every state, and a "Show more" list instead of a cut-off. A
scripted browser check (24 steps, desktop 1440 px and phone 390 px: find by number with spaces and by name, Ctrl+K,
open a source, Escape returns focus, the numbered sources, the legend, tick two companies and compare, open a value's
source in the comparison, a shared comparison link on a fresh visit, an unknown number) passes on the 1,000-company
viewer, the committed smoke viewer and a 7-company single-file viewer. axe-core 4.14 (WCAG 2.2 AA and best practice)
reports 0 violations on the list, a profile, the evidence panel, a comparison and the dark theme, at both widths.
Fixed on the way: a search typed or pasted and submitted within 120 ms was sent back to the list by the debounce.

**NAV.** The job feed pages from the oldest change (100 days back) to the newest, so the 200 s limit cut the newest
ads when NAV was slow (the 1.3.0 smoke artifact stopped at 160 of 183 pages). The limit is now up to 480 s and follows
the run's time budget; on every run below the whole feed loaded (183 pages).

Same 1,000 random companies (seed 1000), 1.3.0 and 1.4.0 run back to back on 24 Oct, keyless, 24 workers:

| Family | 1.3.0: companies / facts | 1.4.0: companies / facts |
|---|---|---|
| Verified website | 120 / 122 | 119 / 121 |
| Company-owned social profiles | 73 / 141 | 73 / 141 |
| Careers page or job ads | 21 / 25 | 21 / 25 |
| Dated own-channel posts | 29 / 211 | 29 / 211 |
| Accounts, roles, workplaces, register events | 823, 999, 765, 997 companies | the same |
| Official PDF copies of filed accounts | 953 / 8,409 | 1,000 / 8,846 |
| Wall clock / requests | 903 s / 8,388 | 865 s / 8,434 |

Both runs passed contract validation and loaded the whole NAV feed (183 pages). No fact was gained; the two
differences are the network on the day, not the code: aabergeplanteskule.no timed out in the 1.4.0 run (verified by its
organisation number in 1.3.0), and in the 1.3.0 run the paced annual-accounts copies endpoint refused 47 companies,
which those envelopes report as an error rather than as "no documents". 1,000 / 1,000 summaries have an overview (3.6 sentences on average,
6.9 numbered sources per summary, 0 sentences dropped); 377 overviews name a recent change and 878 "What changed" parts
compare the accounts year on year.

Smoke test (`samples/smoke-100.jsonl`, three passes, 24 Oct, committed in `docs/smoke/`): 100/100 envelopes,
validation passed on every pass, 111–114 s per pass, third pass 0 changes and 0 carried-forward claims, evidence audit
9,390 / 9,390 excerpts re-found, 100/100 summaries with an overview (3.5 sentences on average), 1,461 / 1,461 sentences
that cite claims carry their sources, 0 sentences dropped as unsupported, 6.9 numbered sources per summary. Verified
websites 9 as in 1.3.0. 93 offline unit tests.

## Version 1.3.0 (23 Oct): dated posts are published, and chain or group sites stop lending their content

Same 1,000 random companies (seed 1000), 1.2.0 and 1.3.0 run back to back on 23 Oct, keyless, 24 workers:

| Family | 1.2.0: companies / facts | 1.3.0: companies / facts |
|---|---|---|
| Dated own-channel posts | 7 / 32 | **29 / 211** |
| Verified website | 116 / 118 | **120 / 122** |
| Company-owned social profiles | 77 / 154 | 73 / 141 (13 chain, group or manager profiles removed, none added) |
| Careers page or job ads | 23 / 25 | 21 / 25 (2 more NAV ads; 2 careers pages of a chain and of a group removed) |
| Website section `blocked` | 27 | 8 (the others were domains that no longer resolve, now `not_available`) |
| Requests | 8,392 | 8,438 |

Both runs passed contract validation. Evidence audit on the 1.3.0 run: 95,630 / 95,630 excerpts re-found in their stored
snapshots (plus 8 NAV ads, verified against their stored projection by design). Wall clock depends on the register's
response times that day (926 s for 1.2.0 at 15:00, 2,025 s for 1.3.0 at 16:15 with the same request count).

What changed, and what each change did on this batch:
- **RSS and Atom posts.** Every feed item was dropped before: ElementTree treats an element without children, such as
  `<pubDate>`, as false, so `pubDate or published or ...` skipped the date. Atom entries now use the `rel="alternate"`
  link; up to 10 items, nothing dated in the future, `utm_*` parameters removed from links.
- **WordPress REST API.** A WordPress site that advertises no feed is asked for `/wp-json/wp/v2/posts` (robots.txt
  honoured); each post cites a JSON pointer into the stored response.
- **What is not activity.** Posts dated before the company was founded (rigelmap.no showed 2013 posts for a company
  founded in 2025; bcaccounting.no showed posts from before its founding), lorem-ipsum excerpts, WordPress's sample post
  ("Hello world!", "Hei, verden!": 7 in this batch) and the theme demo posts dated up to two months after it
  (public-domain stories on ny.holokleros.no).
- **Shared sites.** When the verified page sits on someone else's site, only the page is published, labelled
  `site_scope: shared_site`; the brand, description, profiles, careers page and posts there belong to the chain, the
  group or the manager. A page is shared when it is a sub-page (systemhus.no/forhandlere/..., laringsverkstedet.no/barnehage/...,
  drommekjokkenet.no/alnabru/), when the site prints another organisation number, or when its domain carries none of
  the company's current names (mmanagement.no for MARITIM RESEARCH I AS, sushibrodrene.no for POWER BOOTCAMP AS), and
  in every case only when the site does not print the company's own organisation number. Former names do not count:
  HEGGSTADMOEN EIENDOM AS was TRV GRUPPEN AS and still lists trvgruppen.no, so 1.2.0 gave it TRV's news feed, social
  profiles and careers page. A profile on a shared page is kept only when its handle carries two of the company's own name
  words, one of them not the site's (facebook.com/ostenfjeldskebygg on the Systemhus dealer page,
  instagram.com/froyland.gardsbarnehage on the Læringsverkstedet page).
- **Registered websites that refuse bots.** highsoft.com, sunnokonomi.no, hovelmesteren.no and geoprovider.no are listed
  by the companies themselves in the register, are named after them, and answer robots.txt or HTTP 403 to an automated
  client. They are now published from the register listing (`basis: registry_listing`), with nothing read from them.
- **NAV.** Store numbers no longer stop an ad from being looked up: "NARVESEN BUTIKKEN 600" advertises as "Narvesen
  Harstad Sykehus" (2 ads). Resolving every one of the 9,955 active ads to its employer number on this batch found the
  same 4 companies and 8 ads, so the name-based lookup now misses none here.
- **States and evidence.** A domain that does not resolve with or without `www` is reported as gone (`not_available`),
  not `blocked`. A UTF-8 page with one stray byte (WordPress cuts excerpts in the middle of an "å") no longer becomes
  cp1252 mojibake. The organisation-number proof keeps the number as printed ("971 456 329"), so its claim is no longer
  dropped by the evidence check.
- **Refresh.** A copies list that could not be read keeps the previous run's documents, and a register name search that
  does not answer makes the website section `failed` (previous value kept) instead of rejecting the site. Both showed
  up as false "new" changes on a smoke-test pass while the register was slow.

Hand review of 50 new facts on the 1.3.0 run (all 4 new websites, both new job ads, and 44 new posts, at most 2 per
company, from 23 companies): 50 belong to the company and carry the date the source gives. Every post is on the
company's verified domain and its title is on the linked page; for 9 posts the page itself prints no date, and the date
comes from the feed or the WordPress API that is cited. An earlier review of the first 1.3.0 run is what found the
problems fixed above (TRV's news, posts older than the company, theme demo posts).

Smoke test (`samples/smoke-100.jsonl`, three passes, 23 Oct, committed in `docs/smoke/`): 100/100 envelopes, validation
passed on every pass, third pass 0 changes and 0 carried-forward claims, evidence audit 9,390 / 9,390 excerpts re-found.
4 companies now have 35 dated posts (none in 1.2.0). Verified websites 9 (10 with 1.2.0): supermercado.no answered
HTTP 429 to all three passes after a day of test runs, and a refusal is never published. 80 offline unit tests.

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
16 minutes, inside the 55-minute default budget of that release (40 minutes since 1.5.1). Other families on that batch: register history 997, English industry
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
