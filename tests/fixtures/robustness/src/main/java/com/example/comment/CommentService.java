package com.example.comment;

import com.example.comment.dto.CommentDto;
import com.example.comment.model.Comment;

public class CommentService {

    public CommentDto createComment(Comment comment) {
        CommentDto dto = new CommentDto();
        dto.setAuthor(comment.getAuthor());
        dto.setBody(comment.getBody());
        return dto;
    }

    public void deleteComment(long id) {
    }
}