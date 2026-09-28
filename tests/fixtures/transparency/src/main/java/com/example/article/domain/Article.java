package com.example.article.domain;

/**
 * Article domain entity used by the overloaded service methods.
 */
public class Article {

    private boolean published;

    public boolean isPublished() {
        return published;
    }

    public void setPublished(boolean published) {
        this.published = published;
    }
}
