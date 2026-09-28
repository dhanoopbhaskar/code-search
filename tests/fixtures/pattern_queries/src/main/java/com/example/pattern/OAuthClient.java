package com.example.pattern;

public class OAuthClient {

    private final TokenHolder holder = new TokenHolder();

    public void onLogin(String token) {
        this.holder.setToken(token);
    }

    public void refresh(String token) {
        holder.setToken(token);
    }
}