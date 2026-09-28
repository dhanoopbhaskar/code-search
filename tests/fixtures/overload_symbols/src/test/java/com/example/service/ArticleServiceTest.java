package com.example.service;

import com.example.domain.Article;
import com.example.domain.Profile;
import com.example.domain.Tag;

import java.util.List;

public class ArticleServiceTest {

    private ArticleService articleService;

    public void savesArticleWithTags() {
        Article article = new Article();
        Profile profile = new Profile();
        List<Tag> tags = List.of();
        articleService.save(article, profile, tags);
    }
}
