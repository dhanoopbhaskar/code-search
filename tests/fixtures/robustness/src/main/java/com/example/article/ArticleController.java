package com.example.article;

import com.example.article.exception.ArticleNotFoundException;
import com.example.article.model.Article;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/articles")
public class ArticleController {

    public static final int DEFAULT_FILTER_LIMIT = 20;

    @GetMapping("/{id}")
    public Article getArticle(@PathVariable long id) {
        throw new ArticleNotFoundException("article not found with id " + id);
    }
}