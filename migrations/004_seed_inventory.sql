-- Additive warehouse & recipe seed: units, suppliers, raw materials, initial POs, stock card mutations, and BOM recipes.
-- Safe to run multiple times; skips existing SKUs, units, suppliers, and PO numbers.

DO $$
DECLARE
    v_user_id BIGINT;
    v_sup_roastery INTEGER;
    v_sup_dairy INTEGER;
    v_sup_pantry INTEGER;
    v_po1 BIGINT;
    v_po2 BIGINT;
    v_po3 BIGINT;
    v_rm_milk BIGINT;
BEGIN
    INSERT INTO units (name, symbol)
    SELECT v.name, v.symbol
    FROM (VALUES ('Gram', 'gr'), ('Milliliter', 'ml'), ('Piece', 'pcs')) AS v(name, symbol)
    WHERE NOT EXISTS (SELECT 1 FROM units u WHERE LOWER(u.name) = LOWER(v.name) OR LOWER(u.symbol) = LOWER(v.symbol));

    INSERT INTO suppliers (name, phone, email, address)
    SELECT v.name, v.phone, v.email, v.address
    FROM (VALUES
        ('Kyoto Leaf & Roastery', '0811-2233-4401', 'beans@kyotoleaf.id', 'Jl. Braga No. 42, Bandung'),
        ('Green Meadow Dairy', '0812-8877-6612', 'orders@greenmeadow.id', 'Cisarua Dairy Hub, Bogor'),
        ('Shika Bakery & Pantry', '0813-4455-9908', 'pantry@shikacoffee.id', 'Kemang Timur No. 18, Jakarta')
    ) AS v(name, phone, email, address)
    WHERE NOT EXISTS (SELECT 1 FROM suppliers s WHERE LOWER(s.name) = LOWER(v.name));

    SELECT id INTO v_sup_roastery FROM suppliers WHERE name = 'Kyoto Leaf & Roastery' ORDER BY id LIMIT 1;
    SELECT id INTO v_sup_dairy FROM suppliers WHERE name = 'Green Meadow Dairy' ORDER BY id LIMIT 1;
    SELECT id INTO v_sup_pantry FROM suppliers WHERE name = 'Shika Bakery & Pantry' ORDER BY id LIMIT 1;

    INSERT INTO raw_materials (unit_id, sku, name, current_stock, minimum_stock, latest_purchase_price)
    SELECT u.id, v.sku, v.name, v.stock, v.min_stock, v.price
    FROM (VALUES
        ('gr',  'RAW-BEANS',      'Espresso House Blend',      3500.00, 1000.00,   320.00),
        ('gr',  'RAW-COLD-ROAST', 'Kyoto Cold Brew Blend',     2000.00,  600.00,   360.00),
        ('ml',  'RAW-MILK',       'Hokkaido Fresh Milk',       8000.00, 2500.00,    24.00),
        ('ml',  'RAW-OAT-MILK',   'Barista Oat Milk',          1200.00, 1500.00,    42.00),
        ('gr',  'RAW-MATCHA',     'Uji Ceremonial Matcha',      450.00,  200.00,  1400.00),
        ('gr',  'RAW-HOJICHA',    'Roasted Hojicha Powder',     180.00,  250.00,   950.00),
        ('ml',  'RAW-KUROMITSU',  'Okinawa Kuromitsu Syrup',   1400.00,  400.00,    90.00),
        ('ml',  'RAW-VANILLA',    'Madagascar Vanilla Syrup',   900.00,  300.00,   110.00),
        ('gr',  'RAW-CHOCOLATE',  'Dark Chocolate Ganache',    1600.00,  500.00,   180.00),
        ('ml',  'RAW-YUZU',       'Yuzu Citrus Puree',          320.00,  400.00,   160.00),
        ('gr',  'RAW-OOLONG',     'Loose Leaf Peach Oolong',    600.00,  200.00,   480.00),
        ('gr',  'RAW-SESAME',     'Black Sesame Paste',         700.00,  250.00,   260.00),
        ('pcs', 'RAW-PASTRY',     'Artisan Pastry Pack',         24.00,    8.00,  9500.00),
        ('pcs', 'RAW-SAVORY',     'Japanese Savory Prep Pack',    5.00,   10.00, 11000.00)
    ) AS v(unit_sym, sku, name, stock, min_stock, price)
    JOIN units u ON LOWER(u.symbol) = LOWER(v.unit_sym)
    ON CONFLICT (sku) DO NOTHING;

    SELECT id INTO v_user_id FROM users ORDER BY CASE WHEN role = 'admin' THEN 0 ELSE 1 END, id LIMIT 1;

    IF v_user_id IS NOT NULL THEN
        IF NOT EXISTS (SELECT 1 FROM material_purchases WHERE po_number = 'PO-202611-0001') THEN
            INSERT INTO material_purchases (po_number, supplier_id, user_id, purchase_date, total_cost, notes)
            VALUES ('PO-202611-0001', v_sup_roastery, v_user_id, CURRENT_DATE - 2, 2929000.00, 'Weekly roast & ceremonial tea restock')
            RETURNING id INTO v_po1;

            INSERT INTO material_purchase_items (purchase_id, raw_material_id, quantity, unit_price, subtotal)
            SELECT v_po1, rm.id, it.qty, it.price, ROUND(it.qty * it.price, 2)
            FROM (VALUES
                ('RAW-BEANS',      3500.00,  320.00),
                ('RAW-COLD-ROAST', 2000.00,  360.00),
                ('RAW-MATCHA',      450.00, 1400.00),
                ('RAW-HOJICHA',     180.00,  950.00),
                ('RAW-OOLONG',      600.00,  480.00)
            ) AS it(sku, qty, price)
            JOIN raw_materials rm ON rm.sku = it.sku;

            INSERT INTO stock_mutations (raw_material_id, mutation_type, quantity, stock_before, stock_after, reference_type, reference_id, notes)
            SELECT rm.id, 'in', it.qty, 0.00, it.qty, 'purchase', v_po1, 'PO PO-202611-0001'
            FROM (VALUES
                ('RAW-BEANS',      3500.00),
                ('RAW-COLD-ROAST', 2000.00),
                ('RAW-MATCHA',      450.00),
                ('RAW-HOJICHA',     180.00),
                ('RAW-OOLONG',      600.00)
            ) AS it(sku, qty)
            JOIN raw_materials rm ON rm.sku = it.sku;
        END IF;

        IF NOT EXISTS (SELECT 1 FROM material_purchases WHERE po_number = 'PO-202611-0002') THEN
            INSERT INTO material_purchases (po_number, supplier_id, user_id, purchase_date, total_cost, notes)
            VALUES ('PO-202611-0002', v_sup_dairy, v_user_id, CURRENT_DATE - 1, 248400.00, 'Chilled milk & oat carton delivery')
            RETURNING id INTO v_po2;

            INSERT INTO material_purchase_items (purchase_id, raw_material_id, quantity, unit_price, subtotal)
            SELECT v_po2, rm.id, it.qty, it.price, ROUND(it.qty * it.price, 2)
            FROM (VALUES
                ('RAW-MILK',     8250.00, 24.00),
                ('RAW-OAT-MILK', 1200.00, 42.00)
            ) AS it(sku, qty, price)
            JOIN raw_materials rm ON rm.sku = it.sku;

            INSERT INTO stock_mutations (raw_material_id, mutation_type, quantity, stock_before, stock_after, reference_type, reference_id, notes)
            SELECT rm.id, 'in', it.qty, 0.00, it.qty, 'purchase', v_po2, 'PO PO-202611-0002'
            FROM (VALUES
                ('RAW-MILK',     8250.00),
                ('RAW-OAT-MILK', 1200.00)
            ) AS it(sku, qty)
            JOIN raw_materials rm ON rm.sku = it.sku;

            SELECT id INTO v_rm_milk FROM raw_materials WHERE sku = 'RAW-MILK' LIMIT 1;
            INSERT INTO stock_mutations (raw_material_id, mutation_type, quantity, stock_before, stock_after, reference_type, notes)
            VALUES (v_rm_milk, 'waste', 250.00, 8250.00, 8000.00, 'waste', 'Morning steaming calibration waste');
        END IF;

        IF NOT EXISTS (SELECT 1 FROM material_purchases WHERE po_number = 'PO-202611-0003') THEN
            INSERT INTO material_purchases (po_number, supplier_id, user_id, purchase_date, total_cost, notes)
            VALUES ('PO-202611-0003', v_sup_pantry, v_user_id, CURRENT_DATE, 1029200.00, 'Syrups, ganache, and kitchen baked goods')
            RETURNING id INTO v_po3;

            INSERT INTO material_purchase_items (purchase_id, raw_material_id, quantity, unit_price, subtotal)
            SELECT v_po3, rm.id, it.qty, it.price, ROUND(it.qty * it.price, 2)
            FROM (VALUES
                ('RAW-KUROMITSU', 1400.00,    90.00),
                ('RAW-VANILLA',    900.00,   110.00),
                ('RAW-CHOCOLATE', 1600.00,   180.00),
                ('RAW-YUZU',       320.00,   160.00),
                ('RAW-SESAME',     700.00,   260.00),
                ('RAW-PASTRY',      24.00,  9500.00),
                ('RAW-SAVORY',       5.00, 11000.00)
            ) AS it(sku, qty, price)
            JOIN raw_materials rm ON rm.sku = it.sku;

            INSERT INTO stock_mutations (raw_material_id, mutation_type, quantity, stock_before, stock_after, reference_type, reference_id, notes)
            SELECT rm.id, 'in', it.qty, 0.00, it.qty, 'purchase', v_po3, 'PO PO-202611-0003'
            FROM (VALUES
                ('RAW-KUROMITSU', 1400.00),
                ('RAW-VANILLA',    900.00),
                ('RAW-CHOCOLATE', 1600.00),
                ('RAW-YUZU',       320.00),
                ('RAW-SESAME',     700.00),
                ('RAW-PASTRY',      24.00),
                ('RAW-SAVORY',       5.00)
            ) AS it(sku, qty)
            JOIN raw_materials rm ON rm.sku = it.sku;
        END IF;

        PERFORM setval('po_number_seq', GREATEST((SELECT last_value FROM po_number_seq), 3), true);
    END IF;

    INSERT INTO product_recipes (product_id, raw_material_id, quantity_required)
    SELECT p.id, rm.id, r.qty
    FROM (VALUES
        ('COF-ESPRESSO',            'RAW-BEANS',      18.00),
        ('COF-AMERICANO',           'RAW-BEANS',      18.00),
        ('COF-LONG-BLACK',          'RAW-BEANS',      18.00),
        ('COF-ESPRESSO-MACCHIATO',  'RAW-BEANS',      18.00),
        ('COF-ESPRESSO-MACCHIATO',  'RAW-MILK',       30.00),
        ('COF-PICCOLO',             'RAW-BEANS',      18.00),
        ('COF-PICCOLO',             'RAW-MILK',       90.00),
        ('COF-CORTADO',             'RAW-BEANS',      18.00),
        ('COF-CORTADO',             'RAW-MILK',       60.00),
        ('COF-FLAT-WHITE',          'RAW-BEANS',      18.00),
        ('COF-FLAT-WHITE',          'RAW-MILK',      150.00),
        ('COF-CAPPUCCINO',          'RAW-BEANS',      18.00),
        ('COF-CAPPUCCINO',          'RAW-MILK',      150.00),
        ('COF-NOKOTAN-LATTE',       'RAW-BEANS',      18.00),
        ('COF-NOKOTAN-LATTE',       'RAW-MILK',      180.00),
        ('COF-NOKOTAN-LATTE',       'RAW-VANILLA',    15.00),
        ('COF-ICED-COFFEE-MILK',    'RAW-BEANS',      18.00),
        ('COF-ICED-COFFEE-MILK',    'RAW-MILK',      160.00),
        ('COF-ICED-COFFEE-MILK',    'RAW-KUROMITSU',  15.00),
        ('COF-MOCHA',               'RAW-BEANS',      18.00),
        ('COF-MOCHA',               'RAW-MILK',      150.00),
        ('COF-MOCHA',               'RAW-CHOCOLATE',  20.00),
        ('COF-FOREST-COLD-BREW',    'RAW-COLD-ROAST', 25.00),
        ('COF-KYOTO-COLD-BREW',     'RAW-COLD-ROAST', 25.00),
        ('COF-MATCHA-ESPRESSO',     'RAW-BEANS',      18.00),
        ('COF-MATCHA-ESPRESSO',     'RAW-MILK',      150.00),
        ('COF-MATCHA-ESPRESSO',     'RAW-MATCHA',      4.00),
        ('COF-HOJICHA-ESPRESSO',    'RAW-BEANS',      18.00),
        ('COF-HOJICHA-ESPRESSO',    'RAW-MILK',      150.00),
        ('COF-HOJICHA-ESPRESSO',    'RAW-HOJICHA',     5.00),
        ('COF-BLACK-SESAME-LATTE',  'RAW-BEANS',      18.00),
        ('COF-BLACK-SESAME-LATTE',  'RAW-OAT-MILK',  160.00),
        ('COF-BLACK-SESAME-LATTE',  'RAW-SESAME',     15.00),
        ('COF-KUROMITSU-LATTE',     'RAW-BEANS',      18.00),
        ('COF-KUROMITSU-LATTE',     'RAW-MILK',      160.00),
        ('COF-KUROMITSU-LATTE',     'RAW-KUROMITSU',  20.00),
        ('COF-TOKYO-LATTE',         'RAW-BEANS',      18.00),
        ('COF-TOKYO-LATTE',         'RAW-MILK',      170.00),
        ('COF-TOKYO-LATTE',         'RAW-VANILLA',    20.00),
        ('COF-YUZU-ESPRESSO-TONIC', 'RAW-BEANS',      18.00),
        ('COF-YUZU-ESPRESSO-TONIC', 'RAW-YUZU',       25.00),
        ('BEV-UJI-MATCHA-LATTE',    'RAW-MATCHA',      5.00),
        ('BEV-UJI-MATCHA-LATTE',    'RAW-MILK',      180.00),
        ('BEV-KYOTO-HOJICHA-LATTE', 'RAW-HOJICHA',     6.00),
        ('BEV-KYOTO-HOJICHA-LATTE', 'RAW-MILK',      180.00),
        ('BEV-YUZU-SODA',           'RAW-YUZU',       30.00),
        ('BEV-PEACH-OOLONG',        'RAW-OOLONG',      6.00),
        ('BEV-HOKKAIDO-CHOCOLATE',  'RAW-CHOCOLATE',  30.00),
        ('BEV-HOKKAIDO-CHOCOLATE',  'RAW-MILK',      180.00),
        ('SNK-DORAYAKI-AZUKI',      'RAW-PASTRY',      1.00),
        ('SNK-MATCHA-COOKIE',       'RAW-PASTRY',      1.00),
        ('SNK-KINAKO-MOCHI',        'RAW-PASTRY',      1.00),
        ('BIT-ONIGIRI-SHIO',        'RAW-SAVORY',      1.00),
        ('BIT-TAMAGO-SANDO',        'RAW-SAVORY',      1.00),
        ('BIT-CHICKEN-KARAAGE',     'RAW-SAVORY',      1.00)
    ) AS r(prod_sku, mat_sku, qty)
    JOIN products p ON p.sku = r.prod_sku
    JOIN raw_materials rm ON rm.sku = r.mat_sku
    ON CONFLICT (product_id, raw_material_id) DO NOTHING;
END $$;
