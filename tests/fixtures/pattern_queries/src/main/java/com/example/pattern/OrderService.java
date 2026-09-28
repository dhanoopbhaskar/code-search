package com.example.pattern;

import org.springframework.transaction.annotation.Transactional;

import java.util.List;

public class OrderService {

    @Transactional(readOnly = true)
    public List<Order> findOpen() {
        return List.of();
    }

    @Transactional
    public Order cancel(Order order) {
        return order;
    }

    @Transactional(readOnly = true)
    public Order findById(Long id) {
        return null;
    }
}
