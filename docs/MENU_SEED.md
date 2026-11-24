# Expanded Shika Coffee menu

`migrations/003_seed_expanded_menu.sql` adds **40 new products** without updating or deleting existing products:

| Category | New items | Baseline after 002 + 003 | New prices (IDR) |
| --- | ---: | ---: | ---: |
| Coffee | 20 | 28 (8 original + 20 new) | Rp23,000–Rp38,000 |
| Beverages | 10 | 10 | Rp22,000–Rp32,000 |
| Snacks | 5 | 5 | Rp18,000–Rp28,000 |
| Bites | 5 | 5 | Rp18,000–Rp35,000 |
| **Total** | **40** | **48** | |

The SQL is the authoritative list of names, SKUs, prices, and images. Japanese-inspired options include Kyoto Cold Brew, Hojicha Espresso Latte, Kinako Latte, Kuromitsu Latte, Uji Matcha Latte, Azuki Dorayaki, Kinako Mochi, and onigiri. All drinks are alcohol-free.

All **new** prices are explicit whole Indonesian rupiah values (for example, `32000` means Rp32,000), stored in the existing `NUMERIC(12, 2)` column. This seed does not convert or fix the original eight prices from `002`; their names, prices, images, active status, and other customizations remain untouched.

## Apply to the configured database

Run from the project root, using the project's existing Python environment and installed `requirements.txt` dependencies. The existing schema must already be initialized. The CLI uses `app.database.engine` and the application's existing `DATABASE_URL` from the environment or root `.env`; normal `app.config` requirements, including `JWT_SECRET`, still apply. No separate credentials or hardcoded connection settings are introduced.

Preview offline (does not import database/configuration modules or connect):

```console
python -m app.seed_menu --dry-run
```

Inspect current counts without writing anything:

```console
python -m app.seed_menu --check
```

Apply **only migration 003**, in one transaction:

```console
python -m app.seed_menu
```

Then inspect again:

```console
python -m app.seed_menu --check
```

On a clean eight-coffee reference menu, the first application reports `Added 40 expanded menu item(s).` Repeating it reports `Added 0 expanded menu item(s).` The CLI never executes `001_schema.sql` or `002_seed_coffee_menu.sql`, never truncates data, and never adds the original eight items automatically. Running 003 against an initialized schema without 002 adds only the 40 expanded items.

`--check` explicitly uses a read-only transaction. Its output counts **all** products in the four menu categories, including owner-created items, and separates active from inactive products. Counts are informational, not an assertion that a customized database must contain exactly 48 products. The modes are mutually exclusive; `--dry-run` prints SQL only, without counts or writes.

## Safety and existing customizations

- Categories are matched case-insensitively and reused; existing descriptions and spelling are retained. If historical case-only duplicates already exist, the lowest category ID is used; nothing is merged or deleted.
- A candidate is skipped if **any** existing product has the same `LOWER(name)`, even if its SKU, category, price, image, or active status differs.
- A conflicting SKU is skipped with `ON CONFLICT (sku) DO NOTHING`, even when the owner renamed that product.
- Inactive products stay inactive. Nothing is upserted or overwritten, and existing timestamps are not updated.
- Category/product write locks serialize the guard-and-insert operation, including concurrent runs. Reads remain available; other writers may wait until the short transaction finishes. Any SQL failure rolls the transaction back.
- In a customized database, fewer than 40 insertions can therefore be correct. If both a seeded item's name and SKU are subsequently changed, neither identifier matches it anymore; a later seed can add the reference item as a separate product.

The seed only adds categories/products. It does not add ingredient recipes, raw materials, stock, purchases, or sales. Configure recipes separately as needed for inventory tracking.

## Local images

New coffee variants reuse the eight existing, locally stored coffee photos under `app/static/images/menu/`. These are representative coffee imagery, not newly photographed versions of each flavor; existing files and their credits are unchanged.

Non-coffee products use three original, self-contained SVG **category illustrations**, not mislabeled coffee photos or remote image URLs:

- `app/static/images/menu/shika-expanded-beverages.svg`: a tea/citrus glass.
- `app/static/images/menu/shika-expanded-snacks.svg`: stylized dorayaki and sweets.
- `app/static/images/menu/shika-expanded-bites.svg`: stylized onigiri.

The artwork uses the site's forest-green, cream, and lime palette, has accessible titles/descriptions, and explicitly identifies itself as category artwork rather than a product photograph. Products within a category intentionally share that category illustration.

## Validation (run serially)

The menu tests use the existing `seeded_db` fixture and existing test-database configuration. Before executing schema SQL or `TRUNCATE`, the fixture checks `SELECT current_database()` and refuses any database other than **`shika_coffee_test`**. Without a `TEST_DATABASE_URL` override, the test configuration derives that dedicated database name from the existing database connection settings.

**The fixture truncates the test tables, so do not run these tests alongside other database tests or parallel agents.** Run the focused menu suite serially using the existing virtual environment (Windows):

```console
.\venv\Scripts\python.exe -m pytest tests/test_expanded_menu_seed.py tests/test_coffee_menu_seed.py -q
```

Coverage includes exact names, counts, category placement, whole-rupiah prices, local assets, public menu responses and HTTP image delivery, repeatability, original-row preservation, case-insensitive category/name matching, SKU conflicts, owner edits and inactive status, offline SQL preview, CLI transaction handling, and read-only checking. The fixture includes an unrelated Latte, so the expected product count there is **49**, not the **48**-item clean reference baseline.

## Verified local database run (2026-11-18)

The application's configured root `.env` points to the local PostgreSQL database **`coffeeshop_pos`**. A read-only inspection confirmed a loopback server, the existing `public.categories` and `public.products` schema, and all eight original plus all 40 expansion items already present. No credentials were printed or changed.

| Category | Before | After | Active after | Inactive after |
| --- | ---: | ---: | ---: | ---: |
| Coffee | 28 | 28 | 28 | 0 |
| Beverages | 10 | 10 | 10 | 0 |
| Snacks | 5 | 5 | 5 | 0 |
| Bites | 5 | 5 | 5 | 0 |
| **Total** | **48** | **48** | **48** | **0** |

Only `003_seed_expanded_menu.sql` was reapplied, in a guarded transaction with short lock/statement timeouts. It committed with **0 inserted products**, as expected for an already-seeded database. Full before/after snapshots confirmed every column of all **48 existing products** and **4 existing categories** was unchanged. The 40 expansion SKUs, names, categories, prices, and local image paths matched the seed; a separate read-only transaction confirmed the post-commit counts. Neither `001_schema.sql` nor `002_seed_coffee_menu.sql` was executed, and no application tables were truncated.

The original eight prices are still stored as **`4.00`–`6.50`**. These legacy amounts were deliberately not converted to IDR-scale prices or otherwise repriced. The 40 expansion prices are already whole-rupiah amounts; recipes and stock setup remain separate work.

The existing seed and category artwork already met the requested 20-new-coffee plus 20-other-item requirement; neither was changed during this verification. A focused regression test was added for public delivery of the expanded items and their local JPEG/SVG assets, and this document was updated with the observed results.

Before running tests, a separate read-only connection confirmed the test target was **`shika_coffee_test`**, distinct from `coffeeshop_pos`, and the fixture's pre-truncation guard was inspected. The command above completed with **14 passed**, with one dependency deprecation warning about Starlette's `httpx`-based `TestClient`. The full, unrelated test suite was not run. These results describe this local run, not a production migration or a guarantee about other configured databases.
