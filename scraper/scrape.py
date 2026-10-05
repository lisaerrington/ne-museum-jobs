#!/usr/bin/env python3
"""
North East museum jobs scraper.

Reads sources.yaml, visits every source, pulls out vacancies, and writes
docs/data/jobs.json, which the website reads.

Run locally:   python scraper/scrape.py
Test one:      python scraper/scrape.py --only bowes --verbose
"""

from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup, Tag
from dateutil import parser as dateparser

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "scraper" / "sources.yaml"
OUT_FILE = ROOT / "docs" / "data" / "jobs.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 NE-Museum-Jobs-Bot "
        "(personal job search; github.com)"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = 30
STALE_DAYS = 4  # keep a failed source's old jobs this long before dropping them

# ---------------------------------------------------------------------------
# Keyword lists
# ---------------------------------------------------------------------------

# A job counts as museum/heritage if any of these appear (for general boards).
HERITAGE_RE = re.compile(
    r"\b(museums?|heritage|galler(y|ies)|archiv(e|es|ist|al)|curat(or|orial|e)|"
    r"collections? (assistant|officer|manager|care|management|team|and|&)|conservat(or|ion)|"
    r"exhibitions?|historic (house|building|site|environment|england)|history centre|"
    r"durham cathedral|alnwick castle|bamburgh castle|auckland castle|lindisfarne|"
    r"roman fort|visitor (experience|services|assistant|host)|sunderland culture|"
    r"learning (officer|assistant|coordinator|co-ordinator)|arts? centre|"
    r"preston park|dorman|head of steam|kirkleatham|captain cook|laing|discovery museum|"
    r"great north museum|hancock|hatton|shipley|segedunum|arbeia|woodhorn|"
    r"hexham old gaol|jarrow hall|customs house|beamish|locomotion|bowes|killhope|"
    r"durham history centre|dli|oriental museum|palace green|ngca|national glass|"
    r"sunderland museum|winter gardens|stewart park|middlesbrough theatre)\b",
    re.I,
)

# Words that show a bit of text is a job title.
ROLE_RE = re.compile(
    r"\b(officer|assistant|manager|curator|co-?ordinator|director|lead|head of|"
    r"technician|conservator|archivist|producer|administrator|apprentice(ship)?|"
    r"intern(ship)?|trainee|guide|host|executive|engineer|developer|fundraiser|"
    r"chef|cook|steward|supervisor|team member|team leader|keeper|registrar|"
    r"librarian|educator|facilitator|specialist|analyst|advis[eo]r|designer|"
    r"planner|trustee|crew|attendant|warden|ranger|associate|fellow(ship)?|"
    r"researcher|consultant|evaluator|freelance|cleaner|porter|gardener|"
    r"housekeeper|receptionist|accountant|clerk|chair|secretary|operative|"
    r"maintenance|controller|bookkeeper|buyer|barista|caretaker|handyperson|"
    r"joiner|electrician|fabricator|demonstrator|interpreter|animator|"
    r"programmer|photographer|digitis(er|ation)|cataloguer|commission|champions?|"
    r"vacancy|role)\b",
    re.I,
)

# Bits of text that look like job words but aren't vacancies.
NOT_A_JOB_RE = re.compile(
    r"^(jobs?|careers?|vacanc(y|ies)|current vacancies|work (for|with) us|"
    r"job (description|profile|pack)|application form|apply( now| here)?|"
    r"how to apply|staff benefits|our benefits|volunteer(ing)?( opportunities)?|"
    r"more|more\.\.|read more|find out more|learn more|view|view job|details|"
    r"download.*|privacy.*|cookie.*|recruitment privacy notice|"
    r"equal opportunities.*|living wage employer|disability confident.*|"
    r"armed forces covenant|frequently asked questions|faqs?|contact us|"
    r"sign in|log ?in|register|create an account|job alerts?|get alerts|"
    r"advanced search|search jobs|list vacancies|board of trustees|"
    r"meet the team|our team|our people|about us|"
    r"jobs and volunteering|jobs & opportunities|jobs and opportunities)$",
    re.I,
)

