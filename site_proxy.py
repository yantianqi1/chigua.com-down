"""
Site proxy: fetch, parse, and sanitize chigua.com content.

Provides structured data for the browse SPA:
  - Category list (hard-coded from site nav)
  - Article list per category (paginated, scraped from HTML)
  - Homepage feed (RSS for speed)
  - Article detail (video config + sanitized content)
  - Search (scraped from /?s=keyword)
"""

import asyncio
import html as html_mod
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

import httpx

logger = logging.getLogger("site_proxy")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://chigua.com"
BASE_URL_ALT = "https://51cg1.com"  # site canonical alternates between these
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Domains / URL patterns to strip (ads, tracking, external gambling/adult promos)
AD_DOMAINS = [
    "googletagmanager.com",
    "google-analytics.com",
    "addtoany.com",
    "static.addtoany.com",
    "cloudflare.com/cdn-cgi/scripts",
    "pic.aluxvl.cn",           # ad GIF images
    "cngajnwqu.cc",            # adult nav
    "ljlagami.cc",             # app promo
    "kocgseam.cc",             # external video
    "eexjqeyl.cc",             # external video
    "eecimiiz.cc",             # external video
    "jgtwgawj.cc",             # external
    "51dmw31.com",             # adult manga
    "eygtwjjz.6ea1e.com",      # ad link
    "ads.zyudkkup.com",        # tracking
    "bpi1.yhofqrll.com",       # external API
]

AD_SCRIPT_PATTERNS = [
    r"googletagmanager",
    r"gtag\(",
    r"addtoany",
    r"cloudflare.*email-decode",
    r"tbxw/js/zzz\.js",         # ad/image lazy-loader
    r"tjtagmanager",             # tracking
    r"tjDataLayer",
    r"tjtag\(",
    r"gtag/js",
    r"ads\.zyudkkup",
    r"bpi1\.yhofqrll",
]

# Script sources to remove entirely
STRIP_SCRIPT_SRCS = [
    "/usr/plugins/tbxw/js/zzz.js",
    "googletagmanager",
    "addtoany",
    "cloudflare/cdn-cgi/scripts",
    "tjtag.3.2.3.js",
    "web-sdk-v1.1.3.js",
]

# Categories extracted from chigua.com navigation
CATEGORIES: list[dict] = [
    {"name": "今日吃瓜", "slug": "wpcz"},
    {"name": "学生校园", "slug": "xsxy"},
    {"name": "网红黑料", "slug": "whhl"},
    {"name": "热门大瓜", "slug": "rdsj"},
    {"name": "吃瓜榜单", "slug": "mrdg"},
    {"name": "必看大瓜", "slug": "bkdg"},
    {"name": "看片娱乐", "slug": "ysyl"},
    {"name": "每日大赛", "slug": "mrds"},
    {"name": "伦理道德", "slug": "lldd"},
    {"name": "网黄合集", "slug": "whhj"},
    {"name": "国产剧情", "slug": "gcjq"},
    {"name": "探花精选", "slug": "thjx"},
    {"name": "免费短剧", "slug": "cbdj"},
    {"name": "骚男骚女", "slug": "snsn"},
    {"name": "明星黑料", "slug": "whmx"},
    {"name": "海外吃瓜", "slug": "hwcg"},
    {"name": "人人吃瓜", "slug": "rrcg"},
    {"name": "领导干部", "slug": "ldcg"},
    {"name": "世界杯专栏", "slug": "sjb"},
    {"name": "吃瓜看戏", "slug": "qubk"},
    {"name": "擦边聊骚", "slug": "dcbq"},
    {"name": "51涨知识", "slug": "zzs"},
    {"name": "吃瓜新闻", "slug": "cgxw"},
    {"name": "51品茶", "slug": "51by"},
    {"name": "51剧场", "slug": "51djc"},
    {"name": "原创博主", "slug": "yczq"},
]

# Cache TTL in seconds
CACHE_TTL = 300  # 5 minutes

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class ArticleItem:
    """A single article in a list."""
    id: str           # e.g. "259895"
    title: str
    url: str          # /archives/{id}/
    thumbnail: str    # full image URL
    author: str
    date: str
    categories: list[str] = field(default_factory=list)


@dataclass
class ArticleDetail:
    """Full article detail with video."""
    id: str
    title: str
    url: str
    author: str
    date: str
    categories: list[str]
    thumbnail: str
    videos: list[dict]   # [{"url": m3u8, "title": ...}]
    content_html: str    # sanitized article body HTML
    related: list[ArticleItem] = field(default_factory=list)


