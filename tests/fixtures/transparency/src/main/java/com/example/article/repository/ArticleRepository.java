package com.example.article.repository;

import com.example.article.domain.Article;

/**
 * Spring Data repository. ``save`` is inherited from the external
 * ``JpaRepository`` base (not indexed in this corpus), so a
 * ``repository.save(...)`` call must surface as an unresolved callee.
 */
public interface ArticleRepository extends JpaRepository<Article, Long> {

    void deleteById(long id);
}
