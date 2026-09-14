import os
import io
import asyncio
from datetime import datetime
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db import init_db, pool, ensure_user, get_user
from keyboards import main_menu, order_status_keyboard
from utils import detect_client, make_order_no, make_receipt_no, STATUS_LABELS
from excel_tools import parse_packing_list, create_order_packing_xlsx
from allocation import proportional_matrix

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}

dp = Dispatcher()

class NewClient(StatesGroup):
    code = State(); name = State()

class NewOrder(StatesGroup):
    client_code = State(); qty = State()

class SearchOrder(StatesGroup):
    query = State()

class PackingUpload(StatesGroup):
    brand = State(); file = State()

async def require_user(message: Message):
    user = await get_user(message.from_user.id)
    if user:
        return user
    role = "admin" if message.from_user.id in ADMIN_IDS else "viewer"
    return await ensure_user(message.from_user.id, message.from_user.full_name, role)

async def get_or_create_brand(name: str):
    name = name.strip().upper()
    return await pool().fetchrow('''
        INSERT INTO brands(name) VALUES($1)
        ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name
        RETURNING *
    ''', name)

@dp.message(CommandStart())
async def start(message: Message):
    user = await require_user(message)
    await message.answer(
        f"FBSM Warehouse Bot V1.1\n\nПользователь: {message.from_user.full_name}\nРоль: {user['role']}",
        reply_markup=main_menu(user["role"])
    )

@dp.message(F.text == "👥 Клиенты")
async def clients_menu(message: Message):
    user = await require_user(message)
    if user["role"] not in ("admin", "sales"):
        await message.answer("У вас режим просмотра. Добавлять клиентов может Sales/Admin.")
        return
    await message.answer("Новый клиент: /newclient")

@dp.message(F.text == "📦 Заказы")
async def orders_menu(message: Message):
    await require_user(message)
    rows = await pool().fetch('''
        SELECT o.id,o.order_no,o.status,o.total_qty,c.client_code,c.logistics
        FROM orders o JOIN clients c ON c.id=o.client_id
        WHERE o.status <> 'completed'
        ORDER BY o.created_at DESC LIMIT 30
    ''')
    if not rows:
        await message.answer("Активных заказов пока нет.\nСоздать: /neworder")
        return
    text = ["📦 АКТИВНЫЕ ЗАКАЗЫ\n"]
    for r in rows:
        brands = await pool().fetch('''
            SELECT b.name,ob.qty FROM order_brands ob JOIN brands b ON b.id=ob.brand_id
            WHERE ob.order_id=$1 ORDER BY b.name
        ''', r["id"])
        btxt = ", ".join(f"{x['name']} {x['qty']}" for x in brands) or "бренды не назначены"
        text.append(f"{r['order_no']} | {r['client_code']} | {r['total_qty']} EA\n{btxt}\n{STATUS_LABELS.get(r['status'],r['status'])} | {r['logistics']}\n")
    await message.answer("\n".join(text))

@dp.message(F.text == "📡 LIVE ЗАКАЗЫ")
async def live_orders(message: Message):
    await require_user(message)
    stats = await pool().fetch('''SELECT status,COUNT(*) cnt FROM orders WHERE status<>'completed' GROUP BY status''')
    counts = {r["status"]: r["cnt"] for r in stats}
    lines = ["📡 LIVE ЗАКАЗЫ", ""]
    for key in ["new","paid","warehouse","picking","picked","packed","shipped"]:
        lines.append(f"{STATUS_LABELS[key]} — {counts.get(key,0)}")
    await message.answer("\n".join(lines))

@dp.message(F.text == "🔍 Поиск")
async def search_start(message: Message, state: FSMContext):
    await require_user(message)
    await state.set_state(SearchOrder.query)
    await message.answer("Введите номер заказа или код клиента (например RU0058):")

