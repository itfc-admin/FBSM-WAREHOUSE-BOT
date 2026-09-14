-- Run this once if V1.0 database already exists.
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS source_file TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'allocations_order_id_brand_id_category_id_key'
    ) THEN
        ALTER TABLE allocations
        ADD CONSTRAINT allocations_order_id_brand_id_category_id_key
        UNIQUE(order_id, brand_id, category_id);
    END IF;
END $$;
