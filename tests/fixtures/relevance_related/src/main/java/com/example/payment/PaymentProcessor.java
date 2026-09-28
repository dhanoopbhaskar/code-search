package com.example.payment;

import java.math.BigDecimal;

public class PaymentProcessor {
    private final PaymentGateway paymentGateway;
    private final FraudService fraudService;

    public PaymentProcessor(PaymentGateway paymentGateway, FraudService fraudService) {
        this.paymentGateway = paymentGateway;
        this.fraudService = fraudService;
    }

    public boolean charge(BigDecimal amount) {
        if (fraudService.check(amount)) {
            return paymentGateway.charge(amount);
        }
        return false;
    }

    public void refund(BigDecimal amount) {
        paymentGateway.refund(amount);
    }
}