@dataclass
class ListPage:
    """Paginated article list."""
    items: list[ArticleItem]
    page: int
    has_next: bool
    next_page: int | None


# ---------------------------------------------------------------------------
# HTTP fetch helpers
# ---------------------------------------------------------------------------

_simple_cache: dict[str, tuple[float, str]] = {}  # url -> (timestamp, html)


async def _fetch(url: str, proxy_url: str = "") -> str:
    """Fetch a URL and return its text, with simple in-memory caching."""
    import time
    now = time.monotonic()
    cache_key = url
    if cache_key in _simple_cache:
        ts, html = _simple_cache[cache_key]
        if now - ts < CACHE_TTL:
            return html

    proxy = proxy_url.strip() or None
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        proxy=proxy,
    ) as client:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        html = resp.text

    _simple_cache[cache_key] = (now, html)
    return html


async def _fetch_api(url: str, proxy_url: str = "") -> str:
    """Same as _fetch but with a longer timeout for heavy pages."""
    import time
    now = time.monotonic()
    if url in _simple_cache:
        ts, html = _simple_cache[url]
        if now - ts < CACHE_TTL:
            return html

    proxy = proxy_url.strip() or None
    async with httpx.AsyncClient(
        timeout=60,
        follow_redirects=True,
        proxy=proxy,
    ) as client:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        html = resp.text

    _simple_cache[url] = (now, html)
    return html


# ---------------------------------------------------------------------------
# HTML parsing: article lists
# ---------------------------------------------------------------------------

def _parse_article_list(html: str) -> list[ArticleItem]:
    """Extract article items from category/archive HTML."""
    items: list[ArticleItem] = []

    # Pattern: <a href="/archives/{id}/">...post-card...</a>
    pattern = r'<a[^>]*href="(/archives/(\d+)/)"[^>]*>(.*?)</a>'
    seen_ids = set()

    for match in re.finditer(pattern, html, re.DOTALL):
        href = match.group(1)
        article_id = match.group(2)
        content = match.group(3)

        if article_id in seen_ids:
            continue
        if "post-card" not in content:
            continue
        seen_ids.add(article_id)

        # Title
        title = ""
        tm = re.search(r'post-card-title"[^>]*>([^<]+)', content)
        if tm:
            title = html_mod.unescape(tm.group(1)).strip()

        # Thumbnail
        thumbnail = ""
        im = re.search(r"loadBannerDirect\('([^']+)'", content)
        if im:
            thumbnail = im.group(1)

        # Author
        author = ""
        am = re.search(r'itemprop="author"[^>]*>([^<]+)', content)
        if am:
            author = am.group(1).strip().rstrip("•").strip()

        # Date
        date = ""
        dm = re.search(r'datePublished[^>]*>([^<]+)', content)
        if dm:
            date = dm.group(1).strip().rstrip("•").strip()

        # Categories (the last text span in post-card-info)
        cats: list[str] = []
        cm = re.findall(r'<span>([^<]+)</span>', content)
        if cm:
            # Last span is usually categories
            cat_text = cm[-1]
            cats = [c.strip() for c in cat_text.split(",") if c.strip()]

        items.append(ArticleItem(
            id=article_id,
            title=title,
            url=href,
            thumbnail=thumbnail,
            author=author,
            date=date,
            categories=cats,
        ))

    return items


def _parse_next_page(html: str, current_page: int) -> tuple[bool, int | None]:
    """Check if there's a next page."""
    m = re.search(r'rel="next"[^>]*href="[^"]*/(\d+)/"', html)
    if m:
        return True, int(m.group(1))
    # Also check for next link without rel
    m2 = re.search(r'href="[^"]*/(\d+)/"[^>]*>\s*(?:下一页|»|next)', html, re.IGNORECASE)
    if m2:
        return True, int(m2.group(1))
    return False, None


# ---------------------------------------------------------------------------
# HTML parsing: article detail
# ---------------------------------------------------------------------------

