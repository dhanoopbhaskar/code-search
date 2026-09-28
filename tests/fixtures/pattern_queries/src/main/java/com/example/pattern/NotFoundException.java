package com.example.pattern;

public class NotFoundException extends RuntimeException {
    public NotFoundException(String message) {
        super(message);
    }
}