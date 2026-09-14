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

STATUS_ORDER = ["new","paid","warehouse","picking","picked","packed","shipped","completed"]

def detect_client(code: str):
    code = code.strip().upper()
    if code.startswith("FB00"):
        return {"code": code, "logistics": "IHAN LOGISTICS", "country": "Kazakhstan / Europe"}
    if code.startswith("RU"):
        return {"code": code, "logistics": "MAX CARGO", "country": "Russia"}
    if code.startswith("KG"):
        return {"code": code, "logistics": "MAX CARGO", "country": "Kyrgyzstan"}
    return None

def make_order_no(order_id: int | None = None):
    now = datetime.now()
    suffix = f"{order_id:03d}" if order_id else now.strftime("%H%M%S")
    return f"ORD-{now:%y%m%d}-{suffix}"

def make_receipt_no():
    now = datetime.now()
    return f"REC-{now:%y%m%d-%H%M%S}"
