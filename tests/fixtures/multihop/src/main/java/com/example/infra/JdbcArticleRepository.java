package com.example.infra;

import com.example.core.ArticleRepository;

public class JdbcArticleRepository implements ArticleRepository {
    public String save(String slug) {
        return "INSERT INTO favorites VALUES ('" + slug + "')";
    }
}
