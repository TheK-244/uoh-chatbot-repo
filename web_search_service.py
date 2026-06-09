import gzip
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from config import ALLOWED_SITES, ENABLE_WEB_SEARCH

# Live allowed-site search settings. This version does not use Google CSE.
# It searches only allowed domains, fetches candidate pages in parallel,
# then sends only relevant text windows to the AI instead of the full page start.
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; UOHAssistant/2.0; +https://www.uoh.edu.sa/)"
}
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "25"))
SITEMAP_CACHE_SECONDS = int(os.getenv("SITEMAP_CACHE_SECONDS", str(60 * 60)))
PAGE_CACHE_SECONDS = int(os.getenv("PAGE_CACHE_SECONDS", str(30 * 60)))
LINK_CACHE_SECONDS = int(os.getenv("LINK_CACHE_SECONDS", str(30 * 60)))
MAX_SITEMAP_URLS = int(os.getenv("MAX_SITEMAP_URLS", "40"))
MAX_CANDIDATE_URLS = int(os.getenv("MAX_CANDIDATE_URLS", "15"))
MAX_DISCOVERED_LINKS = int(os.getenv("MAX_DISCOVERED_LINKS", "50"))
MAX_FETCHED_PAGES = int(os.getenv("MAX_FETCHED_PAGES", "10"))
WEB_PAGE_CHAR_LIMIT = int(os.getenv("WEB_PAGE_CHAR_LIMIT", "9000"))
WEB_TOTAL_CHAR_LIMIT = int(os.getenv("WEB_TOTAL_CHAR_LIMIT", "25000"))
WEB_WORKERS = int(os.getenv("WEB_WORKERS", "5"))
WEB_LINK_DEPTH = int(os.getenv("WEB_LINK_DEPTH", "3"))
WEB_USE_SITEMAP = os.getenv("WEB_USE_SITEMAP", "true").lower() == "true"
WEB_MIN_PAGE_SCORE = int(os.getenv("WEB_MIN_PAGE_SCORE", "1"))
WEB_SOURCES_FILE = Path(__file__).resolve().parent / "web_sources.txt"

_sitemap_cache = {}
_page_cache = {}
_link_cache = {}

ARABIC_ENGLISH_HINTS = {
    "جامعة": ["university", "about"],
    "جامعه": ["university", "about"],
    "حائل": ["hail", "uoh"],
    "كليات": ["colleges", "college", "academics"],
    "كلية": ["college", "colleges"],
    "كليه": ["college", "colleges"],
    "قبول": ["admission", "admissions"],
    "تسجيل": ["registration", "registrar"],
    "عمادة": ["deanship", "dean"],
    "عماده": ["deanship", "dean"],
    "العمادات": ["deanships"],
    "تواصل": ["contact", "contacts"],
    "اتصال": ["contact"],
    "موقع": ["location"],
    "مبنى": ["building"],
    "مبني": ["building"],
    "مباني": ["buildings"],
    "تأسست": ["established", "founded", "about"],
    "تاسست": ["established", "founded", "about"],
    "تأسيس": ["established", "founded", "about"],
    "تاسيس": ["established", "founded", "about"],
    "الرؤية": ["vision"],
    "الرؤيه": ["vision"],
    "الرسالة": ["mission"],
    "الرساله": ["mission"],
    "أعضاء": ["faculty", "staff"],
    "اعضاء": ["faculty", "staff"],
    "هيئة": ["faculty"],
    "هييه": ["faculty"],
    "تخصصات": ["programs", "majors"],
    "برامج": ["programs"],
    "تقويم": ["calendar"],
    "التقويم": ["calendar"],
}

STOP_WORDS = {
    "ما", "ماذا", "من", "في", "على", "عن", "الى", "إلى", "هل", "هي", "هو", "كم", "متى",
    "اين", "أين", "ماهي", "وش", "وين", "و", "او", "أو", "ال", "the", "is", "are", "a", "an", "of", "in", "on", "for", "to", "and", "what", "where", "when", "how"
}


def normalize_domain(site):
    site = (site or "").strip().lower()
    site = site.replace("https://", "").replace("http://", "")
    site = site.split("/")[0]
    return site[4:] if site.startswith("www.") else site


def read_web_source_urls():
    """Read manually selected source pages from web_sources.txt."""
    if not WEB_SOURCES_FILE.exists():
        return []

    urls = []
    try:
        for raw_line in WEB_SOURCES_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("http://", "https://")):
                urls.append(line)
    except Exception as exc:
        print("Could not read web_sources.txt:", exc)

    unique_urls = []
    for url in urls:
        if url not in unique_urls:
            unique_urls.append(url)
    return unique_urls


