package com.example.qualitydefects.infra.spec;

import java.util.ArrayList;
import java.util.List;

/**
 * Specification for filtering articles by title, tag, and author.
 *
 * Lives under a ``spec`` path segment inside main source to reproduce the
 * FR-006 regression where a bare ``spec`` segment misclassified a production
 * file as a test and hid it from ``--no-include-tests`` queries.
 */
public class ArticleSpecification {

    public List<String> apply(String title) {
        List<String> filters = new ArrayList<>();
        if (title != null && !title.isBlank()) {
            filters.add("title=" + title);
        }
        return filters;
    }
}
