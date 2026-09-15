# FBSM Warehouse Bot V1.3 — Universal Excel Import

Поддерживает:
- CARIES NOTE / box-SKU формат (.xls/.xlsx)
- TOFFEE Product List (.xls/.xlsx)
- PLAC Packing (.xls/.xlsx)
- старый простой CATEGORY/QTY
- автоматическое определение формата
- предварительный просмотр перед записью
- кнопки Подтвердить / OTHER / Отмена
- хранение Brand → Category → Style → Color → Size → SKU → Box → Qty
- PostgreSQL / Railway

## Railway
Переменные:
BOT_TOKEN
DATABASE_URL=${{Postgres.DATABASE_URL}}
ADMIN_IDS=719400883

Start Command:
python bot.py

## Важно
Если категория не распознана, позиция попадёт в OTHER.
Это безопаснее, чем автоматически записать товар в неправильную категорию.
