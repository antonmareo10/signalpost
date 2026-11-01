"""Offline tests for 1.6.0: cases from reading every website, profile, careers page and post that 1.5.1 published
for 1,000 new companies (seed 20261101).

- A page under a path of someone else's domain stays that page only, even when it prints the company's organisation
  number (BLÅ KORS BARNEHAGE ØVREBØ AS on blakors.no, a housing co-operative on OBOS's vibbo.no).
- A profile handle that spells another organisation in the registered group is that organisation's (VARANGER KRAFT AS
  and its subsidiaries' pages, BAUTA CONSTRUCTION AS and BAUTA GROUP AS's).
- Facebook's "/p/<Name>-<id>/" pages are read without the id (Brokke-VVS-as-61552198067839 is BROKKE VVS AS).
- No revenue percentage from a negative filed year ("up 16796.2%" from NOK -11 k to NOK 1.9 m).
- The domain of the registered e-mail address that refuses the crawler goes through the register's website check too.
- Published URLs carry no session id (vertshusetfrisor.no/c;jsessionid=...), so a refresh sees no false change.
- An identity proof is cited when the address is printed over two lines, or the number sits at the end of the page.
Run: python -m unittest discover -s tests"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from signalpost.agent import Agent, Work  # noqa: E402
from signalpost.ledger import Document, Ledger  # noqa: E402
from signalpost.registry import group_claims  # noqa: E402
from signalpost.synth import _pct_change, check_sentence  # noqa: E402
from signalpost.web import (Candidate, Company, SiteResearcher, SiteResult, extract_site, foreign_entity_handle,  # noqa: E402
                            shared_site)
from test_v2 import fetched  # noqa: E402
from test_v4 import FakeFetcher, result, site  # noqa: E402
from test_v5 import OverviewTests, year  # noqa: E402


def research(company: Company, url: str, html: str, source: str = "registry_website", strength: str = "strong",
             extra: dict | None = None):
    fetcher = FakeFetcher({url: lambda u: result(u, html.encode("utf-8"), "text/html; charset=UTF-8"), **(extra or {})})
    return SiteResearcher(fetcher).research(company, Candidate(url, source, strength))


BLAKORS_PAGE = (
    "<html><head><title>Barnehage Øvrebø - Blå Kors barnehage Øvrebø</title>"
    "<meta property='og:site_name' content='Barnehage Øvrebø'>"
    "<meta name='description' content='Øvrebø barnehage ligger idyllisk til på Lolandskollen, omgitt av flott natur.'></head>"
    "<body><h1>Barnehage Øvrebø</h1><p>Blå Kors Barnehage Øvrebø AS, org.nr. 930 574 643, Lolandsveien 2, 4700 Vennesla.</p>"
    "<a href='https://www.blakors.no/karriere/'>Ledige stillinger</a>"
    "<footer>Blå Kors Norge · Telefon 22 03 27 40 · Org.nr 962 323 855"
    "<a href='https://www.facebook.com/blakorsnorge'>Facebook</a><a href='https://www.instagram.com/blakors/'>Instagram</a>"
    "<a href='https://www.linkedin.com/company/bl-kors-norge/'>LinkedIn</a></footer></body></html>")


class PageOnSomeoneElsesSiteTests(unittest.TestCase):
    def test_a_registered_sub_page_of_a_parent_organisation_publishes_only_the_page(self):
        # The register lists www.blakors.no/barnehage-ovrebo/ for the kindergarten and the page prints its number, so the page
        # is verified; but the profiles, careers page and news of blakors.no are Blå Kors Norge's (962 323 855).
        company = Company(org="930574643", name="BLÅ KORS BARNEHAGE ØVREBØ AS", legal_form="AS")
        found = research(company, "https://www.blakors.no/barnehage-ovrebo/", BLAKORS_PAGE)
        self.assertEqual(found.state, "verified")
        self.assertTrue(found.proof["orgnr"])
        self.assertEqual(found.proof["other_orgnrs"], ["962323855"])
        self.assertTrue(shared_site(company, found))
        ledger = Ledger(company.org)
        info = extract_site(ledger, company, found)
        self.assertTrue(info["shared"])
        website = ledger.first("official_website")
        self.assertEqual(website["value"], "https://www.blakors.no/barnehage-ovrebo/")
        self.assertEqual(website["site_scope"], "shared_site")
        self.assertEqual(ledger.first("website_identity_proof")["value"], "930 574 643")
        for field_name in ("social_profile", "careers_page", "public_brand", "website_description"):
            self.assertIsNone(ledger.first(field_name), field_name)

    def test_a_platform_page_does_not_lend_the_platform_name_as_brand(self):
        html = ("<html><head><title>BENTERUDJORDET BORETTSLAG | En tjeneste fra OBOS</title>"
                "<meta property='og:site_name' content='Vibbo - En tjeneste fra OBOS'></head>"
                "<body><h1>Benterudjordet borettslag</h1><footer>Organisasjonsnummer:948616858</footer></body></html>")
        company = Company(org="948616858", name="BENTERUDJORDET BORETTSLAG", legal_form="BRL")
        found = research(company, "https://vibbo.no/benterudjordet/om", html, "domain_guess_from_legal_name", "weak")
        self.assertEqual(found.state, "verified")
        ledger = Ledger(company.org)
        extract_site(ledger, company, found)
        self.assertEqual(ledger.first("official_website")["site_scope"], "shared_site")
        self.assertIsNone(ledger.first("public_brand"))

    def test_the_home_page_of_a_site_that_prints_the_number_is_still_the_companys_own(self):
        # rohnegarden.no is not named after ANNO 09 AS, but its home page prints the company's number: its profile stays.
        html = ("<html><head><title>Røhnegården - En levende del av Hamars byhistorie</title></head><body><h1>Røhnegården</h1>"
                "<footer>Anno 09 AS · Org.nr 994 253 239 <a href='https://www.facebook.com/rohnegarden'>Facebook</a></footer></body></html>")
        company = Company(org="994253239", name="ANNO 09 AS", legal_form="AS")
        found = research(company, "https://rohnegarden.no", html, "registry_email_domain", "medium")
        self.assertEqual(found.state, "verified")
        self.assertFalse(shared_site(company, found))
        ledger = Ledger(company.org)
        extract_site(ledger, company, found)
        self.assertEqual(ledger.first("social_profile")["value"], "https://www.facebook.com/rohnegarden")

    def test_a_sub_page_on_a_domain_named_after_the_company_is_its_own(self):
        company = Company(org="1", name="MÅSØVAL AS")
        s = site("https://www.masoval.no/om-oss/", "<html><body>Måsøval AS</body></html>")
        s.proof = {"orgnr": {"url": "u", "excerpt": "org.nr 1", "value": "1"}, "other_orgnrs": ["937290658"]}
        self.assertFalse(shared_site(company, s))


class GroupMemberHandleTests(unittest.TestCase):
    varanger = Company(org="985188092", name="VARANGER KRAFT AS", legal_form="AS",
                       group_names=["VARANGER KRAFTMARKED AS", "VARANGER KRAFTFIBER AS", "VARANGER KRAFTENTREPRENØR AS",
                                    "PASVIK KRAFT AS", "BARENTS NETT AS"])

    def test_a_subsidiarys_page_on_the_parents_site_is_the_subsidiarys(self):
        for url in ("https://www.facebook.com/varangerkraftfiber", "http://www.facebook.com/varangerkraftmarked/",
                    "https://www.youtube.com/@varangerkraftfiber/videos", "http://www.instagram.com/varangerkraftmarked/"):
            self.assertTrue(foreign_entity_handle(self.varanger, url), url)
        self.assertFalse(foreign_entity_handle(self.varanger, "https://www.facebook.com/varangerkraft"))

    def test_a_subsidiary_keeps_its_own_page_although_it_contains_the_parents_name(self):
        marked = Company(org="985519366", name="VARANGER KRAFTMARKED AS", legal_form="AS", group_names=["VARANGER KRAFT AS"])
        self.assertFalse(foreign_entity_handle(marked, "http://www.facebook.com/varangerkraftmarked/"))

    def test_the_ultimate_parents_page_is_not_the_subsidiarys(self):
        bauta = Company(org="956595924", name="BAUTA CONSTRUCTION AS", legal_form="AS",
                        aliases=["NORDVEST SVEIS AS"], group_names=["BAUTA INDUSTRIES AS", "BAUTA GROUP AS"])
        self.assertTrue(foreign_entity_handle(bauta, "https://www.linkedin.com/company/bautagroup/"))
        self.assertTrue(foreign_entity_handle(bauta, "https://www.instagram.com/bautagroup/"))
        self.assertFalse(foreign_entity_handle(bauta, "https://www.linkedin.com/company/bauta-construction/"))
        # A group whose own name is the handle keeps it: LABOREMUS GROUP AS and facebook.com/laboremusgroup.
        self.assertFalse(foreign_entity_handle(Company(org="1", name="LABOREMUS GROUP AS", group_names=["LABOREMUS OSLO AS"]),
                                               "https://www.facebook.com/laboremusgroup/"))

    def test_extract_site_drops_group_members_profiles_and_keeps_its_own(self):
        html = ("<html><head><title>Varanger Kraft - Forside</title><meta property='og:site_name' content='Varanger Kraft'></head>"
                "<body><h1>Varanger Kraft</h1><p>Varanger Kraft AS, Nyborgveien 70A, 9800 Vadsø</p><footer>"
                "<a href='https://www.facebook.com/varangerkraft'>Facebook</a>"
                "<a href='http://www.facebook.com/varangerkraftmarked/'>Kraftmarked på Facebook</a>"
                "<a href='http://www.instagram.com/varangerkraftmarked/'>Instagram</a></footer></body></html>")
        s = site("https://www.varanger-kraft.no", html)
        s.proof = {"orgnr": None, "other_orgnrs": []}
        ledger = Ledger(self.varanger.org)
        info = extract_site(ledger, self.varanger, s)
        self.assertEqual([p["url"] for p in info["profiles"]], ["https://www.facebook.com/varangerkraft"])

    def test_the_agent_reads_the_group_names_from_the_register(self):
        structure = {"organisasjonsnummer": "993498548", "navn": "BAUTA GROUP AS", "children": [
            {"organisasjonsnummer": "976901061", "navn": "BAUTA INDUSTRIES AS", "children": [
                {"organisasjonsnummer": "956595924", "navn": "BAUTA CONSTRUCTION AS", "children": []}]}]}
        ledger = Ledger("956595924")
        group_claims(ledger, fetched("https://data.brreg.no/enhetsregisteret/api/konsernstruktur/956595924", structure), "956595924")
        self.assertEqual(sorted(Agent._group_names(ledger, "956595924")), ["BAUTA GROUP AS", "BAUTA INDUSTRIES AS"])


class FacebookIdSlugTests(unittest.TestCase):
    def test_a_p_page_naming_another_company_is_that_companys(self):
        brokke = Company(org="916538227", name="BROKKE ALPINSENTER AS", legal_form="AS")
        self.assertTrue(foreign_entity_handle(brokke, "https://www.facebook.com/p/Brokke-VVS-as-61552198067839/"))
        self.assertFalse(foreign_entity_handle(brokke, "https://www.facebook.com/brokkecom/?locale=nb_NO"))

    def test_the_companys_own_p_page_is_kept(self):
        kines = Company(org="915714323", name="KINES RENHOLD AS", legal_form="AS")
        self.assertFalse(foreign_entity_handle(kines, "https://facebook.com/p/Kines-Renhold-As-100057155092602/"))
        jerstad = Company(org="929395492", name="JERSTAD VVS AS", legal_form="AS")
        self.assertFalse(foreign_entity_handle(jerstad, "https://www.facebook.com/Jerstad-Vvs-Rørlegger-Bedrift-1809952822585712/"))
        hegra = Company(org="937903235", name="HEGRA SPAREBANK")
        self.assertFalse(foreign_entity_handle(hegra, "https://www.facebook.com/pages/Hegra-Sparebank/137392483810"))


class NegativeBaseRevenueTests(OverviewTests):
    def test_no_percentage_from_a_negative_year(self):
        # 914842441 in the 1 Nov batch: revenue NOK -11,087 in 2024 and NOK 1,851,104 in 2025 read "up 16796.2%".
        ledger, s = self.summary([year(2025, 1_851_104, 1_800_000, 17_200_000, 18_000_000),
                                  year(2024, -11_087, -50_000, 15_400_000, 16_000_000)])
        self.assertNotIn("%", " ".join(s["parts"]["overview"]))
        self.assertIn("In 2025 it had revenue of NOK 1.9 m, made an operating profit of NOK 1.8 m and had equity of NOK 17.2 m.",
                      s["parts"]["overview"])
        self.assertNotIn("16796", s["text"])
        self.assertIn("revenue went from NOK -11 k to NOK 1.9 m", " ".join(s["parts"]["what_changed"]))
        self.assertFalse([sig for sig in s["signals"] if sig["text"].startswith("Revenue ")])
        self.assertEqual(s["dropped_unsupported_sentences"], 0)
        self.assertTrue(all(check_sentence(sentence, ledger) for sentence in s["sentences"]))

    def test_the_percentage_needs_two_positive_years(self):
        rows = lambda a, b: ({"revenue": {"value": a}}, {"revenue": {"value": b}})  # noqa: E731
        self.assertEqual(_pct_change(*rows(1_200_000, 1_000_000), "revenue"), 20.0)
        self.assertEqual(_pct_change(*rows(0, 1_000_000), "revenue"), -100.0)
        self.assertIsNone(_pct_change(*rows(1_851_104, -11_087), "revenue"))
        self.assertIsNone(_pct_change(*rows(-50_000, 100_000), "revenue"))
        self.assertIsNone(_pct_change(*rows(100_000, 0), "revenue"))


def listing_work(org: str, name: str, email: str) -> Work:
    entity = {"organisasjonsnummer": org, "navn": name, "epostadresse": email}
    work = Work(org, Ledger(org))
    doc = Document(url=f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}", source_class="official_registry_live",
                   retrieved_at="2026-11-01T00:00:00Z", sha256="c" * 64, text=json.dumps(entity), data=entity)
    work.ledger.json_claim(doc, "/epostadresse", "identity", "registered_email")
    work.company = Company(org=org, name=name, legal_form="AS", emails={email})
    work.entity = entity
    return work


def hjemmeside(domain: str, items: list[dict] | None):
    """Register answers for the website-field search (None: the register does not answer)."""
    answers = {}
    for kind in ("enheter", "underenheter"):
        url = f"https://data.brreg.no/enhetsregisteret/api/{kind}?hjemmeside={domain}&size=100"
        if items is None:
            continue
        body = {"_embedded": {kind: items}} if items and kind == "enheter" else {"page": {"totalElements": 0}}
        answers[url] = (lambda b: lambda u: result(u, json.dumps(b).encode("utf-8"), "application/json"))(body)
    return answers


class EmailDomainListingCheckTests(unittest.TestCase):
    """A shared e-mail domain whose site refuses the crawler is the Saltek risk: the sister company that owns the domain."""
    candidate = Candidate("https://marinor.no", "registry_email_domain", "medium")
    refusal = SiteResult(candidate, "blocked", "site refused automated access (HTTP 403)")

    def run_footprint(self, answers: dict):
        agent = Agent(run_id="t", snapshot_dir=None, cache_dir=None, workers=1, use_search=False, log=lambda *a: None)
        agent.sites = SiteResearcher(FakeFetcher(answers))
        work = listing_work("999888777", "MARINOR AS", "post@marinor.no")
        with mock.patch.object(agent, "candidates", return_value=[self.candidate]), \
                mock.patch.object(agent.sites, "research", return_value=self.refusal), \
                mock.patch.object(agent.nav, "claims", return_value=[]):
            agent.footprint(work)
        return work

    def test_a_domain_the_register_lists_for_another_organisation_is_related(self):
        work = self.run_footprint(hjemmeside("marinor.no", [{"organisasjonsnummer": "913207521", "navn": "MARINOR SERVICE AS",
                                                               "hjemmeside": "www.marinor.no", "organisasjonsform": {"kode": "AS"}}]))
        self.assertIsNone(work.ledger.first("official_website"))
        self.assertEqual(work.states["website"], "ambiguous")
        self.assertIn("register lists this website for another organisation", work.notes["website"])
        self.assertEqual(work.discovery[0]["outcome"], "related")

    def test_no_answer_from_the_register_is_not_checked_not_published(self):
        work = self.run_footprint(hjemmeside("marinor.no", None))
        self.assertIsNone(work.ledger.first("official_website"))
        self.assertEqual(work.states["website"], "failed")
        self.assertIn("did not answer", work.notes["website"])

    def test_a_domain_nobody_else_lists_is_still_published_from_the_register(self):
        work = self.run_footprint(hjemmeside("marinor.no", []))
        website = work.ledger.first("official_website")
        self.assertEqual((website["value"], website["basis"]), ("https://marinor.no", "registry_listing"))
        self.assertEqual(work.states["website"], "available")


class SessionIdTests(unittest.TestCase):
    def test_the_published_website_carries_no_session_id(self):
        company = Company(org="926757504", name="VERTSHUSET FRISØR AS", legal_form="AS")
        values = []
        for session in ("ZoIl3-_DQa94jvXoOt7PZ01sU8VXxClijMPOcUge.timebok", "8Te05MwelBmIWkHzx__7oq2U6kU1p8IRLKWF8L-i.timebok"):
            s = site(f"https://vertshusetfrisor.no/c;jsessionid={session}?0",
                     "<html><head><title>Timebooking</title></head><body>Vertshuset Frisør AS</body></html>")
            s.proof = {"orgnr": None, "other_orgnrs": []}
            ledger = Ledger(company.org)
            extract_site(ledger, company, s)
            values.append(ledger.first("official_website")["value"])
        self.assertEqual(values, ["https://vertshusetfrisor.no/c?0"] * 2)

    def test_session_parameters_go_and_everything_else_stays(self):
        from signalpost.web import strip_session_ids
        self.assertEqual(strip_session_ids("https://x.no/a?PHPSESSID=abc&id=7"), "https://x.no/a?id=7")
        self.assertEqual(strip_session_ids("https://x.no/a?id=7&sid=9#top"), "https://x.no/a?id=7#top")
        self.assertEqual(strip_session_ids("https://x.no/side;jsessionid=AB12/kontakt?jsessionid=1"), "https://x.no/side/kontakt")
        self.assertEqual(strip_session_ids("https://x.no/a?ASPSESSIONIDQQ=1&b=2&c"), "https://x.no/a?b=2&c")
        for unchanged in ("https://x.no/a?0", "https://x.no/", "https://x.no/a?side=2&sort=pris", "https://x.no/a?b=1+2&c=%C3%A5"):
            self.assertEqual(strip_session_ids(unchanged), unchanged)

    def test_a_careers_link_carries_no_session_id(self):
        company = Company(org="1", name="FØRLAND RØR AS")
        s = site("https://www.forlandror.no", "<html><body>Førland Rør AS"
                                              "<a href='https://www.forlandror.no/ledige-stillinger/?PHPSESSID=77aa'>Ledige stillinger</a></body></html>")
        s.proof = {"orgnr": None, "other_orgnrs": []}
        ledger = Ledger(company.org)
        extract_site(ledger, company, s)
        self.assertEqual(ledger.first("careers_page")["value"], "https://www.forlandror.no/ledige-stillinger/")


class IdentityProofExcerptTests(unittest.TestCase):
    def test_an_address_over_two_lines_is_cited(self):
        html = ("<html><head><title>LilleLi Smykker</title></head><body><h1>LilleLi Smykker</h1><p>Sølvsmykker laget i Alta.</p>"
                "<footer><div>LilleLi AS</div><div>Minkveien 6</div><div>9512 ALTA</div><div>Telefon: 91741123</div>"
                "</footer></body></html>")
        company = Company(org="828354922", name="LILLELI AS", legal_form="AS", street="Minkveien 6", postcode="9512", city="ALTA")
        found = research(company, "https://lilleli.no", html, "domain_guess_from_legal_name", "weak", hjemmeside("lilleli.no", []))
        self.assertEqual(found.state, "verified")
        ledger = Ledger(company.org)
        extract_site(ledger, company, found)
        proof = ledger.first("website_identity_proof")
        self.assertEqual((proof["proof_kind"], proof["value"]), ("address", "Minkveien 6 9512 ALTA"))

    def test_an_organisation_number_at_the_end_of_the_page_is_cited(self):
        # lius.no: the number is the page's last line, so a window cut from the page text plus its meta tags ran into
        # "viewport: width=device-width", which the cited page text does not contain.
        html = ("<html><head><title>Lius | Gründerhus og kontorfellesskap i Lørenskog</title>"
                "<meta name='viewport' content='width=device-width, initial-scale=1'></head><body><h1>Lius</h1>"
                "<p>Kontorplass, coworking og møterom på Skårersletta 69.</p>"
                "<footer>© 2026 Skårersletta 69 AS - 935 637 767. Nettside av Digitelle.</footer></body></html>")
        company = Company(org="935637767", name="LIUS AS", legal_form="AS")
        found = research(company, "https://lius.no", html, "domain_guess_from_legal_name", "weak")
        self.assertEqual(found.state, "verified")
        ledger = Ledger(company.org)
        extract_site(ledger, company, found)
        self.assertEqual(ledger.first("website_identity_proof")["value"], "935 637 767")


if __name__ == "__main__":
    unittest.main()
