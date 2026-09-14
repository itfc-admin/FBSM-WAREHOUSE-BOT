CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    full_name TEXT,
    role TEXT NOT NULL DEFAULT 'viewer'
        CHECK (role IN ('admin','sales','warehouse','logistics','viewer')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clients (
    id BIGSERIAL PRIMARY KEY,
    client_code TEXT UNIQUE NOT NULL,
    client_name TEXT,
    country TEXT NOT NULL,
    logistics TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS brands (
    id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS categories (
    id BIGSERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id BIGSERIAL PRIMARY KEY,
    order_no TEXT UNIQUE NOT NULL,
    client_id BIGINT NOT NULL REFERENCES clients(id),
    status TEXT NOT NULL DEFAULT 'new',
    total_qty INTEGER NOT NULL DEFAULT 0,
    created_by BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at TIMESTAMPTZ,
    warehouse_at TIMESTAMPTZ,
    picking_at TIMESTAMPTZ,
    packed_at TIMESTAMPTZ,
    shipped_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS order_status_history (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_by BIGINT REFERENCES users(id),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS order_brands (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    brand_id BIGINT NOT NULL REFERENCES brands(id),
    qty INTEGER NOT NULL DEFAULT 0 CHECK (qty >= 0),
    UNIQUE(order_id, brand_id)
);

CREATE TABLE IF NOT EXISTS receipts (
    id BIGSERIAL PRIMARY KEY,
    receipt_no TEXT UNIQUE NOT NULL,
    brand_id BIGINT NOT NULL REFERENCES brands(id),
    source_file TEXT,
    received_by BIGINT REFERENCES users(id),
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS receipt_items (
    id BIGSERIAL PRIMARY KEY,
    receipt_id BIGINT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    category_id BIGINT NOT NULL REFERENCES categories(id),
    qty INTEGER NOT NULL CHECK (qty >= 0)
);

CREATE TABLE IF NOT EXISTS allocations (
    id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    brand_id BIGINT NOT NULL REFERENCES brands(id),
    category_id BIGINT NOT NULL REFERENCES categories(id),
    qty INTEGER NOT NULL CHECK (qty >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(order_id, brand_id, category_id)
);

INSERT INTO categories(name) VALUES
('T-SHIRT'),('LONGSLEEVE'),('SHIRT'),('DENIM SHIRT'),('SWEATSHIRT'),
('HOODIE'),('SWEATER'),('KNIT'),('PANTS'),('TRAINING PANTS'),
('DENIM PANTS'),('SHORTS'),('SKIRT'),('DRESS'),('JACKET'),('COAT'),
('VEST'),('OTHER')
ON CONFLICT (name) DO NOTHING;