def _sanitize_html(html: str) -> str:
    """Remove ads, tracking scripts, and unwanted elements from HTML content."""
    # Remove <script> tags with ad/tracking content
    for pattern in AD_SCRIPT_PATTERNS:
        html = re.sub(
            r'<script[^>]*>.*?' + pattern + r'.*?</script>',
            '', html, flags=re.DOTALL | re.IGNORECASE
        )

    # Remove specific script sources
    for src_pattern in STRIP_SCRIPT_SRCS:
        html = re.sub(
            r'<script[^>]*' + re.escape(src_pattern) + r'[^>]*>.*?</script>',
            '', html, flags=re.DOTALL | re.IGNORECASE
        )

    # Remove Google Analytics / gtag inline scripts
    html = re.sub(
        r'<script[^>]*google(?:tagmanager|analytics)[^>]*>.*?</script>',
        '', html, flags=re.DOTALL | re.IGNORECASE
    )
    html = re.sub(
        r'<script[^>]*>\s*window\.dataLayer.*?</script>',
        '', html, flags=re.DOTALL
    )
    html = re.sub(
        r'<script[^>]*>\s*function gtag\(.*?</script>',
        '', html, flags=re.DOTALL
    )

    # Remove banner/float ads
    html = re.sub(
        r'<div[^>]*class="[^"]*banner[^"]*"[^>]*>.*?</div>\s*</div>',
        '', html, flags=re.DOTALL
    )
    html = re.sub(
        r'<div[^>]*id="adFloat"[^>]*>.*?</div>\s*</div>\s*</div>',
        '', html, flags=re.DOTALL
    )

    # Remove Base64 decode script (used for obfuscated ad links)
    html = re.sub(
        r'<script>\s*Base64\s*=\s*\{.*?</script>',
        '', html, flags=re.DOTALL
    )

    # Remove images from ad domains (keep pic.*.cn for content images, GIFs filtered later)
    for domain in AD_DOMAINS:
        if 'pic.aluxvl.cn' in domain or 'pic.apgoap' in domain:
            continue
        html = re.sub(
            r'<img[^>]*' + re.escape(domain) + r'[^>]*>',
            '', html, flags=re.IGNORECASE
        )

    # Remove ad GIF images (banner ads from pic CDN with .gif extension)
    html = re.sub(
        r'<img[^>]*pic\.(?:aluxvl|apgoap)\.cn[^>]*\.gif[^>]*>',
        '', html, flags=re.IGNORECASE
    )

    # Remove external adult/promo links
    promo_domains = [
        r'cngajnwqu\.cc', r'ljlagami\.cc', r'kocgseam\.cc',
        r'eexjqeyl\.cc', r'eecimiiz\.cc', r'jgtwgawj\.cc',
        r'51dmw31\.com', r'eygtwjjz\.6ea1e\.com',
        r'caomeiys\.com', r'51cg\d*\.com',
    ]
    for pd in promo_domains:
        html = re.sub(
            r'<a[^>]*' + pd + r'[^>]*>.*?</a>',
            '', html, flags=re.DOTALL | re.IGNORECASE
        )

    # Remove application popup div
    html = re.sub(
        r'<div[^>]*class="[^"]*application-popup[^"]*"[^>]*>.*?</div>\s*</div>\s*</div>',
        '', html, flags=re.DOTALL
    )

    # Remove recommend layer
    html = re.sub(
        r'<div[^>]*class="[^"]*recommend-layer[^"]*"[^>]*>.*?</div>\s*</div>\s*</div>\s*</div>',
        '', html, flags=re.DOTALL
    )

    # Remove footer menu (ads at bottom)
    html = re.sub(
        r'<div[^>]*class="[^"]*foot-menu[^"]*"[^>]*>.*?</div>',
        '', html, flags=re.DOTALL
    )

    # Remove <meta> refresh/redirect
    html = re.sub(r'<meta[^>]*http-equiv="refresh"[^>]*>', '', html, re.IGNORECASE)

    # Remove Cloudflare email-decode script
    html = re.sub(
        r'<script[^>]*email-decode[^>]*>.*?</script>',
        '', html, flags=re.DOTALL
    )

    return html


