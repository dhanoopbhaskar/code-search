package com.example.qualitydefects.util;

import java.io.File;

/**
 * Genuinely recursive directory walker. Its ``walk`` method calls itself,
 * producing a legitimate recursive self-call edge that MUST be preserved by
 * the post-index edge validation sweep (FR-010) — only spurious
 * (non-recursive) self-edges are removed.
 */
public class DirectoryWalker {

    public void walk(File dir) {
        File[] children = dir.listFiles();
        if (children == null) {
            return;
        }
        for (File child : children) {
            if (child.isDirectory()) {
                walk(child);
            }
        }
    }
}
