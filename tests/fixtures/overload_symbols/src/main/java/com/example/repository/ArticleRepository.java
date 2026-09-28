package com.example.repository;

import com.example.domain.Article;

/**
 * Spring Data repository. Its save(Article) is a DIFFERENT receiver than
 * ArticleService.save; call graph edges must never attribute a
 * {@code repository.save(...)} call to ArticleService.save (US3).
 */
public interface ArticleRepository {

    Article save(Article article);
}