package com.example.resource_noise;

import java.util.Locale;

/**
 * Service that creates a slug from an article title and persists articles.
 * "create a slug from the article title" should surface save() at #1.
 */
public class ArticleService {
    private Long id;
    private ArticleRepository repository;

    public String createSlug(String title) {
        return title.trim().toLowerCase(Locale.ROOT).replaceAll("\\s+", "-");
    }

    public void save(Article article) {
        article.setSlug(createSlug(article.getTitle()));
        repository.save(article);
    }
}
