package com.example.trustdefects.controller;

/** Profile REST controller (L3 fixture — @CheckSecurity controller). */
public class ProfileController {

    @CheckSecurity("canView")
    public String getProfile(String username) {
        return username;
    }
}
