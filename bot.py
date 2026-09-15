import os, io, asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db import init_db, pool, ensure_user, get_user
from keyboards import main_menu, clients_menu, orders_menu, warehouse_menu, admin_menu, order_status_keyboard
from utils import detect_client, make_order_no, make_receipt_no, STATUS_LABELS
from excel_tools import parse_packing_list, create_order_packing_xlsx
from allocation import proportional_matrix

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
ADMIN_IDS = {int(x.strip()) for x in os.getenv('ADMIN_IDS','').split(',') if x.strip()}
dp = Dispatcher()

class NewClient(StatesGroup): code=State(); name=State()
class NewOrder(StatesGroup): client_code=State(); qty=State()
class Search(StatesGroup): query=State()
class PackingUpload(StatesGroup): brand=State(); file=State()
class OrderBrand(StatesGroup): order_no=State(); brand=State(); qty=State()
class BrandView(StatesGroup): brand=State()
class AllocateBrand(StatesGroup): brand=State()
class ExportPacking(StatesGroup): order_no=State(); brand=State()

async def require_user(message: Message):
    user = await get_user(message.from_user.id)
    if user: return user
    role = 'admin' if message.from_user.id in ADMIN_IDS else 'viewer'
    return await ensure_user(message.from_user.id, message.from_user.full_name, role)

async def get_or_create_brand(name: str):
    return await pool().fetchrow('''INSERT INTO brands(name) VALUES($1)
        ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING *''', name.strip().upper())

async def show_order(message: Message, r):
    brands = await pool().fetch('''SELECT b.name,ob.qty FROM order_brands ob JOIN brands b ON b.id=ob.brand_id
        WHERE ob.order_id=$1 ORDER BY b.name''', r['id'])
    btxt='\n'.join(f"• {x['name']}: {x['qty']} EA" for x in brands) or '• бренды не назначены'
    text=(f"📦 {r['order_no']}\nКлиент: {r['client_code']} {r.get('client_name') or ''}\n"
          f"Логистика: {r.get('logistics') or '-'}\nКоличество: {r['total_qty']} EA\nБренды:\n{btxt}\n"
          f"Статус: {STATUS_LABELS.get(r['status'],r['status'])}")
    await message.answer(text, reply_markup=order_status_keyboard(r['id'], r['status']))

@dp.message(CommandStart())
async def start(message: Message):
    user=await require_user(message)
    await message.answer(f"🏭 FBSM Warehouse Bot V1.2\n\nПользователь: {message.from_user.full_name}\nРоль: {user['role']}", reply_markup=main_menu(user['role']))

@dp.message(F.text=='⬅️ Главное меню')
async def home(message: Message, state: FSMContext):
    await state.clear(); user=await require_user(message)
    await message.answer('Главное меню', reply_markup=main_menu(user['role']))

@dp.message(F.text=='👥 Клиенты')
async def clients(message: Message):
    await require_user(message); await message.answer('👥 Клиенты', reply_markup=clients_menu())

@dp.message(F.text=='📦 Заказы')
async def orders(message: Message):
    await require_user(message); await message.answer('📦 Заказы', reply_markup=orders_menu())

@dp.message(F.text=='🏭 Склад')
async def warehouse(message: Message):
    await require_user(message); await message.answer('🏭 Склад', reply_markup=warehouse_menu())

@dp.message(F.text=='⚙️ Админ')
async def admin(message: Message):
    user=await require_user(message)
    if user['role']!='admin': return await message.answer('Нет доступа.')
    await message.answer('⚙️ Админ', reply_markup=admin_menu())

@dp.message(F.text=='➕ Новый клиент')
async def newclient(message: Message, state: FSMContext):
    user=await require_user(message)
    if user['role'] not in ('admin','sales'): return await message.answer('Добавлять клиентов может Sales/Admin.')
    await state.set_state(NewClient.code); await message.answer('Введите код клиента: FB00..., RU... или KG...')

