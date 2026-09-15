import os, asyncio, json, secrets
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db import init_db, pool, ensure_user, get_user
from keyboards import main_menu, warehouse_menu, clients_menu, orders_menu, receipt_confirm_keyboard, order_status_keyboard
from utils import detect_client, make_order_no, make_receipt_no, STATUS_LABELS
from excel_universal import parse_universal

load_dotenv()
BOT_TOKEN=os.getenv("BOT_TOKEN")
DATABASE_URL=os.getenv("DATABASE_URL")
ADMIN_IDS={int(x.strip()) for x in os.getenv("ADMIN_IDS","").split(",") if x.strip()}
dp=Dispatcher()
PENDING_RECEIPTS={}

class NewClient(StatesGroup): code=State(); name=State()
class NewOrder(StatesGroup): client_code=State(); qty=State()
class Upload(StatesGroup): brand=State(); file=State()
class BrandContent(StatesGroup): brand=State()
class OrderBrand(StatesGroup): order_no=State(); brand=State(); qty=State()

async def user(message):
    u=await get_user(message.from_user.id)
    if u: return u
    role="admin" if message.from_user.id in ADMIN_IDS else "viewer"
    return await ensure_user(message.from_user.id,message.from_user.full_name,role)

@dp.message(CommandStart())
async def start(message):
    u=await user(message)
    await message.answer(f"🏭 FBSM Warehouse Bot V1.3\n\nПользователь: {message.from_user.full_name}\nРоль: {u['role']}",reply_markup=main_menu(u["role"]))

@dp.message(F.text=="⬅️ Главное меню")
async def back(message,state:FSMContext):
    await state.clear(); u=await user(message)
    await message.answer("Главное меню",reply_markup=main_menu(u["role"]))

@dp.message(F.text=="🏭 Склад")
async def wh(message):
    await user(message); await message.answer("🏭 Склад",reply_markup=warehouse_menu())

@dp.message(F.text=="👥 Клиенты")
async def cl(message):
    await user(message); await message.answer("👥 Клиенты",reply_markup=clients_menu())

@dp.message(F.text=="📦 Заказы")
async def od(message):
    await user(message); await message.answer("📦 Заказы",reply_markup=orders_menu())

@dp.message(F.text=="📥 Приёмка Excel")
async def up_start(message,state):
    u=await user(message)
    if u["role"] not in ("admin","warehouse"): return await message.answer("Приёмка доступна складу/Admin.")
    await state.set_state(Upload.brand)
    await message.answer("Введите бренд поступления, например TOFFEE или CARIES NOTE:")

@dp.message(Upload.brand)
async def up_brand(message,state):
    await state.update_data(brand=(message.text or "").strip().upper())
    await state.set_state(Upload.file)
    await message.answer("Отправьте Packing List в формате .xls или .xlsx")

@dp.message(Upload.file,F.document)
async def up_file(message,state,bot:Bot):
    name=message.document.file_name or ""
    if not name.lower().endswith((".xls",".xlsx")):
        return await message.answer("❌ Нужен Excel .xls или .xlsx")
    data=await state.get_data()
    tmp=Path("/tmp")/f"{secrets.token_hex(4)}_{name}"
    f=await bot.get_file(message.document.file_id)
    await bot.download_file(f.file_path,destination=tmp)
    try:
        parsed=parse_universal(str(tmp))
    except Exception as e:
        return await message.answer(f"❌ Не удалось прочитать Excel:\n{e}")
    token=secrets.token_hex(5)
    PENDING_RECEIPTS[token]={
        "brand":data["brand"],"filename":name,"parsed":parsed,"user_id":message.from_user.id
    }
    await state.clear()
    lines=[
        "🔎 ПРЕДВАРИТЕЛЬНАЯ ПРИЁМКА",
        f"Бренд: {data['brand']}",
        f"Формат: {parsed['format']}",
        f"Лист: {parsed['sheet']}",
        f"Всего: {parsed['total']:,} EA",
        f"Артикулов: {parsed['styles_count']}",
    ]
    if parsed["boxes_count"]: lines.append(f"Коробок: {parsed['boxes_count']}")
    lines.append("")
    for cat,qty in parsed["categories"].items():
        mark="⚠️ " if cat=="OTHER" else ""
        lines.append(f"{mark}{cat}: {qty:,} EA")
    if parsed["unknown"]:
        lines.append(f"\n⚠️ Не распознано кодов: {len(parsed['unknown'])}. Их можно посмотреть кнопкой OTHER.")
    await message.answer("\n".join(lines),reply_markup=receipt_confirm_keyboard(token))

