package com.example.semvec.favorite;

import java.util.ArrayList;
import java.util.List;

public final class FavoritesStore {

    private final List<String> entries = new ArrayList<>();

    public void store(String reader, String article) {
        this.entries.add(reader + ":" + article);
    }

    public int size() {
        return this.entries.size();
    }

    public boolean isEmpty() {
        return this.entries.isEmpty();
    }
}