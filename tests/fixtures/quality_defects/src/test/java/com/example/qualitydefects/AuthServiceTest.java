package com.example.qualitydefects;

import com.example.qualitydefects.auth.AuthService;

import static org.junit.Assert.assertTrue;

public class AuthServiceTest {

    private AuthService authService = new AuthService();

    public void testAuthenticate() {
        assertTrue(authService.authenticate("admin", "secret"));
    }
}
