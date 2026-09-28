package com.example.trustdefects.security;

import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;

/** Custom security annotation used across the six L3 fixture controllers. */
@Retention(RetentionPolicy.RUNTIME)
public @interface CheckSecurity {
    String value();
}
