package com.example.qualitydefects.security;

/**
 * Validates JWT-style tokens. The camelCase ``isTokenValid`` identifier is
 * the FR-003 case: a query for "token valid" must match it via sub-word
 * decomposition of the identifier.
 */
public class TokenService {

    private static final String SECRET = "change-me";

    public boolean isTokenValid(String token, String secret) {
        return token != null && !token.isBlank() && token.startsWith("eyJ");
    }
}
