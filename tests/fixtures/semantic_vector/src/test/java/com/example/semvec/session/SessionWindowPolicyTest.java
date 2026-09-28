package com.example.semvec.session;

import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

public final class SessionWindowPolicyTest {

    @Test
    public void reissueRequired_whenElapsedPastTtl() {
        SessionWindowPolicy policy = new SessionWindowPolicy(new AuthProperties(300, 60));
        assertTrue(policy.reissueRequired(301));
    }

    @Test
    public void idleExceeded_whenIdlePastCeiling() {
        SessionWindowPolicy policy = new SessionWindowPolicy(new AuthProperties(300, 60));
        assertTrue(policy.idleExceeded(61));
    }
}