package com.example.realworld.service;

import com.example.realworld.model.Article;

public class ArticleService {

    public Article getBySlug(String slug) {
        return new Article(slug);
    }
}
