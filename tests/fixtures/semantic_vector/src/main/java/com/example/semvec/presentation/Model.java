package com.example.semvec.presentation;

public final class Model {

    private final String serialized;

    public Model(String serialized) {
        this.serialized = serialized;
    }

    public String toJson() {
        return this.serialized;
    }

    public String schema() {
        return this.serialized;
    }

    public Object projection() {
        return this.serialized;
    }
}