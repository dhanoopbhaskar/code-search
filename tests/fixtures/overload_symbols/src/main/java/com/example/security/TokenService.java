package com.example.security;

import java.util.Map;

/**
 * Token service with two overloads of generateToken. Signature-aware
 * resolution (US2) must return the 2-arg form for
 * {@code generateToken(Map<String,Object>,String)}.
 */
public class TokenService {

    public String generateToken(String subject) {
        return "1-arg:" + subject;
    }

    public String generateToken(Map<String, Object> claims, String subject) {
        return "2-arg:" + claims.size() + ":" + subject;
    }
}
