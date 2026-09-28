package com.example.trustdefects.config;

/**
 * Cross-origin resource sharing configuration (FR-003 S6 fixture). The
 * acronym ``cors`` lives here as a sub-word of ``CorsConfig``; the report's
 * paraphrase "configure cross origin requests from a browser" must reach it
 * via query expansion (cross origin -> cors).
 */
public class CorsConfig {

    public void addCorsMappings() {
        // Allow browser clients from other origins.
    }

    public boolean allowOrigin(String origin) {
        return origin != null;
    }
}
