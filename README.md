# FBSM Warehouse Bot V1.1

Внутренняя Telegram-система склада: клиенты, заказы, статусы, бренды, приёмка Excel, складские остатки и распределение.

## V1.1 добавлено
- загрузка Packing List `.xlsx` прямо в Telegram;
- распознавание колонок Category/Qty/Brand;
- нормализация категорий (`TSHIRT`, `T SHIRT` → `T-SHIRT`; `JEANS` → `DENIM PANTS` и т.д.);
- приход товара по бренду и категориям;
- складской остаток `приход - распределено`;
- привязка бренда и количества к заказу;
- пропорциональное распределение категорий между заказами;
- Excel Packing List по каждому заказу;
- просмотр состава бренда по категориям.

## Коды клиентов
- `FB00...` → IHAN LOGISTICS → Kazakhstan / Europe
- `RU...` → MAX CARGO → Russia
- `KG...` → MAX CARGO → Kyrgyzstan

## Основные команды

```text
/newclient
/neworder
/orderbrand ORDER_NO BRAND QTY
/packing
/stock
/brand BRAND
/allocate BRAND
/export ORDER_NO BRAND
```

Пример:

```text
/orderbrand ORD-260914-150000 TOFFEE 2000
/packing
/allocate TOFFEE
/export ORD-260914-150000 TOFFEE
```

## Excel Packing List
Минимально нужны две колонки. Названия могут немного отличаться:

```text
Category | Qty
T-shirt  | 1200
Pants    | 800
Jeans    | 500
```

Дополнительно может быть колонка `Brand`.

Бот суммирует одинаковые категории и сохраняет их в базу.

## Установка нового проекта

1. Создать PostgreSQL базу.
2. Выполнить `schema.sql`.
3. Скопировать `.env.example` → `.env`.
4. Заполнить `BOT_TOKEN`, `DATABASE_URL`, `ADMIN_IDS`.
5. Установить зависимости:

```bash
pip install -r requirements.txt
```

6. Запустить:

```bash
python bot.py
```

## Если V1.0 уже установлен
Вместо повторного `schema.sql` сначала выполните:

```text
migrate_v1_to_v1_1.sql
```

После этого замените файлы программы на V1.1 и перезапустите бот.

## Роли
- `admin` — всё;
- `sales` — клиенты, заказы, бренды заказа, статусы;
- `warehouse` — приёмка, распределение, склад, упаковка;
- `logistics` — изменение логистических статусов;
- `viewer` — просмотр.
