package com.example.trustdefects.controller;

/** User registration REST controller (L3 fixture — @CheckSecurity controller). */
public class UserController {

    @CheckSecurity("canEdit")
    public String register(String username, String email) {
        return username;
    }
}
