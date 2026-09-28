package com.example.multi;

public enum Status {
    OPEN,
    CLOSED;

    public String label() {
        return name().toLowerCase();
    }
}
