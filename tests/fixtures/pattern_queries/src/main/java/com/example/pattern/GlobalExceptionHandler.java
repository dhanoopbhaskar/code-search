package com.example.pattern;

import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * Advice class with multiple @ExceptionHandler methods — the "enumerate the
 * handlers" pattern (US5).
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(NotFoundException.class)
    public String handleNotFound(NotFoundException ex) {
        return ex.getMessage();
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public String handleIllegal(IllegalArgumentException ex) {
        return ex.getMessage();
    }

    @ExceptionHandler(SecurityException.class)
    public String handleSecurity(SecurityException ex) {
        return ex.getMessage();
    }
}