def allowed_domains():
    domains = [normalize_domain(site) for site in ALLOWED_SITES if normalize_domain(site)]
    for url in read_web_source_urls():
        domain = normalize_domain(urlparse(url).netloc)
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def is_allowed_url(url):
    try:
        parsed = urlparse(url)
        domain = normalize_domain(parsed.netloc)
        if parsed.scheme not in ("http", "https") or not domain:
            return False
        return any(domain == allowed or domain.endswith("." + allowed) for allowed in allowed_domains())
    except Exception:
        return False


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden_tag_depth = 0
        self.parts = []
        self.links = []
        self.title_parts = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas", "iframe"}:
            self.hidden_tag_depth += 1
        if tag == "title":
            self.in_title = True
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas", "iframe"} and self.hidden_tag_depth:
            self.hidden_tag_depth -= 1
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.hidden_tag_depth:
            return
        clean = " ".join(data.split())
        if not clean:
            return
        if self.in_title:
            self.title_parts.append(clean)
        self.parts.append(clean)

    def get_text(self):
        text = "\n".join(self.parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()

    def get_title(self):
        return " ".join(self.title_parts).strip()


def http_get(url, timeout=HTTP_TIMEOUT):
    response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response


def read_xml_response(response):
    content = response.content
    if response.url.lower().endswith(".gz"):
        try:
            content = gzip.decompress(content)
        except Exception:
            pass
    return content.decode(response.encoding or "utf-8", errors="ignore")


def extract_locs_from_sitemap(xml_text):
    locs = []
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except Exception:
        return locs, False

    tag = root.tag.lower()
    is_index = tag.endswith("sitemapindex")
    for elem in root.iter():
        if elem.tag.lower().endswith("loc") and elem.text:
            locs.append(elem.text.strip())
    return locs, is_index


def sitemap_candidates_for_domain(domain):
    domain = normalize_domain(domain)
    bases = [f"https://{domain}"]
    if not domain.startswith("www."):
        bases.append(f"https://www.{domain}")
    return [base + "/sitemap.xml" for base in bases]


def get_sitemap_urls_for_domain(domain):
    domain = normalize_domain(domain)
    cache_key = domain
    cached = _sitemap_cache.get(cache_key)
    if cached and time.time() - cached["time"] < SITEMAP_CACHE_SECONDS:
        return cached["urls"]

    urls = []
    queue = sitemap_candidates_for_domain(domain)
    seen = set()

    while queue and len(urls) < MAX_SITEMAP_URLS:
        sitemap_url = queue.pop(0)
        if sitemap_url in seen:
            continue
        seen.add(sitemap_url)
        if not is_allowed_url(sitemap_url):
            continue
        try:
            response = http_get(sitemap_url, timeout=6)
            locs, is_index = extract_locs_from_sitemap(read_xml_response(response))
        except Exception:
            continue

        if is_index:
            for loc in locs[:15]:
                if is_allowed_url(loc) and loc not in seen:
                    queue.append(loc)
        else:
            for loc in locs:
                if is_allowed_url(loc) and looks_like_html_url(loc):
                    urls.append(loc)
                    if len(urls) >= MAX_SITEMAP_URLS:
                        break

    if not urls:
        urls = crawl_homepage_links(domain)

    for common in common_urls(domain):
        if common not in urls and is_allowed_url(common):
            urls.append(common)

    _sitemap_cache[cache_key] = {"time": time.time(), "urls": urls[:MAX_SITEMAP_URLS]}
    return _sitemap_cache[cache_key]["urls"]


def looks_like_html_url(url):
    lower = url.lower().split("?", 1)[0]
    blocked = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".rar", ".mp4", ".mp3", ".doc", ".docx", ".xls", ".xlsx", ".pdf")
    return not lower.endswith(blocked)


def common_urls(domain):
    base = f"https://{normalize_domain(domain)}"
    www = f"https://www.{normalize_domain(domain)}"
    paths = ["/", "/ar", "/en", "/about", "/About", "/colleges", "/Colleges", "/admission", "/Admission", "/contact", "/Contact"]
    return [base + p for p in paths] + [www + p for p in paths]


def crawl_homepage_links(domain):
    found = []
    for url in common_urls(domain)[:4]:
        try:
            response = http_get(url, timeout=6)
            if "text/html" not in response.headers.get("Content-Type", "").lower():
                continue
            parser = VisibleTextParser()
            parser.feed(response.text)
            for href in parser.links:
                full = urljoin(response.url, href)
                if is_allowed_url(full) and looks_like_html_url(full) and full not in found:
                    found.append(full)
                if len(found) >= 70:
                    return found
        except Exception:
            continue
    return found


