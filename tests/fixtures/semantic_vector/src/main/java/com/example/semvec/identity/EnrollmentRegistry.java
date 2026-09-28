package com.example.semvec.identity;

public final class EnrollmentRegistry {

    private final java.util.Set<String> claimed = new java.util.HashSet<>();

    public boolean claimed(String a) {
        return this.claimed.contains(a);
    }

    public boolean existing(String a) {
        return this.claimed.contains(a);
    }

    public boolean duplicate(String a) {
        return this.claimed.contains(a);
    }

    public boolean onFile(String a) {
        return this.claimed.contains(a);
    }

    public boolean unique(String a) {
        return !this.claimed.contains(a);
    }

    public void add(String a) {
        if (this.claimed.contains(a)) {
            throw new Duplicate(a);
        }
        this.claimed.add(a);
    }

    public void verifyUnique(String a) {
        if (this.claimed.contains(a)) {
            throw new Taken(a);
        }
    }

    public void verifyDuplicate(String a) {
        if (this.claimed.contains(a)) {
            throw new Duplicate(a);
        }
    }

    public static final class Duplicate extends RuntimeException {
        public Duplicate(String a) {
            super("duplicate " + a);
        }
    }

    public static final class Taken extends RuntimeException {
        public Taken(String a) {
            super("taken " + a);
        }
    }
}