# Links pointing here are news, events, shop… not jobs.
NON_JOB_PATH_RE = re.compile(
    r"/(news[^/]*|blog[^/]*|press[^/]*|events?|whats-on|what-s-on|exhibitions?|shop|visit|"
    r"venue-hire|weddings?|tickets?|donate|membership|collections?/object)(/|$)",
    re.I,
)

# Links that look like they lead to a specific vacancy.
JOB_LINK_RE = re.compile(
    r"(jobdetail|job-detail|/jobs?/[^/]+|/vacanc(y|ies)/[^/]+|requirementid=|"
    r"applyform|/careers?/[^/]+|jid=|jobid=|\.pdf$|\.docx?$|submittable|"
    r"jobtrain|applytojob|teamtailor|workable|recruitee|bamboohr|"
    r"pinpointhq|hirehive|eploy|webitrent|tal\.net|amrislive)",
    re.I,
)

NO_VACANCIES_RE = re.compile(
    r"(no (current )?vacancies|not currently recruiting|no current (job|opportunit)|"
    r"no (jobs|positions|roles) (are )?(currently )?(available|advertised)|"
    r"there are (currently )?no (vacancies|jobs|opportunities|positions)|"
    r"no opportunities at (the moment|present)|check back (soon|later))",
    re.I,
)

# Places that make a job "North East".
NE_PLACE_RE = re.compile(
    r"\b(newcastle|gateshead|sunderland|south shields|north shields|tynemouth|"
    r"wallsend|jarrow|hebburn|washington|whitley bay|durham|darlington|hartlepool|"
    r"middlesbrough|stockton|redcar|teesside|tees valley|bishop auckland|"
    r"barnard castle|consett|stanley|chester-le-street|seaham|peterlee|shildon|"
    r"newton aycliffe|spennymoor|crook|morpeth|hexham|alnwick|berwick|ashington|"
    r"blyth|cramlington|bamburgh|northumberland|northumbria|tyne and wear|"
    r"tyne & wear|tyneside|wearside|county durham|co\.? durham|north east|"
    r"north-east|ponteland|haltwhistle|prudhoe|corbridge|rothbury|wooler|"
    r"seahouses|amble|guisborough|saltburn|billingham|yarm|thornaby|weardale|"
    r"teesdale|beamish|gibside|cragside|wallington|housesteads|vindolanda|"
    r"lindisfarne|holy island|kielder|souter|seaton delaval|belsay|warkworth|"
    r"dunstanburgh|chesters|corbridge|aydon|prudhoe|tynemouth priory|"
    r"auckland castle|raby|locomotion)\b"
    r"|\b(NE|DH|SR|TS)\d{1,2}\b|\bDL(1[2-7]|[1-5])\b|\bTD15\b",
    re.I,
)

VOLUNTEER_RE = re.compile(r"\bvolunt(eer|ary)\b", re.I)
FREELANCE_RE = re.compile(r"\b(freelance|commission|tender|consultan(t|cy))\b", re.I)
TRUSTEE_RE = re.compile(r"\b(trustee|board member|non-executive|chair)\b", re.I)

CLOSING_RE = re.compile(
    r"(?:closing|close|closes|deadline|apply by|advert end)[^:\n]{0,20}[:\-–]?\s*"
    r"((?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s*)?"
    r"(\d{1,2}(?:st|nd|rd|th)?\s+[a-z]{3,9},?\s+\d{4}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|"
    r"[a-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})",
    re.I,
)
SALARY_RE = re.compile(r"(£\s?[\d,.]+(?:\s?(?:-|–|to)\s?£?\s?[\d,.]+)?(?:\s?(?:per|p\.?a|an hour|ph|k)\b[^\n|;]{0,20})?)", re.I)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def clean(text: str | None) -> str:
    if not text:
        return ""
    text = htmllib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def job_id(source_id: str, title: str, url: str) -> str:
    key = f"{source_id}|{title.lower()}|{url.split('#')[0]}"
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def parse_date(text: str | None) -> str | None:
    """Return YYYY-MM-DD or None."""
    if not text:
        return None
    text = clean(text)
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)
    try:
        dt = dateparser.parse(text, dayfirst=True, fuzzy=True, default=datetime(2000, 1, 1))
    except (ValueError, OverflowError):
        return None
    if dt.year < 2020:
        return None
    return dt.date().isoformat()


