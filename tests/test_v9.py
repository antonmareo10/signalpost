"""Offline tests for 1.7.0: the cases Builderr's 13 Nov review found, and the new company-site facts.

- A guessed domain is published only when the site itself ties it to the company: the organisation number, the legal
  name with a registered phone, e-mail or street address, or the full legal name with its legal form on a Norwegian
  site named after the company. A name that merely matches the domain is not enough, however unique it is in the
  register (an official run gave ISABELLA CAFE AS an Illinois café's site and WATAHA BYGG AS a Polish association's).
- "Isabella Cafe as ..." is the English word "as", not the legal form AS.
- The domain of the registered e-mail address needs the same proof (the matching domain alone no longer counts).
- New facts from the verified site: its phone number (tel: link), the open positions its careers page lists, and dated
  articles its news page links.
Run: python -m unittest discover -s tests"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from signalpost.html import parse_html  # noqa: E402
from signalpost.ledger import Ledger  # noqa: E402
from signalpost.synth import build_summary  # noqa: E402
from signalpost.web import (Candidate, Company, SiteResearcher, SiteResult, article_posts, career_postings, extract_site,  # noqa: E402
                            legal_name_hit)
from test_v4 import FakeFetcher, result, site  # noqa: E402
from test_v7 import hjemmeside  # noqa: E402

ISABELLA = ("<html lang='en'><head><title>Home | Isabella's Cafe Italian Restaurant | Tinley Park, IL</title></head><body>"
            "<header><h1>Isabella Cafe</h1></header><p>Isabella Cafe as a family restaurant has served Northern Italian food "
            "since 2001. Call 708-555-0101. We ship gift cards to Norway too.</p><footer>Isabella Cafe, 3510 W 183rd St</footer>"
            "</body></html>")


def research(company: Company, url: str, html: str, source: str = "domain_guess_from_legal_name", strength: str = "weak",
             extra: dict | None = None):
    answers = {url: lambda u: result(u, html.encode("utf-8"), "text/html; charset=UTF-8"), **(extra or {})}
    return SiteResearcher(FakeFetcher(answers)).research(company, Candidate(url, source, strength))


class InferredSiteProofTests(unittest.TestCase):
    def test_a_namesake_abroad_is_not_published(self):
        company = Company(org="932415313", name="ISABELLA CAFE AS", legal_form="AS", street="Stabells gate 13", postcode="3510",
                          city="HØNEFOSS")
        researcher = SiteResearcher(FakeFetcher({"https://isabellacafe.com": lambda u: result(u, ISABELLA.encode(), "text/html")}))
        researcher._name_unique = lambda company, words=None: True  # type: ignore[assignment]
        found = researcher.research(company, Candidate("https://isabellacafe.com", "domain_guess_from_legal_name", "weak"))
        self.assertEqual(found.state, "rejected")
        self.assertFalse(found.proof["norwegian_context"])  # "3510" in a US street address and "Norway" do not count

    def test_the_english_word_as_is_not_the_legal_form(self):
        self.assertIsNone(legal_name_hit("ISABELLA CAFE AS", "Isabella Cafe as a family restaurant"))
        self.assertEqual(legal_name_hit("ISABELLA CAFE AS", "Drives av Isabella Cafe AS, Stabells gate 13"), "Isabella Cafe AS")

    def test_a_norwegian_site_with_the_name_but_no_proof_is_not_published(self):
        html = ("<html lang='pl-PL'><head><title>Wataha.no - Informacje z Norwegii</title></head><body><header>Wataha bygg og "
                "arbeid i Norge</header><p>Praktyczne informacje dla Polaków w Norwegii.</p></body></html>")
        found = research(Company(org="933831973", name="WATAHA BYGG AS", legal_form="AS", street="Ramfjordnesvegen 198",
                                 postcode="9021"), "https://wataha.no", html, extra=hjemmeside("wataha.no", []))
        self.assertEqual(found.state, "rejected")

    def test_the_legal_name_with_a_registered_phone_still_verifies_a_guess(self):
        html = ("<html><head><title>Seland Optikk</title></head><body><header>Seland Optikk</header><p>Briller og linser i "
                "Sandnes sentrum.</p><footer>Seland Optikk Sandnes · Tlf 51 66 12 34</footer></body></html>")
        company = Company(org="983075401", name="SELAND OPTIKK SANDNES AS", legal_form="AS", phones={"51661234"})
        found = research(company, "https://selandoptikksandnes.no", html, extra=hjemmeside("selandoptikksandnes.no", []))
        self.assertEqual(found.state, "verified")

    def test_the_full_legal_name_on_a_norwegian_site_named_after_the_company_verifies_a_guess(self):
        html = ("<html><head><title>Bilsalg Nord</title></head><body><h1>Bilsalg Nord</h1><p>Vi selger brukte biler og har "
                "verksted i Narvik.</p><footer>Bilsalg Nord AS</footer></body></html>")
        found = research(Company(org="1", name="BILSALG NORD AS", legal_form="AS"), "https://bilsalgnord.no", html,
                         extra=hjemmeside("bilsalgnord.no", []))
        self.assertEqual(found.state, "verified")

    def test_the_e_mail_domain_needs_a_registered_contact_detail_not_just_the_name(self):
        html = ("<html><head><title>Marinor</title></head><body><header>Marinor</header><p>Vi leverer marine tjenester og er "
                "på kaia hver dag.</p></body></html>")
        company = Company(org="999888777", name="MARINOR AS", legal_form="AS", emails={"post@marinor.no"})
        found = research(company, "https://marinor.no", html, "registry_email_domain", "medium", hjemmeside("marinor.no", []))
        self.assertEqual(found.state, "rejected")
        with_mail = html.replace("</body>", "<footer>Skriv til post@marinor.no</footer></body>")
        found = research(company, "https://marinor.no", with_mail, "registry_email_domain", "medium", hjemmeside("marinor.no", []))
        self.assertEqual(found.state, "verified")


class RegisteredSiteTests(unittest.TestCase):
    def test_a_registered_domain_that_shows_nothing_of_the_company_is_not_published(self):
        # the register still lists it, but the site now says nothing about the company: a lapsed domain may be someone else's
        html = ("<html><head><title>Velkommen</title></head><body><h1>Velkommen</h1><p>Her kommer en ny nettside for "
                "kunder og venner av huset.</p></body></html>")
        found = research(Company(org="1", name="HAVBRUK SERVICE AS", legal_form="AS"), "https://havbrukservice.no", html,
                         "registry_website", "strong")
        self.assertEqual(found.state, "rejected")
        named = html.replace("<h1>Velkommen</h1>", "<h1>Havbruk Service</h1>")
        found = research(Company(org="1", name="HAVBRUK SERVICE AS", legal_form="AS"), "https://havbrukservice.no", named,
                         "registry_website", "strong")
        self.assertEqual(found.state, "verified")


class SitePhoneTests(unittest.TestCase):
    def test_the_footer_phone_is_published_and_a_person_s_number_is_not(self):
        company = Company(org="1", name="VAKTMESTER ANDERSEN AS", people=["Kari Nordmann"])
        s = site("https://www.vaktmesterandersen.no/",
                 "<html><body><h1>Vaktmester Andersen</h1><p>Ring <a href='tel:+4799887766'>Kari Nordmann</a></p>"
                 "<footer><a href='tel:+4722389292'>22 38 92 92</a></footer></body></html>")
        s.proof = {"orgnr": None, "other_orgnrs": []}
        ledger = Ledger(company.org)
        extract_site(ledger, company, s)
        self.assertEqual([c["value"] for c in ledger.by_field("website_phone")], ["+4722389292"])


CAREERS = ("<html><head><title>Ledige stillinger - Fjordbygg</title>"
           "<script type='application/ld+json'>{\"@context\":\"https://schema.org\",\"@type\":\"JobPosting\",\"title\":\"Tømrer til "
           "Bergen\",\"datePosted\":\"2026-10-20\",\"validThrough\":\"2026-12-01\",\"hiringOrganization\":{\"@type\":\"Organization\","
           "\"name\":\"Fjordbygg AS\"},\"url\":\"https://fjordbygg.no/ledige-stillinger/tomrer-bergen\"}</script>"
           "<script type='application/ld+json'>{\"@type\":\"JobPosting\",\"title\":\"Gammel stilling\",\"validThrough\":\"2025-01-01\","
           "\"hiringOrganization\":{\"name\":\"Fjordbygg AS\"}}</script>"
           "<script type='application/ld+json'>{\"@type\":\"JobPosting\",\"title\":\"Selger til søsterselskapet\","
           "\"hiringOrganization\":{\"name\":\"Helt Annet Konsern AS\"}}</script></head><body><h1>Ledige stillinger</h1>"
           "<a href='https://fjordbygg.no/ledige-stillinger/prosjektleder-oslo'>Prosjektleder Oslo</a>"
           "<a href='https://fjordbygg.no/ledige-stillinger/apen-soknad'>Åpen søknad</a>"
           "<a href='https://fjordbygg.no/tjenester/tak'>Tak og fasade</a>"
           "<a href='https://fjordbygg.teamtailor.com/jobs/4567890-lagerarbeider'>Lagerarbeider</a>"
           "<a href='https://andre.teamtailor.com/jobs/1111111-kokk'>Kokk hos noen andre</a></body></html>")


class CareerPostingTests(unittest.TestCase):
    def postings(self, home_url: str, company: Company, other_orgnrs: list[str] | None = None):
        careers_url = "https://fjordbygg.no/ledige-stillinger"
        fetcher = FakeFetcher({careers_url: lambda u: result(u, CAREERS.encode("utf-8"), "text/html; charset=UTF-8")})
        researcher = SiteResearcher(fetcher)
        s = site(home_url, "<html><body>Fjordbygg</body></html>")
        s.proof = {"orgnr": None, "other_orgnrs": other_orgnrs or []}
        ledger = Ledger(company.org)
        out = career_postings(researcher._fetch_page, ledger, company, s, [{"url": careers_url}], "2026-11-13")
        return [p["title"] for p in out], ledger

    def test_open_positions_listed_by_the_company_s_own_careers_page(self):
        titles, ledger = self.postings("https://fjordbygg.no/", Company(org="1", name="FJORDBYGG AS"))
        self.assertEqual(titles, ["Tømrer til Bergen", "Prosjektleder Oslo", "Lagerarbeider"])
        first = ledger.by_field("job_posting")[0]
        self.assertEqual((first["source"], first["event_date"], first["expires"]), ("company_careers_page", "2026-10-20", "2026-12-01"))

    def test_a_group_site_lends_no_postings(self):
        # fjordbygg.no is the group's site for FJORDBYGG VEST AS: its careers page lists the group's adverts ("Fjordbygg AS"
        # hires, not "Fjordbygg Vest AS"), so none of its links, ATS adverts or JSON-LD postings are the company's
        titles, _ = self.postings("https://fjordbygg.no/", Company(org="1", name="FJORDBYGG VEST AS"), other_orgnrs=["987654321"])
        self.assertEqual(titles, [])

    def test_synthesis_says_where_the_positions_are_listed(self):
        _, ledger = self.postings("https://fjordbygg.no/", Company(org="1", name="FJORDBYGG AS"))
        summary = build_summary(ledger, {"accounts": [], "changes": [], "missing": [], "today": "2026-11-13"})
        text = json.dumps(summary, ensure_ascii=False)
        self.assertIn("Its own careers page lists 3 open positions", text)
        self.assertNotIn("on NAV's arbeidsplassen.no", text)


class ArticlePostTests(unittest.TestCase):
    def test_a_dated_article_linked_from_the_news_page(self):
        news = parse_html("<html><body><h1>Nyheter</h1><a href='https://njordaqua.no/aktuelt/havexpo-2026-i-bergen'>"
                          "Vi stiller ut på HavExpo 2026 i Bergen</a><a href='https://njordaqua.no/aktuelt/'>Se alle nyheter</a>"
                          "</body></html>", "https://njordaqua.no/aktuelt/")
        article = ("<html><body><h1>Vi stiller ut på HavExpo 2026 i Bergen</h1><p>Publisert 27. april 2026</p>"
                   "<p>Kom og besøk standen vår.</p></body></html>")
        fetcher = FakeFetcher({"https://njordaqua.no/aktuelt/havexpo-2026-i-bergen":
                               lambda u: result(u, article.encode("utf-8"), "text/html; charset=UTF-8")})
        s = site("https://njordaqua.no/", "<html><body>Njord Aqua</body></html>")
        ledger = Ledger("1")
        posts = article_posts(SiteResearcher(fetcher)._fetch_page, ledger, s, "2026-11-13",
                              [(result("https://njordaqua.no/aktuelt/", b"", "text/html"), news)])
        self.assertEqual([(p["date"], p["title"]) for p in posts], [("2026-04-27", "Vi stiller ut på HavExpo 2026 i Bergen")])
        self.assertEqual(ledger.by_field("website_post")[0]["url"], "https://njordaqua.no/aktuelt/havexpo-2026-i-bergen")


if __name__ == "__main__":
    unittest.main()