@dp.message(SearchOrder.query)
async def search_result(message: Message, state: FSMContext):
    q = message.text.strip().upper()
    rows = await pool().fetch('''
        SELECT o.id,o.order_no,o.status,o.total_qty,o.created_at,
               c.client_code,c.client_name,c.country,c.logistics
        FROM orders o JOIN clients c ON c.id=o.client_id
        WHERE UPPER(o.order_no) LIKE $1 OR UPPER(c.client_code) LIKE $1
        ORDER BY o.created_at DESC LIMIT 20
    ''', f"%{q}%")
    await state.clear()
    if not rows:
        await message.answer("Ничего не найдено.")
        return
    for r in rows:
        brands = await pool().fetch('''SELECT b.name,ob.qty FROM order_brands ob JOIN brands b ON b.id=ob.brand_id WHERE ob.order_id=$1 ORDER BY b.name''', r["id"])
        btxt = "\n".join(f"• {x['name']}: {x['qty']} EA" for x in brands) or "• не назначены"
        text = (
            f"📦 {r['order_no']}\nКлиент: {r['client_code']} {r['client_name'] or ''}\n"
            f"Страна: {r['country']}\nЛогистика: {r['logistics']}\nКоличество: {r['total_qty']} EA\n"
            f"Бренды:\n{btxt}\nСтатус: {STATUS_LABELS.get(r['status'],r['status'])}\nСоздан: {r['created_at']:%d.%m.%Y %H:%M}"
        )
        await message.answer(text, reply_markup=order_status_keyboard(r["id"], r["status"]))

@dp.message(F.text == "🏭 Склад")
async def warehouse_menu(message: Message):
    await require_user(message)
    await message.answer(
        "🏭 СКЛАД V1.1\n\n"
        "📥 /packing — загрузить Packing List Excel\n"
        "📦 /stock — остатки по брендам\n"
        "⚖️ /allocate BRAND — распределить бренд по активным заказам\n"
        "📄 /export ORDER_NO BRAND — выгрузить Packing List заказа\n"
        "🏷 /orderbrand ORDER_NO BRAND QTY — назначить бренд заказу\n"
        "📋 /brand BRAND — состав бренда по категориям"
    )

@dp.message(F.text == "📊 Отчёты")
async def reports(message: Message):
    await require_user(message)
    r = await pool().fetchrow('''SELECT COUNT(*) FILTER(WHERE status<>'completed') active, COUNT(*) FILTER(WHERE status='completed') completed, COALESCE(SUM(total_qty) FILTER(WHERE status<>'completed'),0) qty FROM orders''')
    stock = await pool().fetchval('''
        SELECT COALESCE(SUM(ri.qty),0) - COALESCE((SELECT SUM(qty) FROM allocations),0)
        FROM receipt_items ri
    ''')
    await message.answer(f"📊 ОТЧЁТ\n\nАктивных заказов: {r['active']}\nЗавершённых: {r['completed']}\nВ активных заказах: {r['qty']} EA\nОстаток склада: {stock or 0} EA")

@dp.message(F.text == "⚙️ Админ")
async def admin_menu(message: Message):
    user = await require_user(message)
    if user["role"] != "admin":
        await message.answer("Нет доступа."); return
    await message.answer("⚙️ ADMIN\n\n/setrole TELEGRAM_ID admin|sales|warehouse|logistics|viewer\n/newclient\n/neworder\n/packing\n/stock")

@dp.message(F.text.startswith("/setrole "))
async def set_role(message: Message):
    user = await require_user(message)
    if user["role"] != "admin": await message.answer("Нет доступа."); return
    parts = message.text.split()
    if len(parts) != 3 or parts[2] not in ("admin","sales","warehouse","logistics","viewer"):
        await message.answer("Пример: /setrole 123456789 warehouse"); return
    await pool().execute('''INSERT INTO users(telegram_id,full_name,role) VALUES($1,'',$2) ON CONFLICT(telegram_id) DO UPDATE SET role=EXCLUDED.role,is_active=TRUE''', int(parts[1]), parts[2])
    await message.answer(f"Роль {parts[1]} → {parts[2]}")

