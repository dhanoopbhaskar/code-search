package com.example.tag;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class TagController {

    @GetMapping("/tags")
    public void listTags(@RequestParam long articleId) {
    }
}