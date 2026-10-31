"""Offline tests for 1.5.0: domains registered with the legal form ("<name>as.no", ".as"), a parent heading an operating
group counts as operating, and the summary wording fixed after linting 2,000 summaries.
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

from signalpost import agent as agent_mod  # noqa: E402
from signalpost.agent import Agent, Work  # noqa: E402
from signalpost.ledger import Ledger  # noqa: E402
from signalpost.synth import _sentence  # noqa: E402
from signalpost.web import Company, domain_match  # noqa: E402
from signalpost.web import Candidate, SiteResearcher  # noqa: E402
from test_v4 import FakeFetcher, failed, result  # noqa: E402
from test_v5 import OverviewTests, year  # noqa: E402


class LegalFormDomainTests(unittest.TestCase):
    def test_name_plus_legal_form_spells_the_whole_name(self):
        self.assertEqual(domain_match(Company(org="1", name="MARINOR AS", legal_form="AS"), "www.marinoras.no"), (True, True))
        self.assertEqual(domain_match(Company(org="1", name="REMME BYGG AS", legal_form="AS"), "remme-bygg-as.no"), (True, True))
        self.assertEqual(domain_match(Company(org="1", name="PROCONSULT AS", legal_form="AS"), "proconsult.as"), (True, True))

    def test_the_suffix_rule_needs_the_legal_form_and_the_whole_name(self):
        # Without the legal form (or for another form) "as" is just letters of the label.
        self.assertEqual(domain_match(Company(org="1", name="MARINOR SA", legal_form="SA"), "marinoras.no"), (True, True))  # substring rule
        self.assertEqual(domain_match(Company(org="1", name="AIDA SA", legal_form="SA"), "aidaas.no"), (False, False))
        self.assertEqual(domain_match(Company(org="1", name="AIDA AS", legal_form="AS"), "aidaas.no"), (True, True))
        # A different name before "as" does not match, and very short names are left alone.
        self.assertEqual(domain_match(Company(org="1", name="AIDA AS", legal_form="AS"), "aidobas.no"), (False, False))
        self.assertEqual(domain_match(Company(org="1", name="VIK AS", legal_form="AS"), "vikas.no"), (False, False))

    def _candidates(self, name: str, legal_form: str, resolvable: set[str], revenue: float = 5_000_000) -> list[str]:
        agent = Agent(run_id="t", snapshot_dir=None, cache_dir=None, workers=1, use_search=False, log=lambda *a: None)
        work = Work("123456789", Ledger("123456789"))
        work.company = Company(org="123456789", name=name, legal_form=legal_form, revenue=revenue, industry="41.000")
        work.entity = {}
        with mock.patch.object(agent_mod, "resolve", side_effect=lambda host: ["1.2.3.4"] if host in resolvable else None), \
                mock.patch.object(agent.nav, "homepages", return_value=[]):
            return [c.url for c in agent.candidates(work)]

    def test_an_as_gets_legal_form_domain_guesses(self):
        urls = self._candidates("MARINOR AS", "AS", {"marinoras.no", "marinor.as"})
        self.assertIn("https://marinoras.no", urls)
        self.assertIn("https://marinor.as", urls)

    def test_other_forms_do_not(self):
        self.assertEqual(self._candidates("MARINOR SA", "SA", {"marinoras.no", "marinor.as"}), [])


SALTEK_HOME = ("<html><head><title>Saltek – SALTEK AS, based in Ulsteinvik</title></head><body><h1>Saltek</h1>"
               "<footer>Kontakt Saltek AS Postboks 5 6067 Ulsteinvik E-post: as@saltek.no</footer></body></html>")
BRREG = "https://data.brreg.no/enhetsregisteret/api/{kind}?hjemmeside={domain}&size=100"


def brreg_answer(kind: str, items: list[dict]):
    body = json.dumps({"_embedded": {kind: items}} if items else {"page": {"totalElements": 0}}).encode("utf-8")
    return lambda url: result(url, body, "application/json")


class RegisteredOwnerTests(unittest.TestCase):
    """A site inferred from a shared e-mail domain is checked against the register's website field before it is published."""
    company = Company(org="993234966", name="SALTEK HOLDING AS", legal_form="AS", emails={"as@saltek.no"}, aliases=["SALTEK AS"])

    def research(self, home: str, enheter: list[dict] | None, underenheter: list[dict] | None = None):
        answers = {"https://saltek.no": lambda url: result(url, home.encode("utf-8"), "text/html; charset=UTF-8")}
        if enheter is not None:
            answers[BRREG.format(kind="enheter", domain="saltek.no")] = brreg_answer("enheter", enheter)
            answers[BRREG.format(kind="underenheter", domain="saltek.no")] = brreg_answer("underenheter", underenheter or [])
        fetcher = FakeFetcher(answers)
        found = SiteResearcher(fetcher).research(self.company, Candidate("https://saltek.no", "registry_email_domain", "medium"))
        return found, fetcher

    def test_the_sister_company_that_registered_the_site_keeps_it(self):
        found, _ = self.research(SALTEK_HOME, [{"organisasjonsnummer": "913207521", "navn": "SALTEK AS", "hjemmeside": "www.saltek.no"}])
        self.assertEqual(found.state, "related")
        self.assertIn("913207521", found.reason)

    def test_a_site_nobody_else_registered_is_still_verified(self):
        found, fetcher = self.research(SALTEK_HOME, [{"organisasjonsnummer": "913207999", "navn": "NOSALTEK AS",
                                                      "hjemmeside": "www.nosaltek.no"}],
                                       [{"organisasjonsnummer": "973000001", "navn": "SALTEK HOLDING AS AVD X",
                                         "overordnetEnhet": "993234966", "hjemmeside": "saltek.no"}])
        self.assertEqual(found.state, "verified")
        self.assertTrue(any("hjemmeside=saltek.no" in call for call in fetcher.calls))

    def test_a_nuf_owns_the_site_of_the_foreign_company_it_registers(self):
        nuf = Company(org="927475545", name="MANSOFT", legal_form="NUF", emails={"regnskab@mansoft.dk"})
        home = ("<html><head><title>Mansoft – IT-drift og Microsoft 365 for små og mellemstore virksomheder</title></head><body>"
                "<h1>Mansoft</h1><p>Vi hjælper virksomheder med IT-drift, sikkerhed og Microsoft 365 i Danmark og Norge.</p>"
                "<footer>Kontakt Mansoft A/S, Lyngbyvej 2, 2100 København, regnskab@mansoft.dk</footer></body></html>")
        answers = {"https://mansoft.dk": lambda url: result(url, home.encode("utf-8"), "text/html; charset=UTF-8"),
                   BRREG.format(kind="enheter", domain="mansoft.dk"): brreg_answer("enheter", [
                       {"organisasjonsnummer": "927579235", "navn": "MANSOFT A/S", "organisasjonsform": {"kode": "UTLA"},
                        "hjemmeside": "www.mansoft.dk"}]),
                   BRREG.format(kind="underenheter", domain="mansoft.dk"): brreg_answer("underenheter", [])}
        candidate = Candidate("https://mansoft.dk", "registry_email_domain", "medium")
        found = SiteResearcher(FakeFetcher(answers)).research(nuf, candidate)
        self.assertEqual(found.state, "verified")
        # the same site is still someone else's for a Norwegian AS that happens to share the e-mail domain
        other = Company(org="999999999", name="MANSOFT NORGE AS", legal_form="AS", emails={"regnskab@mansoft.dk"})
        self.assertEqual(SiteResearcher(FakeFetcher(answers)).research(other, candidate).state, "related")

    def test_no_answer_from_the_register_is_not_a_verification(self):
        found, _ = self.research(SALTEK_HOME, None)
        self.assertEqual(found.state, "unreachable")
        self.assertIn("did not answer", found.reason)

    def test_the_organisation_number_on_the_site_needs_no_lookup(self):
        home = SALTEK_HOME.replace("</footer>", " Org.nr. 993 234 966</footer>")
        found, fetcher = self.research(home, [{"organisasjonsnummer": "913207521", "navn": "SALTEK AS", "hjemmeside": "www.saltek.no"}])
        self.assertEqual(found.state, "verified")
        self.assertFalse(any("hjemmeside=" in call for call in fetcher.calls))


