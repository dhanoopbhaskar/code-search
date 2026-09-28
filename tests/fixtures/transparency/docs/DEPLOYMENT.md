# Deployment Notes

## Database connection pool settings

The Hikari connection pool is tuned through `application-dev.properties`:
`maximum-pool-size` controls the max concurrent connections and
`connection-timeout` the max time a thread waits for a connection. When the
pool is exhausted the application surfaces a timeout error, so raise
`maximum-pool-size` before raising timeouts for high-traffic services.

Deploy secrets must never be committed. Rotate the JWT signing key in each
environment instead of reusing the development value.
