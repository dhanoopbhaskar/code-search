package com.example.trustdefects.controller;

/** Follow REST controller (L3 fixture — @CheckSecurity controller). */
public class FollowController {

    @CheckSecurity("canEdit")
    public void follow(String username) {
        // Record the follow relationship.
    }
}
