-- Additive seed: complete pantry ingredients, remaining 18 product BOM recipes (48/48 coverage),
-- transparent menu product images, and initial Shift Notes in PostgreSQL.
-- Safe to run multiple times.

DO $$
DECLARE
    v_user_id BIGINT;
BEGIN
    INSERT INTO raw_materials (unit_id, sku, name, current_stock, minimum_stock, latest_purchase_price)
    SELECT u.id, v.sku, v.name, v.stock, v.min_stock, v.price
    FROM (VALUES
        ('gr', 'RAW-KINAKO',     'Roasted Kinako Powder',          800.00, 200.00, 240.00),
        ('ml', 'RAW-STRAWBERRY', 'Ichigo Strawberry Puree',       1200.00, 300.00, 130.00),
        ('gr', 'RAW-GENMAICHA',  'Uji Genmaicha Tea Leaf',         500.00, 150.00, 420.00),
        ('ml', 'RAW-CARAMEL',    'Salted Caramel Syrup',          1000.00, 300.00, 105.00),
        ('ml', 'RAW-HAZELNUT',   'Roasted Hazelnut Syrup',         950.00, 300.00, 105.00),
        ('ml', 'RAW-HONEY',      'Osaka Blossom Honey',            850.00, 250.00, 140.00),
        ('ml', 'RAW-COCONUT',    'Barista Coconut Milk',          2400.00, 600.00,  38.00),
        ('gr', 'RAW-WHITE-CHOC', 'Hokkaido White Chocolate Sauce', 1100.00, 300.00, 210.00)
    ) AS v(unit_sym, sku, name, stock, min_stock, price)
    JOIN units u ON LOWER(u.symbol) = LOWER(v.unit_sym)
    ON CONFLICT (sku) DO NOTHING;

    INSERT INTO product_recipes (product_id, raw_material_id, quantity_required)
    SELECT p.id, rm.id, r.qty
    FROM (VALUES
        ('BEV-SAKURA-LEMON-TEA',    'RAW-OOLONG',      5.00),
        ('BEV-SAKURA-LEMON-TEA',    'RAW-YUZU',       20.00),
        ('BEV-SAKURA-LEMON-TEA',    'RAW-HONEY',      10.00),
        ('BEV-KUROMITSU-MILK',      'RAW-MILK',      180.00),
        ('BEV-KUROMITSU-MILK',      'RAW-KUROMITSU',  25.00),
        ('BEV-KINAKO-MILK',         'RAW-MILK',      180.00),
        ('BEV-KINAKO-MILK',         'RAW-KINAKO',     12.00),
        ('BEV-KINAKO-MILK',         'RAW-KUROMITSU',  10.00),
        ('BEV-ICHIGO-MILK',         'RAW-MILK',      170.00),
        ('BEV-ICHIGO-MILK',         'RAW-STRAWBERRY', 35.00),
        ('BEV-ICED-GENMAICHA',      'RAW-GENMAICHA',   7.00),
        ('BEV-ICED-GENMAICHA',      'RAW-HONEY',       8.00),
        ('BIT-ONIGIRI-TUNA',        'RAW-SAVORY',      1.00),
        ('BIT-NORI-FRIES',          'RAW-SAVORY',      1.00),
        ('SNK-KUROMITSU-PUDDING',   'RAW-PASTRY',      1.00),
        ('SNK-KUROMITSU-PUDDING',   'RAW-KUROMITSU',  10.00),
        ('SNK-HOJICHA-ROLL',        'RAW-PASTRY',      1.00),
        ('SNK-HOJICHA-ROLL',        'RAW-HOJICHA',     2.00),
        ('COF-OKINAWA-BROWN-SUGAR', 'RAW-BEANS',      18.00),
        ('COF-OKINAWA-BROWN-SUGAR', 'RAW-MILK',      150.00),
        ('COF-OKINAWA-BROWN-SUGAR', 'RAW-KUROMITSU',  20.00),
        ('COF-SALTED-CARAMEL',      'RAW-BEANS',      18.00),
        ('COF-SALTED-CARAMEL',      'RAW-MILK',      160.00),
        ('COF-SALTED-CARAMEL',      'RAW-CARAMEL',    20.00),
        ('COF-OSAKA-HONEY',         'RAW-BEANS',      18.00),
        ('COF-OSAKA-HONEY',         'RAW-HONEY',      20.00),
        ('COF-KINAKO-LATTE',        'RAW-BEANS',      18.00),
        ('COF-KINAKO-LATTE',        'RAW-OAT-MILK',  150.00),
        ('COF-KINAKO-LATTE',        'RAW-KINAKO',     10.00),
        ('COF-CINNAMON-CAPPUCCINO', 'RAW-BEANS',      18.00),
        ('COF-CINNAMON-CAPPUCCINO', 'RAW-MILK',      140.00),
        ('COF-CINNAMON-CAPPUCCINO', 'RAW-VANILLA',    10.00),
        ('COF-COCONUT-LATTE',       'RAW-BEANS',      18.00),
        ('COF-COCONUT-LATTE',       'RAW-COCONUT',   160.00),
        ('COF-COCONUT-LATTE',       'RAW-VANILLA',    10.00),
        ('COF-HAZELNUT-LATTE',      'RAW-BEANS',      18.00),
        ('COF-HAZELNUT-LATTE',      'RAW-MILK',      160.00),
        ('COF-HAZELNUT-LATTE',      'RAW-HAZELNUT',   20.00),
        ('COF-DARK-CHOCOLATE-MOCHA','RAW-BEANS',      18.00),
        ('COF-DARK-CHOCOLATE-MOCHA','RAW-MILK',      150.00),
        ('COF-DARK-CHOCOLATE-MOCHA','RAW-CHOCOLATE',  25.00),
        ('COF-HOKKAIDO-WHITE-MOCHA','RAW-BEANS',      18.00),
        ('COF-HOKKAIDO-WHITE-MOCHA','RAW-MILK',      150.00),
        ('COF-HOKKAIDO-WHITE-MOCHA','RAW-WHITE-CHOC', 25.00)
    ) AS r(prod_sku, mat_sku, qty)
    JOIN products p ON p.sku = r.prod_sku
    JOIN raw_materials rm ON rm.sku = r.mat_sku
    ON CONFLICT (product_id, raw_material_id) DO NOTHING;

    UPDATE products p
    SET image_url = m.image_url,
        updated_at = CURRENT_TIMESTAMP
    FROM (VALUES
        ('BEV-UJI-MATCHA-LATTE',    '/static/images/menu/matcha-latte.png'),
        ('BEV-ICED-GENMAICHA',      '/static/images/menu/matcha-latte.png'),
        ('BEV-KYOTO-HOJICHA-LATTE', '/static/images/menu/hojicha-latte.png'),
        ('BEV-KINAKO-MILK',         '/static/images/menu/hojicha-latte.png'),
        ('BEV-KUROMITSU-MILK',      '/static/images/menu/hojicha-latte.png'),
        ('BEV-YUZU-SODA',           '/static/images/menu/yuzu-soda.png'),
        ('BEV-PEACH-OOLONG',        '/static/images/menu/yuzu-soda.png'),
        ('BEV-SAKURA-LEMON-TEA',    '/static/images/menu/yuzu-soda.png'),
        ('BEV-ICHIGO-MILK',         '/static/images/menu/ichigo-milk.png'),
        ('BEV-HOKKAIDO-CHOCOLATE',  '/static/images/menu/hokkaido-chocolate.png'),
        ('SNK-DORAYAKI-AZUKI',      '/static/images/menu/dorayaki.png'),
        ('SNK-HOJICHA-ROLL',        '/static/images/menu/dorayaki.png'),
        ('SNK-MATCHA-COOKIE',       '/static/images/menu/matcha-cookie.png'),
        ('SNK-KINAKO-MOCHI',        '/static/images/menu/kinako-mochi.png'),
        ('SNK-KUROMITSU-PUDDING',   '/static/images/menu/kinako-mochi.png'),
        ('BIT-ONIGIRI-SHIO',        '/static/images/menu/onigiri.png'),
        ('BIT-ONIGIRI-TUNA',        '/static/images/menu/onigiri.png'),
        ('BIT-TAMAGO-SANDO',        '/static/images/menu/tamago-sando.png'),
        ('BIT-CHICKEN-KARAAGE',     '/static/images/menu/tamago-sando.png'),
        ('BIT-NORI-FRIES',          '/static/images/menu/onigiri.png'),
        ('COF-NOKOTAN-LATTE',       '/static/images/menu/hot-latte.png'),
        ('COF-FLAT-WHITE',          '/static/images/menu/hot-latte.png'),
        ('COF-CAPPUCCINO',          '/static/images/menu/hot-latte.png'),
        ('COF-CORTADO',             '/static/images/menu/hot-latte.png'),
        ('COF-PICCOLO',             '/static/images/menu/hot-latte.png'),
        ('COF-TOKYO-LATTE',         '/static/images/menu/hot-latte.png'),
        ('COF-KINAKO-LATTE',        '/static/images/menu/hot-latte.png'),
        ('COF-CINNAMON-CAPPUCCINO', '/static/images/menu/hot-latte.png'),
        ('COF-HAZELNUT-LATTE',      '/static/images/menu/hot-latte.png'),
        ('COF-BLACK-SESAME-LATTE',  '/static/images/menu/hot-latte.png'),
        ('COF-MATCHA-ESPRESSO',     '/static/images/menu/hot-latte.png'),
        ('COF-ICED-COFFEE-MILK',    '/static/images/menu/iced-latte.png'),
        ('COF-OKINAWA-BROWN-SUGAR', '/static/images/menu/iced-latte.png'),
        ('COF-KUROMITSU-LATTE',     '/static/images/menu/iced-latte.png'),
        ('COF-SALTED-CARAMEL',      '/static/images/menu/iced-latte.png'),
        ('COF-COCONUT-LATTE',       '/static/images/menu/iced-latte.png'),
        ('COF-HOJICHA-ESPRESSO',    '/static/images/menu/iced-latte.png'),
        ('COF-AMERICANO',           '/static/images/menu/cold-brew.png'),
        ('COF-LONG-BLACK',          '/static/images/menu/cold-brew.png'),
        ('COF-FOREST-COLD-BREW',    '/static/images/menu/cold-brew.png'),
        ('COF-KYOTO-COLD-BREW',     '/static/images/menu/cold-brew.png'),
        ('COF-OSAKA-HONEY',         '/static/images/menu/cold-brew.png'),
        ('COF-YUZU-ESPRESSO-TONIC', '/static/images/menu/cold-brew.png'),
        ('COF-ESPRESSO',            '/static/images/menu/cold-brew.png'),
        ('COF-ESPRESSO-MACCHIATO',  '/static/images/menu/cold-brew.png'),
        ('COF-MOCHA',               '/static/images/menu/mocha-cup.png'),
        ('COF-DARK-CHOCOLATE-MOCHA','/static/images/menu/mocha-cup.png'),
        ('COF-HOKKAIDO-WHITE-MOCHA','/static/images/menu/mocha-cup.png')
    ) AS m(sku, image_url)
    WHERE p.sku = m.sku;

    SELECT id INTO v_user_id FROM users ORDER BY CASE WHEN role = 'admin' THEN 0 WHEN role = 'manager' THEN 1 ELSE 2 END, id LIMIT 1;

    IF NOT EXISTS (SELECT 1 FROM shift_notes) THEN
        INSERT INTO shift_notes (user_id, category, content, is_done, created_at) VALUES
            (v_user_id, 'flavor',      'Ethiopia Guji pulling bright white peach and jasmine at 93°C, 1:16 ratio (2:45 drawdown).', FALSE, CURRENT_TIMESTAMP - INTERVAL '18 minutes'),
            (v_user_id, 'flavor',      'Espresso House Blend dialed at 18g in / 36g out in 28s; sweet dark cacao finish with Hokkaido milk.', FALSE, CURRENT_TIMESTAMP - INTERVAL '42 minutes'),
            (v_user_id, 'service',     'Uji tencha tin #2 opened; keep counter chasen soaked in warm water ahead of mid-day rush.', FALSE, CURRENT_TIMESTAMP - INTERVAL '1 hour 10 minutes'),
            (v_user_id, 'maintenance', 'EK43 burrs brushed before opening; schedule zero-point calibration after evening close.', FALSE, CURRENT_TIMESTAMP - INTERVAL '1 hour 40 minutes'),
            (v_user_id, 'maintenance', 'Backflush group heads 1 & 2 with Cafiza after afternoon rush and inspect steam wand gaskets.', TRUE, CURRENT_TIMESTAMP - INTERVAL '2 hours 15 minutes');
    END IF;
END $$;
