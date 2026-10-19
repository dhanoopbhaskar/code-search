package com.example.web;

import com.example.app.ArticleService;

public class ArticleController {
    private final ArticleService articleService;

    public ArticleController(ArticleService articleService) {
        this.articleService = articleService;
    }

    public String favoriteArticle(String slug) {
        return articleService.favorite(slug);
    }
}
