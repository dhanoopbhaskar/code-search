package com.example.pattern;

import org.springframework.transaction.annotation.Transactional;

public class Payment {
    private Long id;
    private Long amount;
    private boolean captured;

    @Transactional(readOnly = true)
    public Long getId() {
        return id;
    }

    public Long getAmount() {
        return amount;
    }

    @Transactional
    public void capture() {
        this.captured = true;
    }

    @Transactional(readOnly = true)
    public boolean isCaptured() {
        return captured;
    }
}
