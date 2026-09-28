package com.example.semvec.favorite;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

public final class FavoritesTrackerTest {

    private final FavoritesTracker tracker = new FavoritesTracker();

    @Test
    public void favoritesArticle_markedForReader() {
        this.tracker.mark("reader-1", "article-7");
        assertTrue(this.tracker.hearted("reader-1", "article-7"));
    }

    @Test
    public void favoritesArticle_bookmarked() {
        this.tracker.bookmark("reader-2", "article-9");
        assertTrue(this.tracker.hearted("reader-2", "article-9"));
    }

    @Test
    public void favoritesArticle_removed() {
        this.tracker.mark("reader-3", "article-3");
        this.tracker.remove("reader-3", "article-3");
        assertFalse(this.tracker.hearted("reader-3", "article-3"));
    }
}