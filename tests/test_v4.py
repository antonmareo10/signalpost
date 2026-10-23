"""Offline tests for v1.3.0: feed items with childless <pubDate>, WordPress REST posts, UTF-8 pages with one stray byte,
domains that no longer resolve, and registered websites that refuse automated access.
Run: python -m unittest discover -s tests"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signalpost.agent import Agent, Work  # noqa: E402
from signalpost.html import parse_html  # noqa: E402
from signalpost.ledger import Document, Ledger  # noqa: E402
from signalpost.net import FetchResult, _to_text  # noqa: E402
from signalpost.web import (Candidate, Company, SiteResearcher, SiteResult, clean_url, domain_match, extract_site,  # noqa: E402
                            feed_posts, is_wordpress, shared_site, wordpress_posts)

HOME = ("<html><head><title>Måsøval</title><meta name='generator' content='WordPress 7.0.2'>"
        "<link rel='alternate' type='application/rss+xml' href='https://www.masoval.no/feed/'></head>"
        "<body><h1>Måsøval</h1><footer>Org.nr. 933 792 854</footer></body></html>")
RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Måsøval</title>
<item><title>Måsøval kåret til Årets Havbedrift 2025</title><link>https://www.masoval.no/artikler/arets-havbedrift/</link>
<pubDate>Thu, 21 Aug 2025 10:14:52 +0000</pubDate><description>Vi har valgt å fokusere STRAY</description></item>
<item><title>Bygg &amp; anlegg</title><link>https://www.masoval.no/artikler/bygg/</link><pubDate>Mon, 02 Jun 2025 08:00:00 +0000</pubDate></item>
<item><title>Annet nettsted</title><link>https://example.com/x</link><pubDate>Mon, 02 Jun 2025 08:00:00 +0000</pubDate></item>
<item><title>Hei, verden!</title><link>https://www.masoval.no/hei-verden/</link><pubDate>Mon, 03 Mar 2014 08:00:00 +0000</pubDate></item>
</channel></rss>"""
ATOM = """<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Blogg</title>
<entry><title>Ny avdeling i Bergen</title><link rel="replies" href="https://firma.no/ny-avdeling/#comments"/>
<link rel="alternate" href="https://firma.no/ny-avdeling/"/><published>2026-03-01T09:00:00Z</published></entry></feed>"""


def result(url: str, body: bytes, content_type: str) -> FetchResult:
    return FetchResult(url=url, final_url=url, status=200, content_type=content_type, body=body, text=_to_text(body, content_type),
                       sha256="b" * 64, retrieved_at="2026-10-22T00:00:00Z")


def failed(url: str, *, status=None, error="", blocked=False) -> FetchResult:
    return FetchResult(url=url, final_url=url, status=status, error=error, blocked=blocked, retrieved_at="2026-10-22T00:00:00Z")


class FakeFetcher:
    def __init__(self, answers):
        self.answers = answers
        self.calls: list[str] = []

    def get(self, url, **_kwargs):
        self.calls.append(url)
        answer = self.answers.get(url) or self.answers.get(url.rstrip("/"))
        return answer(url) if answer else failed(url, status=404, error="HTTP 404")


def site(url: str, html: str) -> SiteResult:
    home = result(url, html.encode("utf-8"), "text/html; charset=UTF-8")
    return SiteResult(Candidate(url, "registry_website", "strong"), "verified", "test", home_url=url,
                      pages=[(home, parse_html(home.text, url))])