@dp.message(NewClient.code)
async def newclient_code(message: Message, state: FSMContext):
    info=detect_client(message.text or '')
    if not info: return await message.answer('❌ Код должен начинаться с FB00, RU или KG.')
    await state.update_data(**info); await state.set_state(NewClient.name)
    await message.answer(f"Логистика: {info['logistics']}\nСтрана: {info['country']}\n\nВведите имя/название клиента:")

@dp.message(NewClient.name)
async def newclient_name(message: Message, state: FSMContext):
    d=await state.get_data()
    try:
        await pool().execute('INSERT INTO clients(client_code,client_name,country,logistics) VALUES($1,$2,$3,$4)',d['code'],message.text.strip(),d['country'],d['logistics'])
        await message.answer(f"✅ Клиент {d['code']} создан.", reply_markup=clients_menu())
    except Exception:
        await message.answer('Такой код клиента уже существует или произошла ошибка.')
    await state.clear()

@dp.message(F.text=='📋 Список клиентов')
async def client_list(message: Message):
    rows=await pool().fetch('SELECT client_code,client_name,country,logistics FROM clients ORDER BY created_at DESC LIMIT 50')
    if not rows: return await message.answer('Клиентов пока нет.')
    lines=['👥 КЛИЕНТЫ','']
    for r in rows: lines.append(f"{r['client_code']} — {r['client_name'] or '-'}\n{r['country']} | {r['logistics']}")
    await message.answer('\n\n'.join(lines))

@dp.message(F.text.in_({'🔍 Поиск','🔎 Найти клиента','🔎 Найти заказ'}))
async def search_start(message: Message, state: FSMContext):
    await state.set_state(Search.query); await message.answer('Введите код клиента или номер заказа:')

@dp.message(Search.query)
async def search_result(message: Message, state: FSMContext):
    q=(message.text or '').strip().upper(); await state.clear()
    rows=await pool().fetch('''SELECT o.id,o.order_no,o.status,o.total_qty,c.client_code,c.client_name,c.logistics
        FROM orders o JOIN clients c ON c.id=o.client_id
        WHERE UPPER(o.order_no) LIKE $1 OR UPPER(c.client_code) LIKE $1 ORDER BY o.created_at DESC LIMIT 20''',f'%{q}%')
    if not rows: return await message.answer('Ничего не найдено.')
    for r in rows: await show_order(message,r)

@dp.message(F.text=='➕ Новый заказ')
async def neworder(message: Message, state: FSMContext):
    user=await require_user(message)
    if user['role'] not in ('admin','sales'): return await message.answer('Создавать заказы может Sales/Admin.')
    await state.set_state(NewOrder.client_code); await message.answer('Введите код клиента:')

@dp.message(NewOrder.client_code)
async def neworder_client(message: Message, state: FSMContext):
    code=(message.text or '').strip().upper(); c=await pool().fetchrow('SELECT * FROM clients WHERE client_code=$1',code)
    if not c: return await message.answer('Клиент не найден. Сначала создайте клиента.')
    await state.update_data(client_id=c['id'],client_code=code); await state.set_state(NewOrder.qty)
    await message.answer('Введите общее количество товара (EA):')

@dp.message(NewOrder.qty)
async def neworder_qty(message: Message, state: FSMContext):
    try: qty=int((message.text or '').replace(',','')); assert qty>0
    except: return await message.answer('Введите количество числом, например 5000.')
    user=await require_user(message); d=await state.get_data(); no=make_order_no()
    r=await pool().fetchrow('INSERT INTO orders(order_no,client_id,total_qty,created_by) VALUES($1,$2,$3,$4) RETURNING id,status',no,d['client_id'],qty,user['id'])
    await pool().execute("INSERT INTO order_status_history(order_id,old_status,new_status,changed_by) VALUES($1,NULL,'new',$2)",r['id'],user['id'])
    await state.clear()
    await message.answer(f"✅ Заказ создан\n\n{no}\nКлиент: {d['client_code']}\nКоличество: {qty} EA\n\nТеперь нажмите «🏷 Бренд в заказ».", reply_markup=orders_menu())

