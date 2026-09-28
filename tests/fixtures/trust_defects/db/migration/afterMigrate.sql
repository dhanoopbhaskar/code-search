-- Post-migration fixture data (S4 language-pollution fixture). This file is
-- indexed as ``sql`` and must NOT surface in the top-5 for the Java-scoped
-- S4 query "get the feed of articles from authors the current user follows".
INSERT INTO articles (id, slug, title, author_username, feed_rank)
VALUES (1, 'how-to-build-a-code-search', 'How to build a code search', 'alice', 10);

INSERT INTO articles (id, slug, title, author_username, feed_rank)
VALUES (2, 'air-gapped-search', 'Air-gapped code search', 'bob', 9);
