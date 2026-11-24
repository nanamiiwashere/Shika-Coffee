DO $$ BEGIN
    CREATE TYPE mutation_type AS ENUM ('in', 'out', 'adjustment', 'waste');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE oauth_provider AS ENUM ('google', 'discord');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE order_type AS ENUM ('dine_in', 'take_away');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE payment_method AS ENUM ('cash', 'qris', 'debit');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE sale_status AS ENUM ('completed', 'cancelled');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('admin', 'cashier', 'manager');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE SEQUENCE IF NOT EXISTS invoice_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE SEQUENCE IF NOT EXISTS po_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

CREATE TABLE IF NOT EXISTS users (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email VARCHAR(150) NOT NULL UNIQUE,
    username VARCHAR(50) UNIQUE,
    password_hash VARCHAR(255),
    full_name VARCHAR(100) NOT NULL,
    avatar_url VARCHAR(255),
    role user_role NOT NULL DEFAULT 'cashier',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_oauth_accounts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider oauth_provider NOT NULL,
    provider_user_id VARCHAR(100) NOT NULL,
    provider_email VARCHAR(150),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_provider_user UNIQUE (provider, provider_user_id)
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS units (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(30) NOT NULL UNIQUE,
    symbol VARCHAR(10) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    phone VARCHAR(25),
    email VARCHAR(150),
    address TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    sku VARCHAR(30) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    price NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    image_url VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS raw_materials (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    unit_id INTEGER NOT NULL REFERENCES units(id) ON DELETE RESTRICT,
    sku VARCHAR(30) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    current_stock NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (current_stock >= 0),
    minimum_stock NUMERIC(12, 2) NOT NULL DEFAULT 10.00 CHECK (minimum_stock >= 0),
    latest_purchase_price NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (latest_purchase_price >= 0),
    image_url VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE raw_materials ADD COLUMN IF NOT EXISTS image_url VARCHAR(255);

CREATE TABLE IF NOT EXISTS product_recipes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    raw_material_id BIGINT NOT NULL REFERENCES raw_materials(id) ON DELETE RESTRICT,
    quantity_required NUMERIC(10, 2) NOT NULL CHECK (quantity_required > 0),
    CONSTRAINT uq_product_ingredient UNIQUE (product_id, raw_material_id)
);

CREATE TABLE IF NOT EXISTS sales (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    invoice_number VARCHAR(35) NOT NULL UNIQUE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    customer_name VARCHAR(50) DEFAULT 'Guest',
    order_type order_type NOT NULL DEFAULT 'dine_in',
    subtotal NUMERIC(12, 2) NOT NULL CHECK (subtotal >= 0),
    discount NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (discount >= 0),
    tax NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (tax >= 0),
    total_amount NUMERIC(12, 2) NOT NULL CHECK (total_amount >= 0),
    payment_method payment_method NOT NULL,
    amount_paid NUMERIC(12, 2) NOT NULL CHECK (amount_paid >= 0),
    change_amount NUMERIC(12, 2) NOT NULL DEFAULT 0.00 CHECK (change_amount >= 0),
    status sale_status NOT NULL DEFAULT 'completed',
    order_status VARCHAR(20) NOT NULL DEFAULT 'received' CHECK (order_status IN ('received', 'processing', 'ready', 'finished')),
    transaction_date TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE sales ADD COLUMN IF NOT EXISTS order_status VARCHAR(20) NOT NULL DEFAULT 'received';
DO $$ BEGIN
    ALTER TABLE sales ADD CONSTRAINT chk_sales_order_status CHECK (order_status IN ('received', 'processing', 'ready', 'finished'));
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS sale_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sale_id BIGINT NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    subtotal NUMERIC(12, 2) NOT NULL CHECK (subtotal >= 0),
    note VARCHAR(200)
);

CREATE TABLE IF NOT EXISTS material_purchases (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    po_number VARCHAR(35) NOT NULL UNIQUE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    purchase_date DATE NOT NULL DEFAULT CURRENT_DATE,
    total_cost NUMERIC(12, 2) NOT NULL CHECK (total_cost >= 0),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS material_purchase_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    purchase_id BIGINT NOT NULL REFERENCES material_purchases(id) ON DELETE CASCADE,
    raw_material_id BIGINT NOT NULL REFERENCES raw_materials(id) ON DELETE RESTRICT,
    quantity NUMERIC(12, 2) NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    subtotal NUMERIC(12, 2) NOT NULL CHECK (subtotal >= 0)
);

CREATE TABLE IF NOT EXISTS stock_mutations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raw_material_id BIGINT NOT NULL REFERENCES raw_materials(id) ON DELETE RESTRICT,
    mutation_type mutation_type NOT NULL,
    quantity NUMERIC(12, 2) NOT NULL CHECK (quantity > 0),
    stock_before NUMERIC(12, 2) NOT NULL,
    stock_after NUMERIC(12, 2) NOT NULL,
    reference_type VARCHAR(40) NOT NULL,
    reference_id BIGINT,
    notes VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shift_notes (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    category VARCHAR(20) NOT NULL CHECK (category IN ('flavor', 'maintenance', 'service')),
    content VARCHAR(240) NOT NULL,
    is_done BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_product_recipes_material ON product_recipes (raw_material_id);
CREATE INDEX IF NOT EXISTS idx_product_recipes_product ON product_recipes (product_id);
CREATE INDEX IF NOT EXISTS idx_products_category ON products (category_id);
CREATE INDEX IF NOT EXISTS idx_sale_items_product ON sale_items (product_id);
CREATE INDEX IF NOT EXISTS idx_sale_items_sale ON sale_items (sale_id);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales (transaction_date);
CREATE INDEX IF NOT EXISTS idx_sales_status ON sales (status);
CREATE INDEX IF NOT EXISTS idx_sales_order_status ON sales (order_status);
CREATE INDEX IF NOT EXISTS idx_stock_mutations_date ON stock_mutations (created_at);
CREATE INDEX IF NOT EXISTS idx_stock_mutations_material ON stock_mutations (raw_material_id);
CREATE INDEX IF NOT EXISTS idx_shift_notes_created_at ON shift_notes (created_at DESC, id DESC);

