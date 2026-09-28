# code-search vs grep benchmark

This report compares the code-search engine against a plain `rg` oracle on the
article-service corpus.

## Query: how do comments get created

Top result by code-search: `ArticleService.createComment`. By `rg`: no literal
match (the phrase is prose, not code).

## Query: database schema

Top result by code-search: `V1__create_articles_table.sql`. By `rg`: no match.

## Query: how is an article created

Top result by code-search: `ArticleService.createComment`/`ArticleService`.
By `rg`: no match.

## Conclusion

The engine outranks `rg` on abstract-paraphrase queries because it fuses BM25
with vector semantics, while `rg` can only match literal text.
