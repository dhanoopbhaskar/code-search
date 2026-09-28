package com.example.trustdefects.security;

/**
 * Token issuing/validation (L1 fixture). The exact-identifier query
 * ``TokenService`` must rank this file #1 ahead of semantically-similar
 * security classes (AuthService, SecurityFilter). The JWT vocabulary below
 * is the F1-typo control ("jwt tokne genration" must still resolve here),
 * while the SERVICE_NAME constant keeps the exact-identifier query anchored.
 */
public class TokenService {

    private static final String SERVICE_NAME = "TokenService";
    private static final String JWT_PREFIX = "eyJ";

    public String generateToken(String username) {
        String jwt = "JWT " + JWT_PREFIX;
        String token = "JWT token " + JWT_PREFIX;
        String jwtToken = jwt + token;
        return jwtToken;
    }

    public boolean isTokenValid(String token) {
        return token != null && token.startsWith(JWT_PREFIX);
    }
}
