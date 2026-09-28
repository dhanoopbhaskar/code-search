package com.example.web;

import com.example.domain.Article;
import com.example.domain.Profile;
import com.example.domain.Tag;
import com.example.service.ArticleService;

import java.util.List;

/**
 * Controller that calls the 3-arg ArticleService.save overload — the real
 * caller that must appear in ArticleService.save's call graph.
 */
public class ArticleController {

    private ArticleService articleService;

    public Article save(Article article, Profile profile, List<Tag> tags) {
        return articleService.save(article, profile, tags);
    }

    public Article update(Article article, Profile profile) {
        return articleService.save(article, profile, List.of());
    }
}