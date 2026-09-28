package com.example.qualitydefects.auth;

import java.util.HashMap;
import java.util.Map;

/**
 * Service backing the auth controller. ``authenticate`` and ``isAuthenticated``
 * provide same-name resolution candidates (FR-010): ``isAuthenticated`` also
 * exists in SecurityContext, exercising the same-name-different-id sweep.
 */
public class AuthService {

    private static final Map<String, String> USERS = new HashMap<>();

    public boolean authenticate(String username, String password) {
        return USERS.get(username) != null && USERS.get(username).equals(password);
    }

    public boolean isAuthenticated(String username) {
        return USERS.containsKey(username);
    }
}