def normalize_text_for_search(text):
    text = (text or "").lower()
    arabic_map = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
    text = text.translate(arabic_map)
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    return text


def query_terms(query):
    normalized = normalize_text_for_search(query)
    tokens = re.findall(r"[\u0600-\u06FFa-zA-Z0-9]{2,}", normalized)
    terms = []
    for token in tokens:
        if token not in STOP_WORDS and token not in terms:
            terms.append(token)
            for hint in ARABIC_ENGLISH_HINTS.get(token, []):
                if hint not in terms:
                    terms.append(hint)

    # Add short exact phrases. They improve accuracy for terms like "عمادة القبول".
    filtered = [t for t in tokens if t not in STOP_WORDS]
    for size in (3, 2):
        for i in range(0, max(0, len(filtered) - size + 1)):
            phrase = " ".join(filtered[i:i + size])
            if phrase and phrase not in terms:
                terms.insert(0, phrase)
    return terms


def score_text_against_query(text, terms):
    if not terms:
        return 0
    searchable = normalize_text_for_search(text)
    score = 0
    for term in terms:
        if term in searchable:
            if " " in term:
                score += 8
            elif len(term) >= 5:
                score += 3
            else:
                score += 2
    if any(term in terms for term in ("university", "uoh", "hail", "جامعه", "حائل")):
        if "uoh" in searchable or "حائل" in searchable or "hail" in searchable:
            score += 2
    return score


def fetch_page_text(url):
    if not is_allowed_url(url):
        return {"url": url, "title": "", "text": ""}

    cached = _page_cache.get(url)
    if cached and time.time() - cached["time"] < PAGE_CACHE_SECONDS:
        return cached["data"]

    data = {"url": url, "title": "", "text": ""}
    try:
        response = http_get(url)
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return data

        parser = VisibleTextParser()
        parser.feed(response.text)
        text = parser.get_text()
        data = {"url": response.url, "title": parser.get_title(), "text": text}
    except Exception:
        pass

    _page_cache[url] = {"time": time.time(), "data": data}
    return data


def fetch_page_links(url):
    """Fetch allowed internal links from one page with a short cache."""
    if not is_allowed_url(url):
        return []

    cached = _link_cache.get(url)
    if cached and time.time() - cached["time"] < LINK_CACHE_SECONDS:
        return cached["links"]

    links = []
    try:
        response = http_get(url, timeout=HTTP_TIMEOUT)
        if "text/html" not in response.headers.get("Content-Type", "").lower():
            return []
        parser = VisibleTextParser()
        parser.feed(response.text)
        for href in parser.links:
            full = urljoin(response.url, href).split("#", 1)[0]
            if is_allowed_url(full) and looks_like_html_url(full) and full not in links:
                links.append(full)
    except Exception:
        links = []

    _link_cache[url] = {"time": time.time(), "links": links}
    return links


def discover_links_from_source_pages(query, source_urls, max_depth=WEB_LINK_DEPTH):
    """Use web_sources.txt as seed pages and crawl a small trusted depth.

    Depth is intentionally bounded. Depth=1 means links found inside the
    manually trusted pages. Depth=2 means links found inside those links too,
    but only the highest URL-score pages are expanded. This avoids the old
    slow behavior where sitemap search could fan out across too many pages.
    """
    terms = query_terms(query)
    seen = set(source_urls)
    discovered = []
    frontier = list(source_urls)

    for depth in range(max(0, max_depth)):
        if not frontier:
            break

        next_candidates = []
        # Fetch link lists in parallel. This fixes the slow sequential seed-page
        # discovery that could add many seconds before page scoring even starts.
        with ThreadPoolExecutor(max_workers=WEB_WORKERS) as executor:
            future_to_url = {executor.submit(fetch_page_links, url): url for url in frontier[:MAX_CANDIDATE_URLS]}
            for future in as_completed(future_to_url):
                try:
                    page_links = future.result()
                except Exception:
                    page_links = []
                for full in page_links:
                    if full in seen:
                        continue
                    seen.add(full)
                    parsed = urlparse(full)
                    haystack = f"{parsed.netloc} {parsed.path.replace('-', ' ').replace('_', ' ')} {full}"
                    score = score_text_against_query(haystack, terms)
                    next_candidates.append((score, full))

        next_candidates.sort(key=lambda item: item[0], reverse=True)

        # Keep a small amount of weak URL matches for Arabic SharePoint URLs,
        # but prioritize URLs whose path/title-like parts match the question.
        for score, url in next_candidates[:MAX_DISCOVERED_LINKS]:
            discovered.append((score, url))

        # Only expand the best links on the next depth level.
        frontier = [url for score, url in next_candidates[:MAX_CANDIDATE_URLS] if score > 0]

    discovered.sort(key=lambda item: item[0], reverse=True)
    unique = []
    for _, url in discovered:
        if url not in unique:
            unique.append(url)
        if len(unique) >= MAX_DISCOVERED_LINKS:
            break
    return unique


