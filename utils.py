import re
from datetime import datetime

STATUS_LABELS = {
    "new": "🆕 Новый",
    "paid": "💰 Оплачен",
    "warehouse": "📋 Передан на склад",
    "picking": "🛒 В сборке",
    "picked": "✅ Собран",
    "packed": "📦 Упакован",
    "shipped": "🚚 Отгружен",
    "completed": "🏁 Завершён",
}
STATUS_ORDER = list(STATUS_LABELS.keys())

def detect_client(code: str):
    code = code.strip().upper()
    if code.startswith("FB00"):
        return {"code": code, "logistics": "IHAN LOGISTICS", "country": "Kazakhstan / Europe"}
    if code.startswith("RU"):
        return {"code": code, "logistics": "MAX CARGO", "country": "Russia"}
    if code.startswith("KG"):
        return {"code": code, "logistics": "MAX CARGO", "country": "Kyrgyzstan"}
    return None

def clean(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()

def make_order_no():
    return f"ORD-{datetime.now():%y%m%d-%H%M%S}"

def make_receipt_no():
    return f"REC-{datetime.now():%y%m%d-%H%M%S}"

def classify_category(product_name="", style_no="", sku=""):
    text = f"{product_name} {style_no} {sku}".upper().replace("_"," ").replace("-"," ")
    # High-confidence product-name rules first.
    rules = [
        (["DENIM PANTS","DENIM PANT","JEANS","데님 팬츠","데님팬츠","청바지"], "DENIM PANTS"),
        (["TRAINING PANTS","TRAINING PANT","JOGGER","조거","트레이닝 팬츠","트레이닝팬츠"], "TRAINING PANTS"),
        (["SHORTS","SHORT PANTS","숏팬츠","반바지"], "SHORTS"),
        (["T-SHIRT","T SHIRT","TSHIRT","티셔츠","반팔티"], "T-SHIRT"),
        (["LONGSLEEVE","LONG SLEEVE","긴팔티"], "LONGSLEEVE"),
        (["SWEATSHIRT","SWEAT SHIRT","맨투맨"], "SWEATSHIRT"),
        (["HOODIE","HOODED","후드"], "HOODIE"),
        (["DENIM SHIRT","데님 셔츠"], "DENIM SHIRT"),
        (["CARDIGAN","가디건"], "CARDIGAN"),
        (["SWEATER","스웨터"], "SWEATER"),
        (["KNIT","니트"], "KNIT"),
        (["JACKET","자켓","재킷"], "JACKET"),
        (["COAT","코트"], "COAT"),
        (["VEST","조끼"], "VEST"),
        (["SKIRT","스커트"], "SKIRT"),
        (["DRESS","ONEPIECE","ONE PIECE","원피스"], "DRESS"),
        (["SHIRT","BLOUSE","셔츠","블라우스"], "SHIRT"),
        (["PANTS","PANT","TROUSER","팬츠","바지"], "PANTS"),
    ]
    for words, cat in rules:
        if any(w in text for w in words):
            return cat

    # Conservative style/SKU code mapping used when product name is absent.
    compact = re.sub(r"[^A-Z0-9]", "", f"{style_no}{sku}".upper())
    token_rules = [
        ("TS", "T-SHIRT"),
        ("PT", "PANTS"),
        ("JK", "JACKET"),
        ("SK", "SKIRT"),
        ("BL", "SHIRT"),
        ("OP", "DRESS"),
        ("VT", "VEST"),
        ("CT", "COAT"),
        ("CD", "CARDIGAN"),
    ]
    for token, cat in token_rules:
        if token in compact:
            return cat
    return "OTHER"
