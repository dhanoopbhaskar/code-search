package com.example.payment;

import java.math.BigDecimal;

public class PaymentGateway {
    private final PaymentNetwork paymentNetwork;

    public PaymentGateway(PaymentNetwork paymentNetwork) {
        this.paymentNetwork = paymentNetwork;
    }

    public boolean charge(BigDecimal amount) {
        return paymentNetwork.authorize(amount);
    }

    public void refund(BigDecimal amount) {
        paymentNetwork.capture(amount);
    }
}
