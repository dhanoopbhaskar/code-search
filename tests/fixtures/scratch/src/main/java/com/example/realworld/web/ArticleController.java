package com.example.realworld.web;

import com.example.realworld.model.Article;
import com.example.realworld.service.ArticleService;

public class ArticleController {

    private ArticleService articleService;

    public Article getBySlug(String slug) {
        return articleService.getBySlug(slug);
    }
}