class FeedTests(unittest.TestCase):
    def test_rss_items_with_a_childless_pubdate_become_posts(self):
        # <pubDate> has no child elements, so ElementTree treats it as falsy: v1.2.0 dropped every RSS item.
        body = RSS.encode("utf-8").replace(b"STRAY", b"p\xc3...")  # WordPress cut an "å" in half: invalid UTF-8
        fetcher = FakeFetcher({"https://www.masoval.no/feed/": lambda u: result(u, body, "application/rss+xml; charset=UTF-8")})
        ledger = Ledger("933792854")
        posts = feed_posts(fetcher, ledger, site("https://www.masoval.no/", HOME))
        self.assertEqual([p["date"] for p in posts], ["2025-08-21", "2025-06-02"])
        self.assertEqual(posts[0]["title"], "Måsøval kåret til Årets Havbedrift 2025")
        self.assertEqual(posts[1]["title"], "Bygg & anlegg")
        self.assertTrue(all(c["section"] == "activity" for c in ledger.claims))

    def test_atom_entry_uses_the_alternate_link_and_published_date(self):
        html = HOME.replace("https://www.masoval.no/feed/", "https://firma.no/feed.atom")
        fetcher = FakeFetcher({"https://firma.no/feed.atom": lambda u: result(u, ATOM.encode(), "application/atom+xml")})
        posts = feed_posts(fetcher, Ledger("933792854"), site("https://firma.no/", html))
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["url"], "https://firma.no/ny-avdeling/")
        self.assertEqual(posts[0]["date"], "2026-03-01")

    def test_wordpress_rest_posts_cite_a_json_pointer(self):
        html = "<html><head><title>Takelund</title></head><body><img src='/wp-content/uploads/logo.png'>Takelund</body></html>"
        s = site("https://takelund.no/", html)
        self.assertTrue(is_wordpress(s))
        api = "https://takelund.no/wp-json/wp/v2/posts?per_page=10&_fields=id,date,link,title,excerpt"
        data = [{"id": 7, "date": "2026-08-01T00:01:07", "link": "https://takelund.no/sommerfest/",
                 "title": {"rendered": "Sommerfest &#8211; takk for sist"}},
                {"id": 6, "date": "2030-01-01T00:00:00", "link": "https://takelund.no/framtid/", "title": {"rendered": "Framtid"}},
                {"id": 5, "date": "2026-05-01T00:00:00", "link": "https://annen.no/x/", "title": {"rendered": "Annen"}}]
        fetcher = FakeFetcher({api: lambda u: result(u, json.dumps(data).encode(), "application/json; charset=UTF-8")})
        ledger = Ledger("923676368")
        posts = wordpress_posts(fetcher, ledger, s)
        self.assertEqual([(p["date"], p["title"]) for p in posts], [("2026-08-01", "Sommerfest – takk for sist")])
        evidence = ledger.evidence[ledger.claims[0]["evidence_ids"][0]]
        self.assertEqual(evidence["locator"], "/0")
        self.assertEqual(evidence["source_class"], "company_owned_website_api")

    def test_non_wordpress_site_gets_no_rest_call(self):
        fetcher = FakeFetcher({})
        self.assertEqual(wordpress_posts(fetcher, Ledger("1"), site("https://x.no/", "<html><body>Wix</body></html>")), [])
        self.assertEqual(fetcher.calls, [])


class DecodingTests(unittest.TestCase):
    def test_one_stray_byte_keeps_a_utf8_page_utf8(self):
        body = "Måsøval kåret – vi valgte å".encode("utf-8") + b" p\xc3..."
        self.assertTrue(_to_text(body, "text/html; charset=UTF-8").startswith("Måsøval kåret"))

    def test_a_real_cp1252_page_still_decodes(self):
        body = "Bølgen & Moi – Kårstø".encode("cp1252") * 50
        self.assertTrue(_to_text(body, "text/html").startswith("Bølgen & Moi – Kårstø"))