@dp.message(F.text=='📋 Активные заказы')
async def active_orders(message: Message):
    rows=await pool().fetch('''SELECT o.id,o.order_no,o.status,o.total_qty,c.client_code,c.client_name,c.logistics
        FROM orders o JOIN clients c ON c.id=o.client_id WHERE o.status<>'completed' ORDER BY o.created_at DESC LIMIT 50''')
    if not rows: return await message.answer('Активных заказов нет.')
    for r in rows: await show_order(message,r)

@dp.message(F.text=='✅ Завершённые')
async def completed(message: Message):
    rows=await pool().fetch('''SELECT o.order_no,o.total_qty,c.client_code,o.completed_at FROM orders o JOIN clients c ON c.id=o.client_id
        WHERE o.status='completed' ORDER BY o.completed_at DESC LIMIT 50''')
    if not rows: return await message.answer('Завершённых заказов пока нет.')
    await message.answer('\n'.join(['🏁 ЗАВЕРШЁННЫЕ','']+[f"{r['order_no']} | {r['client_code']} | {r['total_qty']} EA" for r in rows]))

@dp.message(F.text=='🏷 Бренд в заказ')
async def orderbrand_start(message: Message, state: FSMContext):
    await state.set_state(OrderBrand.order_no); await message.answer('Введите номер заказа, например ORD-260915-112300:')

@dp.message(OrderBrand.order_no)
async def orderbrand_order(message: Message, state: FSMContext):
    no=(message.text or '').strip().upper(); r=await pool().fetchrow('SELECT id FROM orders WHERE order_no=$1',no)
    if not r: return await message.answer('Заказ не найден. Проверьте номер.')
    await state.update_data(order_no=no,order_id=r['id']); await state.set_state(OrderBrand.brand); await message.answer('Введите бренд, например TOFFEE:')

@dp.message(OrderBrand.brand)
async def orderbrand_brand(message: Message, state: FSMContext):
    await state.update_data(brand=(message.text or '').strip().upper()); await state.set_state(OrderBrand.qty); await message.answer('Введите количество этого бренда в заказе (EA):')

@dp.message(OrderBrand.qty)
async def orderbrand_qty(message: Message, state: FSMContext):
    try: qty=int((message.text or '').replace(',','')); assert qty>=0
    except: return await message.answer('Введите количество числом.')
    d=await state.get_data(); b=await get_or_create_brand(d['brand'])
    await pool().execute('''INSERT INTO order_brands(order_id,brand_id,qty) VALUES($1,$2,$3)
        ON CONFLICT(order_id,brand_id) DO UPDATE SET qty=EXCLUDED.qty''',d['order_id'],b['id'],qty)
    await state.clear(); await message.answer(f"✅ {d['order_no']}: {d['brand']} = {qty} EA", reply_markup=orders_menu())

@dp.message(F.text=='📡 LIVE')
async def live(message: Message):
    stats=await pool().fetch("SELECT status,COUNT(*) cnt FROM orders WHERE status<>'completed' GROUP BY status")
    c={r['status']:r['cnt'] for r in stats}; lines=['📡 LIVE ЗАКАЗЫ','']
    for k in ['new','paid','warehouse','picking','picked','packed','shipped']: lines.append(f"{STATUS_LABELS[k]} — {c.get(k,0)}")
    await message.answer('\n'.join(lines))

@dp.message(F.text=='📥 Приёмка Excel')
async def packing_start(message: Message, state: FSMContext):
    user=await require_user(message)
    if user['role'] not in ('admin','warehouse'): return await message.answer('Приёмку может делать Warehouse/Admin.')
    await state.set_state(PackingUpload.brand); await message.answer('Введите бренд поступления, например TOFFEE:')

@dp.message(PackingUpload.brand)
async def packing_brand(message: Message, state: FSMContext):
    await state.update_data(brand=(message.text or '').strip().upper()); await state.set_state(PackingUpload.file)
    await message.answer('Теперь отправьте Excel Packing List (.xlsx).')

