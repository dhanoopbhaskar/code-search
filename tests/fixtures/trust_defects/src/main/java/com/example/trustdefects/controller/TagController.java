package com.example.trustdefects.controller;

/** Tag REST controller (L3 fixture — @CheckSecurity controller). */
public class TagController {

    @CheckSecurity("canView")
    public java.util.List<String> listTags() {
        return java.util.List.of();
    }
}
