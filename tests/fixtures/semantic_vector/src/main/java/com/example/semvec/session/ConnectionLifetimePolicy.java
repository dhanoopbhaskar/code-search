package com.example.semvec.session;

public final class ConnectionLifetimePolicy {

    private final long lifetime;
    private final long ceiling;

    public ConnectionLifetimePolicy(long lifetime, long ceiling) {
        this.lifetime = lifetime;
        this.ceiling = ceiling;
    }

    public boolean severed(long age, long idle) {
        return age > this.lifetime || idle > this.ceiling;
    }

    public void sever() {
        this.teardown();
    }

    public void teardown() {
    }

    public void evict() {
    }

    public void severance() {
    }

    public boolean session(long age, long idle) {
        return this.severed(age, idle);
    }

    public void end(long age) {
        if (this.severed(age, 0)) {
            this.evict();
        }
    }
}