package com.example.article.assembler;

import com.example.article.dto.ArticleDto;
import com.example.article.model.Article;

public class ArticleAssembler {

    public ArticleDto toDto(Article article) {
        ArticleDto dto = new ArticleDto();
        dto.setTitle(article.getTitle());
        dto.setSlug(slugify(article.getTitle()));
        return dto;
    }

    public String slugify(String title) {
        return title.toLowerCase().replace(" ", "-");
    }
}
