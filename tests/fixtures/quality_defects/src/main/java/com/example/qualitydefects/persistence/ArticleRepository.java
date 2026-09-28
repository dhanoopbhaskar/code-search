package com.example.qualitydefects.persistence;

import java.util.ArrayList;
import java.util.List;

/**
 * Repository exposing pagination helpers. The ``Pageable``/``PageRequest``
 * and ``Page<`` identifiers reproduce the FR-003/FR-007 "pagination" query:
 * the natural-language term must resolve to these identifiers via sub-word
 * decomposition and the ``pag*`` prefix fallback.
 */
public class ArticleRepository {

    public List<String> findAll(Pageable pageable) {
        List<String> rows = new ArrayList<>();
        for (int i = pageable.getOffset(); i < pageable.getOffset() + pageable.getPageSize(); i++) {
            rows.add("row-" + i);
        }
        return rows;
    }

    public Page<Article> findPage(PageRequest request) {
        return new Page<>(request.getPageNumber(), request.getPageSize());
    }

    public static final class Pageable {
        public int getOffset() {
            return 0;
        }

        public int getPageSize() {
            return 20;
        }
    }

    public static final class PageRequest {
        public int getPageNumber() {
            return 0;
        }

        public int getPageSize() {
            return 20;
        }
    }

    public static final class Page<T> {
        private final int number;
        private final int size;

        public Page(int number, int size) {
            this.number = number;
            this.size = size;
        }

        public int getNumber() {
            return number;
        }

        public int getSize() {
            return size;
        }
    }

    public static final class Article {
    }
}
