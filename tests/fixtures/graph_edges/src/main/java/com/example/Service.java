package com.example;

public class Service implements Api {
    private final Repo repo;

    public Service(Repo repo) {
        this.repo = repo;
    }

    @Override
    public void run() {
        repo.save(new Article());
        this.repo.persist();
    }

    private void helper(Article article) {
        this.repo.persist(article);
    }

    @Route("/service")
    public void endpoint() {
    }
}