@dp.callback_query(F.data.startswith("receipt_other:"))
async def other(call):
    token=call.data.split(":",1)[1]
    p=PENDING_RECEIPTS.get(token)
    if not p: return await call.answer("Приёмка устарела",show_alert=True)
    arr=p["parsed"]["unknown"]
    if not arr: await call.message.answer("✅ Все позиции распределены по категориям.")
    else: await call.message.answer("⚠️ OTHER / нераспознанные:\n\n"+"\n".join(arr[:30]))
    await call.answer()

@dp.callback_query(F.data.startswith("receipt_cancel:"))
async def cancel_receipt(call):
    token=call.data.split(":",1)[1]; PENDING_RECEIPTS.pop(token,None)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("❌ Приёмка отменена.")
    await call.answer()

@dp.callback_query(F.data.startswith("receipt_ok:"))
async def confirm_receipt(call):
    token=call.data.split(":",1)[1]
    p=PENDING_RECEIPTS.get(token)
    if not p: return await call.answer("Приёмка устарела",show_alert=True)
    if p["user_id"]!=call.from_user.id: return await call.answer("Подтвердить может загрузивший сотрудник",show_alert=True)
    u=await get_user(call.from_user.id)
    parsed=p["parsed"]; brand=p["brand"]
    async with pool().acquire() as conn:
        async with conn.transaction():
            bid=await conn.fetchval("""INSERT INTO brands(name) VALUES($1)
                ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id""",brand)
            rec_no=make_receipt_no()
            rid=await conn.fetchval("""INSERT INTO receipts(receipt_no,brand_id,source_filename,source_format,received_by)
                VALUES($1,$2,$3,$4,$5) RETURNING id""",rec_no,bid,p["filename"],parsed["format"],u["id"])
            cat_ids={}
            for cat,qty in parsed["categories"].items():
                cid=await conn.fetchval("""INSERT INTO categories(name) VALUES($1)
                    ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id""",cat)
                cat_ids[cat]=cid
                await conn.execute("INSERT INTO receipt_items(receipt_id,category_id,qty) VALUES($1,$2,$3)",rid,cid,qty)
            for d in parsed["details"]:
                await conn.execute("""INSERT INTO receipt_details
                    (receipt_id,category_id,box_no,style_no,product_name,color,size,sku,qty,raw_row)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)""",
                    rid,cat_ids[d["category"]],d["box_no"],d["style_no"],d["product_name"],
                    d["color"],d["size"],d["sku"],d["qty"],json.dumps(d,ensure_ascii=False))
    PENDING_RECEIPTS.pop(token,None)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"✅ Приёмка подтверждена\n{rec_no}\nБренд: {brand}\nКоличество: {parsed['total']:,} EA")
    await call.answer()

@dp.message(F.text=="📦 Остатки")
async def stock(message):
    rows=await pool().fetch("""SELECT b.name brand,c.name category,
        COALESCE(SUM(ri.qty),0)-COALESCE((SELECT SUM(a.qty) FROM allocations a WHERE a.brand_id=b.id AND a.category_id=c.id),0) balance
        FROM receipt_items ri JOIN receipts r ON r.id=ri.receipt_id JOIN brands b ON b.id=r.brand_id
        JOIN categories c ON c.id=ri.category_id GROUP BY b.id,b.name,c.id,c.name ORDER BY b.name,c.name""")
    if not rows:return await message.answer("Остатков пока нет.")
    grouped={}
    for r in rows: grouped.setdefault(r["brand"],[]).append((r["category"],r["balance"]))
    for brand,items in grouped.items():
        lines=[f"🏷 {brand}"]; total=0
        for cat,q in items:
            lines.append(f"{cat}: {q:,} EA"); total+=q
        lines.append(f"TOTAL: {total:,} EA")
        await message.answer("\n".join(lines))

@dp.message(F.text=="🏷 Бренды")
async def brands(message):
    rows=await pool().fetch("""SELECT b.name,COALESCE(SUM(ri.qty),0) qty FROM brands b
        LEFT JOIN receipts r ON r.brand_id=b.id LEFT JOIN receipt_items ri ON ri.receipt_id=r.id
        GROUP BY b.id,b.name ORDER BY b.name""")
    if not rows:return await message.answer("Брендов пока нет.")
    await message.answer("🏷 БРЕНДЫ\n\n"+"\n".join(f"{r['name']} — {r['qty']:,} EA" for r in rows))

