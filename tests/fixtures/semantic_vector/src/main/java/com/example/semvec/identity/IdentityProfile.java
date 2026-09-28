package com.example.semvec.identity;

public final class IdentityProfile {

    private final String displayName;
    private final String address;

    public IdentityProfile(String displayName, String address) {
        this.displayName = displayName;
        this.address = address;
    }

    public String displayName() {
        return this.displayName;
    }

    public String address() {
        return this.address;
    }
}