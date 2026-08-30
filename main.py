"""
Automated Thumbnail Store Generator (Sell.app)
------------------------------------------------------------------
Generates a professional-style YouTube thumbnail, uploads it as a
product+variant on Sell.app (with confirmed field structure pulled
directly from Sell.app's own API), and every 16 runs (4/day x 4 days)
also creates a bundle listing.
"""

import os
import json
import random
import re
import time
import datetime
import requests
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# ---------------- CONFIG ----------------
TOPICS_FILE = "topics_database.json"
RUN_COUNTER_FILE = "run_counter.json"
OUTPUT_DIR = "output"
THUMB_SIZE = (1280, 720)
SINGLE_PRICE_CENTS = 500     # $5.00
BUNDLE_PRICE_CENTS = 3000    # $30.00

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
SELLAPP_API_KEY = os.environ.get("SELLAPP_API_KEY")
SELLAPP_STORE_ID = os.environ.get("SELLAPP_STORE_ID")

# Used to pull today's real trending YouTube topics instead of cycling a
# fixed static list - see fetch_trending_topic(). Falls back to
# TOPICS_FILE below if this isn't set or the API call fails.
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
TRENDING_USED_FILE = "trending_used.json"
# A handful of category IDs to pull from so results aren't just Music/
# Movies/Gaming (YouTube narrowed the general "mostPopular" chart to just
# those three in July 2025). None = the general chart.
TRENDING_CATEGORY_IDS = ["26", "28", "22", "24"]  # Howto&Style, Science&Tech, People&Blogs, Entertainment
# Dropped: None/general (now Music/Movies/Gaming only, since YouTube's July
# 2025 change - not a fit for clickbait vlog/how-to style thumbnails).
# Dropped: 27 (Education) - 404s for this chart/region combo.
ACCENT_COLORS = ["#3355AA", "#D8362A", "#1E9E62", "#8B3FD1"]  # rotates daily

# Used to host generated thumbnails at a public URL so Sell.app's "Manual"
# deliverable (a link/comment shown to the buyer) can point somewhere real.
# ThumbnailStore itself is private, so images are pushed to a SEPARATE
# public repo instead - see the setup notes above create_sellapp_variant().
ASSET_TOKEN = os.environ.get("ASSET_TOKEN")
ASSET_REPO = os.environ.get("ASSET_REPO")     # e.g. "zainali123-web/thumbnail-assets"
ASSET_BRANCH = os.environ.get("ASSET_BRANCH", "main")

# Used to auto-post each new thumbnail to Pinterest via Buffer, and to link
# each pin back to the actual Sell.app product page.
BUFFER_API_KEY = os.environ.get("BUFFER_API_KEY")
BUFFER_PINTEREST_CHANNEL_ID = os.environ.get("BUFFER_PINTEREST_CHANNEL_ID")
BUFFER_PINTEREST_BOARD_ID = os.environ.get("BUFFER_PINTEREST_BOARD_ID")  # fallback/default board

# One board per trending category, so pins land on a topically-focused
# board instead of a single generic one (better Pinterest SEO - boards are
# "topical signals" to Pinterest's algorithm). Falls back to
# BUFFER_PINTEREST_BOARD_ID above if a specific one isn't set.
BUFFER_BOARD_BY_CATEGORY = {
    "26": os.environ.get("BUFFER_BOARD_HOWTO"),          # Howto & Style
    "28": os.environ.get("BUFFER_BOARD_TECH"),           # Science & Technology
    "22": os.environ.get("BUFFER_BOARD_PEOPLE"),         # People & Blogs
    "24": os.environ.get("BUFFER_BOARD_ENTERTAINMENT"),  # Entertainment
}
STORE_DOMAIN = os.environ.get("STORE_DOMAIN")   # e.g. "yourstore.sell.app"

PIN_SIZE = (1000, 1500)  # Pinterest's recommended 2:3 vertical ratio

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

os.makedirs(OUTPUT_DIR, exist_ok=True)


STOPWORDS = {
    "the", "a", "an", "how", "to", "this", "i", "my", "is", "of", "in", "on",
    "for", "with", "and", "you", "your", "we", "our", "vs", "official",
    "video", "new", "it", "at", "be", "so", "just", "me", "that",
}


