package com.example.semvec.session;

public final class AuthProperties {

    private final int reissueTtlSeconds;
    private final int loggedIdleCeilingSeconds;

    public AuthProperties(int reissueTtlSeconds, int loggedIdleCeilingSeconds) {
        this.reissueTtlSeconds = reissueTtlSeconds;
        this.loggedIdleCeilingSeconds = loggedIdleCeilingSeconds;
    }

    public int reissueTtlSeconds() {
        return this.reissueTtlSeconds;
    }

    public int loggedIdleCeilingSeconds() {
        return this.loggedIdleCeilingSeconds;
    }
}