class DomainTests(unittest.TestCase):
    def test_domain_match(self):
        self.assertEqual(domain_match(Company(org="1", name="HIGHSOFT AS"), "www.highsoft.com"), (True, True))
        self.assertEqual(domain_match(Company(org="1", name="CANON NORGE AS"), "canon.no"), (False, True))
        self.assertEqual(domain_match(Company(org="1", name="SAMEIET ULLEVÅLSVEIEN 51"), "norian.no"), (False, False))

    def test_a_domain_that_no_longer_resolves_is_gone_not_blocked(self):
        dns = lambda u: failed(u, error="unsafe_url: hostname did not resolve", blocked=True)  # noqa: E731
        fetcher = FakeFetcher({"https://hazl.no": dns, "https://www.hazl.no/": dns})
        found = SiteResearcher(fetcher).research(Company(org="934237285", name="HAZL AS"),
                                                Candidate("https://hazl.no", "registry_website", "strong"))
        self.assertEqual(found.state, "gone")

    def test_www_that_exists_but_times_out_is_unreachable_not_gone(self):
        fetcher = FakeFetcher({"https://hazl.no": lambda u: failed(u, error="unsafe_url: hostname did not resolve", blocked=True),
                               "https://www.hazl.no/": lambda u: failed(u, error="URLError: timed out")})
        found = SiteResearcher(fetcher).research(Company(org="934237285", name="HAZL AS"),
                                                Candidate("https://hazl.no", "registry_website", "strong"))
        self.assertEqual(found.state, "unreachable")


class RegisteredSiteRefusingAccessTests(unittest.TestCase):
    def _work(self, name: str, entity: dict) -> Work:
        work = Work("996840506", Ledger("996840506"))
        doc = Document(url="https://data.brreg.no/enhetsregisteret/api/enheter/996840506", source_class="official_register",
                       retrieved_at="2026-10-22T00:00:00Z", sha256="c" * 64, text=json.dumps(entity), data=entity)
        if entity.get("hjemmeside"):
            work.ledger.json_claim(doc, "/hjemmeside", "identity", "registered_website", confidence=0.9)
        if entity.get("epostadresse"):
            work.ledger.json_claim(doc, "/epostadresse", "identity", "registered_email")
        work.company = Company(org="996840506", name=name)
        return work

    def test_registered_website_named_after_the_company_is_published_from_the_register(self):
        work = self._work("HIGHSOFT AS", {"hjemmeside": "www.highsoft.com"})
        refused = [(Candidate("https://www.highsoft.com", "registry_website", "strong"),
                    SiteResult(Candidate("https://www.highsoft.com", "registry_website", "strong"), "blocked", "robots.txt disallows this URL"))]
        site_info = Agent._registered_site_refusing_access(work, refused)
        self.assertIsNotNone(site_info)
        claim = work.ledger.first("official_website")
        self.assertEqual(claim["basis"], "registry_listing")
        self.assertEqual(claim["site_access"], "refused")
        self.assertEqual(claim["evidence_ids"], work.ledger.first("registered_website")["evidence_ids"])

    def test_manager_site_is_never_published_from_the_register(self):
        work = self._work("SAMEIET ULLEVÅLSVEIEN 51", {"hjemmeside": "https://www.norian.no/eiendom"})
        refused = [(Candidate("https://www.norian.no/eiendom", "registry_website", "strong"),
                    SiteResult(Candidate("https://www.norian.no/eiendom", "registry_website", "strong"), "blocked",
                               "site refused automated access (HTTP 403)"))]
        self.assertIsNone(Agent._registered_site_refusing_access(work, refused))
        self.assertIsNone(work.ledger.first("official_website"))

    def test_email_domain_needs_the_whole_legal_name(self):
        work = self._work("CANON NORGE AS", {"epostadresse": "post@canon.no"})
        refused = [(Candidate("https://canon.no", "registry_email_domain", "medium"),
                    SiteResult(Candidate("https://canon.no", "registry_email_domain", "medium"), "blocked",
                               "site refused automated access (HTTP 403)"))]
        self.assertIsNone(Agent._registered_site_refusing_access(work, refused))
        work = self._work("GEOPROVIDER AS", {"epostadresse": "post@geoprovider.no"})
        refused = [(Candidate("https://geoprovider.no", "registry_email_domain", "medium"),
                    SiteResult(Candidate("https://geoprovider.no", "registry_email_domain", "medium"), "blocked",
                               "site refused automated access (HTTP 403)"))]
        self.assertIsNotNone(Agent._registered_site_refusing_access(work, refused))

    def test_a_dead_domain_is_not_a_refusal(self):
        work = self._work("HAZL AS", {"hjemmeside": "www.hazl.no"})
        refused = [(Candidate("https://www.hazl.no", "registry_website", "strong"),
                    SiteResult(Candidate("https://www.hazl.no", "registry_website", "strong"), "gone", "the domain does not resolve"))]
        self.assertIsNone(Agent._registered_site_refusing_access(work, refused))


