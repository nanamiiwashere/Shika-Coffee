-- Reference coffee menu. Run after 001_schema.sql, inside a transaction.
-- Safe to repeat: preserve existing names, prices, images, and inactive products.
INSERT INTO categories (name, description)
SELECT 'Coffee', 'Freshly brewed coffee and espresso favorites.'
WHERE NOT EXISTS (SELECT 1 FROM categories WHERE LOWER(name) = 'coffee')
ON CONFLICT (name) DO NOTHING;

INSERT INTO products (category_id, sku, name, price, image_url)
SELECT category.id, menu.sku, menu.name, menu.price, menu.image_url
FROM (
    VALUES
        ('COF-AMERICANO', 'Americano', 4.50, '/static/images/menu/americano.jpg'),
        ('COF-CAPPUCCINO', 'Cappuccino', 5.00, '/static/images/menu/cappuccino.jpg'),
        ('COF-ESPRESSO', 'Espresso', 4.00, '/static/images/menu/espresso.jpg'),
        ('COF-FLAT-WHITE', 'Flat White', 5.50, '/static/images/menu/flat-white.jpg'),
        ('COF-FOREST-COLD-BREW', 'Forest Cold Brew', 5.50, '/static/images/menu/forest-cold-brew.jpg'),
        ('COF-ICED-COFFEE-MILK', 'Iced Coffee Milk', 5.00, '/static/images/menu/iced-coffee-milk.jpg'),
        ('COF-MOCHA', 'Mocha', 6.00, '/static/images/menu/mocha.jpg'),
        ('COF-NOKOTAN-LATTE', 'Nokotan Latte', 6.50, '/static/images/menu/nokotan-latte.jpg')
) AS menu (sku, name, price, image_url)
CROSS JOIN (
    SELECT id FROM categories WHERE LOWER(name) = 'coffee' ORDER BY id LIMIT 1
) AS category
WHERE NOT EXISTS (
    SELECT 1 FROM products existing WHERE LOWER(existing.name) = LOWER(menu.name)
)
ON CONFLICT (sku) DO NOTHING;
