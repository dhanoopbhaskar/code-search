package com.example.service;

import com.example.domain.Article;
import com.example.domain.Profile;
import com.example.domain.Tag;
import com.example.repository.ArticleRepository;

import java.util.List;

/**
 * ArticleService exposes two save() overloads. Call-graph edges (US3) must be
 * receiver-keyed: the 3-arg save is called from the controller, never from a
 * {@code repository.save} call inside this class.
 */
public class ArticleService {

    private ArticleRepository repository;

    public Article save(Article article, Profile profile, List<Tag> tags) {
        article.setTitle(article.getTitle() + tags.size());
        return repository.save(article);
    }

    public Article save(Article article) {
        return repository.save(article);
    }

    public void profileFavorited(Profile profile) {
        Article article = new Article();
        repository.save(article);
    }

    public void profileUnfavorited(Profile profile) {
        Article article = new Article();
        repository.save(article);
    }
}