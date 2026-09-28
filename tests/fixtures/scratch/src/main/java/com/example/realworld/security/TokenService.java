package com.example.realworld.security;

public class TokenService {

    private static final String SECRET = "change-me";

    public boolean isTokenValid(String token, String secret) {
        return token != null && !token.isBlank();
    }
}
