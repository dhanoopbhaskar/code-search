package com.example.semvec.session;

public final class SessionWindowPolicy {

    int reissueTtl;
    int loggedCeiling;
    int elapsed;

    public boolean reissueRequired(int elapsed) {
        return elapsed > this.reissueTtl;
    }

    public boolean idleExceeded(int idle) {
        return idle > this.loggedCeiling;
    }

    public boolean renew(int age) {
        return age < this.reissueTtl;
    }

    public void reissue() {
        this.elapsed = 0;
    }

    public void revoke() {
        this.elapsed = 0;
    }

    public void logout() {
        this.elapsed = 0;
    }
}