-- Initial schema migration.
--
-- Reproduces FR-008: a SQL migration splits into multiple line-block chunks
-- under _fallback_chunk_file. Searches for "INSERT INTO" must return this file
-- at most once.
CREATE TABLE articles (
    id BIGINT PRIMARY KEY,
    slug VARCHAR(255) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    body TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tags (
    id BIGINT PRIMARY KEY,
    name VARCHAR(64) NOT NULL UNIQUE
);

CREATE TABLE article_tags (
    article_id BIGINT NOT NULL REFERENCES articles(id),
    tag_id BIGINT NOT NULL REFERENCES tags(id),
    PRIMARY KEY (article_id, tag_id)
);

CREATE INDEX idx_articles_slug ON articles(slug);
CREATE INDEX idx_articles_created_at ON articles(created_at);
CREATE INDEX idx_tags_name ON tags(name);

INSERT INTO articles (id, slug, title, body) VALUES
    (1, 'how-to-build-a-code-search', 'How to build a code search tool', 'A long body about indexing and retrieval.'),
    (2, 'rff-and-bm25', 'RRF and BM25', 'Reciprocal rank fusion explained.'),
    (3, 'air-gapped-search', 'Air-gapped code search', 'Running retrieval with zero network access.');

INSERT INTO tags (id, name) VALUES (1, 'search'), (2, 'bm25'), (3, 'architecture');

INSERT INTO article_tags (article_id, tag_id) VALUES
    (1, 1), (1, 3), (2, 1), (2, 2), (3, 1);
