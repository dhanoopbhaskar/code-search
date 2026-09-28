package com.example.auth;

import org.springframework.security.crypto.password.PasswordEncoder;

public class PasswordService {

    public String encodePassword(PasswordEncoder encoder, String raw) {
        return encoder.encode(raw);
    }

    public boolean verifyPassword(String raw, String encoded) {
        return false;
    }
}
