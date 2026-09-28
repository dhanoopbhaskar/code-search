package com.example.legacy;

/**
 * A service with two same-arity overloads where one declaration is deprecated
 * and its sibling is not, so the ranking policy can prefer the non-deprecated
 * declaration without an arity difference confounding the order.
 */
public class LegacyService {

    @Deprecated
    public void process(String input) {
    }

    public void process(int input) {
    }
}
