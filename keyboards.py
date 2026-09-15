from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from utils import STATUS_LABELS, STATUS_ORDER

def main_menu(role):
    rows=[
        [KeyboardButton(text="📦 Заказы"),KeyboardButton(text="🏭 Склад")],
        [KeyboardButton(text="👥 Клиенты"),KeyboardButton(text="📡 LIVE")],
        [KeyboardButton(text="🔍 Поиск"),KeyboardButton(text="📊 Отчёты")],
    ]
    if role=="admin":
        rows.append([KeyboardButton(text="⚙️ Админ")])
    return ReplyKeyboardMarkup(keyboard=rows,resize_keyboard=True)

def warehouse_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📥 Приёмка Excel"),KeyboardButton(text="📦 Остатки")],
        [KeyboardButton(text="🏷 Бренды"),KeyboardButton(text="🔎 Состав бренда")],
        [KeyboardButton(text="⚖️ Распределение"),KeyboardButton(text="📄 Packing List")],
        [KeyboardButton(text="⬅️ Главное меню")]
    ],resize_keyboard=True)

def clients_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="➕ Новый клиент"),KeyboardButton(text="📋 Список клиентов")],
        [KeyboardButton(text="⬅️ Главное меню")]
    ],resize_keyboard=True)

def orders_menu():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="➕ Новый заказ"),KeyboardButton(text="📋 Активные заказы")],
        [KeyboardButton(text="🏷 Бренд в заказ"),KeyboardButton(text="✅ Завершённые")],
        [KeyboardButton(text="⬅️ Главное меню")]
    ],resize_keyboard=True)

def receipt_confirm_keyboard(token):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить приёмку",callback_data=f"receipt_ok:{token}")],
        [InlineKeyboardButton(text="📋 Показать OTHER",callback_data=f"receipt_other:{token}")],
        [InlineKeyboardButton(text="❌ Отмена",callback_data=f"receipt_cancel:{token}")]
    ])

def order_status_keyboard(order_id,current_status):
    rows=[]
    try: idx=STATUS_ORDER.index(current_status)
    except: idx=-1
    if idx+1<len(STATUS_ORDER):
        nxt=STATUS_ORDER[idx+1]
        rows.append([InlineKeyboardButton(text=f"➡️ {STATUS_LABELS[nxt]}",callback_data=f"status:{order_id}:{nxt}")])
    rows.append([InlineKeyboardButton(text="📜 История",callback_data=f"history:{order_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