_TRAILING_TRIM = {"for", "and", "or", "the", "a", "an", "to", "with", "in", "on", "of", "at", "so", "but"}


def _clean_headline(title):
    """Turns a raw video title into a short, thumbnail-style ALL CAPS
    headline: strips channel-branding suffixes and bracketed tags, trims
    to a punchy length, and avoids ending on a dangling connector word."""
    title = title.split("|")[0]
    title = re.sub(r"[\(\[].*?[\)\]]", "", title)
    title = title.strip(" -:\u2013\u2014")
    words = title.split()[:6]
    while words and words[-1].lower() in _TRAILING_TRIM:
        words.pop()
    return " ".join(words).upper() if words else "TRENDING NOW"


def _extract_keyword(title):
    """Pulls a short, stopword-free phrase from the title to use as the
    Pexels stock-photo search query."""
    words = [w.strip(".,!?:;\"'()[]") for w in title.split()]
    significant = [w for w in words if w.lower() not in STOPWORDS and len(w) > 2]
    return " ".join(significant[:3]) if significant else "youtube trending"


_MUSIC_MARKERS = (
    "official video", "official music video", "lyric video", "lyrics",
    "official audio", "video oficial", "official mv", "audio oficial",
    " ft.", " feat.", "(mv)",
)


def _looks_like_music_video(title):
    """Filters out music tracks that slip through even from non-music
    categories - not a fit for a clickbait vlog/how-to thumbnail store."""
    t = title.lower()
    return any(marker in t for marker in _MUSIC_MARKERS)


def fetch_trending_topic():
    """
    Pulls today's trending YouTube videos across a few categories, picks
    one not already used today, and derives a thumbnail headline + a
    Pexels search keyword from it. Returns None (triggering the static
    topics_database.json fallback in get_next_topic) if YOUTUBE_API_KEY
    isn't set, the request fails, or every trending video today has
    already been used.
    """
    if not YOUTUBE_API_KEY:
        print("YOUTUBE_API_KEY not set - falling back to static topics database.")
        return None

    today = datetime.date.today().isoformat()
    used = {}
    if os.path.exists(TRENDING_USED_FILE):
        with open(TRENDING_USED_FILE, "r") as f:
            used = json.load(f)
    used_today = set(used.get(today, []))

    candidates = []
    for category_id in TRENDING_CATEGORY_IDS:
        params = {
            "part": "snippet",
            "chart": "mostPopular",
            "regionCode": "US",
            "maxResults": 15,
            "key": YOUTUBE_API_KEY,
        }
        if category_id:
            params["videoCategoryId"] = category_id
        try:
            response = requests.get(
                "https://www.googleapis.com/youtube/v3/videos", params=params, timeout=15
            )
            response.raise_for_status()
            items = response.json().get("items", [])
        except Exception as e:
            print(f"YouTube trending fetch failed for category {category_id}: {e}")
            continue
        for item in items:
            vid = item.get("id")
            title = item.get("snippet", {}).get("title")
            if vid and title and vid not in used_today and not _looks_like_music_video(title):
                candidates.append((vid, title, category_id))

    if not candidates:
        print("No unused trending videos found today - falling back to static topics database.")
        return None

    video_id, title, category_id = random.choice(candidates)
    print(f"Trending topic: {title}")

    used.setdefault(today, []).append(video_id)
    used = dict(sorted(used.items())[-14:])  # keep ~2 weeks of history, no more
    with open(TRENDING_USED_FILE, "w") as f:
        json.dump(used, f, indent=2)

    return {
        "id": video_id,
        "headline": _clean_headline(title),
        "keyword": _extract_keyword(title),
        "accent_color": random.choice(ACCENT_COLORS),
        "category_id": category_id,
    }