@dp.message(F.text=="🔎 Состав бренда")
async def brand_start(message,state):
    await state.set_state(BrandContent.brand); await message.answer("Введите бренд:")

@dp.message(BrandContent.brand)
async def brand_content(message,state):
    brand=(message.text or "").strip().upper(); await state.clear()
    rows=await pool().fetch("""SELECT c.name category,SUM(ri.qty) qty FROM receipt_items ri
        JOIN receipts r ON r.id=ri.receipt_id JOIN brands b ON b.id=r.brand_id
        JOIN categories c ON c.id=ri.category_id WHERE b.name=$1 GROUP BY c.name ORDER BY c.name""",brand)
    if not rows:return await message.answer("Бренд не найден.")
    await message.answer(f"🏷 {brand}\n\n"+"\n".join(f"{r['category']}: {r['qty']:,} EA" for r in rows))

@dp.message(F.text=="➕ Новый клиент")
async def nc(message,state):
    u=await user(message)
    if u["role"] not in ("admin","sales"):return await message.answer("Доступ Sales/Admin.")
    await state.set_state(NewClient.code); await message.answer("Введите код FB00..., RU... или KG...")

@dp.message(NewClient.code)
async def nc2(message,state):
    info=detect_client(message.text or "")
    if not info:return await message.answer("❌ Неверный код.")
    await state.update_data(**info); await state.set_state(NewClient.name)
    await message.answer(f"{info['logistics']} | {info['country']}\nВведите имя клиента:")

@dp.message(NewClient.name)
async def nc3(message,state):
    d=await state.get_data()
    try:
        await pool().execute("INSERT INTO clients(client_code,client_name,country,logistics) VALUES($1,$2,$3,$4)",
            d["code"],message.text.strip(),d["country"],d["logistics"])
        await message.answer(f"✅ Клиент {d['code']} создан.")
    except: await message.answer("Клиент уже существует или ошибка.")
    await state.clear()

@dp.message(F.text=="📋 Список клиентов")
async def cls(message):
    rows=await pool().fetch("SELECT * FROM clients ORDER BY created_at DESC LIMIT 100")
    if not rows:return await message.answer("Клиентов нет.")
    await message.answer("\n\n".join(f"{r['client_code']} — {r['client_name']}\n{r['country']} | {r['logistics']}" for r in rows))

@dp.message(F.text=="➕ Новый заказ")
async def no(message,state):
    u=await user(message)
    if u["role"] not in ("admin","sales"):return await message.answer("Доступ Sales/Admin.")
    await state.set_state(NewOrder.client_code); await message.answer("Введите код клиента:")

@dp.message(NewOrder.client_code)
async def no2(message,state):
    code=(message.text or "").strip().upper()
    c=await pool().fetchrow("SELECT * FROM clients WHERE client_code=$1",code)
    if not c:return await message.answer("Клиент не найден.")
    await state.update_data(client_id=c["id"],client_code=code); await state.set_state(NewOrder.qty)
    await message.answer("Введите общее количество EA:")

@dp.message(NewOrder.qty)
async def no3(message,state):
    try:q=int((message.text or "").replace(",",""))
    except:return await message.answer("Введите число.")
    d=await state.get_data(); u=await user(message); no=make_order_no()
    row=await pool().fetchrow("INSERT INTO orders(order_no,client_id,total_qty,created_by) VALUES($1,$2,$3,$4) RETURNING id,status",
        no,d["client_id"],q,u["id"])
    await pool().execute("INSERT INTO order_status_history(order_id,new_status,changed_by) VALUES($1,'new',$2)",row["id"],u["id"])
    await state.clear()
    await message.answer(f"✅ {no}\n{d['client_code']} | {q:,} EA",reply_markup=order_status_keyboard(row["id"],"new"))