@dp.message(F.text == "/newclient")
async def newclient(message: Message, state: FSMContext):
    user = await require_user(message)
    if user["role"] not in ("admin","sales"): await message.answer("Нет доступа."); return
    await state.set_state(NewClient.code); await message.answer("Введите код клиента: FB00..., RU... или KG...")

@dp.message(NewClient.code)
async def newclient_code(message: Message, state: FSMContext):
    info = detect_client(message.text)
    if not info: await message.answer("❌ Неверный код. Разрешены FB00..., RU..., KG..."); return
    await state.update_data(**info); await state.set_state(NewClient.name)
    await message.answer(f"Логистика: {info['logistics']}\nСтрана: {info['country']}\n\nВведите имя/название клиента:")

@dp.message(NewClient.name)
async def newclient_name(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        await pool().execute('''INSERT INTO clients(client_code,client_name,country,logistics) VALUES($1,$2,$3,$4)''', data["code"], message.text.strip(), data["country"], data["logistics"])
        await message.answer(f"✅ Клиент {data['code']} создан.")
    except Exception as e:
        await message.answer("Такой код клиента уже существует." if "unique" in str(e).lower() else f"Ошибка: {e}")
    await state.clear()

@dp.message(F.text == "/neworder")
async def neworder(message: Message, state: FSMContext):
    user = await require_user(message)
    if user["role"] not in ("admin","sales"): await message.answer("Нет доступа."); return
    await state.set_state(NewOrder.client_code); await message.answer("Введите код клиента:")

@dp.message(NewOrder.client_code)
async def neworder_client(message: Message, state: FSMContext):
    code = message.text.strip().upper(); client = await pool().fetchrow("SELECT * FROM clients WHERE client_code=$1", code)
    if not client: await message.answer("Клиент не найден. Сначала /newclient"); return
    await state.update_data(client_id=client["id"], client_code=client["client_code"]); await state.set_state(NewOrder.qty)
    await message.answer(f"Клиент {client['client_code']} найден. Введите общее количество товара (EA):")

@dp.message(NewOrder.qty)
async def neworder_qty(message: Message, state: FSMContext):
    try:
        qty = int(message.text.replace(",", "").strip()); assert qty >= 0
    except Exception:
        await message.answer("Введите количество числом, например 5000"); return
    user = await require_user(message); data = await state.get_data(); temp_no = make_order_no()
    row = await pool().fetchrow('''INSERT INTO orders(order_no,client_id,total_qty,created_by) VALUES($1,$2,$3,$4) RETURNING id,order_no,status,created_at''', temp_no, data["client_id"], qty, user["id"])
    await pool().execute('''INSERT INTO order_status_history(order_id,old_status,new_status,changed_by) VALUES($1,NULL,'new',$2)''', row["id"], user["id"])
    await state.clear()
    await message.answer(f"✅ Заказ создан\n\n{row['order_no']}\nКлиент: {data['client_code']}\nКоличество: {qty} EA\nСтатус: 🆕 Новый\n\nТеперь назначьте бренд:\n/orderbrand {row['order_no']} TOFFEE {qty}", reply_markup=order_status_keyboard(row["id"], row["status"]))

@dp.message(F.text.startswith("/orderbrand "))
async def order_brand(message: Message):
    user = await require_user(message)
    if user["role"] not in ("admin","sales","warehouse"): await message.answer("Нет доступа."); return
    parts = message.text.split(maxsplit=3)
    if len(parts) != 4: await message.answer("Формат: /orderbrand ORDER_NO BRAND QTY\nПример: /orderbrand ORD-260914-120000 TOFFEE 2000"); return
    order_no, brand_name, qty_text = parts[1], parts[2].upper(), parts[3]
    try: qty = int(qty_text.replace(",", "")); assert qty >= 0
    except Exception: await message.answer("QTY должно быть числом."); return
    order = await pool().fetchrow("SELECT * FROM orders WHERE order_no=$1", order_no.upper())
    if not order: await message.answer("Заказ не найден."); return
    brand = await get_or_create_brand(brand_name)
    await pool().execute('''INSERT INTO order_brands(order_id,brand_id,qty) VALUES($1,$2,$3) ON CONFLICT(order_id,brand_id) DO UPDATE SET qty=EXCLUDED.qty''', order["id"], brand["id"], qty)
    await message.answer(f"✅ {order_no}: {brand['name']} = {qty} EA")

@dp.message(F.text == "/packing")
async def packing_start(message: Message, state: FSMContext):
    user = await require_user(message)
    if user["role"] not in ("admin","warehouse"): await message.answer("Приёмку может делать Warehouse/Admin."); return
    await state.set_state(PackingUpload.brand)
    await message.answer("Введите бренд поступления, например TOFFEE:")

@dp.message(PackingUpload.brand)
async def packing_brand(message: Message, state: FSMContext):
    brand = message.text.strip().upper()
    if not brand: await message.answer("Введите бренд."); return
    await state.update_data(brand=brand); await state.set_state(PackingUpload.file)
    await message.answer("Теперь отправьте Excel Packing List (.xlsx). Бот найдёт Category/Qty и посчитает категории.")

@dp.message(PackingUpload.file, F.document)
async def packing_file(message: Message, state: FSMContext, bot: Bot):
    name = message.document.file_name or "packing.xlsx"
    if not name.lower().endswith(".xlsx"):
        await message.answer("Нужен файл .xlsx"); return
    data = await state.get_data()
    buf = io.BytesIO(); await bot.download(message.document, destination=buf)
    try:
        parsed = parse_packing_list(buf.getvalue(), data["brand"])
    except Exception as e:
        await message.answer(f"❌ Не удалось прочитать Excel: {e}"); return
    user = await require_user(message); brand = await get_or_create_brand(parsed["brand"]); receipt_no = make_receipt_no()
    async with pool().acquire() as conn:
        async with conn.transaction():
            receipt = await conn.fetchrow('''INSERT INTO receipts(receipt_no,brand_id,source_file,received_by) VALUES($1,$2,$3,$4) RETURNING id''', receipt_no, brand["id"], name, user["id"])
            for category, qty in parsed["items"].items():
                cat = await conn.fetchrow('''INSERT INTO categories(name) VALUES($1) ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id''', category)
                await conn.execute('''INSERT INTO receipt_items(receipt_id,category_id,qty) VALUES($1,$2,$3)''', receipt["id"], cat["id"], qty)
    await state.clear()
    lines = [f"✅ ПРИЁМКА {receipt_no}", f"Бренд: {brand['name']}", f"Файл: {name}", f"Всего: {parsed['total_qty']} EA", "", "Категории:"]
    lines += [f"• {c}: {q} EA" for c,q in parsed["items"].items()]
    if parsed["warnings"]: lines += ["", "⚠️ " + " | ".join(parsed["warnings"][:3])]
    await message.answer("\n".join(lines))

@dp.message(F.text == "/stock")
async def stock(message: Message):
    await require_user(message)
    rows = await pool().fetch('''
        SELECT b.name brand,c.name category,
               COALESCE(SUM(ri.qty),0) received,
               COALESCE((SELECT SUM(a.qty) FROM allocations a WHERE a.brand_id=b.id AND a.category_id=c.id),0) allocated
        FROM brands b
        JOIN receipts r ON r.brand_id=b.id
        JOIN receipt_items ri ON ri.receipt_id=r.id
        JOIN categories c ON c.id=ri.category_id
        GROUP BY b.id,b.name,c.id,c.name
        ORDER BY b.name,c.name
    ''')
    if not rows: await message.answer("Склад пока пуст."); return
    by_brand = {}
    for r in rows: by_brand.setdefault(r["brand"], []).append((r["category"], r["received"], r["allocated"]))
    for brand, items in by_brand.items():
        total = sum(x[1]-x[2] for x in items)
        lines = [f"📦 {brand} — остаток {total} EA"] + [f"• {c}: {rec-al} (приход {rec}, распределено {al})" for c,rec,al in items]
        await message.answer("\n".join(lines))

@dp.message(F.text.startswith("/brand "))
async def brand_view(message: Message):
    await require_user(message); brand = message.text.split(maxsplit=1)[1].strip().upper()
    rows = await pool().fetch('''
        SELECT c.name,COALESCE(SUM(ri.qty),0) qty
        FROM brands b JOIN receipts r ON r.brand_id=b.id JOIN receipt_items ri ON ri.receipt_id=r.id JOIN categories c ON c.id=ri.category_id
        WHERE b.name=$1 GROUP BY c.name ORDER BY c.name
    ''', brand)
    if not rows: await message.answer("Бренд/приход не найден."); return
    await message.answer("\n".join([f"🏷 {brand}",""]+[f"• {r['name']}: {r['qty']} EA" for r in rows]))

@dp.message(F.text.startswith("/allocate "))
async def allocate(message: Message):
    user = await require_user(message)
    if user["role"] not in ("admin","warehouse"): await message.answer("Распределять может Warehouse/Admin."); return
    brand_name = message.text.split(maxsplit=1)[1].strip().upper()
    brand = await pool().fetchrow("SELECT * FROM brands WHERE name=$1", brand_name)
    if not brand: await message.answer("Бренд не найден."); return

    stock_rows = await pool().fetch('''
        SELECT c.id category_id,c.name,
               COALESCE(SUM(ri.qty),0) - COALESCE((SELECT SUM(a.qty) FROM allocations a WHERE a.brand_id=$1 AND a.category_id=c.id),0) available
        FROM receipts r JOIN receipt_items ri ON ri.receipt_id=r.id JOIN categories c ON c.id=ri.category_id
        WHERE r.brand_id=$1 GROUP BY c.id,c.name HAVING COALESCE(SUM(ri.qty),0) - COALESCE((SELECT SUM(a.qty) FROM allocations a WHERE a.brand_id=$1 AND a.category_id=c.id),0) > 0
    ''', brand["id"])
    category_stock = {r["name"]: r["available"] for r in stock_rows}
    cat_ids = {r["name"]: r["category_id"] for r in stock_rows}

    orders = await pool().fetch('''
        SELECT o.id,o.order_no,c.client_code,
               ob.qty - COALESCE((SELECT SUM(a.qty) FROM allocations a WHERE a.order_id=o.id AND a.brand_id=$1),0) remaining
        FROM order_brands ob JOIN orders o ON o.id=ob.order_id JOIN clients c ON c.id=o.client_id
        WHERE ob.brand_id=$1 AND o.status <> 'completed'
          AND ob.qty - COALESCE((SELECT SUM(a.qty) FROM allocations a WHERE a.order_id=o.id AND a.brand_id=$1),0) > 0
        ORDER BY o.created_at
    ''', brand["id"])
    order_demand = {r["id"]: r["remaining"] for r in orders}
    if not category_stock: await message.answer("Нет свободного остатка этого бренда."); return
    if not order_demand: await message.answer("Нет активных заказов с этим брендом и ненулевым остатком потребности. Используйте /orderbrand."); return

    matrix, cat_quota, order_quota = proportional_matrix(category_stock, order_demand)
    async with pool().acquire() as conn:
        async with conn.transaction():
            for oid, cats in matrix.items():
                for cat, qty in cats.items():
                    if qty <= 0: continue
                    await conn.execute('''
                        INSERT INTO allocations(order_id,brand_id,category_id,qty) VALUES($1,$2,$3,$4)
                        ON CONFLICT(order_id,brand_id,category_id) DO UPDATE SET qty=allocations.qty+EXCLUDED.qty
                    ''', oid, brand["id"], cat_ids[cat], qty)
    lookup = {r["id"]: r for r in orders}
    lines = [f"✅ РАСПРЕДЕЛЕНИЕ {brand_name}", f"Распределено: {sum(order_quota.values())} EA", ""]
    for oid, total in order_quota.items():
        r = lookup[oid]; lines.append(f"• {r['order_no']} / {r['client_code']}: {total} EA")
    lines += ["", "По категориям:"] + [f"• {c}: {q} EA" for c,q in cat_quota.items()]
    await message.answer("\n".join(lines))

@dp.message(F.text.startswith("/export "))
async def export_order(message: Message):
    await require_user(message)
    parts = message.text.split(maxsplit=2)
    if len(parts) != 3: await message.answer("Формат: /export ORDER_NO BRAND"); return
    order_no, brand_name = parts[1].upper(), parts[2].upper()
    row = await pool().fetchrow('''
        SELECT o.id,o.order_no,c.client_code,b.id brand_id,b.name brand
        FROM orders o JOIN clients c ON c.id=o.client_id JOIN order_brands ob ON ob.order_id=o.id JOIN brands b ON b.id=ob.brand_id
        WHERE o.order_no=$1 AND b.name=$2
    ''', order_no, brand_name)
    if not row: await message.answer("Заказ/бренд не найден."); return
    items = await pool().fetch('''SELECT c.name,SUM(a.qty) qty FROM allocations a JOIN categories c ON c.id=a.category_id WHERE a.order_id=$1 AND a.brand_id=$2 GROUP BY c.name ORDER BY c.name''', row["id"], row["brand_id"])
    if not items: await message.answer("Для этого заказа ещё нет распределения."); return
    binary = create_order_packing_xlsx(row["order_no"], row["client_code"], row["brand"], [(x["name"], x["qty"]) for x in items])
    filename = f"{row['order_no']}_{row['client_code']}_{row['brand']}_PACKING.xlsx".replace("/", "-")
    await message.answer_document(BufferedInputFile(binary, filename=filename), caption=f"📄 Packing List\n{row['order_no']} / {row['client_code']} / {row['brand']}")

@dp.callback_query(F.data.startswith("status:"))
async def change_status(call: CallbackQuery):
    _, order_id, new_status = call.data.split(":"); order_id = int(order_id)
    user = await get_user(call.from_user.id)
    if not user or user["role"] not in ("admin","sales","warehouse","logistics"): await call.answer("Нет прав", show_alert=True); return
    order = await pool().fetchrow("SELECT * FROM orders WHERE id=$1", order_id)
    if not order: await call.answer("Заказ не найден", show_alert=True); return
    timestamp_column = {"paid":"paid_at","warehouse":"warehouse_at","picking":"picking_at","packed":"packed_at","shipped":"shipped_at","completed":"completed_at"}.get(new_status)
    if timestamp_column: await pool().execute(f"UPDATE orders SET status=$1, {timestamp_column}=NOW() WHERE id=$2", new_status, order_id)
    else: await pool().execute("UPDATE orders SET status=$1 WHERE id=$2", new_status, order_id)
    await pool().execute('''INSERT INTO order_status_history(order_id,old_status,new_status,changed_by) VALUES($1,$2,$3,$4)''', order_id, order["status"], new_status, user["id"])
    await call.message.edit_reply_markup(reply_markup=order_status_keyboard(order_id,new_status)); await call.message.answer(f"✅ {order['order_no']} → {STATUS_LABELS.get(new_status,new_status)}"); await call.answer()

@dp.callback_query(F.data.startswith("history:"))
async def history(call: CallbackQuery):
    order_id = int(call.data.split(":")[1])
    rows = await pool().fetch('''SELECT h.new_status,h.changed_at,u.full_name FROM order_status_history h LEFT JOIN users u ON u.id=h.changed_by WHERE h.order_id=$1 ORDER BY h.changed_at''', order_id)
    lines = ["📜 ИСТОРИЯ ЗАКАЗА", ""] + [f"{r['changed_at']:%d.%m.%Y %H:%M} — {STATUS_LABELS.get(r['new_status'],r['new_status'])} ({r['full_name'] or 'system'})" for r in rows]
    await call.message.answer("\n".join(lines)); await call.answer()

async def main():
    if not BOT_TOKEN or not DATABASE_URL: raise RuntimeError("Заполните BOT_TOKEN и DATABASE_URL в .env")
    await init_db(DATABASE_URL); bot = Bot(BOT_TOKEN); await dp.start_polling(bot)

if __name__ == "__main__": asyncio.run(main())
