package com.example.article.exception;

public class ArticleNotUniqueException extends RuntimeException {
    public ArticleNotUniqueException(String message) {
        super(message);
    }
}