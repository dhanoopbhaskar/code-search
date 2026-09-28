package com.example.qualitydefects.auth;

/**
 * Cross-layer call-graph fixture (FR-009): ``AuthController.authenticate``
 * calls ``AuthService.authenticate``. The controller layer was previously
 * disconnected from the graph because source FQNs were silently dropped.
 */
public class AuthController {

    private AuthService authService;

    public boolean authenticate(String username, String password) {
        return authService.authenticate(username, password);
    }
}
