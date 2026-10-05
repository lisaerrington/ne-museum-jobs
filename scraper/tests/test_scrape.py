"""Offline tests: run with  python -m pytest scraper/tests  (or python scraper/tests/test_scrape.py)."""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import scrape  # noqa: E402

FX = HERE / "fixtures"


class FakeResp:
    def __init__(self, path, url):
        self.content = (FX / path).read_bytes()
        self.text = self.content.decode("utf-8")
        self.url = url
        self.status_code = 200

    def raise_for_status(self):
        pass


def patch(path):
    scrape.fetch = lambda url, session: FakeResp(path, url)


def titles(jobs):
    return [j["title"] for j in jobs]


def test_bowes():
    jobs, st = scrape.extract_page((FX / "bowes.html").read_text(), "https://thebowesmuseum.org.uk/jobs-and-volunteering/")
    t = titles(jobs)
    assert "Catering Assistant" in t, t
    assert not any("VISIT" in x or "SUPPORT" in x for x in t), t
    cat = next(j for j in jobs if j["title"] == "Catering Assistant")
    assert cat["url"].endswith("/catering-assistant/"), cat["url"]
    assert "12.71" in cat["salary"], cat


def test_auckland():
    jobs, st = scrape.extract_page((FX / "auckland.html").read_text(), "https://aucklandproject.org/support-us/jobs/")
    t = titles(jobs)
    assert t == ["Facilities Assistant"], t
    assert jobs[0]["url"].endswith(".pdf"), jobs[0]


def test_baltic():
    jobs, st = scrape.extract_page((FX / "baltic.html").read_text(), "https://baltic.art/jobs-and-volunteering/")
    t = titles(jobs)
    assert "Hires and Events Manager" in t, t
    assert "Birds, Bees, Bikes and Trees Evaluator (Young People)" in t, t
    assert not any("Artist in Residence" in x or "Open Call" in x for x in t), t
    assert not any(x.endswith(":") or "3.6million" in x for x in t), t
    h = next(j for j in jobs if j["title"] == "Hires and Events Manager")
    assert h["closing"] == "2026-10-12", h


def test_ne_museums_none():
    jobs, st = scrape.extract_page((FX / "nemuseums.html").read_text(), "https://www.northeastmuseums.org.uk/about/jobs")
    assert jobs == [], titles(jobs)
    assert st["no_vacancies"]


def test_cathedral_no_duplicates():
    jobs, _ = scrape.extract_page((FX / "cathedral.html").read_text(), "https://www.durhamcathedral.co.uk/more/jobs")
    assert sorted(titles(jobs)) == ["Chief Property Officer", "Learning & Engagement Administrator"], titles(jobs)
    assert all("/more/jobs/" in j["url"] for j in jobs)


def test_region_postcodes():
    assert not scrape.NE_PLACE_RE.search("Mount Grace Priory, Saddle Bridge, Northallerton, DL6 3JG")
    assert scrape.NE_PLACE_RE.search("Bessie Surtees House, Sandhill, NE1 3JF")
    assert scrape.NE_PLACE_RE.search("Barnard Castle DL12 8NP")


def test_jobtrain():
    patch("jobtrain.html")
    jobs, _ = scrape.handle_jobtrain({"url": "https://www.jobtrain.co.uk/beamishmuseum"}, None)
    assert titles(jobs) == ["Food and Beverage Stock Controller", "Metal Fabricator Apprentice (Fixed Term)"]
    assert jobs[0]["url"] == "https://www.jobtrain.co.uk/beamishmuseum/Job/JobDetail?JobId=157"
    assert jobs[0]["salary"] == "£28,494"
    assert jobs[1]["closing"] == "2026-10-10"


def test_nejobs_rss_and_filter():
    patch("nejobs.xml")
    src = {"id": "northeastjobs", "url": "x", "museum": False}
    raw, _ = scrape.handle_rss(src, None)
    kept = scrape.filter_jobs(src, raw)
    t = titles(kept)
    assert "Catering Assistant (Preston Park)" in t and "Learning Coordinator" in t, t
    assert "Care Assistant" not in t
    assert not any("Abbey Hill" in x or "Positive Journeys" in x for x in t), t
    pp = next(j for j in kept if j["title"].startswith("Catering"))
    assert pp["closing"] == "2026-10-20" and pp["salary"] == "£24,027", pp
    lc = next(j for j in kept if j["title"] == "Learning Coordinator")
    assert lc["org"] == "North East Museums", lc


def test_listing_artsjobs():
    patch("artsjobs.html")
    src = {"id": "artsjobs", "url": "https://www.artsjobs.org.uk/jobs/search", "item": ".listing-copy-wrapper",
           "title": "h2 a", "org": ".job__organisation-name", "location": ".job__region-england",
           "salary": ".job__job-salary-band", "closing": ".job__job-closing-date", "summary": ".job__body", "museum": False}
    raw, _ = scrape.handle_listing(src, None)
    assert len(raw) == 2
    kept = scrape.filter_jobs(src, raw)
    assert titles(kept) == ["Exhibitions Officer"], titles(kept)
    assert kept[0]["closing"] == "2026-10-30"


def test_listing_jobsacuk_region():
    patch("jobsacuk.html")
    src = {"id": "jobsacuk", "url": "https://www.jobs.ac.uk/search/", "item": ".j-search-result__text", "title": "a",
           "org": ".j-search-result__employer", "department": ".j-search-result__department",
           "location_regex": r"Location:\s*([^\n]+)", "salary_regex": r"Salary:\s*([^\n]+)", "museum": False, "region": True}
    raw, _ = scrape.handle_listing(src, None)
    kept = scrape.filter_jobs(src, raw)
    ne = [j for j in kept if not j["wider"]]
    assert titles(ne) == ["Collections Assistant (NLHF Engagement)"], [(j["title"], j["location"]) for j in kept]
    assert ne[0]["location"] == "Durham"


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("PASS", name)
            except AssertionError as e:
                fails += 1
                print("FAIL", name, e)
    sys.exit(1 if fails else 0)
