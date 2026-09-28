package com.example.article;

import org.springframework.security.access.prepost.PreAuthorize;

public class ArticleRepository {
    // Articles are persisted (stored) here and read back by id.

    public void deleteById(Long id) {
    }

    @PreAuthorize("hasRole('ADMIN')")
    public void save(Comment comment) {
    }

    public ArticleResponse findById(Long id) {
        return null;
    }
}
