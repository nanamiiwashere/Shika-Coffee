-- Additive menu expansion: 20 coffees, 10 beverages, 5 snacks, and 5 bites.
-- Run against the existing schema, inside a transaction (python -m app.seed_menu).
-- Serialize inserts so concurrent runs cannot bypass the LOWER(name) guards.
LOCK TABLE categories, products IN SHARE ROW EXCLUSIVE MODE;

INSERT INTO categories (name, description)
SELECT menu.name, menu.description
FROM (
    VALUES
        ('Coffee', 'Freshly brewed coffee and espresso favorites.'),
        ('Beverages', 'Alcohol-free tea, milk, chocolate, and fruit refreshments.'),
        ('Snacks', 'Sweet treats with Japanese-inspired flavors.'),
        ('Bites', 'Savory small plates and Japanese-inspired light bites.')
) AS menu (name, description)
WHERE NOT EXISTS (
    SELECT 1 FROM categories existing WHERE LOWER(existing.name) = LOWER(menu.name)
)
ON CONFLICT (name) DO NOTHING;

INSERT INTO products (category_id, sku, name, price, image_url)
SELECT category.id, menu.sku, menu.name, menu.price, menu.image_url
FROM (
    VALUES
        ('Coffee', 'COF-KYOTO-COLD-BREW', 'Kyoto Cold Brew', 30000, '/static/images/menu/forest-cold-brew.jpg'),
        ('Coffee', 'COF-TOKYO-LATTE', 'Tokyo Vanilla Latte', 32000, '/static/images/menu/nokotan-latte.jpg'),
        ('Coffee', 'COF-HOJICHA-ESPRESSO', 'Hojicha Espresso Latte', 35000, '/static/images/menu/iced-coffee-milk.jpg'),
        ('Coffee', 'COF-KINAKO-LATTE', 'Kinako Latte', 34000, '/static/images/menu/nokotan-latte.jpg'),
        ('Coffee', 'COF-KUROMITSU-LATTE', 'Kuromitsu Latte', 34000, '/static/images/menu/iced-coffee-milk.jpg'),
        ('Coffee', 'COF-OKINAWA-BROWN-SUGAR', 'Okinawa Brown Sugar Coffee', 33000, '/static/images/menu/iced-coffee-milk.jpg'),
        ('Coffee', 'COF-MATCHA-ESPRESSO', 'Uji Matcha Espresso', 38000, '/static/images/menu/nokotan-latte.jpg'),
        ('Coffee', 'COF-BLACK-SESAME-LATTE', 'Black Sesame Latte', 36000, '/static/images/menu/nokotan-latte.jpg'),
        ('Coffee', 'COF-YUZU-ESPRESSO-TONIC', 'Yuzu Espresso Tonic', 35000, '/static/images/menu/americano.jpg'),
        ('Coffee', 'COF-OSAKA-HONEY', 'Osaka Honey Coffee', 30000, '/static/images/menu/americano.jpg'),
        ('Coffee', 'COF-SALTED-CARAMEL', 'Salted Caramel Latte', 34000, '/static/images/menu/iced-coffee-milk.jpg'),
        ('Coffee', 'COF-HAZELNUT-LATTE', 'Hazelnut Latte', 32000, '/static/images/menu/nokotan-latte.jpg'),
        ('Coffee', 'COF-COCONUT-LATTE', 'Coconut Latte', 32000, '/static/images/menu/iced-coffee-milk.jpg'),
        ('Coffee', 'COF-HOKKAIDO-WHITE-MOCHA', 'Hokkaido White Mocha', 37000, '/static/images/menu/mocha.jpg'),
        ('Coffee', 'COF-DARK-CHOCOLATE-MOCHA', 'Dark Chocolate Mocha', 35000, '/static/images/menu/mocha.jpg'),
        ('Coffee', 'COF-CINNAMON-CAPPUCCINO', 'Cinnamon Cappuccino', 30000, '/static/images/menu/cappuccino.jpg'),
        ('Coffee', 'COF-PICCOLO', 'Piccolo', 25000, '/static/images/menu/flat-white.jpg'),
        ('Coffee', 'COF-CORTADO', 'Cortado', 26000, '/static/images/menu/flat-white.jpg'),
        ('Coffee', 'COF-LONG-BLACK', 'Long Black', 24000, '/static/images/menu/americano.jpg'),
        ('Coffee', 'COF-ESPRESSO-MACCHIATO', 'Espresso Macchiato', 23000, '/static/images/menu/espresso.jpg'),
        ('Beverages', 'BEV-UJI-MATCHA-LATTE', 'Uji Matcha Latte', 32000, '/static/images/menu/shika-expanded-beverages.svg'),
        ('Beverages', 'BEV-KYOTO-HOJICHA-LATTE', 'Kyoto Hojicha Latte', 30000, '/static/images/menu/shika-expanded-beverages.svg'),
        ('Beverages', 'BEV-KINAKO-MILK', 'Kinako Milk', 28000, '/static/images/menu/shika-expanded-beverages.svg'),
        ('Beverages', 'BEV-KUROMITSU-MILK', 'Kuromitsu Milk', 28000, '/static/images/menu/shika-expanded-beverages.svg'),
        ('Beverages', 'BEV-YUZU-SODA', 'Yuzu Citrus Soda', 27000, '/static/images/menu/shika-expanded-beverages.svg'),
        ('Beverages', 'BEV-SAKURA-LEMON-TEA', 'Sakura Lemon Tea', 26000, '/static/images/menu/shika-expanded-beverages.svg'),
        ('Beverages', 'BEV-PEACH-OOLONG', 'Peach Oolong Tea', 25000, '/static/images/menu/shika-expanded-beverages.svg'),
        ('Beverages', 'BEV-ICED-GENMAICHA', 'Iced Genmaicha', 22000, '/static/images/menu/shika-expanded-beverages.svg'),
        ('Beverages', 'BEV-HOKKAIDO-CHOCOLATE', 'Hokkaido Chocolate Milk', 30000, '/static/images/menu/shika-expanded-beverages.svg'),
        ('Beverages', 'BEV-ICHIGO-MILK', 'Ichigo Strawberry Milk', 30000, '/static/images/menu/shika-expanded-beverages.svg'),
        ('Snacks', 'SNK-DORAYAKI-AZUKI', 'Azuki Dorayaki', 22000, '/static/images/menu/shika-expanded-snacks.svg'),
        ('Snacks', 'SNK-MATCHA-COOKIE', 'Matcha White Chocolate Cookie', 18000, '/static/images/menu/shika-expanded-snacks.svg'),
        ('Snacks', 'SNK-KINAKO-MOCHI', 'Kinako Mochi', 24000, '/static/images/menu/shika-expanded-snacks.svg'),
        ('Snacks', 'SNK-HOJICHA-ROLL', 'Hojicha Roll Cake', 28000, '/static/images/menu/shika-expanded-snacks.svg'),
        ('Snacks', 'SNK-KUROMITSU-PUDDING', 'Kuromitsu Milk Pudding', 25000, '/static/images/menu/shika-expanded-snacks.svg'),
        ('Bites', 'BIT-ONIGIRI-SHIO', 'Shio Onigiri', 18000, '/static/images/menu/shika-expanded-bites.svg'),
        ('Bites', 'BIT-ONIGIRI-TUNA', 'Tuna Mayo Onigiri', 24000, '/static/images/menu/shika-expanded-bites.svg'),
        ('Bites', 'BIT-TAMAGO-SANDO', 'Tamago Sando', 30000, '/static/images/menu/shika-expanded-bites.svg'),
        ('Bites', 'BIT-CHICKEN-KARAAGE', 'Shoyu Chicken Karaage', 35000, '/static/images/menu/shika-expanded-bites.svg'),
        ('Bites', 'BIT-NORI-FRIES', 'Nori Fries', 25000, '/static/images/menu/shika-expanded-bites.svg')
) AS menu (category_name, sku, name, price, image_url)
CROSS JOIN LATERAL (
    SELECT id FROM categories
    WHERE LOWER(name) = LOWER(menu.category_name)
    ORDER BY id LIMIT 1
) AS category
WHERE NOT EXISTS (
    SELECT 1 FROM products existing WHERE LOWER(existing.name) = LOWER(menu.name)
)
ON CONFLICT (sku) DO NOTHING
RETURNING sku, name;