class GroupRevenueTierTests(unittest.TestCase):
    def test_a_parent_heading_an_operating_group_is_operating(self):
        self.assertEqual(Agent._activity_tier(Company(org="1", name="MEASURE IT AS", revenue=158_161_385, industry="26.510")), "operating")
        self.assertIsNone(Agent._activity_tier(Company(org="1", name="MEASURE IT AS", revenue=None, industry="26.510")))


class SummaryWordingTests(OverviewTests):
    def test_a_change_that_rounds_to_zero_is_almost_unchanged(self):
        _, s = self.summary([year(2025, 100_020, 5_000, 100_000, 200_000), year(2024, 100_000, 5_000, 90_000, 190_000)])
        overview = " ".join(s["parts"]["overview"])
        self.assertIn("had revenue of NOK 100 k, almost unchanged on 2024", overview)
        money = " ".join(s["parts"]["money"])
        self.assertIn("revenue of NOK 100 k (almost unchanged from 2024)", money)
        self.assertNotRegex(s["text"], r"(up|down) 0\.0%")
        self.assertIn("revenue was almost unchanged at NOK 100 k", " ".join(s["parts"]["what_changed"]))
        self.assertEqual(s["dropped_unsupported_sentences"], 0)

    def test_identical_revenue_is_unchanged_in_every_part(self):
        _, s = self.summary([year(2025, 144_000, 9_000, 100_000, 200_000), year(2024, 144_000, 8_000, 90_000, 190_000)])
        self.assertIn("revenue of NOK 144 k (unchanged from 2024)", " ".join(s["parts"]["money"]))

    def test_break_even_is_not_called_a_profit(self):
        _, s = self.summary([year(2025, 0, -15_000, -20_000, 48_000), year(2024, 0, 0, -5_000, 50_000)])
        changed = " ".join(s["parts"]["what_changed"])
        self.assertIn("the operating result went from break-even (NOK 0) to a loss of NOK 15 k", changed)
        self.assertNotIn("profit of NOK 0", s["text"])
        self.assertIn("show no revenue (NOK 0)", " ".join(s["parts"]["money"]))
        _, s = self.summary([year(2025, 500_000, 0, 20_000, 48_000), year(2024, 450_000, 7_000, 5_000, 50_000)])
        self.assertIn("the operating result went from a profit of NOK 7 k to break-even (NOK 0)", " ".join(s["parts"]["what_changed"]))
        self.assertEqual(s["dropped_unsupported_sentences"], 0)

    def test_an_ambiguous_website_says_why_without_naming_the_other_company(self):
        for note, words in (("https://www.saltek.no/: the register lists this website for another organisation (913207521)",
                             "listed in the register as another organisation's website"),
                            ("https://www.usbl.no: registered website shares the company's contact details but names another "
                             "business (group/manager site)", "shares the company's contact details but names another business"),
                            ("https://x.no: site shows another organisation number (992795808)", "prints another organisation number")):
            _, s = self.summary([year(2025, 500_000, 7_000, 20_000, 48_000)],
                                states={"website": "ambiguous", "hiring": "not_available"}, notes={"website": note})
            gap = next(t for t in s["parts"]["unknown"] if "a verified website" in t)
            self.assertTrue(gap.startswith("Ambiguous: a verified website ("), gap)
            self.assertIn(words, gap)
            self.assertNotIn("http", gap)
            self.assertNotRegex(gap, r"\d{9}")

    def test_a_name_ending_in_a_full_stop_closes_the_sentence(self):
        self.assertEqual(_sentence("Its registered parent is CANON EUROPE N.V..", [])["text"], "Its registered parent is CANON EUROPE N.V.")
        self.assertEqual(_sentence("It says: “more to come...”", [])["text"], "It says: “more to come...”")