def find_closing(text: str) -> str | None:
    m = CLOSING_RE.search(text or "")
    return parse_date(m.group(2)) if m else None


def find_salary(text: str) -> str:
    m = SALARY_RE.search(text or "")
    return clean(m.group(1)) if m else ""


def fetch(url: str, session: requests.Session) -> requests.Response:
    last = None
    for attempt in range(3):
        try:
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code in (429, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            return r
        except requests.RequestException as e:  # retry
            last = e
            time.sleep(2 + attempt * 3)
    raise last  # type: ignore[misc]


AREA_RULES = [
    ("Northumberland", r"\b(northumberland|morpeth|hexham|alnwick|berwick|ashington|blyth|cramlington|bamburgh|"
                       r"ponteland|haltwhistle|prudhoe|corbridge|rothbury|wooler|seahouses|amble|kielder|cragside|"
                       r"wallington|housesteads|vindolanda|lindisfarne|holy island|seaton delaval|belsay|warkworth|"
                       r"dunstanburgh|chesters|aydon|woodhorn|TD15|NE(4[6-9]|6[1-9]|7[01]))\b"),
    ("Tees Valley", r"\b(middlesbrough|stockton|redcar|hartlepool|darlington|teesside|tees valley|guisborough|"
                    r"saltburn|billingham|yarm|thornaby|preston park|dorman|kirkleatham|head of steam|captain cook|"
                    r"mima|TS\d{1,2}|DL[1-3])\b"),
    ("County Durham", r"\b(county durham|co\.? durham|durham|bishop auckland|barnard castle|consett|stanley|"
                      r"chester-le-street|seaham|peterlee|shildon|newton aycliffe|spennymoor|crook|weardale|"
                      r"teesdale|beamish|bowes|killhope|locomotion|auckland|raby|DH\d{1,2}|DL(1[2-7]|4|5))\b"),
    ("Tyne & Wear", r"\b(newcastle|gateshead|sunderland|south shields|north shields|tynemouth|wallsend|jarrow|"
                    r"hebburn|washington|whitley bay|tyne (and|&) wear|tyneside|wearside|laing|discovery museum|"
                    r"great north museum|hancock|hatton|shipley|segedunum|arbeia|gibside|souter|baltic|"
                    r"seven stories|SR\d{1,2}|NE\d{1,2})\b"),
]
AREA_RES = [(name, re.compile(rx, re.I)) for name, rx in AREA_RULES]


def infer_area(text: str) -> str:
    for name, rx in AREA_RES:
        if rx.search(text or ""):
            return name
    return ""


def classify(title: str, context: str = "") -> str:
    t = f"{title} {context[:200]}"
    if VOLUNTEER_RE.search(title):
        return "volunteer"
    if TRUSTEE_RE.search(title):
        return "trustee"
    if FREELANCE_RE.search(t):
        return "freelance"
    return "job"


# ---------------------------------------------------------------------------
# Generic "careers page" extractor
# ---------------------------------------------------------------------------

JUNK_SELECTORS = [
    "script", "style", "noscript", "svg", "iframe", "nav",
    "[role=navigation]", "[aria-hidden=true]",
    "#cookie-notice", ".cookie", ".cookies", "#cookies", ".cc-window",
    ".breadcrumb", ".breadcrumbs", ".site-header", ".site-footer",
    "#site-header", "#site-footer", ".skip-link", ".menu", "#menu",
]


def main_content(soup: BeautifulSoup) -> Tag:
    for sel in JUNK_SELECTORS:
        for el in soup.select(sel):
            el.decompose()
    body = soup.body or soup
    # header/footer directly under body (or one wrapper deep) are site chrome
    for el in body.find_all(["header", "footer"]):
        if not el.find_parent(["main", "article"]):
            el.decompose()
    for sel in ["main", "[role=main]", "article", "#main", "#content", ".content", "#primary"]:
        el = body.select_one(sel)
        if el and len(clean(el.get_text(" "))) > 200:
            return el
    return body


def _usable(href: str) -> bool:
    return bool(href) and not href.startswith(("mailto:", "tel:", "#", "javascript:"))


def _jobish(full: str, base_url: str) -> bool:
    base_path = urlparse(base_url).path.rstrip("/")
    path = urlparse(full).path.rstrip("/")
    if NON_JOB_PATH_RE.search(path):
        return False
    return bool(JOB_LINK_RE.search(full)) or (bool(base_path) and path.startswith(base_path + "/"))


def nearby_link(el: Tag, base_url: str) -> str | None:
    """Best link for a job heading: itself, its parent <a>, or a job-ish link nearby."""
    a = el if el.name == "a" else el.find_parent("a")
    if a and _usable(a.get("href", "")):
        return urljoin(base_url, a["href"])
    a = el.find("a", href=True)
    if a:
        return urljoin(base_url, a["href"])
    # Look at following siblings until the next heading of same/higher level.
    stop_tags = {"h1", "h2", "h3", "h4"} if el.name and el.name.startswith("h") else set()
    sib = el.find_next_sibling()
    hops = 0
    while sib is not None and hops < 8:
        if sib.name in stop_tags:
            break
        for cand in ([sib] if sib.name == "a" else []) + sib.find_all("a", href=True):
            href = cand.get("href", "")
            if href and not href.startswith(("mailto:", "tel:", "#", "javascript:")):
                return urljoin(base_url, href)
        sib = sib.find_next_sibling()
        hops += 1
    # Look just before the heading (card layouts often put an image link first).
    sib = el.find_previous_sibling()
    if sib is not None:
        cands = ([sib] if sib.name == "a" else []) + sib.find_all("a", href=True)
        for cand in cands:
            if _usable(cand.get("href", "")):
                full = urljoin(base_url, cand["href"])
                if _jobish(full, base_url):
                    return full
    # Walk up a couple of levels looking for a job-ish link.
    parent = el.parent
    for _ in range(3):
        if parent is None:
            break
        links = [x for x in parent.find_all("a", href=True) if _usable(x["href"])]
        if 0 < len(links) <= 4:
            for x in links:
                full = urljoin(base_url, x["href"])
                if _jobish(full, base_url):
                    return full
        parent = parent.parent
    return None


def block_text(el: Tag, limit: int = 600) -> str:
    """Text of the job's surrounding block (for dates, salary, location)."""
    parts = [clean(el.get_text(" "))]
    sib = el.find_next_sibling()
    hops = 0
    stop = {"h1", "h2", "h3"} if el.name in {"h1", "h2", "h3"} else {"h1", "h2", "h3", "h4"}
    while sib is not None and hops < 8 and sum(len(p) for p in parts) < limit:
        if sib.name in stop:
            break
        parts.append(clean(sib.get_text(" ")))
        sib = sib.find_next_sibling()
        hops += 1
    text = " ".join(p for p in parts if p)
    if len(text) < 60 and el.parent is not None:
        text = clean(el.parent.get_text(" "))
    return text[:limit]


def looks_like_title(t: str) -> bool:
    if not (4 <= len(t) <= 110):
        return False
    if len(t.split()) > 14:
        return False
    if NOT_A_JOB_RE.match(t.strip(" :.-–|")):
        return False
    if t.endswith((".", "?", "!")) and len(t.split()) > 6:
        return False
    if t.endswith(":"):
        return False
    if re.search(r"https?://|@|©|\bcookies?\b", t, re.I):
        return False
    return True


GENERIC_LINK_TEXT_RE = re.compile(
    r"^(apply\b.*|more\b.*|read more.*|find out more.*|learn more.*|view\b.*|details|"
    r"job (description|profile|pack).*|download.*|click here.*|here|info|information|"
    r"see more.*|full details.*|application (form|pack).*|candidate (pack|information).*)$",
    re.I,
)


def extract_page(html: str, url: str) -> tuple[list[dict], dict]:
    soup = BeautifulSoup(html, "lxml")
    title_tag = clean(soup.title.string if soup.title else "")
    root = main_content(soup)
    text = clean(root.get_text(" "))
    h1 = clean(root.find("h1").get_text(" ")) if root.find("h1") else ""
    base_path = urlparse(url).path.rstrip("/")
    found: dict[str, dict] = {}

    def same_page(link: str) -> bool:
        return link.split("#")[0].rstrip("/") == url.split("#")[0].rstrip("/")

    def add(title: str, link: str | None, context: str):
        title = clean(title).strip(" :–-|•")
        key = title.lower()
        if not looks_like_title(title) or key == h1.lower():
            return
        link = link or url
        if NON_JOB_PATH_RE.search(urlparse(link).path) and not same_page(link):
            return
        if same_page(link):
            link = url  # drop in-page #anchors
        job = {
            "title": title,
            "url": link,
            "closing": find_closing(context),
            "salary": find_salary(context),
            "context": context[:400],
        }
        old = found.get(key)
        if old is None:
            found[key] = job
            return
        # Seen before (e.g. a contents list): keep the richer version.
        if same_page(old["url"]) and not same_page(link):
            old["url"] = link
        for f in ("closing", "salary"):
            if not old.get(f) and job.get(f):
                old[f] = job[f]
        if len(job["context"]) > len(old["context"]):
            old["context"] = job["context"]

    # 1) Headings and short bold/list/paragraph lines that read like job titles.
    for el in root.find_all(["h2", "h3", "h4", "h5", "h6", "strong", "b", "li", "p", "dt", "td", "span", "button", "summary"]):
        if el.find(["h2", "h3", "h4", "h5", "li", "p", "table", "div"]):
            continue  # only leaf-ish elements
        t = clean(el.get_text(" "))
        if not ROLE_RE.search(t) or not looks_like_title(t):
            continue
        if el.name in {"p", "li", "span", "td"} and (len(t) > 80 or ". " in t):
            continue
        add(t, nearby_link(el, url), block_text(el))

    # 2) Links that look like vacancies (child pages of the careers page, ATS links).
    for a in root.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        full = urljoin(url, href)
        path = urlparse(full).path.rstrip("/")
        t = clean(a.get_text(" "))
        is_child = bool(base_path) and path.startswith(base_path + "/") and path != base_path
        is_ats = bool(JOB_LINK_RE.search(full)) and urlparse(full).netloc != urlparse(url).netloc
        if not (is_child or is_ats or (ROLE_RE.search(t) and JOB_LINK_RE.search(full))):
            continue
        if not same_page(full) and any(j["url"] == full for j in found.values()):
            continue  # already have this vacancy from its heading
        if GENERIC_LINK_TEXT_RE.match(t) or not t:
            # Take the title from the closest heading above the link.
            h = a.find_previous(["h2", "h3", "h4", "h5", "strong"])
            if h is None:
                continue
            t = clean(h.get_text(" "))
            if not ROLE_RE.search(t):
                continue
        add(t, full, block_text(a.parent if a.parent is not None else a))

    jobs = list(found.values())
    status = {
        "page_title": title_tag,
        "no_vacancies": bool(NO_VACANCIES_RE.search(text)),
        "fingerprint": hashlib.sha1(text.encode()).hexdigest()[:16],
        "snippet": text[:300],
        "too_many": len(jobs) > 40,
    }
    if status["too_many"]:
        jobs = jobs[:40]
    return jobs, status


# ---------------------------------------------------------------------------
# Source-type handlers. Each returns (jobs, status dict)
# ---------------------------------------------------------------------------

def handle_page(src: dict, session: requests.Session):
    r = fetch(src["url"], session)
    r.raise_for_status()
    jobs, status = extract_page(r.text, r.url)
    for j in jobs:
        j.setdefault("location", src.get("area", ""))
    return jobs, status


def handle_rss(src: dict, session: requests.Session):
    items = []
    for u in src.get("urls") or [src["url"]]:
        r = fetch(u, session)
        if r.status_code == 404 and items:
            break
        r.raise_for_status()
        items += BeautifulSoup(r.content, "xml").find_all("item")
    jobs = []
    for item in items:
        title = clean(item.title.get_text() if item.title else "")
        link = clean(item.link.get_text() if item.link else "")
        desc_html = item.description.get_text() if item.description else ""
        desc = clean(BeautifulSoup(desc_html, "lxml").get_text(" | "))
        cats = " ".join(clean(c.get_text()) for c in item.find_all("category"))
        if re.match(r"(schools|social (care|work)|early years)", cats, re.I):
            continue
        pub = clean(item.pubDate.get_text()) if item.pubDate else ""
        closing = None
        m = re.search(r"Advert End Date:\s*([\d/]+)", desc)
        if m:
            closing = parse_date(m.group(1))
        closing = closing or find_closing(desc)
        sal = ""
        m = re.search(r"Salary:\s*([^|]+)", desc)
        sal = clean(m.group(1)) if m else find_salary(desc)
        contract = ""
        m = re.search(r"Contract Type:\s*([^|]+)", desc)
        if m:
            contract = clean(m.group(1))
        org = ""
        m = re.match(r"(.{3,80}?) (are|is) (seeking|looking)", desc)
        if m:
            org = m.group(1)
        if " – " in title and src["id"] == "mdnorth":
            org, title = [clean(x) for x in title.split(" – ", 1)]
        jobs.append({
            "title": title,
            "url": link,
            "org": org,
            "closing": closing,
            "salary": sal,
            "contract": contract,
            "posted": parse_date(pub),
            "category": cats,
            "context": f"{desc} {cats}"[:600],
        })
    return jobs, {"no_vacancies": False}


def handle_listing(src: dict, session: requests.Session):
    urls = src.get("urls") or [src["url"]]
    jobs = []
    for u in urls:
        r = fetch(u, session)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        for card in soup.select(src["item"]):
            a = card.select_one(src.get("title", "a"))
            if a is None:
                continue
            title = clean(a.get_text(" "))
            href = a.get("href") or (a.find_parent("a") or {}).get("href")
            if not title or not href:
                continue
            text = clean(card.get_text("\n"))
            text_lines = card.get_text("\n")

            def pick(key):
                sel = src.get(key)
                if sel:
                    el = card.select_one(sel)
                    if el:
                        return clean(el.get_text(" "))
                rx = src.get(f"{key}_regex")
                if rx:
                    m = re.search(rx, text_lines)
                    if m:
                        return clean(m.group(1))
                return ""

            org = pick("org")
            dept = pick("department")
            jobs.append({
                "title": title,
                "url": urljoin(u, href),
                "org": org if not dept else f"{org} – {dept}" if org else dept,
                "location": pick("location"),
                "salary": pick("salary") or find_salary(text),
                "closing": parse_date(pick("closing")) or find_closing(text),
                "summary": pick("summary")[:300],
                "context": text[:600],
            })
        time.sleep(1)
    # de-duplicate across pages
    uniq = {}
    for j in jobs:
        uniq.setdefault(j["url"], j)
    return list(uniq.values()), {"no_vacancies": False}


def handle_jobtrain(src: dict, session: requests.Session):
    base = src["url"].rstrip("/")
    jobs = []
    skip = 0
    while True:
        r = fetch(f"{base}/Home/_JobCard?Skip={skip}&postedDate=Anytime", session)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        cards = soup.select(".job-card")
        for card in cards:
            a = card.select_one("a[href*='JobDetail']")
            if not a:
                continue
            fields = {}
            for p in card.select("p.jobdetailsitem"):
                label = clean(p.strong.get_text()) if p.strong else ""
                val = clean(p.get_text(" ")).replace(label, "", 1).strip()
                fields[label.rstrip(":").lower()] = val
            loc = card.select_one(".job-card__location")
            badge = clean(card.select_one(".job-card__status").get_text(" ")) if card.select_one(".job-card__status") else ""
            text = clean(card.get_text(" "))
            jobs.append({
                "title": clean(a.get_text(" ")),
                "url": urljoin(base + "/", a["href"]),
                "location": clean(loc.get_text(" ")).replace("location_on", "").strip() if loc else "",
                "salary": fields.get("salary", ""),
                "closing": parse_date(fields.get("closing date")) or find_closing(text),
                "contract": fields.get("department", ""),
                "closing_soon": "closing soon" in badge.lower(),
                "context": text[:400],
            })
        total = soup.select_one("#totalMatchRecords")
        total_n = int(total["value"]) if total and total.get("value", "").isdigit() else len(jobs)
        skip += max(len(cards), 1)
        if not cards or len(jobs) >= total_n or skip > 300:
            break
    return jobs, {"no_vacancies": len(jobs) == 0}


def handle_nt_api(src: dict, session: requests.Session):
    r = fetch(src["url"], session)
    r.raise_for_status()
    items = r.json().get("data", {}).get("items", [])
    jobs = []
    for i in items:
        lat, lon = i.get("latitude") or 0, i.get("longitude") or 0
        in_ne = 54.35 < lat < 55.85 and -2.75 < lon < -0.9
        sal = i.get("salary")
        jobs.append({
            "title": clean(i.get("title")),
            "url": f"https://careers.nationaltrust.org.uk/OA_HTML/a/#/vacancy-detail/{i.get('id')}",
            "org": f"National Trust – {clean(i.get('locationTitle'))}",
            "location": clean(i.get("location")),
            "salary": f"£{sal:,.0f}" if isinstance(sal, (int, float)) and sal else "",
            "closing": parse_date(i.get("closing")),
            "posted": parse_date(i.get("posted")),
            "context": clean(i.get("keywords", ""))[:300],
            "_in_ne": in_ne,
        })
    return jobs, {"no_vacancies": False}


def handle_eh_api(src: dict, session: requests.Session):
    r = fetch(src["url"], session)
    r.raise_for_status()
    jobs = []
    for i in r.json().get("jobs", []):
        jobs.append({
            "title": clean(i.get("title")),
            "url": i.get("applyLink") or src.get("visit") or src["url"],
            "org": "English Heritage",
            "location": clean(i.get("location")),
            "salary": clean(i.get("salary", "")).split(" / ")[0],
            "closing": parse_date((i.get("closingDate") or "")[:10]),
            "posted": parse_date((i.get("publicationDate") or "")[:10]),
            "contract": clean(i.get("type")),
            "context": clean(BeautifulSoup(i.get("aboutTeamRole") or "", "lxml").get_text(" "))[:400],
        })
    return jobs, {"no_vacancies": False}


HANDLERS = {
    "page": handle_page,
    "rss": handle_rss,
    "listing": handle_listing,
    "jobtrain": handle_jobtrain,
    "nt_api": handle_nt_api,
    "eh_api": handle_eh_api,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def filter_jobs(src: dict, jobs: list[dict]) -> list[dict]:
    out = []
    include = re.compile(src["include"], re.I) if src.get("include") else None
    for j in jobs:
        blob = " ".join(str(j.get(k, "")) for k in ("title", "org", "location", "context", "category"))
        if include and not include.search(blob):
            continue
        fields = src.get("heritage_fields")
        hblob = " ".join(str(j.get(k, "")) for k in fields) if fields else blob
        if not src.get("museum", False) and not HERITAGE_RE.search(hblob):
            continue
        if src.get("region"):
            in_ne = j.pop("_in_ne", None)
            if in_ne is None:
                in_ne = bool(NE_PLACE_RE.search(" ".join(str(j.get(k, "")) for k in ("title", "org", "location", "context"))))
            j["wider"] = not in_ne
        j.pop("_in_ne", None)
        out.append(j)
    return out


def load_previous() -> dict:
    if OUT_FILE.exists():
        try:
            return json.loads(OUT_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"jobs": [], "sources": []}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated source ids to run")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print, don't write jobs.json")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(SOURCES_FILE.read_text())
    sources = cfg["sources"]
    if args.only:
        wanted = set(args.only.split(","))
        sources = [s for s in sources if s["id"] in wanted]

    prev = load_previous()
    prev_jobs = {j["id"]: j for j in prev.get("jobs", [])}
    prev_sources = {s["id"]: s for s in prev.get("sources", [])}
    stamp = now_iso()
    today = stamp[:10]

    session = requests.Session()
    all_jobs: list[dict] = []
    source_report = []

    for src in sources:
        sid = src["id"]
        handler = HANDLERS.get(src.get("type", "page"))
        report = {
            "id": sid,
            "name": src["name"],
            "url": src.get("visit") or src.get("url") or (src.get("urls") or [""])[0],
            "area": src.get("area", ""),
            "note": src.get("note", ""),
            "checked_at": stamp,
        }
        old = prev_sources.get(sid, {})
        try:
            raw, status = handler(src, session)
            jobs = filter_jobs(src, raw)
            report.update(status="ok", count=len(jobs), found_raw=len(raw))
            if status.get("no_vacancies") and not jobs:
                report["status"] = "none"
            elif not jobs:
                report["status"] = "empty"
            if status.get("too_many"):
                report["warning"] = "Lots of matches – some may not be real jobs."
            fp = status.get("fingerprint")
            if fp:
                report["fingerprint"] = fp
                report["changed_at"] = old.get("changed_at", today) if old.get("fingerprint") == fp else today
                report["snippet"] = status.get("snippet", "")
            log(f"[{sid:18}] {report['status']:5} {len(jobs):3} kept / {len(raw):3} found")
        except Exception as e:  # noqa: BLE001 – one bad site must not stop the rest
            report.update(status="error", count=0, error=f"{type(e).__name__}: {str(e)[:200]}")
            report["changed_at"] = old.get("changed_at")
            log(f"[{sid:18}] ERROR {e}")
            # carry forward previous jobs from this source for a few days
            jobs = []
            for pj in prev_jobs.values():
                if pj.get("source_id") == sid:
                    last = pj.get("last_seen", today)
                    if (datetime.fromisoformat(today) - datetime.fromisoformat(last)).days <= STALE_DAYS:
                        pj = dict(pj, stale=True)
                        all_jobs.append(pj)
            source_report.append(report)
            continue

        for j in jobs:
            j["id"] = job_id(sid, j["title"], j["url"])
            j["source_id"] = sid
            j["source"] = src["name"]
            j.setdefault("org", "")
            if not j["org"] and src.get("museum") and src.get("type") in ("page", "jobtrain"):
                j["org"] = src["name"]
            area = src.get("area", "")
            if area in ("", "Region-wide"):
                area = infer_area(" ".join(str(j.get(k, "")) for k in ("title", "org", "location", "context"))) or "North East"
            j["area"] = area
            j["kind"] = classify(j["title"], j.get("context", ""))
            pj = prev_jobs.get(j["id"])
            if pj:
                j["first_seen"] = pj["first_seen"]
            else:  # first sighting: use the advert's own posted date if it has one
                posted = j.get("posted")
                j["first_seen"] = posted if posted and posted <= today else today
            j["found_at"] = pj.get("found_at", pj["first_seen"]) if pj else stamp
            j["last_seen"] = today
            if args.verbose:
                log(f"      - {j['title']}  [{j.get('closing') or '-'}]  {j['url']}")
            all_jobs.append(j)
        source_report.append(report)
        time.sleep(0.5)

    if args.only:
        # keep untouched sources' jobs and reports when testing a subset
        ran = {s["id"] for s in sources}
        all_jobs += [j for j in prev.get("jobs", []) if j.get("source_id") not in ran]
        source_report += [s for s in prev.get("sources", []) if s["id"] not in ran]

    # Drop jobs whose closing date has passed (keep today's).
    all_jobs = [j for j in all_jobs if not j.get("closing") or j["closing"] >= today]

    # Same job on two boards: keep the one from the museum's own site / earliest.
    seen_titles: dict[str, dict] = {}
    deduped = []
    for j in sorted(all_jobs, key=lambda x: (x.get("first_seen", ""), x["source_id"])):
        k = re.sub(r"[^a-z0-9]", "", j["title"].lower())
        org_k = re.sub(r"[^a-z0-9]", "", (j.get("org") or "").lower())[:12]
        key = f"{k}|{org_k}" if org_k else k
        if key in seen_titles:
            seen_titles[key].setdefault("also_on", []).append({"source": j["source"], "url": j["url"]})
            continue
        seen_titles[key] = j
        deduped.append(j)

    for j in deduped:
        j.pop("context", None)

    deduped.sort(key=lambda j: (j.get("first_seen", ""), j.get("closing") or "9999"), reverse=True)

    out = {
        "generated_at": stamp,
        "job_count": len(deduped),
        "sources": sorted(source_report, key=lambda s: s["name"].lower()),
        "manual": cfg.get("manual", []),
        "jobs": deduped,
    }
    if args.dry_run:
        print(json.dumps(out, indent=2)[:5000])
    else:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(out, indent=1, ensure_ascii=False))
        log(f"Wrote {len(deduped)} jobs from {len(source_report)} sources -> {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
