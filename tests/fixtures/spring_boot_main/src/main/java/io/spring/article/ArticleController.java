package io.spring.article;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class ArticleController {

  @GetMapping("/articles")
  public String listArticles() {
    return "articles";
  }
}