@dp.message(PackingUpload.file, F.document)
async def packing_file(message: Message, state: FSMContext, bot: Bot):
    name=message.document.file_name or 'packing.xlsx'
    if not name.lower().endswith('.xlsx'): return await message.answer('Нужен файл .xlsx')
    d=await state.get_data(); buf=io.BytesIO(); await bot.download(message.document,destination=buf)
    try: parsed=parse_packing_list(buf.getvalue(),d['brand'])
    except Exception as e: return await message.answer(f'❌ Не удалось прочитать Excel: {e}')
    user=await require_user(message); b=await get_or_create_brand(parsed['brand']); rec_no=make_receipt_no()
    async with pool().acquire() as conn:
        async with conn.transaction():
            rec=await conn.fetchrow('INSERT INTO receipts(receipt_no,brand_id,source_file,received_by) VALUES($1,$2,$3,$4) RETURNING id',rec_no,b['id'],name,user['id'])
            for cat,qty in parsed['items'].items():
                cid=await conn.fetchval('INSERT INTO categories(name) VALUES($1) ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id',cat)
                await conn.execute('INSERT INTO receipt_items(receipt_id,category_id,qty) VALUES($1,$2,$3)',rec['id'],cid,qty)
    await state.clear(); lines=[f"✅ ПРИЁМКА {rec_no}",f"Бренд: {b['name']}",f"Всего: {parsed['total_qty']} EA",'']+[f"• {c}: {q} EA" for c,q in parsed['items'].items()]
    await message.answer('\n'.join(lines),reply_markup=warehouse_menu())

@dp.message(F.text=='📦 Остатки')
async def stock(message: Message):
    rows=await pool().fetch('''SELECT b.name brand,c.name category,COALESCE(SUM(ri.qty),0) received,
        COALESCE((SELECT SUM(a.qty) FROM allocations a WHERE a.brand_id=b.id AND a.category_id=c.id),0) allocated
        FROM brands b JOIN receipts r ON r.brand_id=b.id JOIN receipt_items ri ON ri.receipt_id=r.id JOIN categories c ON c.id=ri.category_id
        GROUP BY b.id,b.name,c.id,c.name ORDER BY b.name,c.name''')
    if not rows: return await message.answer('Склад пока пуст.')
    by={}
    for r in rows: by.setdefault(r['brand'],[]).append(r)
    for brand,items in by.items():
        total=sum(x['received']-x['allocated'] for x in items); lines=[f"📦 {brand} — остаток {total} EA"]
        lines += [f"• {x['category']}: {x['received']-x['allocated']} EA" for x in items]
        await message.answer('\n'.join(lines))

@dp.message(F.text=='🏷 Состав бренда')
async def brand_start(message: Message, state: FSMContext):
    await state.set_state(BrandView.brand); await message.answer('Введите бренд:')

@dp.message(BrandView.brand)
async def brand_result(message: Message, state: FSMContext):
    brand=(message.text or '').strip().upper(); await state.clear()
    rows=await pool().fetch('''SELECT c.name,COALESCE(SUM(ri.qty),0) qty FROM brands b JOIN receipts r ON r.brand_id=b.id
        JOIN receipt_items ri ON ri.receipt_id=r.id JOIN categories c ON c.id=ri.category_id WHERE b.name=$1 GROUP BY c.name ORDER BY c.name''',brand)
    if not rows: return await message.answer('Бренд/приход не найден.')
    await message.answer('\n'.join([f'🏷 {brand}','']+[f"• {r['name']}: {r['qty']} EA" for r in rows]))

@dp.message(F.text=='⚖️ Распределить бренд')
async def alloc_start(message: Message, state: FSMContext):
    user=await require_user(message)
    if user['role'] not in ('admin','warehouse'): return await message.answer('Распределять может Warehouse/Admin.')
    await state.set_state(AllocateBrand.brand); await message.answer('Введите бренд для распределения:')

