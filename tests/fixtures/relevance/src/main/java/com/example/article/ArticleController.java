package com.example.article;

import com.example.article.dto.ArticleResponse;

public class ArticleController {
    private final ArticleService articleService;

    public ArticleController(ArticleService articleService) {
        this.articleService = articleService;
    }

    public ArticleResponse createComment(Long articleId, String body, String author) {
        return articleService.createComment(articleId, body, author);
    }

    public ArticleResponse getArticle(Long articleId) {
        return articleService.getArticle(articleId);
    }
}
