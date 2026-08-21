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


def create_sellapp_variant(product_id, price_cents, image_path):
    """
    STEP B: Create variant with valid JSON structure

    Fixes applied vs the previous version, based on the 422 errors seen:
      1. pricing.price entries use the key "price" (not "amount") -
         Sell.app's validator literally requires "pricing.price.price".
      2. "minimum_purchase_quantity" is a required top-level field - added.
      3. deliverable.types value changed to lowercase "downloadable_files".
         Sell.app rejected the uppercase "DOWNLOADABLE_FILES" as an invalid
         option, so this assumes their accepted values are lowercase
         snake_case. If this specific string still comes back invalid,
         open the Sell.app dashboard, manually create a product with a
         "Downloadable Files" deliverable, and check the Network tab in
         DevTools for the exact string sent in deliverable.types - use
         that literal value here instead.
      4. "payment_methods" was hardcoded to ["stripe", "paypal"], which
         Sell.app rejected with "Payment Method stripe is not allowed" /
         "paypal is not allowed" - meaning those gateways aren't actually
         connected on this store. The key is removed here so Sell.app
         falls back to whatever payment methods the store has enabled.
         If you want to explicitly restrict it, connect Stripe/PayPal at
         sell.app/dashboard/settings?settings=payment first, then add
         "payment_methods": ["stripe", "paypal"] back in.
      5. Removed "humble" - not a confirmed/required field, and it wasn't
         mentioned anywhere in Sell.app's own docs, so it's safer left out
         until confirmed.

    NOTE (separate from the validation errors): this still only sends the
    local *filename* in deliverable.data, not the actual file content. For
    the product to deliver a real file to buyers, the image likely needs
    to be uploaded to Sell.app first (a file-upload endpoint returning a
    file id/URL), with that reference used in deliverable.data instead of
    just the filename. Worth double-checking against Sell.app's Product
    Variants API reference or a manual dashboard upload's Network request.
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
        "pricing": {
            "price": [
                {
                    "price": price_cents / 100,
                    "currency": "USD"
                }
            ]
        },
        "deliverable": {
            "types": ["downloadable_files"],
            "data": {
                "downloadable_files": [
                    {
                        "name": os.path.basename(image_path)
                    }
                ]
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
    """Combines STEP A + STEP B"""
    product = create_sellapp_product(title, description)
    if not product or "data" not in product or "id" not in product["data"]:
        print("Skipping variant creation - product creation did not return a valid ID.")
        return None
    product_id = product["data"]["id"]
    return create_sellapp_variant(product_id, price_cents, image_path)


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
