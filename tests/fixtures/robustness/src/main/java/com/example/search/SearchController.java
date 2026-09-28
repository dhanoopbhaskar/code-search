package com.example.search;

import com.example.article.model.Article;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class SearchController {

    @GetMapping("/search")
    public void search(@RequestParam String query) {
    }

    public Article findRelated(Article article) {
        return article;
    }
}