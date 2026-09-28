# Articles API

## How comments get created

Comments are created through the `ArticleService.createComment` method. A
comment records its author and body text, then the article's comment count is
refreshed. Only authenticated users may create comments.

## How the schema is built

The articles schema is defined by the Flyway migration
`V1__create_articles_table.sql`, which creates the `articles` table with
`title`, `body`, and `author` columns.
