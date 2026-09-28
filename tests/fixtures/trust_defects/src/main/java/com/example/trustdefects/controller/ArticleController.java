package com.example.trustdefects.controller;

import com.example.trustdefects.service.ArticleService;

/** Article REST controller (L3 fixture — one of six @CheckSecurity controllers). */
public class ArticleController {

    private ArticleService articleService;

    @CheckSecurity("canEdit")
    public void updateArticle(String slug) {
        articleService.getBySlug(slug);
    }
}