if __name__ == "__main__":
    unittest.main()


class PostFilterTests(unittest.TestCase):
    RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Rigel</title>
<item><title>New Client Landed</title><link>https://rigelmap.no/2013/08/29/new-client-landed/</link>
<pubDate>Thu, 29 Aug 2013 10:00:00 +0000</pubDate><description>Some text</description></item>
<item><title>Another post with a gallery</title><link>https://rigelmap.no/2025/06/01/gallery/</link>
<pubDate>Sun, 01 Jun 2025 10:00:00 +0000</pubDate><description>Lorem ipsum dolor sit amet, consectetur</description></item>
<item><title>Ny maskin levert til Statens vegvesen</title><link>https://rigelmap.no/ny-maskin/?utm_source=rss&amp;utm_medium=rss&amp;utm_campaign=ny-maskin</link>
<pubDate>Mon, 02 Jun 2025 10:00:00 +0000</pubDate><description>Vi leverte</description></item>
</channel></rss>"""

    def test_posts_before_the_company_existed_and_lorem_ipsum_are_skipped(self):
        html = HOME.replace("https://www.masoval.no/feed/", "https://rigelmap.no/feed/")
        fetcher = FakeFetcher({"https://rigelmap.no/feed/": lambda u: result(u, self.RSS.encode(), "application/rss+xml")})
        posts = feed_posts(fetcher, Ledger("935342511"), site("https://rigelmap.no/", html), not_before="2025-01-20")
        self.assertEqual([p["title"] for p in posts], ["Ny maskin levert til Statens vegvesen"])
        self.assertEqual(posts[0]["url"], "https://rigelmap.no/ny-maskin/")

    def test_clean_url_keeps_real_parameters(self):
        self.assertEqual(clean_url("https://x.no/a/?utm_source=rss&id=7"), "https://x.no/a/?id=7")
        self.assertEqual(clean_url("https://x.no/a/"), "https://x.no/a/")


class SharedSiteTests(unittest.TestCase):
    def _verified(self, url: str, html: str, proof: dict) -> SiteResult:
        s = site(url, html)
        s.proof = {"orgnr": None, "other_orgnrs": [], "phone": None, "email": None, "address": None, **proof}
        return s

    def test_a_dealer_page_on_a_chain_site_publishes_only_the_page(self):
        html = ("<html><head><title>Systemhus Østenfjeldske</title><meta name='description' content='Systemhus bygger hus'></head>"
                "<body><a href='https://www.facebook.com/systemhus'>Facebook</a> Østenfjeldske Bygg &amp; Entreprenør AS</body></html>")
        company = Company(org="952590340", name="ØSTENFJELDSKE BYGG & ENTREPRENØR AS")
        s = self._verified("https://www.systemhus.no/forhandlere/ostenfjeldske/", html, {})
        self.assertTrue(shared_site(company, s))
        ledger = Ledger(company.org)
        info = extract_site(ledger, company, s)
        self.assertTrue(info["shared"])
        self.assertEqual(ledger.first("official_website")["site_scope"], "shared_site")
        self.assertIsNone(ledger.first("social_profile"))
        self.assertIsNone(ledger.first("website_description"))

    def test_own_site_is_not_shared(self):
        company = Company(org="933792854", name="MÅSØVAL AS")
        self.assertFalse(shared_site(company, self._verified("https://www.masoval.no/", HOME, {})))
        # a group site printing another organisation number, without this company's own
        company = Company(org="984024924", name="HEGGSTADMOEN EIENDOM AS")
        self.assertTrue(shared_site(company, self._verified("https://trv.no/", "<html><body>TRV</body></html>",
                                                            {"other_orgnrs": ["937290658"]})))
        # but not when it prints this company's number
        self.assertFalse(shared_site(company, self._verified("https://trv.no/", "<html><body>TRV</body></html>",
                                                             {"orgnr": {"url": "u", "excerpt": "984 024 924", "value": "984 024 924"},
                                                              "other_orgnrs": ["937290658"]})))

    def test_orgnr_printed_with_spaces_becomes_an_identity_proof_claim(self):
        html = ("<html><head><title>Fram</title></head><body><h1>Frammuseet</h1><p>Polarskuta Fram og Gjøa på Bygdøy i Oslo. Åpent hver dag hele året.</p><footer>Frammuseet · Org.nr. 971 456 329</footer></body></html>")
        company = Company(org="971456329", name="STIFTELSEN TIL BEVARELSE AV POLARSKIBET FRAM")
        s = SiteResearcher(FakeFetcher({"https://frammuseum.no": lambda u: result(u, html.encode(), "text/html; charset=utf-8")})) \
            .research(company, Candidate("https://frammuseum.no", "registry_website", "strong"))
        self.assertEqual(s.state, "verified")
        ledger = Ledger(company.org)
        extract_site(ledger, company, s)
        self.assertEqual(ledger.first("website_identity_proof")["value"], "971 456 329")


class GroupSiteAndDemoTests(unittest.TestCase):
    def test_name_overlap(self):
        from signalpost.web import name_overlap
        self.assertTrue(name_overlap(Company(org="1", name="VEF ENTREPRENØR AS"), "www.vef.no"))
        self.assertTrue(name_overlap(Company(org="1", name="VARME & SANITÆR AS"), "www.v-s.no"))
        self.assertTrue(name_overlap(Company(org="1", name="FAMILIEKIROPRAKTOREN JÆREN AS"), "www.kiroklinikken.no"))
        self.assertTrue(name_overlap(Company(org="1", name="ADVOKATFIRMAET ØIVIND ØSTBERG AS"), "www.familierettadvokaten.no"))
        self.assertFalse(name_overlap(Company(org="1", name="HEGGSTADMOEN EIENDOM AS"), "trv.no"))
        self.assertFalse(name_overlap(Company(org="1", name="MARITIM RESEARCH I AS"), "www.mmanagement.no"))

    def test_group_site_without_the_name_in_its_domain_is_shared(self):
        s = site("https://trv.no/", "<html><body>TRV Gruppen · Heggstadmoen Eiendom AS</body></html>")
        s.proof = {"orgnr": None, "other_orgnrs": []}
        self.assertTrue(shared_site(Company(org="984024924", name="HEGGSTADMOEN EIENDOM AS"), s))

    def test_theme_demo_posts_after_the_sample_post_are_skipped(self):
        rss = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>The Land of The Vikings</title><link>https://ny.holokleros.no/2017/10/vikings/</link><pubDate>Sat, 14 Oct 2017 10:00:00 +0000</pubDate></item>
<item><title>Hello world!</title><link>https://ny.holokleros.no/2017/09/hello-world/</link><pubDate>Sun, 17 Sep 2017 10:00:00 +0000</pubDate></item>
<item><title>The Door In The Wall</title><link>https://ny.holokleros.no/2017/03/door/</link><pubDate>Tue, 14 Mar 2017 10:00:00 +0000</pubDate></item>
<item><title>Nye åpningstider i spaet</title><link>https://ny.holokleros.no/2019/05/apningstider/</link><pubDate>Wed, 01 May 2019 10:00:00 +0000</pubDate></item>
</channel></rss>"""
        html = HOME.replace("https://www.masoval.no/feed/", "https://ny.holokleros.no/feed/")
        fetcher = FakeFetcher({"https://ny.holokleros.no/feed/": lambda u: result(u, rss.encode(), "application/rss+xml")})
        posts = feed_posts(fetcher, Ledger("983939694"), site("https://ny.holokleros.no/", html), not_before="2001-11-01")
        self.assertEqual([p["title"] for p in posts], ["Nye åpningstider i spaet"])


