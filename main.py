"""
Automated Thumbnail Store Generator (Sell.app)
------------------------------------------------------------------
Generates a professional-style YouTube thumbnail and uploads it
to Sell.app with proper Pricing ($5.00), Unlimited Stock, and Deliverable.
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


def create_sellapp_product(title, description, price_cents, image_path):
    url = "https://sell.app/api/v2/products"
    headers = {
        "Authorization": f"Bearer {SELLAPP_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    price_dollars = f"{price_cents / 100:.2f}"

    # Main Payload with direct Pricing & Deliverable
    payload = {
        "title": title,
        "description": description,
        "visibility": "PUBLIC",
        "price": price_cents,
        "currency": "USD",
        "pricing": {
            "type": "SINGLE_PAYMENT",
            "price": {
                "price": price_dollars,
                "currency": "USD"
            }
        },
        "stock": -1,
        "unlimited_stock": True,
        "deliverable": {
            "type": "TEXT",
            "data": {
                "text": "Thank you for your purchase! Your high-resolution YouTube thumbnail template is ready."
            }
        }
    }

    print("Uploading Product to Sell.app...", flush=True)
    resp = requests.post(url, headers=headers, json=payload)
    print(f"Sell.app API Status Code: {resp.status_code}", flush=True)
    print(f"Sell.app API Response: {resp.text}", flush=True)

    if resp.status_code not in (200, 201):
        print(f"ERROR: Product creation failed with code {resp.status_code}", flush=True)
        return None

    res_json = resp.json()
    product_id = res_json.get("id")
    if not product_id and "data" in res_json and isinstance(res_json["data"], dict):
        product_id = res_json["data"].get("id")

    # Fallback Variant Attach Call (in case Sell.app requires separate variant record)
    if product_id:
        variant_url = f"https://sell.app/api/v2/products/{product_id}/variants"
        variant_payload = {
            "title": "Standard License",
            "description": "High-resolution thumbnail template download",
            "stock": -1,
            "unlimited_stock": True,
            "pricing": {
                "type": "SINGLE_PAYMENT",
                "price": {
                    "price": price_dollars,
                    "currency": "USD"
                }
            },
            "deliverable": {
                "type": "TEXT",
                "data": {
                    "text": "Thank you for your purchase!"
                }
            }
        }
        print(f"Attaching Variant to Product ID: {product_id}...", flush=True)
        var_resp = requests.post(variant_url, headers=headers, json=variant_payload)
        print(f"Variant API Status: {var_resp.status_code}", flush=True)
        print(f"Variant API Response: {var_resp.text}", flush=True)

    return res_json


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
    print("--- STARTING THUMBNAIL GENERATOR ---", flush=True)

    print("Picking a topic...", flush=True)
    topic = get_next_topic()
    headline_display = topic["headline"].replace("\n", " ")
    print(f"Topic: {headline_display}", flush=True)

    print("Downloading stock photo...", flush=True)
    bg_path = download_stock_photo(topic["keyword"])

    print("Creating thumbnail...", flush=True)
    output_path = os.path.join(OUTPUT_DIR, f"thumbnail_{topic['id']}.jpg")
    create_thumbnail(bg_path, topic["headline"], topic["accent_color"], output_path)

    print("Uploading to Sell.app...", flush=True)
    title = f"YouTube Thumbnail Template | Clickbait Design | {headline_display.title()} | High CTR"
    description = (
        "Professional, ready-to-use YouTube thumbnail template designed for high click-through rate (CTR). "
        "High-resolution JPG (1280x720, YouTube-standard size), instantly downloadable after purchase."
    )
    create_sellapp_product(title, description, SINGLE_PRICE_CENTS, output_path)

    run_count = get_and_increment_run_count()
    if run_count % 16 == 0:
        print("Creating bundle listing...", flush=True)
        bundle_title = f"16-Pack Thumbnail Bundle #{run_count // 16}"
        bundle_description = "A bundle of 16 professional YouTube thumbnail templates."
        create_sellapp_product(bundle_title, bundle_description, BUNDLE_PRICE_CENTS, output_path)

    print("--- PROCESS COMPLETED SUCCESSFULLY ---", flush=True)


if __name__ == "__main__":
    main()
