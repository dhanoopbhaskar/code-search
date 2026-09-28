package com.example.multi;

public record Point(int x, int y) {
    public int sum() {
        return x + y;
    }
}
