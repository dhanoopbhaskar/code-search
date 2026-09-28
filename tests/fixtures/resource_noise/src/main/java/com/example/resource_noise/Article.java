package com.example.resource_noise;

import java.time.Instant;

/**
 * Article entity with tiny field-declaration chunks and the favorite logic that
 * a Java query ("removes a favorite from an article") should surface at #1.
 */
public class Article {
    private Long id;
    private String title;
    private String slug;
    private String body;
    private String author;
    private Instant createdAt;
    private boolean favorited;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public boolean isFavorited() {
        return favorited;
    }

    public void setFavorited(boolean favorited) {
        this.favorited = favorited;
    }

    public void removeFavorite() {
        this.favorited = false;
    }
}