def _extract_article_body(html: str) -> str:
    """Extract the main article content from the page HTML.

    The Mirages theme embeds content directly without a dedicated wrapper div.
    We find the <article> tag, skip past leading ads/blockquotes, and stop
    before keyword-tag / external-download sections.
    """
    # Scope to <article> if present
    article_m = re.search(r'<article[^>]*>(.*?)</article>', html, re.DOTALL)
    search_area = article_m.group(1) if article_m else html

    # Real content starts after the last </blockquote> (site-address promo)
    bq_ends = [m.end() for m in re.finditer(r'</blockquote>', search_area)]
    if bq_ends:
        start = bq_ends[-1]
    else:
        start = 0

    # End before keyword tags or external download divs
    end_markers = [
        r'关键词[：:]',
        r'<div[^>]*class="[^"]*btn-download[^"]*"',
        r'<div[^>]*style="[^"]*text-align:center[^"]*margin-block[^"]*"',
    ]
    end = len(search_area)
    for marker in end_markers:
        m = re.search(marker, search_area[start:])
        if m:
            end = start + m.start()
            break

    content = search_area[start:end]

    # --- strip ad / promo cruft from the extracted content ---

    # Leftover blockquotes (site address promos)
    content = re.sub(r'<blockquote>.*?</blockquote>', '', content, flags=re.DOTALL)

    # "text top apps" button row (快手视频 / 成人抖阴 etc.)
    content = re.sub(
        r'<div[^>]*class="[^"]*text_top_apps[^"]*"[^>]*>.*?</div>\s*</div>',
        '', content, flags=re.DOTALL,
    )
    content = re.sub(
        r'<a[^>]*class="[^"]*btn-app[^"]*"[^>]*>.*?</a>',
        '', content, flags=re.DOTALL,
    )

    # Telegram invite / channel links
    content = re.sub(
        r'<a[^>]*href="https?://t\.me/[^"]*"[^>]*>.*?</a>',
        '', content, flags=re.DOTALL,
    )

    # Cloudflare email-protection spans
    content = re.sub(
        r'<span[^>]*class="[^"]*__cf_email__[^"]*"[^>]*>.*?</span>',
        '', content, flags=re.DOTALL,
    )
    content = re.sub(
        r'<a[^>]*href="/cdn-cgi/l/email-protection[^"]*"[^>]*>.*?</a>',
        '', content, flags=re.DOTALL,
    )

    # Fix all lazy-load images: replace tbxw/zw.png placeholder with
    # the actual image URL stored in data-xkrkllgl, then rewrite to use
    # our local image proxy so the CDN doesn't block hotlinking.
    from urllib.parse import quote as url_quote

    def _fix_img(m):
        real = m.group(1) or ""
        orig = m.group(0)
        if real:
            proxy_src = f"/api/site/image-proxy?url={url_quote(real, safe='')}"
            result = re.sub(r'\s+src="[^"]*"', f' src="{proxy_src}"', orig)
            result = re.sub(r'\s+data-xkrkllgl="[^"]*"', '', result)
            return result
        return orig

    content = re.sub(
        r'<img[^>]*data-xkrkllgl="([^"]+)"[^>]*>',
        _fix_img, content,
    )

    # Remove leftover zw.png images that weren't caught (safety net)
    content = re.sub(r'<img[^>]*zw\.png[^>]*>', '', content)

    # Remove banner.png ad images
    content = re.sub(r'<img[^>]*banner\.png[^>]*>', '', content)

    if len(content.strip()) > 50:
        return content.strip()

    # Fallback: take a generous slice of search_area but strip obvious ads
    fallback = search_area
    fallback = re.sub(r'<blockquote>.*?</blockquote>', '', fallback, flags=re.DOTALL)
    fallback = re.sub(r'<div[^>]*class="[^"]*btn-download[^"]*".*?</div>', '', fallback, flags=re.DOTALL)
    return fallback.strip()


def _strip_player_ads(config: dict) -> dict:
    """Remove video_player_ads from DPlayer config."""
    if "video_player_ads" in config:
        config["video_player_ads"] = []
    return config