class RenamedCompanyTests(unittest.TestCase):
    def test_a_former_name_in_the_domain_does_not_make_the_site_own(self):
        company = Company(org="984024924", name="HEGGSTADMOEN EIENDOM AS", aliases=["TRV GRUPPEN AS", "TRONDHEIM RENHOLDSVERK AS"])
        s = site("https://trv.no/", "<html><body>TRV Gruppen</body></html>")
        s.proof = {"orgnr": None, "other_orgnrs": []}
        self.assertTrue(shared_site(company, s))


class SharedSiteProfileTests(unittest.TestCase):
    def test_dealer_keeps_its_own_profile_but_not_the_chains(self):
        html = ("<html><head><title>Systemhus Østenfjeldske</title></head><body>"
                "<a href='https://www.facebook.com/systemhus'>Facebook</a>"
                "<a href='https://www.facebook.com/ostenfjeldskebygg'>Østenfjeldske Bygg på Facebook</a>"
                "<a href='https://www.instagram.com/systemhus'>Instagram</a>"
                "Østenfjeldske Bygg &amp; Entreprenør AS, Hamar</body></html>")
        company = Company(org="952590340", name="ØSTENFJELDSKE BYGG & ENTREPRENØR AS")
        s = site("https://www.systemhus.no/forhandlere/ostenfjeldske/", html)
        s.proof = {"orgnr": None, "other_orgnrs": []}
        ledger = Ledger(company.org)
        extract_site(ledger, company, s)
        self.assertEqual([c["normalized_url"] for c in ledger.by_field("social_profile")], ["https://www.facebook.com/ostenfjeldskebygg"])

    def test_manager_profile_sharing_one_word_is_not_kept(self):
        from signalpost.web import own_handle_on_shared_site
        company = Company(org="990468915", name="MARITIM RESEARCH I AS")
        self.assertFalse(own_handle_on_shared_site(company, "https://www.linkedin.com/company/maritim-management", "www.mmanagement.no"))

    def test_nynorsk_eigedom_is_generic(self):
        self.assertTrue(domain_match(Company(org="1", name="TORPOMOEN EIGEDOM AS"), "torpomoen.no")[1])


