# Article Lifecycle FAQ

## What happens when an article is saved

Saving an article stores it through the repository. The saved article
is returned to the caller, optionally published when the publish flag is set.

## How the article is stored

The ArticleService stores each article via ArticleRepository.save, which
persists it to the underlying store.