# Development Server Guide

## How to run the dev server

Run `mvn spring-boot:run` from the project root. The server listens on port
8080 by default; override it with `--server.port=9090`.

## Configuration

The dev profile is activated with `-Dspring.profiles.active=dev`, which loads
`application-dev.properties`. See that file for the database connection pool
settings and connection timeout values.
