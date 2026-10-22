"""Offline tests for v1.2.0: other spellings of the same site (www / apex / root) after a failure that says nothing
about the site, never after a refusal. Run: python -m unittest discover -s tests"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signalpost.net import FetchResult  # noqa: E402
from signalpost.web import Candidate, Company, SiteResearcher, alternate_urls, recoverable_failure  # noqa: E402

ORG = "925854743"
PAGE = ("<html><head><title>Bjelk</title></head><body><h1>Bjelk</h1>"
        "<footer>Bjelk AS · Org.nr. 925 854 743 · Oslo</footer></body></html>")


def ok(url: str) -> FetchResult:
    return FetchResult(url=url, final_url=url, status=200, content_type="text/html; charset=utf-8", body=PAGE.encode(),
                       text=PAGE, sha256="a" * 64, retrieved_at="2026-10-22T00:00:00Z")


def failed(url: str, *, status=None, error="", blocked=False) -> FetchResult:
    return FetchResult(url=url, final_url=url, status=status, error=error, blocked=blocked, retrieved_at="2026-10-22T00:00:00Z")


class FakeFetcher:
    def __init__(self, answers):
        self.answers = answers
        self.calls: list[str] = []

    def get(self, url, **_kwargs):
        self.calls.append(url)
        answer = self.answers.get(url) or self.answers.get(url.rstrip("/"))
        return answer(url) if answer else failed(url, error="URLError: timed out")


class AlternateSpellingTests(unittest.TestCase):
    def test_which_failures_are_recoverable(self):
        self.assertTrue(recoverable_failure(failed("u", error="unsafe_url: hostname did not resolve", blocked=True)))
        self.assertTrue(recoverable_failure(failed("u", error="URLError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")))
        self.assertTrue(recoverable_failure(failed("u", error="URLError: timed out")))
        self.assertTrue(recoverable_failure(failed("u", status=404, error="HTTP 404")))
        self.assertFalse(recoverable_failure(failed("u", error="robots.txt disallows this URL", blocked=True)))
        self.assertFalse(recoverable_failure(failed("u", error="unsafe_url: non-public address blocked", blocked=True)))
        for refusal in (401, 403, 429):
            self.assertFalse(recoverable_failure(failed("u", status=refusal, error=f"HTTP {refusal}")))

    def test_alternates_stay_on_the_same_registrable_domain(self):
        self.assertEqual(alternate_urls("https://mossbilverksted.no"), ["https://www.mossbilverksted.no/"])
        self.assertEqual(alternate_urls("https://www.fjellstova.com"), ["https://fjellstova.com/"])
        self.assertEqual(alternate_urls("https://www.paradigma.no/gammel/side.html"),
                         ["https://www.paradigma.no/", "https://paradigma.no/"])
        self.assertEqual(alternate_urls("https://pdi.trading.no"), ["https://www.pdi.trading.no/"])
        self.assertEqual(alternate_urls("not a url"), [])

    def _research(self, answers, url="https://bjelk.no", strength="weak"):
        fetcher = FakeFetcher(answers)
        researcher = SiteResearcher(fetcher)  # type: ignore[arg-type]
        researcher._name_unique = lambda company, words=None: False  # type: ignore[assignment]
        result = researcher.research(Company(org=ORG, name="BJELK AS"), Candidate(url, "domain_guess_from_legal_name", strength))
        return result, fetcher.calls

    def test_dns_failure_on_apex_falls_back_to_www_and_still_needs_proof(self):
        result, calls = self._research({
            "https://bjelk.no": lambda u: failed(u, error="unsafe_url: hostname did not resolve", blocked=True),
            "https://www.bjelk.no/": ok,
        })
        self.assertEqual(result.state, "verified")
        self.assertEqual(result.reason, "organisation number shown on the site")
        self.assertEqual(result.home_url, "https://www.bjelk.no/")
        self.assertIn("https://www.bjelk.no/", calls)

    def test_robots_refusal_is_never_retried_under_another_spelling(self):
        result, calls = self._research({
            "https://bjelk.no": lambda u: failed(u, error="robots.txt disallows this URL", blocked=True),
            "https://www.bjelk.no/": ok,
        })
        self.assertEqual(result.state, "blocked")
        self.assertNotIn("https://www.bjelk.no/", calls)

    def test_http_refusal_is_never_retried_under_another_spelling(self):
        result, calls = self._research({
            "https://bjelk.no": lambda u: failed(u, status=403, error="HTTP 403"),
            "https://www.bjelk.no/": ok,
        })
        self.assertEqual(result.state, "blocked")
        self.assertNotIn("https://www.bjelk.no/", calls)

    def test_refusal_on_the_alternate_is_reported_as_blocked(self):
        result, _ = self._research({
            "https://bjelk.no": lambda u: failed(u, error="URLError: timed out"),
            "https://www.bjelk.no/": lambda u: failed(u, error="robots.txt disallows this URL", blocked=True),
        })
        self.assertEqual(result.state, "blocked")

    def test_both_spellings_down_stays_unreachable(self):
        result, _ = self._research({
            "https://bjelk.no": lambda u: failed(u, error="URLError: timed out"),
        })
        self.assertEqual(result.state, "unreachable")


class SmallCompanyTests(unittest.TestCase):
    def test_activity_tiers(self):
        from signalpost.agent import Agent
        tier = Agent._activity_tier
        self.assertEqual(tier(Company(org=ORG, name="BJELK AS", employees=2)), "operating")
        self.assertEqual(tier(Company(org=ORG, name="BJELK AS", revenue=1_500_000)), "operating")
        self.assertEqual(tier(Company(org=ORG, name="BJELK AS", revenue=300_000)), "small")
        self.assertIsNone(tier(Company(org=ORG, name="BJELK AS", revenue=20_000)))
        self.assertIsNone(tier(Company(org=ORG, name="BJELK HOLDING AS", revenue=5_000_000)))
        self.assertIsNone(tier(Company(org=ORG, name="BJELK AS", revenue=5_000_000, industry="68.209")))

    def _decide(self, note, **proof):
        base = {"orgnr": None, "other_orgnrs": [], "phone": None, "email": None, "address": None, "name_identity": {"url": "u"},
                "name_anywhere": None, "domain_name": None, "legal_name_exact": None, "norwegian_context": True}
        base.update(proof)
        researcher = SiteResearcher(fetcher=None)  # type: ignore[arg-type]
        researcher._name_unique = lambda company, words=None: True  # type: ignore[assignment]
        return researcher._decide(Company(org=ORG, name="BJELK AS"), Candidate("https://bjelk.no", "domain_guess_from_legal_name",
                                                                             "weak", note), base, "bjelk.no")

    def test_unique_name_alone_verifies_an_operating_company_but_not_a_small_one(self):
        from signalpost.web import LOW_ACTIVITY
        self.assertEqual(self._decide("")[0], "verified")
        self.assertEqual(self._decide(LOW_ACTIVITY)[0], "rejected")

    def test_small_company_still_verified_by_orgnr_or_registered_contact(self):
        from signalpost.web import LOW_ACTIVITY
        self.assertEqual(self._decide(LOW_ACTIVITY, orgnr={"url": "u", "excerpt": "Org.nr. 925 854 743"})[0], "verified")
        self.assertEqual(self._decide(LOW_ACTIVITY, phone={"url": "u", "digits": "92630552"})[0], "verified")

    def test_brand_separators_are_dropped(self):
        from signalpost.web import clean_brand
        self.assertEqual(clean_brand("Tonemakeriet |"), "Tonemakeriet")
        self.assertEqual(clean_brand("– Bjelk –"), "Bjelk")
        self.assertEqual(clean_brand("Vin & Medisin"), "Vin & Medisin")


if __name__ == "__main__":
    unittest.main()


class SharedNameTests(unittest.TestCase):
    """Precision fixes found by hand review of the 1,000-company batch (22 Oct)."""

    def test_foreign_company_with_the_same_name(self):
        from signalpost.web import foreign_form_hit
        self.assertEqual(foreign_form_hit("KRISS CONSULTING AS", "Kriss Consulting Inc Home Services About Us"),
                         "kriss consulting inc")
        self.assertIsNone(foreign_form_hit("ELINAR OY LTD NUF", "Elinar Oy Ltd, document AI"))  # a NUF keeps its own form
        self.assertIsNone(foreign_form_hit("HANSEN BYGG AS", "© Hansen Bygg AS 2024"))

    def test_lang_attribute_alone_is_not_norwegian_context(self):
        from signalpost.web import looks_norwegian
        self.assertTrue(looks_norwegian("Vi er et lite firma som har levert tjenester til kunder. Kontakt oss på telefon."))
        self.assertFalse(looks_norwegian("We innovate business solutions in the IT industry and implement them for customers."))

    def _research(self, html, url="https://www.kriss-consulting.com/", name="KRISS CONSULTING AS", unique=True, lang_no=True):
        page = html if not lang_no else html.replace("<html>", '<html lang="no">')

        def answer(u):
            return FetchResult(url=u, final_url=u, status=200, content_type="text/html", body=page.encode(), text=page,
                               sha256="b" * 64, retrieved_at="2026-10-22T00:00:00Z")
        fetcher = FakeFetcher({url: answer, url.rstrip("/"): answer})
        researcher = SiteResearcher(fetcher)  # type: ignore[arg-type]
        researcher._name_unique = lambda company, words=None: unique  # type: ignore[assignment]
        return researcher.research(Company(org="826756152", name=name, city="KRISTIANSAND S", postcode="4624"),
                                   Candidate(url, "domain_guess_from_legal_name", "weak"))

    def test_kriss_consulting_inc_is_rejected(self):
        html = ("<html><head><title>Kriss Consulting Inc</title></head><body><h1>Kriss Consulting Inc</h1>"
                "<p>We innovate business solutions in the IT industry. We are pioneers in developing IT solutions.</p></body></html>")
        result = self._research(html)
        self.assertEqual(result.state, "rejected")
        self.assertIn("another legal form", result.reason)

    def test_english_page_with_lang_no_and_unique_name_is_not_enough(self):
        html = ("<html><head><title>Kriss Consulting</title></head><body><h1>Kriss Consulting</h1>"
                "<p>We innovate business solutions in the IT industry. We are pioneers in developing IT solutions.</p></body></html>")
        self.assertEqual(self._research(html).state, "rejected")

    def test_web_host_default_page_is_parked(self):
        html = ("<html><head><title>lekeplassmontorene.no -- This domain is hosted by NordkappNett</title></head><body>"
                "lekeplassmontorene.no -- This domain is hosted by NordkappNett AS. Phone: (+47) 7847 1100</body></html>")
        result = self._research(html, url="http://lekeplassmontorene.no", name="LEKEPLASSMONTØRENE AS")
        self.assertEqual(result.state, "parked")

    def test_group_brand_domain_needs_the_distinctive_words_to_be_unique(self):
        calls = []
        researcher = SiteResearcher(fetcher=None)  # type: ignore[arg-type]

        def unique(company, words=None):
            calls.append(words)
            return False
        researcher._name_unique = unique  # type: ignore[assignment]
        proof = {"orgnr": None, "other_orgnrs": [], "phone": None, "email": None, "address": None, "name_identity": {"url": "u"},
                 "name_anywhere": None, "domain_name": None, "legal_name_exact": None, "norwegian_context": True}
        state, _, _ = researcher._decide(Company(org="932561158", name="LEGENTIC SERVICES AS"),
                                         Candidate("https://legentic.com", "domain_guess_from_legal_name", "weak"), proof, "legentic.com")
        self.assertEqual(calls, [["legentic"]])  # "services" is generic: the domain only matched "legentic"
        self.assertEqual(state, "rejected")
