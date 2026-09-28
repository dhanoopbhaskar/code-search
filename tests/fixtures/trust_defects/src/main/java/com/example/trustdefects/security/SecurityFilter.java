package com.example.trustdefects.security;

/** Security service with a name semantically close to TokenService (L1 control). */
public class SecurityFilter {

    public boolean filter(String token) {
        return token != null;
    }
}
