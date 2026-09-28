package com.example.semvec.identity;

import java.util.HashMap;
import java.util.Map;

public final class IdentityDirectory {

    private final Map<String, IdentityProfile> byAddress = new HashMap<>();

    public void put(String address, IdentityProfile profile) {
        this.byAddress.put(address, profile);
    }

    public IdentityProfile get(String address) {
        return this.byAddress.get(address);
    }

    public boolean contains(String address) {
        return this.byAddress.containsKey(address);
    }
}