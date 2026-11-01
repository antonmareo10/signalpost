"""Offline tests for the v7 work: cases from reading every website, profile, careers page and post that 1.5.1 published
for 1,000 new companies (seed 20261101).

- A page under a path of someone else's domain stays that page only, even when it prints the company's organisation
  number (BLÅ KORS BARNEHAGE ØVREBØ AS on blakors.no, a housing co-operative on OBOS's vibbo.no).
- A profile handle that spells another organisation in the registered group is that organisation's (VARANGER KRAFT AS
  and its subsidiaries' pages, BAUTA CONSTRUCTION AS and BAUTA GROUP AS's).
- Facebook's "/p/<Name>-<id>/" pages are read without the id (Brokke-VVS-as-61552198067839 is BROKKE VVS AS).
Run: python -m unittest discover -s tests"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from signalpost.agent import Agent  # noqa: E402
from signalpost.ledger import Ledger  # noqa: E402
from signalpost.registry import group_claims  # noqa: E402
from signalpost.web import Candidate, Company, SiteResearcher, extract_site, foreign_entity_handle, shared_site  # noqa: E402
from test_v2 import fetched  # noqa: E402
from test_v4 import FakeFetcher, result, site  # noqa: E402


def research(company: Company, url: str, html: str, source: str = "registry_website", strength: str = "strong"):
    fetcher = FakeFetcher({url: lambda u: result(u, html.encode("utf-8"), "text/html; charset=UTF-8")})
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


if __name__ == "__main__":
    unittest.main()
