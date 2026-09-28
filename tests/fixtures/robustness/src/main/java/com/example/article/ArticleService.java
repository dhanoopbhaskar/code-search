package com.example.article;

import com.example.article.assembler.ArticleAssembler;
import com.example.article.dto.ArticleDto;
import com.example.article.exception.ArticleNotUniqueException;
import com.example.article.exception.ArticleNotFoundException;
import com.example.article.model.Article;

public class ArticleService {
    private final ArticleAssembler assembler = new ArticleAssembler();

    public ArticleDto findById(long id) {
        Article article = null;
        if (article == null) {
            throw new ArticleNotFoundException("article not found with id " + id);
        }
        return assembler.toDto(article);
    }

    public ArticleDto createArticle(ArticleDto input) {
        ArticleDto created = new ArticleDto();
        if (input.getTitle() == null) {
            throw new ArticleNotUniqueException("There's already an article with this title");
        }
        created.setTitle(input.getTitle());
        created.setSlug(assembler.slugify(input.getTitle()));
        return created;
    }
}