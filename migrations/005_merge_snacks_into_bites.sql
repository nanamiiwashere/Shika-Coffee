-- Merge Snacks category products into Bites and delete the Snacks category.
-- Idempotent: safe to run whether Snacks still exists or was already merged.

DO $$
DECLARE
    v_bites_id INTEGER;
    v_snacks_id INTEGER;
BEGIN
    SELECT id INTO v_bites_id FROM categories WHERE LOWER(name) = 'bites' ORDER BY id LIMIT 1;
    SELECT id INTO v_snacks_id FROM categories WHERE LOWER(name) IN ('snack', 'snacks') ORDER BY id LIMIT 1;

    IF v_snacks_id IS NOT NULL THEN
        IF v_bites_id IS NULL THEN
            UPDATE categories
            SET name = 'Bites',
                description = COALESCE(description, 'Savory small plates, sweets, and Japanese-inspired light bites.')
            WHERE id = v_snacks_id;
        ELSE
            UPDATE products
            SET category_id = v_bites_id,
                updated_at = CURRENT_TIMESTAMP
            WHERE category_id = v_snacks_id;

            DELETE FROM categories WHERE id = v_snacks_id;
        END IF;
    END IF;
END $$;