@dp.message(F.text=="📋 Активные заказы")
async def active(message):
    rows=await pool().fetch("""SELECT o.*,c.client_code FROM orders o JOIN clients c ON c.id=o.client_id
        WHERE o.status<>'completed' ORDER BY o.created_at DESC LIMIT 50""")
    if not rows:return await message.answer("Активных заказов нет.")
    for r in rows:
        await message.answer(f"{r['order_no']} | {r['client_code']} | {r['total_qty']:,} EA\n{STATUS_LABELS[r['status']]}",
            reply_markup=order_status_keyboard(r["id"],r["status"]))

@dp.callback_query(F.data.startswith("status:"))
async def status(call):
    _,oid,ns=call.data.split(":"); oid=int(oid)
    u=await get_user(call.from_user.id)
    if not u or u["role"] not in ("admin","sales","warehouse","logistics"):return await call.answer("Нет прав",show_alert=True)
    o=await pool().fetchrow("SELECT * FROM orders WHERE id=$1",oid)
    col={"paid":"paid_at","warehouse":"warehouse_at","picking":"picking_at","picked":"picked_at","packed":"packed_at","shipped":"shipped_at","completed":"completed_at"}.get(ns)
    if col: await pool().execute(f"UPDATE orders SET status=$1,{col}=NOW() WHERE id=$2",ns,oid)
    else: await pool().execute("UPDATE orders SET status=$1 WHERE id=$2",ns,oid)
    await pool().execute("INSERT INTO order_status_history(order_id,old_status,new_status,changed_by) VALUES($1,$2,$3,$4)",oid,o["status"],ns,u["id"])
    await call.message.edit_reply_markup(reply_markup=order_status_keyboard(oid,ns))
    await call.message.answer(f"✅ {o['order_no']} → {STATUS_LABELS[ns]}"); await call.answer()

@dp.callback_query(F.data.startswith("history:"))
async def hist(call):
    oid=int(call.data.split(":")[1])
    rows=await pool().fetch("""SELECT h.*,u.full_name FROM order_status_history h LEFT JOIN users u ON u.id=h.changed_by
        WHERE h.order_id=$1 ORDER BY h.changed_at""",oid)
    await call.message.answer("📜 ИСТОРИЯ\n\n"+"\n".join(f"{r['changed_at']:%d.%m.%Y %H:%M} — {STATUS_LABELS.get(r['new_status'],r['new_status'])} ({r['full_name'] or 'system'})" for r in rows))
    await call.answer()

@dp.message(F.text=="📡 LIVE")
async def live(message):
    rows=await pool().fetch("SELECT status,COUNT(*) cnt FROM orders WHERE status<>'completed' GROUP BY status")
    d={r["status"]:r["cnt"] for r in rows}
    await message.answer("📡 LIVE\n\n"+"\n".join(f"{STATUS_LABELS[k]} — {d.get(k,0)}" for k in STATUS_LABELS if k!="completed"))

@dp.message(F.text=="📊 Отчёты")
async def rep(message):
    r=await pool().fetchrow("""SELECT COUNT(*) FILTER(WHERE status<>'completed') active,
        COUNT(*) FILTER(WHERE status='completed') completed,COALESCE(SUM(total_qty) FILTER(WHERE status<>'completed'),0) qty FROM orders""")
    await message.answer(f"📊 ОТЧЁТ\n\nАктивных: {r['active']}\nЗавершённых: {r['completed']}\nВ работе: {r['qty']:,} EA")

@dp.message(F.text=="⚙️ Админ")
async def adm(message):
    u=await user(message)
    if u["role"]!="admin":return await message.answer("Нет доступа.")
    await message.answer("⚙️ Админ\n\nНазначение роли:\n/setrole TELEGRAM_ID admin|sales|warehouse|logistics|viewer")

@dp.message(F.text.startswith("/setrole "))
async def sr(message):
    u=await user(message)
    if u["role"]!="admin":return
    p=message.text.split()
    if len(p)!=3:return await message.answer("Пример: /setrole 123456 warehouse")
    await pool().execute("""INSERT INTO users(telegram_id,full_name,role) VALUES($1,'',$2)
        ON CONFLICT(telegram_id) DO UPDATE SET role=EXCLUDED.role,is_active=TRUE""",int(p[1]),p[2])
    await message.answer("✅ Роль обновлена.")

async def main():
    if not BOT_TOKEN or not DATABASE_URL: raise RuntimeError("BOT_TOKEN/DATABASE_URL not set")
    await init_db(DATABASE_URL)
    await dp.start_polling(Bot(BOT_TOKEN))

if __name__=="__main__":
    asyncio.run(main())
