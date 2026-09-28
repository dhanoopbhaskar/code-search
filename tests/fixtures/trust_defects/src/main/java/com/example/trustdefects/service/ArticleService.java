package com.example.trustdefects.service;

import com.example.trustdefects.domain.Article;
import com.example.trustdefects.domain.User;

/**
 * Article service (S4 / X1 fixture). ``getFeedByUser`` is the ground-truth
 * answer to the report's "get the feed of articles from authors the current
 * user follows" query; ``getBySlug`` is the definition target for "definition
 * of ArticleService.getBySlug".
 */
public class ArticleService {

    public Article getBySlug(String slug) {
        if (slug == null || slug.isBlank()) {
            return null;
        }
        return new Article();
    }

    public java.util.List<Article> getFeedByUser(User currentUser) {
        return java.util.List.of();
    }

    public boolean isSlugAlreadyTaken(String slug) {
        return slug != null && slug.equals("taken");
    }

    public Article save(Article article) {
        return article;
    }

    public Article save(Article article, boolean publish) {
        return article;
    }
}