@dp.message(AllocateBrand.brand)
async def alloc_result(message: Message, state: FSMContext):
    brand_name=(message.text or '').strip().upper(); await state.clear(); b=await pool().fetchrow('SELECT * FROM brands WHERE name=$1',brand_name)
    if not b: return await message.answer('Бренд не найден.')
    sr=await pool().fetch('''SELECT c.id category_id,c.name,COALESCE(SUM(ri.qty),0)-COALESCE((SELECT SUM(a.qty) FROM allocations a WHERE a.brand_id=$1 AND a.category_id=c.id),0) available
        FROM receipts r JOIN receipt_items ri ON ri.receipt_id=r.id JOIN categories c ON c.id=ri.category_id
        WHERE r.brand_id=$1 GROUP BY c.id,c.name HAVING COALESCE(SUM(ri.qty),0)-COALESCE((SELECT SUM(a.qty) FROM allocations a WHERE a.brand_id=$1 AND a.category_id=c.id),0)>0''',b['id'])
    stock={r['name']:r['available'] for r in sr}; ids={r['name']:r['category_id'] for r in sr}
    ors=await pool().fetch('''SELECT o.id,o.order_no,c.client_code,ob.qty-COALESCE((SELECT SUM(a.qty) FROM allocations a WHERE a.order_id=o.id AND a.brand_id=$1),0) remaining
        FROM order_brands ob JOIN orders o ON o.id=ob.order_id JOIN clients c ON c.id=o.client_id
        WHERE ob.brand_id=$1 AND o.status<>'completed' AND ob.qty-COALESCE((SELECT SUM(a.qty) FROM allocations a WHERE a.order_id=o.id AND a.brand_id=$1),0)>0 ORDER BY o.created_at''',b['id'])
    demand={r['id']:r['remaining'] for r in ors}
    if not stock: return await message.answer('Нет свободного остатка этого бренда.')
    if not demand: return await message.answer('Нет активных заказов с этим брендом. Сначала нажмите «🏷 Бренд в заказ».')
    matrix,catq,ordq=proportional_matrix(stock,demand)
    async with pool().acquire() as conn:
        async with conn.transaction():
            for oid,cats in matrix.items():
                for cat,qty in cats.items():
                    if qty>0: await conn.execute('''INSERT INTO allocations(order_id,brand_id,category_id,qty) VALUES($1,$2,$3,$4)
                        ON CONFLICT(order_id,brand_id,category_id) DO UPDATE SET qty=allocations.qty+EXCLUDED.qty''',oid,b['id'],ids[cat],qty)
    lookup={r['id']:r for r in ors}; lines=[f'✅ РАСПРЕДЕЛЕНИЕ {brand_name}',f"Распределено: {sum(ordq.values())} EA",'']
    for oid,total in ordq.items(): lines.append(f"• {lookup[oid]['order_no']} / {lookup[oid]['client_code']}: {total} EA")
    await message.answer('\n'.join(lines))

@dp.message(F.text=='📄 Packing List заказа')
async def export_start(message: Message, state: FSMContext):
    await state.set_state(ExportPacking.order_no); await message.answer('Введите номер заказа:')

@dp.message(ExportPacking.order_no)
async def export_order_no(message: Message, state: FSMContext):
    await state.update_data(order_no=(message.text or '').strip().upper()); await state.set_state(ExportPacking.brand); await message.answer('Введите бренд:')

@dp.message(ExportPacking.brand)
async def export_result(message: Message, state: FSMContext):
    d=await state.get_data(); await state.clear(); brand=(message.text or '').strip().upper()
    r=await pool().fetchrow('''SELECT o.id,o.order_no,c.client_code,b.id brand_id,b.name brand FROM orders o JOIN clients c ON c.id=o.client_id
        JOIN order_brands ob ON ob.order_id=o.id JOIN brands b ON b.id=ob.brand_id WHERE o.order_no=$1 AND b.name=$2''',d['order_no'],brand)
    if not r: return await message.answer('Заказ/бренд не найден.')
    items=await pool().fetch('''SELECT c.name,SUM(a.qty) qty FROM allocations a JOIN categories c ON c.id=a.category_id
        WHERE a.order_id=$1 AND a.brand_id=$2 GROUP BY c.name ORDER BY c.name''',r['id'],r['brand_id'])
    if not items: return await message.answer('Для этого заказа ещё нет распределения.')
    binary=create_order_packing_xlsx(r['order_no'],r['client_code'],r['brand'],[(x['name'],x['qty']) for x in items])
    filename=f"{r['order_no']}_{r['client_code']}_{r['brand']}_PACKING.xlsx".replace('/','-')
    await message.answer_document(BufferedInputFile(binary,filename=filename),caption=f"📄 Packing List\n{r['order_no']} / {r['client_code']} / {r['brand']}")

