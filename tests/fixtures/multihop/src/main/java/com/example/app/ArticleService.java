package com.example.app;

import com.example.core.ArticleRepository;

public class ArticleService {
    private final ArticleRepository articleRepository;

    public ArticleService(ArticleRepository articleRepository) {
        this.articleRepository = articleRepository;
    }

    public String favorite(String slug) {
        // WHY: favorites are stored through the repository so every write keeps
        // the read model consistent.
        return articleRepository.save(slug);
    }
}
