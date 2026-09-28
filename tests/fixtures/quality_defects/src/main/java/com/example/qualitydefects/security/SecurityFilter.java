package com.example.qualitydefects.security;

/**
 * Servlet-style filter that calls into TokenService. This is the reference
 * (non-defining) caller of ``isTokenValid`` and must rank below the defining
 * chunk of ``isTokenValid`` for symbol-like queries (FR-001).
 */
public class SecurityFilter {

    private TokenService tokenService;

    public boolean doFilterInternal() {
        String authHeader = "Bearer eyJhbGciOiJIUzI1NiJ9";
        String token = authHeader.substring(7);
        return tokenService.isTokenValid(token, "secret");
    }
}
