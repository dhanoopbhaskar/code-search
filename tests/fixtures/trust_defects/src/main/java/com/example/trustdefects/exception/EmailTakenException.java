package com.example.trustdefects.exception;

/**
 * Raised when a registration email is already taken (F3 fixture). The query
 * "does user already exist with this email" must surface this exception via
 * the ``email taken`` / ``email exists`` expansion.
 */
public class EmailTakenException extends RuntimeException {

    public EmailTakenException(String email) {
        super("email already in use: " + email);
    }
}
