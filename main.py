def create_sellapp_product(title, description, image_path):
    """
    Sell.app میں product بنائیں اور PUBLISH کریں
    """
    print(f"📦 Sell.app میں product بنا رہے ہیں: {title}")
    
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
        "visibility": "PUBLIC",  # ✅ براہ راست PUBLIC
        "type": "product"
    }
    
    response = requests.post(url, headers=headers, json=payload)
    
    if response.status_code not in (200, 201):
        print(f"❌ Product Error: {response.status_code} - {response.text}")
        return None
    
    product = response.json()
    product_id = product["data"]["id"]
    print(f"✅ Product بنایا گیا (ID: {product_id})")
    
    return product_id