def get_next_topic():
    trending = fetch_trending_topic()
    if trending:
        return trending

    with open(TOPICS_FILE, "r") as f:
        data = json.load(f)
    unused = [t for t in data["topics"] if not t["used"]]
    if not unused:
        for t in data["topics"]:
            t["used"] = False
        unused = data["topics"]
    topic = random.choice(unused)
    for t in data["topics"]:
        if t["id"] == topic["id"]:
            t["used"] = True
    with open(TOPICS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    topic.setdefault("category_id", None)
    return topic


def download_stock_photo(keyword, output_path="background.jpg"):
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": keyword, "orientation": "landscape", "per_page": 10}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    results = response.json()
    if not results.get("photos"):
        raise Exception(f"No stock photo found for keyword: {keyword}")
    photo = random.choice(results["photos"])
    photo_url = photo["src"]["large2x"]
    photo_data = requests.get(photo_url)
    with open(output_path, "wb") as f:
        f.write(photo_data.content)
    return output_path


def create_thumbnail(background_path, headline, accent_hex, output_path):
    img = Image.open(background_path).convert("RGB")
    target_w, target_h = THUMB_SIZE
    scale = max(target_w / img.width, target_h / img.height)
    new_size = (int(img.width * scale), int(img.height * scale))
    img = img.resize(new_size, Image.LANCZOS)
    left = (img.width - target_w) // 2
    top = (img.height - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))

    img = ImageEnhance.Brightness(img).enhance(0.55)
    img = ImageEnhance.Contrast(img).enhance(1.15)

    overlay = Image.new("RGBA", THUMB_SIZE, (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(overlay)
    for x in range(target_w):
        alpha = int(180 * max(0, (target_w * 0.65 - x) / (target_w * 0.65)))
        grad_draw.line([(x, 0), (x, target_h)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay)

    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (18, target_h)], fill=accent_hex)

    font_size = 92
    font = ImageFont.truetype(FONT_BOLD, font_size)
    lines = headline.split("\n")
    line_height = font_size + 14
    total_text_height = line_height * len(lines)
    y = (target_h - total_text_height) // 2
    for line in lines:
        draw.text((70, y), line, font=font, fill="white", stroke_width=6, stroke_fill="black")
        y += line_height

    img.convert("RGB").save(output_path, quality=95)
    return output_path


def upload_image_publicly(image_path):
    """
    Uploads the generated thumbnail to a separate PUBLIC GitHub repo via
    GitHub's own Contents API, and returns a public jsdelivr CDN URL for it
    (not raw.githubusercontent.com - see note below). ThumbnailStore itself
    stays private; only images go to the public repo, one file per
    thumbnail.

    NOTE on jsdelivr vs raw.githubusercontent.com: raw.githubusercontent.com
    is NOT reliable for third-party services (like Pinterest/Buffer) to
    fetch from - it can take anywhere from a few seconds to ~1 minute to
    propagate a brand-new file across GitHub's CDN, and content-type
    headers are inconsistent. jsdelivr's GitHub mirror (cdn.jsdelivr.net/gh/)
    is built specifically for hot-linking and is what we use instead.

    One-time setup needed (not per-run - do this once):
      1. Create a new PUBLIC repo, e.g. "thumbnail-assets", under the same
         GitHub account/org.
      2. Create a GitHub Personal Access Token with write access to just
         that repo (Settings -> Developer settings -> Fine-grained tokens ->
         Repository access: only "thumbnail-assets" -> Permissions:
         Contents: Read and write).
      3. In the ThumbnailStore repo -> Settings -> Secrets and variables ->
         Actions, add:
           - ASSET_TOKEN = the token from step 2
           - ASSET_REPO  = "yourusername/thumbnail-assets"
      4. In the workflow YAML (the step that runs `python main.py`), add
         these two as extra env vars alongside the existing ones:
           ASSET_TOKEN: ${{ secrets.ASSET_TOKEN }}
           ASSET_REPO: ${{ secrets.ASSET_REPO }}
    After that, every run uploads and links automatically - no manual step.
    """
    import base64

    if not ASSET_TOKEN or not ASSET_REPO:
        raise Exception(
            "ASSET_TOKEN / ASSET_REPO not set - see the "
            "one-time setup notes in upload_image_publicly()'s docstring."
        )

    # Defensive: strip accidental whitespace/newlines that can sneak in when
    # copy-pasting secret values - a stray newline in a token or repo name is
    # a common, hard-to-spot cause of 404s from the GitHub API.
    asset_token = ASSET_TOKEN.strip()
    asset_repo = ASSET_REPO.strip()
    asset_branch = ASSET_BRANCH.strip()

    filename = os.path.basename(image_path)
    unique_prefix = str(int(time.time() * 1000))
    repo_path = f"images/{unique_prefix}_{filename}"

    with open(image_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode("utf-8")

    api_url = f"https://api.github.com/repos/{asset_repo}/contents/{repo_path}"
    headers = {
        "Authorization": f"Bearer {asset_token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "message": f"Add thumbnail {filename}",
        "content": content_b64,
        "branch": asset_branch,
    }

    response = requests.put(api_url, headers=headers, json=payload)
    if response.status_code not in (200, 201):
        raise Exception(f"Public asset upload failed: {response.status_code} {response.text}")

    commit_sha = response.json().get("commit", {}).get("sha", asset_branch)
    # Pin to the exact commit SHA (not the branch name) - jsdelivr caches
    # branch-based URLs aggressively and can keep serving 404/stale content
    # for a brand-new file; a SHA-pinned URL is always correct on first
    # fetch since that exact SHA+path combination has never been requested
    # (and therefore never cached) before.
    jsdelivr_url = f"https://cdn.jsdelivr.net/gh/{asset_repo}@{commit_sha}/{repo_path}"

    _wait_until_url_is_live(jsdelivr_url)

    print(f"Image uploaded publicly: {jsdelivr_url}")
    return jsdelivr_url


def _wait_until_url_is_live(url, attempts=8, delay_seconds=4):
    """
    Polls a freshly-uploaded asset URL until it actually returns a real
    image (not a 404/placeholder), so we never hand Buffer/Pinterest a URL
    that isn't fetchable yet. jsdelivr fetches a file from GitHub on its
    OWN first request and caches it - so the very first request can still
    404 while that fetch happens; this loop specifically covers that gap
    (this was the root cause of the "Pinterest is hitting some snags with
    the Source URL" publish failures). Doesn't raise on final failure -
    lets the caller's Pinterest post attempt fail naturally with a clear
    error message instead of crashing the whole run.
    """
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, timeout=15)
            content_type = resp.headers.get("Content-Type", "")
            if resp.status_code == 200 and content_type.startswith("image/"):
                print(f"[debug] Asset URL confirmed live after {attempt} attempt(s).")
                return True
            print(f"[debug] Asset not live yet (attempt {attempt}/{attempts}): "
                  f"status={resp.status_code} content-type={content_type!r}")
        except requests.RequestException as e:
            print(f"[debug] Asset check failed (attempt {attempt}/{attempts}): {e}")
        time.sleep(delay_seconds)
    print(f"[debug] WARNING: asset URL still not confirmed live after {attempts} attempts: {url}")
    return False


def smart_title(text):
    """Like str.title(), but doesn't mangle apostrophes (str.title() turns
    "lock's" into "Lock'S" because it treats the apostrophe as a word
    boundary). Only capitalizes the first letter of each space-separated
    word instead."""
    return " ".join(w[:1].upper() + w[1:].lower() if w else w for w in text.split(" "))


def _wrap_text(draw, text, font, max_width):
    """Simple word-wrap helper: splits text into lines that fit max_width."""
    words = text.split(" ")
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generate_pinterest_pin(thumbnail_path, headline, accent_hex, output_path):
    """
    Builds a vertical Pinterest pin graphic: the thumbnail on top, then
    price/stock/payment info below, laid out left/right, ending in a
    call-to-action bar. This is a separate image from the product thumbnail
    itself - Pinterest strongly favors tall pins over the landscape 16:9
    thumbnail format. Height is computed from actual content so there's no
    dead space before the CTA bar.
    """
    pin_w = PIN_SIZE[0]
    top_h = int(pin_w * 0.5)  # thumbnail strip height

    thumb = Image.open(thumbnail_path).convert("RGB")
    scale = pin_w / thumb.width
    thumb = thumb.resize((pin_w, int(thumb.height * scale)), Image.LANCZOS)
    if thumb.height > top_h:
        top = (thumb.height - top_h) // 2
        thumb = thumb.crop((0, top, pin_w, top + top_h))
    else:
        top_h = thumb.height

    # Tall scratch canvas to draw on, cropped to actual content height at the end
    scratch_h = PIN_SIZE[0] * 3
    pin = Image.new("RGB", (pin_w, scratch_h), "white")
    pin.paste(thumb, (0, 0))

    draw = ImageDraw.Draw(pin)
    font_price = ImageFont.truetype(FONT_BOLD, 90)
    font_label = ImageFont.truetype(FONT_BOLD, 30)
    font_body = ImageFont.truetype(FONT_REGULAR, 26)
    font_small = ImageFont.truetype(FONT_REGULAR, 22)
    font_cta = ImageFont.truetype(FONT_BOLD, 48)

    # --- limited stock badge, top-right of the thumbnail ---
    badge_text = "LIMITED STOCK"
    badge_w = draw.textlength(badge_text, font=font_label) + 40
    draw.rectangle([pin_w - badge_w - 30, 30, pin_w - 30, 90], fill="#D8362A")
    draw.text((pin_w - badge_w - 10, 42), badge_text, font=font_label, fill="white")

    y = top_h + 50

    # --- price ---
    draw.text((50, y), "$5", font=font_price, fill="black")
    draw.text((210, y + 34), "instant download", font=font_body, fill="#555555")
    y += 150

    # --- left/right info cards: crypto only | pay with card ---
    card_top = y
    card_h = 110
    card_w = (pin_w - 120) // 2
    draw.rectangle([50, card_top, 50 + card_w, card_top + card_h], outline="#DDDDDD", width=2)
    draw.text((50 + 24, card_top + 20), "CRYPTO ONLY", font=font_label, fill="black")
    draw.text((50 + 24, card_top + 62), "accepted payment", font=font_small, fill="#777777")

    right_x = 50 + card_w + 20
    draw.rectangle([right_x, card_top, right_x + card_w, card_top + card_h], outline=accent_hex, width=2)
    draw.text((right_x + 24, card_top + 20), "PAY WITH CARD", font=font_label, fill="black")
    draw.text((right_x + 24, card_top + 62), "via MoonPay - see below", font=font_small, fill="#777777")
    y = card_top + card_h + 60

    # --- 3 steps: how to pay with card using MoonPay ---
    draw.text((50, y), "How to pay with card:", font=font_label, fill="black")
    y += 60
    steps = [
        "1. Buy SOL with your card on MoonPay",
        "2. Send the SOL to our wallet address",
        "3. Get your instant download",
    ]
    for step in steps:
        for line in _wrap_text(draw, step, font_body, pin_w - 100):
            draw.text((50, y), line, font=font_body, fill="#333333")
            y += 38
        y += 12

    # --- bottom CTA bar, positioned right after the content (no gap) ---
    cta_h = 130
    cta_top = y + 30
    draw.rectangle([0, cta_top, pin_w, cta_top + cta_h], fill=accent_hex)
    cta_text = "Shop now"
    cta_w = draw.textlength(cta_text, font=font_cta)
    draw.text(((pin_w - cta_w) / 2, cta_top + (cta_h - 48) / 2), cta_text, font=font_cta, fill="white")

    final_h = cta_top + cta_h
    pin = pin.crop((0, 0, pin_w, final_h))
    pin.save(output_path, quality=95)
    return output_path


def build_pinterest_copy(headline_display):
    """
    SEO-oriented title + description for the Pinterest post. Per current
    Pinterest SEO guidance: keyword-rich title/description carry the
    ranking weight, not hashtags - so hashtags are kept to 1-2 at the very
    end rather than stuffed throughout.
    """
    title = f"{smart_title(headline_display)} - YouTube Thumbnail Template | High CTR Clickbait Design"
    description = (
        f"\"{smart_title(headline_display)}\" YouTube thumbnail template - a high-converting, "
        "ready-to-use clickbait-style design made for content creators, vloggers, and "
        "video editors who want more clicks. Instant digital download, 1280x720 "
        "YouTube-standard size. #youtubethumbnail #thumbnaildesign"
    )
    return title, description


def get_product_url(product, slug_fallback=None):
    """
    Best-effort extraction of the live product page URL from Sell.app's
    product creation response. Field name isn't confirmed against Sell.app's
    schema, so this tries a few likely candidates and falls back to the
    store homepage rather than failing the whole run if none match.
    """
    data = (product or {}).get("data", {})
    for key in ("url", "permalink", "product_url"):
        if data.get(key):
            return data[key]
    slug = data.get("slug") or slug_fallback
    if STORE_DOMAIN and slug:
        return f"https://{STORE_DOMAIN}/product/{slug}"
    if STORE_DOMAIN:
        return f"https://{STORE_DOMAIN}"
    return None


def post_to_buffer_pinterest(image_url, title, description, link, category_id=None):
    """
    Posts the pin to Pinterest via Buffer's API (createPost mutation),
    using addToQueue so it goes out on Buffer's normal posting schedule
    rather than all at once. Routes to the board matching category_id if
    one is configured, otherwise falls back to BUFFER_PINTEREST_BOARD_ID.
    """
    chosen_board = BUFFER_BOARD_BY_CATEGORY.get(category_id) or BUFFER_PINTEREST_BOARD_ID
    if not BUFFER_API_KEY or not BUFFER_PINTEREST_CHANNEL_ID or not chosen_board:
        print("Buffer/Pinterest not configured - skipping Pinterest post.")
        return None

    # Defensive: strip accidental whitespace/newlines from copy-pasted secret
    # values - this exact class of bug (extra chars breaking an ID) already
    # bit us once with ASSET_REPO.
    channel_id = BUFFER_PINTEREST_CHANNEL_ID.strip()
    board_id = chosen_board.strip()
    print(f"[debug] using board for category {category_id!r}")
    print(f"[debug] channelId length = {len(channel_id)} (expect 24 for a Buffer channel id)")
    print(f"[debug] boardId length = {len(board_id)}")

    query = """
    mutation CreatePin($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess {
          post { id dueAt }
        }
        ... on MutationError {
          message
        }
      }
    }
    """
    variables = {
        "input": {
            "text": description,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "addToQueue",
            "assets": [{"image": {"url": image_url}}],
            "metadata": {
                "pinterest": {
                    "title": title,
                    "url": link,
                    "boardServiceId": board_id,
                }
            },
        }
    }
    response = requests.post(
        "https://api.buffer.com",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {BUFFER_API_KEY}",
        },
        json={"query": query, "variables": variables},
    )
    result = response.json()
    print(f"[debug] Buffer response: {json.dumps(result)[:2000]}")

    top_level_errors = result.get("errors")
    if top_level_errors:
        print(f"Buffer/Pinterest post failed (API-level error): {top_level_errors}")
        return None

    data = result.get("data") or {}
    create_post = data.get("createPost") or {}
    message = create_post.get("message")
    if message:
        print(f"Buffer/Pinterest post failed: {message}")
        return None

    print("Pin queued on Pinterest via Buffer.")
    return result


