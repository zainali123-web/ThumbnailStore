def create_sellapp_product(title, description, price_cents, image_path):
    headers = {
        "Authorization": f"Bearer {SELLAPP_API_KEY}",
        "Content-Type": "application/json",
    }

    # STEP 1: Main Product Container Banayein
    url_product = "https://sell.app/api/v2/products"
    product_payload = {
        "title": title,
        "description": description,
        "visibility": "PUBLIC"
    }

    print("Creating Base Product...")
    resp = requests.post(url_product, headers=headers, json=product_payload)
    print(f"Product API Status: {resp.status_code}")
    print(f"Product API Response: {resp.text}")

    if resp.status_code not in (200, 201):
        return None

    res_json = resp.json()
    product_id = res_json.get("id")
    if not product_id and "data" in res_json and isinstance(res_json["data"], dict):
        product_id = res_json["data"].get("id")

    if not product_id:
        print("ERROR: Could not find Product ID in response.")
        return res_json

    print(f"--> Base Product Created! Product ID: {product_id}")

    # STEP 2: Product ID ke andar Variant, Price ($5.00) aur Stock Attach Karein
    url_variant = f"https://sell.app/api/v2/products/{product_id}/variants"
    variant_payload = {
        "title": "Default Variant",
        "description": "Digital Download",
        "stock": -1,
        "unlimited_stock": True,
        "pricing": {
            "type": "SINGLE_PAYMENT",
            "humble": False,
            "price": {"price": str(price_cents), "currency": "USD"}
        }
    }

    print(f"Attaching Variant to Product ID {product_id}...")
    var_resp = requests.post(url_variant, headers=headers, json=variant_payload)
    print(f"Variant API Status: {var_resp.status_code}")
    print(f"Variant API Response: {var_resp.text}")

    return res_json