class TitleTests(unittest.TestCase):
    def test_icon_titles_inside_inline_svg_are_not_the_page_title(self):
        from signalpost.html import parse_html
        page = parse_html("<html><head><title>Reisebyrået med ekstra service - Travelmate</title></head><body><a href='/f'>"
                          "<svg><title>Facebook icon</title></svg></a><svg><title>Instagram icon</title></svg><p>Hei</p></body></html>",
                          "https://travelmate.no/")
        self.assertEqual(page.title, "Reisebyrået med ekstra service - Travelmate")


class PersonalHandleTests(unittest.TestCase):
    def test_a_role_holders_own_page_is_not_a_company_profile(self):
        from signalpost.web import personal_handle
        kiil = Company(org="1", name="KIIL MGMT AS", people=["Dennis Kiil", "AS REVISION"])
        self.assertTrue(personal_handle(kiil, "https://www.instagram.com/denniskiil/"))
        self.assertFalse(personal_handle(kiil, "https://www.instagram.com/kiilmgmt/"))
        aarum = Company(org="1", name="INGENIØR- OG MURFIRMA LARS AARUM AS", people=["Lars Aarum"])
        self.assertFalse(personal_handle(aarum, "https://www.facebook.com/LarsAarum"))


class TestPostTests(unittest.TestCase):
    def test_a_post_published_to_try_the_site_is_not_activity(self):
        from signalpost.web import test_post
        self.assertTrue(test_post("TEst 2 – hubspot"))
        self.assertTrue(test_post("Testinnlegg"))
        self.assertFalse(test_post("Test av ny elbil fra Tesla i Norge"))
        self.assertFalse(test_post("Kontrollert og testet"))
        self.assertFalse(test_post("Testing av lekeplass"))