@dp.message(F.text.in_({'📊 Отчёты','📊 Сводка'}))
async def reports(message: Message):
    r=await pool().fetchrow("SELECT COUNT(*) FILTER(WHERE status<>'completed') active,COUNT(*) FILTER(WHERE status='completed') completed,COALESCE(SUM(total_qty) FILTER(WHERE status<>'completed'),0) qty FROM orders")
    await message.answer(f"📊 ОТЧЁТ\n\nАктивных заказов: {r['active']}\nЗавершённых: {r['completed']}\nВ активных заказах: {r['qty']} EA")

@dp.message(F.text=='👤 Сотрудники и роли')
async def roles(message: Message):
    await message.answer('Роли: admin / sales / warehouse / logistics / viewer\n\nНазначение роли:\n/setrole TELEGRAM_ID role')

@dp.message(F.text.startswith('/setrole '))
async def setrole(message: Message):
    user=await require_user(message)
    if user['role']!='admin': return await message.answer('Нет доступа.')
    p=message.text.split()
    if len(p)!=3 or p[2] not in ('admin','sales','warehouse','logistics','viewer'): return await message.answer('Пример: /setrole 123456789 warehouse')
    await pool().execute("INSERT INTO users(telegram_id,full_name,role) VALUES($1,'',$2) ON CONFLICT(telegram_id) DO UPDATE SET role=EXCLUDED.role,is_active=TRUE",int(p[1]),p[2])
    await message.answer(f"✅ {p[1]} → {p[2]}")

@dp.callback_query(F.data.startswith('status:'))
async def change_status(call: CallbackQuery):
    _,oid,new=call.data.split(':'); oid=int(oid); user=await get_user(call.from_user.id)
    if not user or user['role'] not in ('admin','sales','warehouse','logistics'): return await call.answer('Нет прав',show_alert=True)
    o=await pool().fetchrow('SELECT * FROM orders WHERE id=$1',oid)
    col={'paid':'paid_at','warehouse':'warehouse_at','picking':'picking_at','packed':'packed_at','shipped':'shipped_at','completed':'completed_at'}.get(new)
    if col: await pool().execute(f'UPDATE orders SET status=$1,{col}=NOW() WHERE id=$2',new,oid)
    else: await pool().execute('UPDATE orders SET status=$1 WHERE id=$2',new,oid)
    await pool().execute('INSERT INTO order_status_history(order_id,old_status,new_status,changed_by) VALUES($1,$2,$3,$4)',oid,o['status'],new,user['id'])
    await call.message.edit_reply_markup(reply_markup=order_status_keyboard(oid,new)); await call.message.answer(f"✅ {o['order_no']} → {STATUS_LABELS[new]}"); await call.answer()

@dp.callback_query(F.data.startswith('history:'))
async def history(call: CallbackQuery):
    oid=int(call.data.split(':')[1]); rows=await pool().fetch('''SELECT h.new_status,h.changed_at,u.full_name FROM order_status_history h LEFT JOIN users u ON u.id=h.changed_by WHERE h.order_id=$1 ORDER BY h.changed_at''',oid)
    await call.message.answer('\n'.join(['📜 ИСТОРИЯ ЗАКАЗА','']+[f"{r['changed_at']:%d.%m.%Y %H:%M} — {STATUS_LABELS.get(r['new_status'],r['new_status'])} ({r['full_name'] or 'system'})" for r in rows])); await call.answer()

async def main():
    if not BOT_TOKEN or not DATABASE_URL: raise RuntimeError('BOT_TOKEN/DATABASE_URL not set')
    await init_db(DATABASE_URL); await dp.start_polling(Bot(BOT_TOKEN))

if __name__=='__main__': asyncio.run(main())
