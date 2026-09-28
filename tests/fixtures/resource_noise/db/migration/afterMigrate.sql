-- After-migrate data cleanup: dedupe and prune stale rows.
-- Mirrors the realworld-springboot afterMigrate.sql that outranked Java answers.

DELETE FROM favorites WHERE article_id IN (
    SELECT a.id FROM articles a
    LEFT JOIN favorites f ON f.article_id = a.id
    WHERE f.id IS NULL AND a.created_at < NOW() - INTERVAL '90 days'
);

INSERT INTO articles (title, slug, body) VALUES
    ('Migrations are ordered by version', 'migrations-are-ordered-by-version', 'seed');

UPDATE articles SET updated_at = NOW() WHERE slug = 'migrations-are-ordered-by-version';

CREATE INDEX idx_articles_slug ON articles (slug);
