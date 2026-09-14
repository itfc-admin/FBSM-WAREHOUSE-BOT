from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from utils import STATUS_LABELS, STATUS_ORDER

def main_menu(role: str):
    rows = [
        [KeyboardButton(text="📦 Заказы"), KeyboardButton(text="🔍 Поиск")],
        [KeyboardButton(text="🏭 Склад"), KeyboardButton(text="👥 Клиенты")],
        [KeyboardButton(text="📡 LIVE ЗАКАЗЫ"), KeyboardButton(text="📊 Отчёты")],
    ]
    if role == "admin":
        rows.append([KeyboardButton(text="⚙️ Админ")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def order_status_keyboard(order_id: int, current_status: str):
    try:
        idx = STATUS_ORDER.index(current_status)
    except ValueError:
        idx = -1
    rows = []
    if idx + 1 < len(STATUS_ORDER):
        nxt = STATUS_ORDER[idx+1]
        rows.append([InlineKeyboardButton(
            text=f"➡️ {STATUS_LABELS[nxt]}",
            callback_data=f"status:{order_id}:{nxt}"
        )])
    rows.append([InlineKeyboardButton(text="📜 История", callback_data=f"history:{order_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