def choose_candidate_urls(query, urls):
    terms = query_terms(query)
    scored = []
    manual_urls = set(read_web_source_urls())
    for url in urls:
        parsed = urlparse(url)
        haystack = f"{parsed.netloc} {parsed.path.replace('-', ' ').replace('_', ' ')} {url}"
        score = score_text_against_query(haystack, terms)
        if url in manual_urls:
            score += 2
        scored.append((score, url))

    scored.sort(key=lambda item: item[0], reverse=True)
    # Keep manually trusted source pages even if their URL path does not contain
    # the query words. Many SharePoint/ASP.NET pages have generic URLs while the
    # useful text is inside the page body.
    selected = []
    for score, url in scored:
        if score > 0 or url in manual_urls:
            selected.append(url)
        if len(selected) >= MAX_CANDIDATE_URLS:
            break
    if selected:
        return selected
    return [url for _, url in scored[:MAX_CANDIDATE_URLS]]


def extract_relevant_content(text, terms, limit=WEB_PAGE_CHAR_LIMIT):
    if len(text) <= limit:
        return text

    searchable = normalize_text_for_search(text)
    best_index = -1
    best_weight = -1
    for term in terms:
        idx = searchable.find(term)
        if idx == -1:
            continue
        weight = 8 if " " in term else len(term)
        if weight > best_weight:
            best_weight = weight
            best_index = idx

    if best_index == -1:
        return text[:limit]

    start = max(0, best_index - limit // 3)
    end = min(len(text), start + limit)
    start = max(0, end - limit)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "... " + snippet
    if end < len(text):
        snippet += " ..."
    return snippet


def fetch_and_score_page(url, terms):
    page = fetch_page_text(url)
    text = page.get("text", "")
    if len(text) < 80:
        return None
    score = score_text_against_query(f"{page.get('title', '')}\n{text}", terms)
    if terms and score < WEB_MIN_PAGE_SCORE:
        return None
    content = extract_relevant_content(text, terms, WEB_PAGE_CHAR_LIMIT)
    return {
        "title": page.get("title") or url,
        "link": page.get("url") or url,
        "snippet": content[:300],
        "content": content,
        "score": score,
        "source": "allowed_site",
    }


def restricted_web_search(query):
    """Search allowed websites directly without Google.

    Improvements over the old version:
    - fewer candidate pages,
    - parallel page fetching,
    - exact phrase scoring,
    - relevant text windows instead of the first part of each page.
    """
    if not ENABLE_WEB_SEARCH or not allowed_domains():
        return []

    terms = query_terms(query)
    all_urls = []

    manual_urls = read_web_source_urls()
    for url in manual_urls:
        if url not in all_urls and is_allowed_url(url) and looks_like_html_url(url):
            all_urls.append(url)

    for url in discover_links_from_source_pages(query, manual_urls):
        if url not in all_urls and is_allowed_url(url) and looks_like_html_url(url):
            all_urls.append(url)

    # Sitemap search is optional because it is often the slowest part on large
    # university sites. Enable WEB_USE_SITEMAP=true only if web_sources.txt and
    # depth crawling do not cover enough pages.
    if WEB_USE_SITEMAP:
        for domain in allowed_domains():
            for url in get_sitemap_urls_for_domain(domain):
                if url not in all_urls and is_allowed_url(url):
                    all_urls.append(url)

    candidate_urls = choose_candidate_urls(query, all_urls)
    if not candidate_urls:
        return []

    page_results = []
    with ThreadPoolExecutor(max_workers=WEB_WORKERS) as executor:
        future_to_url = {executor.submit(fetch_and_score_page, url, terms): url for url in candidate_urls[:MAX_CANDIDATE_URLS]}
        for future in as_completed(future_to_url):
            try:
                result = future.result()
            except Exception:
                result = None
            if result:
                page_results.append(result)

    page_results.sort(key=lambda item: item.get("score", 0), reverse=True)

    trimmed = []
    total_chars = 0
    for result in page_results:
        remaining = WEB_TOTAL_CHAR_LIMIT - total_chars
        if remaining <= 0:
            break
        result["content"] = result["content"][:remaining]
        total_chars += len(result["content"])
        trimmed.append(result)
        if len(trimmed) >= MAX_FETCHED_PAGES:
            break

    return trimmed
