package com.example.pattern;

/**
 * Definition of setToken plus call sites (US5): "where is setToken called
 * from" must surface both the definition and the callers.
 */
public class TokenHolder {

    private String token;

    public void setToken(String token) {
        this.token = token;
    }

    public String getToken() {
        return token;
    }
}