def _parse_article_page(html: str) -> ArticleDetail:
    """Parse an article detail page."""
    article_id = ""
    id_m = re.search(r'/archives/(\d+)/', html)
    if id_m:
        article_id = id_m.group(1)

    # Extract the post/article area first (avoid nav contamination)
    post_area = html
    for pattern in [
        r'<article[^>]*>(.*?)</article>',
        r'<div[^>]*class="[^"]*post-single[^"]*"[^>]*>(.*?)</div>\s*<div[^>]*class="[^"]*near',
        r'<div[^>]*class="[^"]*post-content-area[^"]*"[^>]*>(.*?)(?:<div[^>]*class="[^"]*near|<div[^>]*class="[^"]*comment)',
    ]:
        m = re.search(pattern, html, re.DOTALL)
        if m and len(m.group(1)) > 500:
            post_area = m.group(1)
            break

    # Title
    title = ""
    for pattern in [
        r'<h1[^>]*class="[^"]*post-title[^"]*"[^>]*>(.*?)</h1>',
        r'<h1[^>]*itemprop="headline"[^>]*>(.*?)</h1>',
        r'<h1[^>]*>(.*?)</h1>',
    ]:
        tm = re.search(pattern, html, re.DOTALL)
        if tm:
            title = re.sub(r'<[^>]+>', '', html_mod.unescape(tm.group(1))).strip()
            if title:
                break

    # Author — scoped to post_area first, fallback to full html
    author = ""
    for area in [post_area, html]:
        am = re.search(r'itemprop="author"[^>]*>\s*(?:<[^>]+>)*\s*([^<]+)', area)
        if am:
            author = am.group(1).strip().rstrip("•").strip()
            if author:
                break
        am2 = re.search(r'class="[^"]*post-author[^"]*"[^>]*>\s*(?:<[^>]+>)*\s*([^<]+)', area)
        if am2:
            author = am2.group(1).strip().rstrip("•").strip()
            if author:
                break

    # Date — scoped to post_area first
    date = ""
    for area in [post_area, html]:
        dm = re.search(r'datePublished[^>]*>([^<]+)', area)
        if dm:
            date = dm.group(1).strip().rstrip("•").strip()
            if date:
                break
        dm2 = re.search(r'<time[^>]*datetime="([^"]+)"', area)
        if dm2:
            date = dm2.group(1)
            if date:
                break
        dm3 = re.search(r'itemprop="datePublished"[^>]*content="([^"]+)"', area)
        if dm3:
            date = dm3.group(1)
            if date:
                break

    # Categories — only within the post-meta area (not nav)
    # Find post-meta div first
    cats: list[str] = []
    meta_area = ""
    mm = re.search(
        r'<(?:div|span)[^>]*class="[^"]*(?:post-meta|post-info|entry-meta|meta)[^"]*"[^>]*>(.*?)</(?:div|span)>',
        html, re.DOTALL
    )
    if mm:
        meta_area = mm.group(1)
    # Search in meta_area first, then fallback to post_area
    search_area = meta_area or post_area
    for cm in re.finditer(r'<a[^>]*href="/category/([^/]+)/"[^>]*>([^<]+)</a>', search_area):
        cats.append(cm.group(2).strip())
    # Deduplicate
    cats = list(dict.fromkeys(cats))
    # If we found too many, it's likely still matching nav — limit to those actually
    # in the post area and not too many
    if len(cats) > 15:
        # Try more targeted: only within 500 chars of the title
        title_pos = html.find(title) if title else 0
        nearby = html[title_pos:title_pos + 3000] if title_pos > 0 else post_area
        cats = []
        for cm in re.finditer(r'<a[^>]*href="/category/([^/]+)/"[^>]*>([^<]+)</a>', nearby):
            cats.append(cm.group(2).strip())
        cats = list(dict.fromkeys(cats))

    # Thumbnail — pick the first content image (from either CDN domain)
    thumbnail = ""
    im = re.search(r'data-xkrkllgl="(https://pic\.(?:aluxvl|apgoap)\.cn[^"]+\.(?:jpe?g|png|webp))"', html)
    if im:
        thumbnail = im.group(1)
    if not thumbnail:
        im2 = re.search(r'<img[^>]*src="(https://pic\.(?:aluxvl|apgoap)\.cn[^"]+)"', html)
        if im2:
            thumbnail = im2.group(1)

    # Videos from DPlayer data-config
    videos: list[dict] = []
    for div_match in re.finditer(r"<div\s[^>]*data-config=([^>]*)>", html):
        div_html = div_match.group()
        for pattern in (r"data-config='([^']*)'", r'data-config="([^"]*)"'):
            cm = re.search(pattern, div_html)
            if cm:
                try:
                    cfg = json.loads(html_mod.unescape(cm.group(1)))
                    cfg = _strip_player_ads(cfg)
                    url = cfg["video"]["url"]
                    vtitle = ""
                    ttm = re.search(r'data-video_title="([^"]*)"', div_html)
                    if ttm:
                        vtitle = html_mod.unescape(ttm.group(1)).strip()
                    if not vtitle:
                        vtitle = title
                    videos.append({"url": url, "title": vtitle, "type": cfg["video"].get("type", "hls")})
                except (KeyError, json.JSONDecodeError):
                    pass
                break

    # Content body — images already fixed during extraction
    body_html = _extract_article_body(html)
    body_html = _sanitize_html(body_html)

    # Related articles
    related = _parse_article_list(html)

    return ArticleDetail(
        id=article_id,
        title=title,
        url=f"/archives/{article_id}/",
        author=author,
        date=date,
        categories=cats,
        thumbnail=thumbnail,
        videos=videos,
        content_html=body_html,
        related=[r for r in related if r.id != article_id][:10],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_categories() -> list[dict]:
    """Return the hard-coded category list (matches original site navigation)."""
    return CATEGORIES


async def get_homepage_feed(proxy_url: str = "") -> ListPage:
    """Get homepage article list via RSS feed for speed."""
    url = f"{BASE_URL}/feed/"
    html = await _fetch(url, proxy_url)
    items = _parse_feed_items(html)
    return ListPage(items=items, page=1, has_next=True, next_page=2)


async def get_category_page(slug: str, page: int = 1, proxy_url: str = "") -> ListPage:
    """Get a paginated list of articles in a category by scraping HTML."""
    if page == 1:
        url = f"{BASE_URL}/category/{slug}/"
    else:
        url = f"{BASE_URL}/category/{slug}/{page}/"

    html = await _fetch(url, proxy_url)
    items = _parse_article_list(html)
    has_next, next_page = _parse_next_page(html, page)

    return ListPage(items=items, page=page, has_next=has_next, next_page=next_page)


async def get_article_detail(article_id: str, proxy_url: str = "") -> ArticleDetail:
    """Get full article detail with videos and sanitized content."""
    url = f"{BASE_URL}/archives/{article_id}/"
    html = await _fetch_api(url, proxy_url)
    return _parse_article_page(html)


async def search_articles(query: str, proxy_url: str = "") -> list[ArticleItem]:
    """Search articles by keyword."""
    url = f"{BASE_URL}/?s={httpx.URL(query).raw_path if hasattr(httpx, 'URL') else __import__('urllib').parse.quote(query)}"
    # Use urllib to encode the query
    from urllib.parse import quote
    url = f"{BASE_URL}/?s={quote(query)}"
    html = await _fetch(url, proxy_url)
    items = _parse_article_list(html)
    return items


def _parse_feed_items(xml_text: str) -> list[ArticleItem]:
    """Parse RSS feed XML into ArticleItem list."""
    items: list[ArticleItem] = []
    seen_ids = set()

    for item_match in re.finditer(r'<item>(.*?)</item>', xml_text, re.DOTALL):
        item_xml = item_match.group(1)

        # Link / ID
        link_m = re.search(r'<link>(?:https?://[^/]+)?(/archives/(\d+)/)</link>', item_xml)
        if not link_m:
            continue
        url = link_m.group(1)
        article_id = link_m.group(2)
        if article_id in seen_ids:
            continue
        seen_ids.add(article_id)

        # Title
        title = ""
        tm = re.search(r'<title>(.*?)</title>', item_xml)
        if tm:
            title = html_mod.unescape(tm.group(1)).strip()

        # Author
        author = ""
        am = re.search(r'<dc:creator>(.*?)</dc:creator>', item_xml)
        if am:
            author = am.group(1).strip()

        # Date
        date = ""
        dm = re.search(r'<pubDate>(.*?)</pubDate>', item_xml)
        if dm:
            date = dm.group(1).strip()

        # Thumbnail - extract first image from content:encoded
        thumbnail = ""
        content_m = re.search(r'<content:encoded[^>]*>(.*?)</content:encoded>', item_xml, re.DOTALL)
        if content_m:
            content = content_m.group(1)
            im = re.search(r'data-xkrkllgl="([^"]+)"', content)
            if im:
                thumbnail = im.group(1)
            if not thumbnail:
                im2 = re.search(r'<img[^>]*src="(https://[^"]+\.(?:jpe?g|png|webp))"', content)
                if im2:
                    thumbnail = im2.group(1)

        # Categories from content
        cats: list[str] = []
        for cm in re.finditer(r'<a[^>]*href="/category/([^/]+)/"[^>]*>([^<]+)</a>', item_xml):
            cats.append(cm.group(2).strip())

        items.append(ArticleItem(
            id=article_id,
            title=title,
            url=url,
            thumbnail=thumbnail,
            author=author,
            date=date,
            categories=cats,
        ))

    return items


async def get_image_proxy(image_url: str, proxy_url: str = "") -> bytes:
    """Proxy a single image, returning its bytes (for CORS avoidance)."""
    proxy = proxy_url.strip() or None
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        proxy=proxy,
    ) as client:
        resp = await client.get(
            image_url,
            headers={"User-Agent": USER_AGENT, "Referer": BASE_URL},
        )
        resp.raise_for_status()
        return resp.content
