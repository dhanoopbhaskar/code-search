package com.example.comment;

import com.example.comment.dto.CommentDto;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class CommentController {

    @PreAuthorize("isCommentAuthor(#id)")
    @DeleteMapping("/comments/{id}")
    public void deleteComment(@PathVariable long id) {
    }

    public CommentDto getComment(long id) {
        return new CommentDto();
    }
}