class TooManyRequestsTests(unittest.TestCase):
    """HTTP 429 from a shop platform is a request to slow down: wait and ask again (twice at most), but leave the
    register's paced endpoints to their own pacer."""
    def fetch(self, url, answers):
        from signalpost import net
        fetcher = net.Fetcher()
        calls = []

        def raw_get(u, **_kw):
            calls.append(u)
            status = answers.pop(0)
            return net.FetchResult(url=u, final_url=u, status=status, error=None if status == 200 else f"HTTP {status}",
                                   body=b"<html>ok</html>" if status == 200 else b"", text="", retrieved_at="2026-10-31T00:00:00Z")
        with mock.patch.object(fetcher, "_raw_get", side_effect=raw_get), mock.patch.object(net.time, "sleep") as sleep:
            result = fetcher.get(url, retries=0, snapshot=False)
        return result, calls, sleep

    def test_a_shop_that_asks_us_to_slow_down_is_asked_again(self):
        result, calls, sleep = self.fetch("https://kenslastudio.com/", [429, 200])
        self.assertEqual(result.status, 200)
        self.assertEqual(len(calls), 2)
        sleep.assert_called_once_with(3.0)

    def test_it_gives_up_after_two_more_tries(self):
        result, calls, _ = self.fetch("https://kenslastudio.com/", [429, 429, 429, 200])
        self.assertEqual(result.status, 429)
        self.assertEqual(len(calls), 3)

    def test_the_registers_paced_endpoints_are_left_to_their_pacer(self):
        result, calls, _ = self.fetch("https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/1/aar", [429, 200])
        self.assertEqual(result.status, 429)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
