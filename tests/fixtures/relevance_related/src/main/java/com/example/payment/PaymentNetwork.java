package com.example.payment;

import java.math.BigDecimal;

public class PaymentNetwork {
    public boolean authorize(BigDecimal amount) {
        return true;
    }

    public void capture(BigDecimal amount) {
    }
}
