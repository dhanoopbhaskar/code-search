package com.example.trustdefects.domain;

/** A published article with a unique slug and an author. */
public class Article {

    private String slug;
    private String title;
    private String author;

    public String getSlug() {
        return slug;
    }

    public String getTitle() {
        return title;
    }

    public String getAuthor() {
        return author;
    }
}
