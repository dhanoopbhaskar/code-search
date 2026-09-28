package com.example.trustdefects.controller;

import com.example.trustdefects.service.FavoriteService;

/** Favoriting REST controller (L3 fixture — @CheckSecurity controller). */
public class ArticleFavoriteController {

    private FavoriteService favoriteService;

    @CheckSecurity("canEdit")
    public void favoriteArticle(String slug, String username) {
        favoriteService.favorite(slug, username);
    }
}
