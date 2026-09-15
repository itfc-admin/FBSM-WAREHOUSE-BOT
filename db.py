import asyncpg
from pathlib import Path
_pool = None

async def init_db(database_url: str):
    global _pool

    _pool = await asyncpg.create_pool(
        database_url,
        min_size=1,
        max_size=10
    )

    schema_path = Path(__file__).with_name("schema.sql")

    if schema_path.exists():
        schema_sql = schema_path.read_text(encoding="utf-8")

        async with _pool.acquire() as conn:
            await conn.execute(schema_sql)

    return _pool

def pool():
    if _pool is None:
        raise RuntimeError("Database not initialized")
    return _pool

async def ensure_user(telegram_id: int, full_name: str, role: str = "viewer"):
    q = '''
    INSERT INTO users (telegram_id, full_name, role)
    VALUES ($1,$2,$3)
    ON CONFLICT (telegram_id)
    DO UPDATE SET full_name = EXCLUDED.full_name
    RETURNING *;
    '''
    return await pool().fetchrow(q, telegram_id, full_name, role)

async def get_user(telegram_id: int):
    return await pool().fetchrow(
        "SELECT * FROM users WHERE telegram_id=$1 AND is_active=TRUE", telegram_id
    )
