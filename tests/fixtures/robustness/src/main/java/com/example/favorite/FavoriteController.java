package com.example.favorite;

import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class FavoriteController {

    @PostMapping("/articles/{id}/favorite")
    public void favorite(long id) {
    }

    @DeleteMapping("/articles/{id}/favorite")
    public void unfavorite(long id) {
    }
}