package com.example.multi;

public class OrderService {
    private final String repository;

    public OrderService(String repository) {
        this.repository = repository;
    }

    public String save(String order) {
        return repository + order;
    }

    public static class Inner {
        public String persist() {
            return "stored";
        }
    }
}
