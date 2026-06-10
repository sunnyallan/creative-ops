-- v2.0 Commit C: drop legacy brand_kits table now that all code reads from brands

DROP TABLE IF EXISTS brand_kits CASCADE;
