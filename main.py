"""
Automated Thumbnail Store Generator (Sell.app)
------------------------------------------------------------------
Generates a professional YouTube thumbnail and uploads it to Sell.app.
Now with auto-publish functionality.
"""

import os
import json
import random
import requests
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

# ================ CONFIG ================
TOPICS_FILE = "topics_database.json"
RUN_COUNTER_FILE = "run_counter.json"
OUTPUT_DIR = "output"
THUMB_SIZE = (1280, 720)
SINGLE_PRICE_CENTS = 500  # $5.00
BUNDLE_PRICE_CENTS = 3000  # $30.00 bundle price
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
SELLAPP_API_KEY = os.environ.get("SELLAPP_API_KEY")
SELLAPP_STORE_ID = os.environ.get("SELLAPP_STORE_ID")
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ================ FUNCTIONS ================

def get_next_topic():
    """اگلا topic حاصل کریں"""
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
    """Pexels سے stock photo download کریں"""
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
    """Thumbnail بنائیں اور save کریں"""
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
    """Sell.app میں product بنائیں"""
    url = "https://sell.app/api/v2/products"
    headers = {
        "Authorization": f"Bearer {SELLAPP_API_KEY}",
        "X-STORE": SELLAPP_STORE_ID,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    payload = {
        "title": title,
        "description": description,
        "visibility": "PUBLIC",
        "type": "product",
    }
    
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code not in (200, 201):
        print(f"❌ Product Creation Error: {response.text}")
        return None
    
    product = response.json()
    print(f"✅ Product بنایا: {title}")
    return product

def publish_product(product_id):
    """Product کو publish کریں (draft سے live کریں)"""
    url = f"https://sell.app/api/v2/products/{product_id}/publish"
    headers = {
        "Authorization": f"Bearer {SELLAPP_API_KEY}",
        "X-STORE": SELLAPP_STORE_ID,
    }
    
    try:
        response = requests.post(url, headers=headers)
        
        if response.status_code in (200, 201, 204):
            print(f"✅ Product published (فوری طور پر live ہو گیا)!")
            return True
        else:
            print(f"⚠️ Publish میں مسئلہ: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Publish error: {str(e)}")
        return False

def create_sellapp_variant(product_id, price_cents):
    """Product کے لیے variant بنائیں"""
    url = f"https://sell.app/api/v2/products/{product_id}/variants"
    headers = {
        "Authorization": f"Bearer {SELLAPP_API_KEY}",
        "X-STORE": SELLAPP_STORE_ID,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    payload = {
        "title": "Default Variant",
        "description": "High resolution thumbnail template file",
        "pricing": {
            "humble": False,
            "price": {
                "price": price_cents,
                "currency": "USD"
            }
        },
        "deliverable": [
            {
                "types": ["file"],
                "data": {
                    "stock": -1
                }
            }
        ],
        "minimum_purchase_quantity": 1,
        "payment_methods": ["SOL"]
    }
    
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code not in (200, 201):
        print(f"❌ Variant creation failed: {response.status_code} {response.text}")
        return None
    
    variant = response.json()
    print(f"✅ Variant بنایا: ${price_cents/100:.2f}")
    return variant

def create_full_sellapp_listing(title, description, price_cents):
    """پورا listing بنائیں, variant add کریں, اور publish کریں"""
    print(f"\n📝 '{title}' listing شروع کیا...")
    
    # Step 1: Product بنائیں
    product = create_sellapp_product(title, description)
    if not product or "data" not in product or "id" not in product["data"]:
        print("❌ Product ID نہیں ملا - variant skip ہو رہا ہے")
        return None
    
    product_id = product["data"]["id"]
    print(f"   Product ID: {product_id}")
    
    # Step 2: Variant بنائیں
    variant = create_sellapp_variant(product_id, price_cents)
    if not variant:
        print(f"❌ Variant نہیں بن سکا")
        return None
    
    # Step 3: ⭐ PUBLISH کریں
    print(f"   Publishing...")
    publish_success = publish_product(product_id)
    
    if publish_success:
        print(f"✅ '{title}' مکمل طور پر setup ہو گیا!\n")
    else:
        print(f"⚠️ '{title}' draft میں ہے - ہاتھ سے publish کریں\n")
    
    return product_id

def get_and_increment_run_count():
    """Run counter کو بڑھائیں"""
    count = 0
    if os.path.exists(RUN_COUNTER_FILE):
        with open(RUN_COUNTER_FILE, "r") as f:
            count = json.load(f).get("count", 0)
    
    count += 1
    with open(RUN_COUNTER_FILE, "w") as f:
        json.dump({"count": count}, f)
    
    return count

def main():
    """Main function"""
    print("🚀 Automated Thumbnail Generator شروع ہوا...\n")
    
    # Step 1: Topic لیں
    print("1️⃣ Topic منتخب کیا جا رہا ہے...")
    topic = get_next_topic()
    headline_display = topic["headline"].replace("\n", " ")
    print(f"   📌 Topic: {headline_display}\n")
    
    # Step 2: Stock photo download کریں
    print("2️⃣ Stock photo download ہو رہی ہے...")
    bg_path = download_stock_photo(topic["keyword"])
    print(f"   ✅ Download complete\n")
    
    # Step 3: Thumbnail بنائیں
    print("3️⃣ Thumbnail بنایا جا رہا ہے...")
    output_path = os.path.join(OUTPUT_DIR, f"thumbnail_{topic['id']}.jpg")
    create_thumbnail(bg_path, topic["headline"], topic["accent_color"], output_path)
    print(f"   ✅ Saved: {output_path}\n")
    
    # Step 4: Sell.app میں upload کریں
    print("4️⃣ Sell.app پر upload ہو رہا ہے...\n")
    title = f"YouTube Thumbnail Template | Clickbait Design | {headline_display.title()} | High CTR"
    description = (
        "Professional, ready-to-use YouTube thumbnail template designed for high click-through rate (CTR). "
        "High-resolution JPG (1280x720), instantly accessible after purchase."
    )
    create_full_sellapp_listing(title, description, SINGLE_PRICE_CENTS)
    
    # Step 5: Run count check - bundle بنائیں یا نہیں
    run_count = get_and_increment_run_count()
    RUNS_PER_DAY = 4
    BUNDLE_EVERY_DAYS = 4
    bundle_trigger_every_n_runs = RUNS_PER_DAY * BUNDLE_EVERY_DAYS
    
    print(f"📊 Run #{run_count}/{bundle_trigger_every_n_runs}")
    
    if run_count % bundle_trigger_every_n_runs == 0:
        print(f"\n🎁 Bundle بننے کا وقت آ گیا! (ہر {BUNDLE_EVERY_DAYS} دن میں)\n")
        bundle_number = run_count // bundle_trigger_every_n_runs
        bundle_title = f"16-Pack Thumbnail Bundle #{bundle_number}"
        bundle_description = "A bundle of 16 professional YouTube thumbnail templates at a discounted price."
        create_full_sellapp_listing(bundle_title, bundle_description, BUNDLE_PRICE_CENTS)
    
    print("✅ مکمل!")

if __name__ == "__main__":
    main()
