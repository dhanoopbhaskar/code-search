package com.example.semvec.favorite;

import java.util.HashMap;
import java.util.Map;
import java.util.Set;

public final class FavoritesTracker {

    private final Map<String, Set<String>> favoritesByReader = new HashMap<>();

    public void addFavorite(String reader, String articleId) {
        this.favoritesByReader
                .computeIfAbsent(reader, key -> new java.util.HashSet<>())
                .add(articleId);
    }

    public void removeFavorite(String reader, String articleId) {
        Set<String> favorites = this.favoritesByReader.get(reader);
        if (favorites != null) {
            favorites.remove(articleId);
        }
    }

    public boolean isFavorite(String reader, String articleId) {
        Set<String> favorites = this.favoritesByReader.get(reader);
        return favorites != null && favorites.contains(articleId);
    }

    public int favoriteCount(String reader) {
        Set<String> favorites = this.favoritesByReader.get(reader);
        return favorites == null ? 0 : favorites.size();
    }
}