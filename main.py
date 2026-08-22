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

# Used to host generated thumbnails at a public URL so Sell.app's "Manual"
# deliverable (a link/comment shown to the buyer) can point somewhere real.
# ThumbnailStore itself is private, so images are pushed to a SEPARATE
# public repo instead - see the setup notes above create_sellapp_variant().
ASSET_TOKEN = os.environ.get("ASSET_TOKEN")
ASSET_REPO = os.environ.get("ASSET_REPO")     # e.g. "zainali123-web/thumbnail-assets"
ASSET_BRANCH = os.environ.get("ASSET_BRANCH", "main")

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_next_topic():
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
    GitHub's own Contents API, and returns a public raw.githubusercontent.com
    URL for it. ThumbnailStore itself stays private; only images go to the
    public repo, one file per thumbnail.

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
    repo_path = f"images/{filename}"

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

    raw_url = f"https://raw.githubusercontent.com/{asset_repo}/{asset_branch}/{repo_path}"
    print(f"Image uploaded publicly: {raw_url}")
    return raw_url


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


def create_full_sellapp_listing(title, description, price_cents, image_path):
    """Combines: upload image publicly -> create product -> create variant"""
    image_url = upload_image_publicly(image_path)
    product = create_sellapp_product(title, description)
    if not product or "data" not in product or "id" not in product["data"]:
        print("Skipping variant creation - product creation did not return a valid ID.")
        return None
    product_id = product["data"]["id"]
    return create_sellapp_variant(product_id, price_cents, image_url)


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
    title = f"YouTube Thumbnail Template | Clickbait Design | {headline_display.title()} | High CTR"
    description = (
        "Professional, ready-to-use YouTube thumbnail template designed for high click-through rate (CTR). "
        "Perfect for YouTubers, content creators, vloggers, and video editors who want eye-catching, "
        "clickbait-style thumbnails that stand out in search and suggested feeds. "
        "High-resolution JPG (1280x720, YouTube-standard size), instantly downloadable after purchase. "
        "Keywords: youtube thumbnail template, clickbait thumbnail, thumbnail design, content creator template, "
        "video thumbnail, high CTR thumbnail, youtube graphics."
    )
    create_full_sellapp_listing(title, description, SINGLE_PRICE_CENTS, output_path)

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
        create_full_sellapp_listing(bundle_title, bundle_description, BUNDLE_PRICE_CENTS, output_path)

    print("Done.")


if __name__ == "__main__":
    main()
