package com.example.qualitydefects.security;

/**
 * Security context holding the current user. Its ``isAuthenticated`` method
 * shares a name with ``AuthService.isAuthenticated``; a same-name
 * mis-resolution would attach a spurious ``isAuthenticated -> isAuthenticated``
 * edge, which the post-index validation sweep must remove (FR-010).
 */
public class SecurityContext {

    private String currentUser;

    public boolean isAuthenticated() {
        return currentUser != null;
    }
}
