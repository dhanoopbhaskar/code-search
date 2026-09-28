package com.example.article;

import com.example.article.model.Article;
import org.springframework.security.access.prepost.PreAuthorize;

public class ArticleAuthorization {

    @PreAuthorize("hasRole('ADMIN') or isArticleOwner(#article)")
    public boolean canDeleteArticle(Article article) {
        return isArticleOwner(article);
    }

    private boolean isArticleOwner(Article article) {
        return article.getAuthor() != null;
    }
}