package com.example.article;

public class Comment {
    private String author;
    private String body;

    public Comment(String author, String body) {
        this.author = author;
        this.body = body;
    }

    public String getAuthor() { return author; }
    public void setAuthor(String author) { this.author = author; }
    public String getBody() { return body; }
    public void setBody(String body) { this.body = body; }
}
