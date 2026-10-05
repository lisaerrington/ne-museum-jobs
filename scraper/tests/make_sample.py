"""Builds a sample jobs.json from the offline fixtures (end-to-end test of scrape.main).

    python scraper/tests/make_sample.py  ->  writes /tmp/sample-jobs.json
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import scrape  # noqa: E402
from test_scrape import FakeResp  # noqa: E402

MAP = {
    "thebowesmuseum": "bowes.html",
    "aucklandproject": "auckland.html",
    "baltic.art": "baltic.html",
    "northeastmuseums": "nemuseums.html",
    "jobtrain": "jobtrain.html",
    "northeastjobs": "nejobs.xml",
    "artsjobs": "artsjobs.html",
    "jobs.ac.uk": "jobsacuk.html",
}


def fake_fetch(url, session):
    for k, f in MAP.items():
        if k in url:
            return FakeResp(f, url)
    raise ConnectionError("offline test – source not in fixtures")


scrape.fetch = fake_fetch
scrape.time.sleep = lambda s: None
scrape.OUT_FILE = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/sample-jobs.json")
if scrape.OUT_FILE.exists():
    scrape.OUT_FILE.unlink()
scrape.main([])
