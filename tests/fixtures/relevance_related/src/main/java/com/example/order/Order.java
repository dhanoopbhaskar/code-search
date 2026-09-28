package com.example.order;

import java.util.List;

public class Order {
    private Long id;
    private List<OrderItem> items;
    private OrderStatus status;

    public void addItem(OrderItem item) {
        items.add(item);
    }

    public OrderStatus getStatus() {
        return status;
    }

    public void setStatus(OrderStatus status) {
        this.status = status;
    }
}