class RefreshRobustnessTests(unittest.TestCase):
    def test_copies_list_not_read_keeps_the_previous_documents(self):
        from signalpost.refresh import diff
        old = {"id": "c-1", "section": "accounts", "field": "annual_accounts_copy", "key": "annual_accounts_copy|2024", "value": "2024",
               "evidence_ids": ["ev-1"]}
        previous = {"run": {"run_id": "r1", "completed_at": "2026-10-23T10:00:00Z"}, "claims": [old]}
        changes, carried = diff({"claims": []}, previous, set(), {"annual_accounts_copy"})
        self.assertEqual(changes, [])
        self.assertEqual([c["carried_forward_from"] for c in carried], ["r1"])
        # and the next run that reads the list again reports no "new" document
        changes, _ = diff({"claims": [old]}, {"run": {"run_id": "r2"}, "claims": carried}, set())
        self.assertEqual(changes, [])

    def test_name_search_outage_is_not_a_rejection(self):
        html = ("<html><head><title>Supermercado</title></head><body><h1>Supermercado</h1><p>Spansk og latinamerikansk mat i Oslo. "
                "Vi har åpent hver dag og leverer til hele Norge.</p></body></html>")
        down = lambda u: failed(u, status=503, error="HTTP 503")  # noqa: E731
        answers = {"https://supermercado.no": lambda u: result(u, html.encode(), "text/html; charset=utf-8")}
        fetcher = FakeFetcher(answers)
        fetcher.get_original = fetcher.get

        def get(url, **kwargs):
            if "data.brreg.no" in url:
                return down(url)
            return fetcher.get_original(url, **kwargs)
        fetcher.get = get
        found = SiteResearcher(fetcher).research(Company(org="916361750", name="SUPERMERCADO AS", employees=3),
                                                 Candidate("https://supermercado.no", "domain_guess_from_legal_name", "weak"))
        self.assertEqual(found.state, "unreachable")
