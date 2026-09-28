package com.example.article;

import com.example.article.repository.ArticleRepository;
import com.example.article.domain.Article;

/**
 * Article service exposing two save() overloads and one framework/external
 * callee (repository.save) that must surface as an unresolved edge.
 */
public class ArticleService {

    private final ArticleRepository repository;

    public ArticleService(ArticleRepository repository) {
        this.repository = repository;
    }

    public Article save(Article article) {
        return repository.save(article);
    }

    public Article save(Article article, boolean publish) {
        Article saved = repository.save(article);
        if (publish) {
            saved.setPublished(true);
        }
        return saved;
    }

    public void delete(long id) {
        repository.deleteById(id);
    }
}
