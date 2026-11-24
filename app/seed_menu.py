"""Apply only the additive expanded-menu seed to the configured PostgreSQL DB."""

import argparse
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parent.parent / "migrations" / "003_seed_expanded_menu.sql"
CHECK_SQL = """
    SELECT category.name,
           COUNT(product.id) AS total,
           COUNT(product.id) FILTER (WHERE product.is_active) AS active,
           COUNT(product.id) FILTER (WHERE NOT product.is_active) AS inactive
    FROM categories category
    LEFT JOIN products product ON product.category_id = category.id
    WHERE LOWER(category.name) IN ('coffee', 'beverages', 'snacks', 'bites')
    GROUP BY category.id, category.name
    ORDER BY CASE LOWER(category.name)
        WHEN 'coffee' THEN 1 WHEN 'beverages' THEN 2 WHEN 'snacks' THEN 3 ELSE 4 END,
        category.id
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Read-only category counts; do not seed.")
    mode.add_argument("--dry-run", action="store_true", help="Print only migration 003; do not connect.")
    args = parser.parse_args(argv)

    sql = SEED_PATH.read_text(encoding="utf-8") if not args.check else None
    if args.dry_run:
        print(sql, end="")
        return 0

    # Keep help and SQL preview usable without application config or DB access.
    from sqlalchemy.exc import SQLAlchemyError

    try:
        from app.database import engine
    except KeyError as exc:
        parser.exit(1, f"Missing application configuration: {exc.args[0]}. Use the existing environment or .env.\n")

    try:
        with engine.begin() as connection:
            if args.check:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                rows = connection.exec_driver_sql(CHECK_SQL).mappings().all()
            else:
                inserted = connection.exec_driver_sql(sql).fetchall()
        # Report success only after the transaction has committed.
        if args.check:
            for row in rows:
                print(f"{row['name']}: {row['total']} total ({row['active']} active, {row['inactive']} inactive)")
            print(f"Total in these categories: {sum(row['total'] for row in rows)}")
        else:
            print(f"Added {len(inserted)} expanded menu item(s). Existing products were left unchanged.")
        return 0
    except SQLAlchemyError:
        # Driver exception text can contain connection details; do not print credentials.
        parser.exit(1, "Menu seed/check failed; no changes committed. Check database access and the existing schema.\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
