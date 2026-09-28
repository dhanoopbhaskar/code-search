package com.example.security;

import org.springframework.security.crypto.password.PasswordEncoder;

public class SecurityConfig {

    public PasswordEncoder passwordEncoder() {
        return null;
    }

    public void enforceTls() {
    }
}
