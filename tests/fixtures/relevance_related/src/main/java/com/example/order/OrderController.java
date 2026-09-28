package com.example.order;

public class OrderController {
    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    public Order create(Order order) {
        return orderService.createOrder(order);
    }

    public Order get(Long orderId) {
        return orderService.getOrder(orderId);
    }
}
