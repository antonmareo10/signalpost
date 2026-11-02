"""Offline tests for 1.6.1: cases from reading every website, profile, careers page, post, brand, description and
e-mail address that 1.6.0 published for 1,000 new companies (seed 20261102), and the same rules measured on the
earlier batches.

- A registered website whose domain spells the whole name of another organisation that lists it in the register, and only
  part of this company's name, is that organisation's: GAUTE ROSTRUP EIENDOM AS (property) lists gaute-rostrup.no, the
  frame shop GAUTE ROSTRUP AS's site. Only the page is attributed (no description, profile, e-mail or posts).
- A site whose domain is named after the company's registered parent (or ultimate parent) and not after the company is
  the group's site: only the verified page is attributed to the company, never the group's brand, description,
  profiles, careers page, e-mail addresses or posts (BOREAL BANE AS on boreal.no, BACKE ROGALAND AS on backe.no).
- No e-mail address is taken from a page (other than the home page) that links addresses on three or more domains: it
  lists other organisations' contacts (PANTAENIUS NUF and its group's "Avdelinger" page: Hamburg, Monaco, Skive...).
- A site name with a part that names another legal entity is not the brand ("Langset AS - Forside" on LANGSET GROUP AS).
Run: python -m unittest discover -s tests"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from signalpost.agent import Agent  # noqa: E402
from signalpost.html import parse_html  # noqa: E402
from signalpost.ledger import Ledger  # noqa: E402
from signalpost.registry import group_claims  # noqa: E402
from signalpost.web import (Candidate, Company, SiteResearcher, acceptable_brand, directory_page, extract_site,  # noqa: E402
                            parent_domain, shared_site)
from test_v2 import fetched  # noqa: E402
from test_v4 import FakeFetcher, result, site  # noqa: E402
from test_v7 import hjemmeside  # noqa: E402

ROSTRUP_HOME = (
    "<html><head><title>Hjem - Gaute Rostrup AS, Innramming, kunstnermateriell, Sandnes</title>"
    "<meta name='description' content='Gaute Rostrup AS er en spesial forretning for innramming. Vi har tre fagbrev og tre "
    "mesterbrev.'></head>"
    "<body><h1>Gaute Rostrup</h1><p>Innramming og kunstnermateriell i Sandnes. Ring 51 66 13 75.</p>"
    "<a href='mailto:post@gaute-rostrup.no'>post@gaute-rostrup.no</a>"
    "<footer><a href='https://www.instagram.com/gauterostrup/'>Instagram</a></footer></body></html>")
ROSTRUP_OWNERS = [{"organisasjonsnummer": "945070781", "navn": "GAUTE ROSTRUP AS", "hjemmeside": "www.gaute-rostrup.no",
                   "organisasjonsform": {"kode": "AS"}},
                  {"organisasjonsnummer": "984399804", "navn": "GAUTE ROSTRUP EIENDOM AS", "hjemmeside": "www.gaute-rostrup.no",
                   "organisasjonsform": {"kode": "AS"}}]


class SisterSiteInTheRegisterTests(unittest.TestCase):
    eiendom = Company(org="984399804", name="GAUTE ROSTRUP EIENDOM AS", legal_form="AS", phones={"51661375"})

    def research(self, owners, company=None):
        url = "https://www.gaute-rostrup.no"
        fetcher = FakeFetcher({url: lambda u: result(u, ROSTRUP_HOME.encode("utf-8"), "text/html; charset=UTF-8"),
                               **hjemmeside("gaute-rostrup.no", owners)})
        return SiteResearcher(fetcher).research(company or self.eiendom, Candidate(url, "registry_website", "strong"))

    def test_the_sisters_site_publishes_only_the_page(self):
        found = self.research(ROSTRUP_OWNERS)
        self.assertEqual(found.state, "verified")
        self.assertEqual([o["org"] for o in found.proof["site_of"]], ["945070781"])
        self.assertTrue(shared_site(self.eiendom, found))
        ledger = Ledger(self.eiendom.org)
        info = extract_site(ledger, self.eiendom, found)
        self.assertTrue(info["shared"])
        website = ledger.first("official_website")
        self.assertEqual((website["value"], website["site_scope"]), ("https://www.gaute-rostrup.no", "shared_site"))
        self.assertIn("GAUTE ROSTRUP AS (945070781)", website["verification"])
        for field_name in ("website_description", "social_profile", "website_email", "public_brand", "careers_page"):
            self.assertIsNone(ledger.first(field_name), field_name)

    def test_the_organisation_the_domain_spells_keeps_its_site(self):
        shop = Company(org="945070781", name="GAUTE ROSTRUP AS", legal_form="AS", phones={"51661375"})
        found = self.research(ROSTRUP_OWNERS, shop)
        self.assertEqual(found.state, "verified")
        self.assertNotIn("site_of", found.proof)  # the domain spells its whole name: no lookup, its own site
        self.assertFalse(shared_site(shop, found))
        ledger = Ledger(shop.org)
        extract_site(ledger, shop, found)
        self.assertEqual(ledger.first("social_profile")["value"], "https://www.instagram.com/gauterostrup/")

    def test_a_domain_nobody_else_spells_stays_the_companys(self):
        found = self.research([ROSTRUP_OWNERS[1]])
        self.assertEqual(found.proof["site_of"], [])
        self.assertFalse(shared_site(self.eiendom, found))

    def test_no_answer_from_the_register_attributes_only_the_page(self):
        found = self.research(None)
        self.assertIsNone(found.proof["site_of"])
        self.assertTrue(shared_site(self.eiendom, found))
        ledger = Ledger(self.eiendom.org)
        extract_site(ledger, self.eiendom, found)
        self.assertIn("did not answer", ledger.first("official_website")["verification"])
        self.assertIsNone(ledger.first("social_profile"))


BOREAL_HOME = (
    "<html><head><title>Boreal - forside</title><meta property='og:site_name' content='Boreal'>"
    "<meta name='description' content='Boreal er et ledende nasjonalt konsern innen kollektivtransport. Vi kjører busser, trikker, "
    "hurtigbåter og ferger.'></head>"
    "<body><h1>Boreal</h1><p>Boreal Bane AS kjører Gråkallbanen i Trondheim.</p>"
    "<a href='https://www.boreal.no/jobb/jobb-i-boreal'>Jobb i Boreal</a>"
    "<a href='mailto:post@boreal.no'>post@boreal.no</a>"
    "<footer>Navn/tittel: Boreal Norge AS <a href='https://www.facebook.com/borealnorge'>Facebook</a>"
    "<a href='https://www.linkedin.com/company/boreal-norge-as/'>LinkedIn</a></footer></body></html>")


class ParentNamedDomainTests(unittest.TestCase):
    boreal_bane = Company(org="954653137", name="BOREAL BANE AS", legal_form="AS", parent_names=["BOREAL NORGE AS"],
                          group_names=["BOREAL NORGE AS"])

    def test_a_domain_named_after_the_parent_is_the_groups_site(self):
        self.assertTrue(parent_domain(self.boreal_bane, "boreal.no"))
        backe = Company(org="992352612", name="BACKE ROGALAND AS", legal_form="AS", parent_names=["BACKE ENTREPRENØR AS"])
        self.assertTrue(parent_domain(backe, "backe.no"))

    def test_only_the_page_is_published_from_the_parents_site(self):
        s = site("https://www.boreal.no/forside/", BOREAL_HOME)
        s.proof = {"orgnr": None, "other_orgnrs": []}
        self.assertTrue(shared_site(self.boreal_bane, s))
        ledger = Ledger(self.boreal_bane.org)
        info = extract_site(ledger, self.boreal_bane, s)
        self.assertTrue(info["shared"])
        self.assertEqual(ledger.first("official_website")["site_scope"], "shared_site")
        for field_name in ("public_brand", "website_description", "social_profile", "careers_page", "website_email"):
            self.assertIsNone(ledger.first(field_name), field_name)

    def test_a_subsidiary_on_a_domain_named_after_itself_keeps_its_site(self):
        bauta = Company(org="956595924", name="BAUTA CONSTRUCTION AS", legal_form="AS",
                        parent_names=["BAUTA INDUSTRIES AS", "BAUTA GROUP AS"])
        s = site("https://bautaconstruction.no", "<html><body>Bauta Construction</body></html>")
        s.proof = {"orgnr": None, "other_orgnrs": []}
        self.assertFalse(shared_site(bauta, s))

    def test_a_parent_holding_named_after_a_person_does_not_take_the_family_domain(self):
        # syltern.no is JOHS J SYLTERN AS's own site; its parent ØYSTEIN SYLTERN AS is not what the domain spells.
        syltern = Company(org="816510872", name="JOHS J SYLTERN AS", legal_form="AS", parent_names=["ØYSTEIN SYLTERN AS"])
        self.assertFalse(parent_domain(syltern, "syltern.no"))

    def test_a_company_without_a_registered_parent_is_unaffected(self):
        varanger = Company(org="985188092", name="VARANGER KRAFT AS", legal_form="AS",
                           group_names=["VARANGER KRAFTMARKED AS", "PASVIK KRAFT AS"])
        self.assertFalse(parent_domain(varanger, "varanger-kraft.no"))

    def test_the_agent_reads_only_the_parents_for_this_rule(self):
        structure = {"organisasjonsnummer": "993498548", "navn": "BAUTA GROUP AS", "children": [
            {"organisasjonsnummer": "976901061", "navn": "BAUTA INDUSTRIES AS", "children": [
                {"organisasjonsnummer": "956595924", "navn": "BAUTA CONSTRUCTION AS", "children": [
                    {"organisasjonsnummer": "999999999", "navn": "BAUTA SERVICE AS", "children": []}]}]}]}
        ledger = Ledger("956595924")
        group_claims(ledger, fetched("https://data.brreg.no/enhetsregisteret/api/konsernstruktur/956595924", structure), "956595924")
        self.assertEqual(sorted(Agent._group_names(ledger, "956595924", ("group_parent", "group_ultimate_parent"))),
                         ["BAUTA GROUP AS", "BAUTA INDUSTRIES AS"])
        self.assertIn("BAUTA SERVICE AS", Agent._group_names(ledger, "956595924"))


OFFICES_PAGE = (
    "<html><head><title>Avdelinger | Pantaenius</title></head><body><h1>Pantaenius afdelinger</h1>"
    "<p>Pantaenius GmbH, Grosser Grasbrook 10, 20457 Hamburg <a href='mailto:info@pantaenius.com'>info@pantaenius.com</a></p>"
    "<p>Succursale de Monaco <a href='mailto:info@monaco.pantaenius.com'>monaco@pantaenius.com</a></p>"
    "<p>Pantaenius A/S, Østerbro 11, 7800 Skive <a href='mailto:info@pantaenius.dk'>info@pantaenius.dk</a></p>"
    "<p>Pantaenius Ltd, Plymouth <a href='mailto:info@pantaenius.co.uk'>info@pantaenius.co.uk</a></p></body></html>")


class DirectoryPageEmailTests(unittest.TestCase):
    def test_a_page_listing_several_organisations_addresses_lends_none(self):
        company = Company(org="914332516", name="PANTAENIUS NUF", legal_form="NUF")
        home_url = "https://www.pantaenius.com/dk-no/"
        offices_url = "https://www.pantaenius.com/dk-no/kundeservice/kontakt/avdelinger/"
        s = site(home_url, "<html><head><title>Pantaenius Danmark</title></head><body><h1>Pantaenius</h1>"
                           "<a href='mailto:kundeservice@pantaenius.com'>Skriv til oss</a></body></html>")
        offices = result(offices_url, OFFICES_PAGE.encode("utf-8"), "text/html; charset=UTF-8")
        s.pages.append((offices, parse_html(offices.text, offices_url)))
        s.proof = {"orgnr": None, "other_orgnrs": []}
        self.assertTrue(directory_page(s.pages[1][1]))
        self.assertFalse(directory_page(s.pages[0][1]))
        ledger = Ledger(company.org)
        extract_site(ledger, company, s)
        self.assertEqual([c["value"] for c in ledger.by_field("website_email")], ["kundeservice@pantaenius.com"])

    def test_a_contact_page_with_the_companys_own_addresses_is_read(self):
        page = parse_html("<html><body><a href='mailto:post@acme.no'>post</a><a href='mailto:faktura@acme.no'>faktura</a>"
                          "<a href='mailto:ola@gmail.com'>Ola</a></body></html>", "https://acme.no/kontakt")
        self.assertFalse(directory_page(page))


class BrandNamingAnotherEntityTests(unittest.TestCase):
    def test_a_site_name_part_naming_another_legal_entity_is_not_the_brand(self):
        langset = Company(org="921899130", name="LANGSET GROUP AS", legal_form="AS")
        self.assertFalse(acceptable_brand("Langset AS - Forside", langset, "langset.no"))
        self.assertTrue(acceptable_brand("Langset", langset, "langset.no"))
        self.assertTrue(acceptable_brand("Release by Scatec", Company(org="929432517", name="RELEASE SOLAR AS"), "releasesolar.com"))


if __name__ == "__main__":
    unittest.main()