def create_sellapp_product(title, description):
    """STEP A: Create base product"""
    url = "https://sell.app/api/v2/products"
    headers = {
        "Authorization": f"Bearer {SELLAPP_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "store_id": SELLAPP_STORE_ID,
        "title": title,
        "description": description,
        "visibility": "PUBLIC",
        "type": "product",
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code not in (200, 201):
        print(f"Sell.app product creation failed: {response.status_code} {response.text}")
        return None
    product = response.json()
    print(f"Product created on Sell.app: {title}")
    return product


def create_sellapp_variant(product_id, price_cents, image_url):
    """
    STEP B: Create variant with confirmed JSON structure.

    This structure was captured directly from Sell.app's own dashboard
    (via DevTools -> Network -> Payload while saving a real product), so
    these field names/values are confirmed, not guesses:

      - pricing.price is a flat OBJECT: {"price": ..., "currency": "USD"}
      - pricing.humble is required (False = fixed price, not
        "pay what you want")
      - payment_methods must match what's actually connected on the store
        - this store only has Solana connected, so ["SOL"]
      - minimum_purchase_quantity is required
      - deliverable.types uses "MANUAL" for a manually-delivered
        link/message (Sell.app's dashboard calls this "Static Value" in
        the UI, but the underlying type value is "MANUAL")
      - deliverable.data.comment holds the actual text/link shown to the
        buyer after purchase - this is where the public download link for
        the thumbnail goes
    """
    url = f"https://sell.app/api/v2/products/{product_id}/variants"
    headers = {
        "Authorization": f"Bearer {SELLAPP_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    payload = {
        "title": "Default Variant",
        "description": "Instant download thumbnail template",
        "minimum_purchase_quantity": 1,
        "payment_methods": ["SOL"],
        "pricing": {
            "price": {
                "price": price_cents,
                "currency": "USD"
            },
            "humble": False
        },
        "deliverable": {
            "types": ["MANUAL"],
            "data": {
                "comment": f"Here is your thumbnail download link: {image_url}"
            }
        }
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code not in (200, 201):
        print(f"Sell.app variant creation failed: {response.status_code} {response.text}")
        return None

    variant = response.json()
    print(f"Variant created with price ${price_cents/100:.2f}.")
    return variant


def create_full_sellapp_listing(title, description, price_cents, image_path, headline_display, accent_hex, category_id=None):
    """Combines: upload image publicly -> create product -> create variant -> post pin to Pinterest"""
    image_url = upload_image_publicly(image_path)
    product = create_sellapp_product(title, description)
    if not product or "data" not in product or "id" not in product["data"]:
        print("Skipping variant creation - product creation did not return a valid ID.")
        return None
    product_id = product["data"]["id"]
    variant = create_sellapp_variant(product_id, price_cents, image_url)

    product_url = get_product_url(product)
    print(f"[debug] product_url for Pinterest link = {product_url}")
    if product_url:
        try:
            print("Creating Pinterest pin...")
            pin_path = os.path.join(OUTPUT_DIR, f"pin_{os.path.basename(image_path)}")
            generate_pinterest_pin(image_path, headline_display, accent_hex, pin_path)
            pin_image_url = upload_image_publicly(pin_path)
            pin_title, pin_description = build_pinterest_copy(headline_display)
            post_to_buffer_pinterest(pin_image_url, pin_title, pin_description, product_url, category_id)
        except Exception as e:
            # Pinterest/Buffer is a marketing nice-to-have - never let a
            # failure here crash the run or block the tracking-file commit.
            print(f"Pinterest posting failed (non-fatal, continuing): {e}")
    else:
        print("No product URL available (STORE_DOMAIN not set) - skipping Pinterest post.")

    return variant


def get_and_increment_run_count():
    count = 0
    if os.path.exists(RUN_COUNTER_FILE):
        with open(RUN_COUNTER_FILE, "r") as f:
            count = json.load(f).get("count", 0)
    count += 1
    with open(RUN_COUNTER_FILE, "w") as f:
        json.dump({"count": count}, f)
    return count


def main():
    print("Picking a topic...")
    topic = get_next_topic()
    headline_display = topic["headline"].replace("\n", " ")
    print(f"Topic: {headline_display}")

    print("Downloading stock photo...")
    bg_path = download_stock_photo(topic["keyword"])

    print("Creating thumbnail...")
    output_path = os.path.join(OUTPUT_DIR, f"thumbnail_{topic['id']}.jpg")
    create_thumbnail(bg_path, topic["headline"], topic["accent_color"], output_path)

    print("Uploading to Sell.app...")
    title = f"YouTube Thumbnail Template | Clickbait Design | {smart_title(headline_display)} | High CTR"
    description = (
        "Professional, ready-to-use YouTube thumbnail template designed for high click-through rate (CTR). "
        "Perfect for YouTubers, content creators, vloggers, and video editors who want eye-catching, "
        "clickbait-style thumbnails that stand out in search and suggested feeds. "
        "High-resolution JPG (1280x720, YouTube-standard size), instantly downloadable after purchase. "
        "Keywords: youtube thumbnail template, clickbait thumbnail, thumbnail design, content creator template, "
        "video thumbnail, high CTR thumbnail, youtube graphics."
    )
    create_full_sellapp_listing(title, description, SINGLE_PRICE_CENTS, output_path, headline_display, topic["accent_color"], topic.get("category_id"))

    run_count = get_and_increment_run_count()
    RUNS_PER_DAY = 4
    BUNDLE_EVERY_DAYS = 4
    bundle_trigger_every_n_runs = RUNS_PER_DAY * BUNDLE_EVERY_DAYS  # = 16

    if run_count % bundle_trigger_every_n_runs == 0:
        print("Every-4-day bundle trigger - creating bundle listing...")
        bundle_title = f"16-Pack Thumbnail Bundle #{run_count // bundle_trigger_every_n_runs}"
        bundle_description = (
            "A bundle of 16 professional YouTube thumbnail templates at a "
            "discounted price. High-resolution, instantly downloadable."
        )
        create_full_sellapp_listing(bundle_title, bundle_description, BUNDLE_PRICE_CENTS, output_path, headline_display, topic["accent_color"], topic.get("category_id"))

    print("Done.")


if __name__ == "__main__":
    main()
