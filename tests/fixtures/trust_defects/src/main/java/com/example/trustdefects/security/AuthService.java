package com.example.trustdefects.security;

/** Authentication service, semantically similar to TokenService (L1 control). */
public class AuthService {

    public boolean authenticate(String username, String password) {
        return username != null && !username.isBlank();
    }
}
