package com.example.semvec.presentation;

public final class ArticleContent {

    private final long identifier;
    private final String headline;
    private final String bodyText;
    private final long authoredAtEpoch;
    private final String ownerName;

    public ArticleContent(
            long identifier,
            String headline,
            String bodyText,
            long authoredAtEpoch,
            String ownerName) {
        this.identifier = identifier;
        this.headline = headline;
        this.bodyText = bodyText;
        this.authoredAtEpoch = authoredAtEpoch;
        this.ownerName = ownerName;
    }

    public long identifier() {
        return this.identifier;
    }

    public String headline() {
        return this.headline;
    }

    public String bodyText() {
        return this.bodyText;
    }

    public long authoredAtEpoch() {
        return this.authoredAtEpoch;
    }

    public String ownerName() {
        return this.ownerName;
    }
}