package com.example.semvec.identity;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

public final class EnrollmentRegistryTest {

    @Test
    public void verifyUnique_rejectsExistingAddress() {
        EnrollmentRegistry registry = new EnrollmentRegistry();
        registry.add("someone@example.com");
        assertThrows(EnrollmentRegistry.Taken.class, () -> registry.verifyUnique("someone@example.com"));
    }

    @Test
    public void add_rejectsDuplicateAddress() {
        EnrollmentRegistry registry = new EnrollmentRegistry();
        registry.add("someone@example.com");
        assertThrows(EnrollmentRegistry.Duplicate.class, () -> registry.add("someone@example.com"));
    }

    @Test
    public void alreadyOnFile_trueForClaimedAddress() {
        EnrollmentRegistry registry = new EnrollmentRegistry();
        registry.add("someone@example.com");
        assertTrue(registry.alreadyOnFile("someone@example.com"));
    }
}