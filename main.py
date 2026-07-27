import os
import sys
import json
import random
import requests
from PIL import Image, ImageDraw, ImageFont

# 1. API Keys aur Configuration load karna
SELL_API_KEY = os.environ.get("SELL_API_KEY") or os.environ.get("SELLAPP_API_KEY")
SELLAPP_STORE_ID = os.environ.get("SELLAPP_STORE_ID")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

if not SELL_API_KEY:
    print("Error: Sell.app API Key is missing in GitHub Secrets!")
    sys.exit(1)

if not SELLAPP_STORE_ID:
    print("Error: Sell.app Store ID is missing in GitHub Secrets!")
    sys.exit(1)

# 2. Topic Pick karna aur Dictionary handle karna
print("Picking a topic...")
try:
    with open("topics_database.json", "r") as f:
        topics_data = json.load(f)
        topics = topics_data.get("topics", ["DEFAULT TOPIC"])
except Exception as e:
    topics = [{"headline": "THE BIGGEST UPGRADE", "keyword": "upgrade"}]

selected_topic = random.choice(topics)

# Agar topic dictionary hai toh usme se headline aur keyword nikalna
if isinstance(selected_topic, dict):
    topic_text = selected_topic.get("headline", "DEFAULT TOPIC")
    search_query = selected_topic.get("keyword", topic_text)
else:
    topic_text = str(selected_topic)
    search_query = topic_text

print(f"Topic: {topic_text}")

# 3. Stock Photo Download karna (Pexels)
print("Downloading stock photo...")
photo_path = "temp_image.jpg"
if PEXELS_API_KEY:
    headers = {"Authorization": PEXELS_API_KEY}
    response = requests.get(
        f"https://api.pexels.com/v1/search?query={search_query}&per_page=1",
        headers=headers
    )
    if response.status_code == 200:
        photos = response.json().get("photos", [])
        if photos:
            img_url = photos[0]["src"]["large"]
            img_data = requests.get(img_url).content
            with open(photo_path, "wb") as handler:
                handler.write(img_data)

# Agar pexels se image na mile ya key na ho toh fallback image create karna
if not os.path.exists(photo_path):
    img = Image.new('RGB', (1280, 720), color=(73, 109, 137))
    img.save(photo_path)

# 4. Thumbnail Create karna
print("Creating thumbnail...")
output_thumbnail = "final_thumbnail.jpg"
base_img = Image.open(photo_path).resize((1280, 720))

# Text overlay effect
draw = ImageDraw.Draw(base_img)
try:
    font = ImageFont.truetype("arial.ttf", 80)
except IOError:
    font = ImageFont.load_default()

draw.text((50, 50), topic_text, fill=(255, 255, 255), font=font)
base_img.save(output_thumbnail)

# 5. Sell.app par Upload karna (Store ID ke sath)
print("Uploading to Sell.app...")
sell_url = f"https://api.sell.app/v1/shops/{SELLAPP_STORE_ID}/products"

headers = {
    "Authorization": f"Bearer {SELL_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

payload = {
    "title": f"Thumbnail - {topic_text}",
    "description": f"High quality automated generated thumbnail for: {topic_text}",
    "price": 5.00,
    "currency": "USD",
    "type": "file",
    "visibility": "visible"
}

try:
    response = requests.post(sell_url, headers=headers, json=payload)
    print(f"Sell.app Response Code: {response.status_code}")
    print(f"Sell.app Response: {response.text}")
    
    response.raise_for_status()
    print("Product uploaded successfully to Sell.app!")
    
except requests.exceptions.HTTPError as err:
    print(f"Sell.app product creation failed: {err}")
    sys.exit(1)
except Exception as e:
    print(f"An unexpected error occurred: {e}")
    sys.exit(1)

print("Done.")
