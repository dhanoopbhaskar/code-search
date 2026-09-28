package com.example.pattern;

import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * Service whose transactional methods reproduce the "11+ @Transactional
 * occurrences" pattern (US5). Each annotated method carries
 * {@code readOnly = true} on the read path.
 */
public class PaymentService {

    @Transactional(readOnly = true)
    public List<Payment> findPaid() {
        return List.of();
    }

    @Transactional
    public Payment refund(Payment payment) {
        return payment;
    }

    @Transactional(readOnly = true)
    public Payment findById(Long id) {
        return null;
    }

    @Transactional
    public Payment capture(Payment payment) {
        return payment;
    }
}
