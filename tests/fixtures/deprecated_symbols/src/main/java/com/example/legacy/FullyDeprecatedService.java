package com.example.legacy;

/**
 * A service whose every same-name overload is deprecated, so the ranking
 * policy still returns all candidates (each carrying ``deprecated: true``)
 * rather than dropping them.
 */
public class FullyDeprecatedService {

    @Deprecated
    public void run(String input) {
    }

    @Deprecated
    public void run(int input) {
    }
}
