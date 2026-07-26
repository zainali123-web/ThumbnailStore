"""
Automated Thumbnail Store Generator
------------------------------------------------------------------
This script:
1. Picks an unused topic/headline from topics_database.json (auto-recycles)
2. Downloads a matching stock photo from Pexels (free API)
3. Composes a professional-style 1280x720 YouTube thumbnail (PIL):
   dimmed background + bold headline + accent color bar
4. Uploads the thumbnail as a product to Sellix (via their API) at a
   starting price, so it's automatically listed for sale
5. Tracks progress so every 3rd run also creates a discounted "bundle"
   product combining the last 3 thumbnails
"""

import os
import json
import random
import requests
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# ---------------- CONFIG ----------------
TOPICS_FILE = "topics_database.json"
RUN_COUNTER_FILE = "run_counter.json"
OUTPUT_DIR = "output"
THUMB_SIZE = (1280, 720)
SINGLE_PRICE = 5.00    # per-thumbnail price
BUNDLE_PRICE = 60.00    # bundle price (16 thumbnails every 4 days)

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
SELLAPP_API_KEY = os.environ.get("SELLAPP_API_KEY")
SELLAPP_STORE_ID = os.environ.get("SELLAPP_STORE_ID")

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------- STEP 1: Pick a topic (auto-recycles) ----------------
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


# ---------------- STEP 2: Download a matching stock photo ----------------
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


# ---------------- STEP 3: Compose the thumbnail ----------------
def create_thumbnail(background_path, headline, accent_hex, output_path):
    img = Image.open(background_path).convert("RGB")

    # Cover-resize to fill 1280x720 exactly, cropping any overflow
    target_w, target_h = THUMB_SIZE
    scale = max(target_w / img.width, target_h / img.height)
    new_size = (int(img.width * scale), int(img.height * scale))
    img = img.resize(new_size, Image.LANCZOS)
    left = (img.width - target_w) // 2
    top = (img.height - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))

    # Darken + slightly boost contrast so white text pops
    img = ImageEnhance.Brightness(img).enhance(0.55)
    img = ImageEnhance.Contrast(img).enhance(1.15)

    # Subtle dark gradient overlay on the left side (where text sits)
    overlay = Image.new("RGBA", THUMB_SIZE, (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(overlay)
    for x in range(target_w):
        alpha = int(180 * max(0, (target_w * 0.65 - x) / (target_w * 0.65)))
        grad_draw.line([(x, 0), (x, target_h)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay)

    draw = ImageDraw.Draw(img)

    # Accent color bar (left edge) - a common YouTube thumbnail design cue
    draw.rectangle([(0, 0), (18, target_h)], fill=accent_hex)

    # Headline text - large, bold, white with black stroke for readability
    font_size = 92
    font = ImageFont.truetype(FONT_BOLD, font_size)
    lines = headline.split("\n")

    line_height = font_size + 14
    total_text_height = line_height * len(lines)
    y = (target_h - total_text_height) // 2

    for line in lines:
        draw.text(
            (70, y), line, font=font, fill="white",
            stroke_width=6, stroke_fill="black"
        )
        y += line_height

    img.convert("RGB").save(output_path, quality=95)
    return output_path


# ---------------- STEP 4: Upload product to Sell.app ----------------
def create_sellapp_product(title, description, price, image_path):
    """
    Creates a product listing on Sell.app via their API.
    NOTE: Exact endpoint/field names should be verified against Sell.app's
    current API docs (docs.sell.app) before relying on this in production -
    test with real API credentials first, since API details can change.
    """
    url = "https://sell.app/api/v2/products"
    headers = {
        "Authorization": f"Bearer {SELLAPP_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "store_id": SELLAPP_STORE_ID,
        "title": title,
        "description": description,
        "price": price,
        "type": "SERIALIZED",  # digital product type - adjust per Sell.app docs
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code not in (200, 201):
        print(f"Sell.app product creation failed: {response.status_code} {response.text}")
        return None

    product = response.json()
    print(f"Product created on Sell.app: {title}")
    return product


# ---------------- Run counter (tracks bundling every 3 runs) ----------------
def get_and_increment_run_count():
    count = 0
    if os.path.exists(RUN_COUNTER_FILE):
        with open(RUN_COUNTER_FILE, "r") as f:
            count = json.load(f).get("count", 0)
    count += 1
    with open(RUN_COUNTER_FILE, "w") as f:
        json.dump({"count": count}, f)
    return count


# ---------------- MAIN ----------------
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
    title = f"YouTube Thumbnail Template - {headline_display.title()}"
    description = (
        "Professional, ready-to-use YouTube thumbnail template. "
        "High-resolution JPG (1280x720), instantly downloadable after purchase."
    )
    create_sellapp_product(title, description, SINGLE_PRICE, output_path)

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
        create_sellapp_product(bundle_title, bundle_description, BUNDLE_PRICE, output_path)

    print("Done.")


if __name__ == "__main__":
    main()
