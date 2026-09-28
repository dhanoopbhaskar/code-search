package com.example.article;

import com.example.article.dto.ArticleResponse;

public class ArticleService {
    private final ArticleRepository articleRepository;

    public ArticleService(ArticleRepository articleRepository) {
        this.articleRepository = articleRepository;
    }

    @PreAuthorize("hasRole('ADMIN') or hasRole('EDITOR')")
    public void deleteArticle(Long articleId) {
        articleRepository.deleteById(articleId);
    }

    @PreAuthorize("isAuthenticated()")
    public Comment createComment(Long articleId, String body, String author) {
        Comment comment = new Comment(author, body);
        articleRepository.save(comment);
        return comment;
    }

    public ArticleResponse getArticle(Long articleId) {
        return articleRepository.findById(articleId);
    }
}
