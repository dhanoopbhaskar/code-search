package com.example.realworld.security;

import com.example.realworld.security.TokenService;

public class SecurityFilter {

    private TokenService tokenService;

    public boolean doFilterInternal() {
        String authHeader = "Bearer abcdef1234567890abcdef";
        String token = authHeader.substring(7);
        if (tokenService.isTokenValid(token, "secret")) {
            return true;
        }
        return false;
    }
}
