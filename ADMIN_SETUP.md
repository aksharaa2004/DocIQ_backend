# DocIQ admin setup

For local development, the backend creates an admin account automatically on startup:

- Email: `admin@gmail.com`
- Password: `admin@1234`

No sign-up is needed. To use different credentials, set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `backend/.env` before starting the backend. If the configured email already belongs to an account, the backend promotes that account without changing its password.

Set `JWT_SECRET` to a long, private random value. Keep it out of source control. Production mode requires `JWT_SECRET`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD`; it does not use the built-in development credentials.

The backend warns if `JWT_SECRET` is missing in local development and creates a temporary secret. Sessions issued with a temporary secret stop working when the backend restarts. Configure a persistent secret for normal use.

Older documents do not have an owner because the previous upload flow did not store one. New uploads made after signing in are linked to the signed-in account. The admin document list labels older records as unassigned.

AI usage reporting starts counting successful AI API operations after this update is deployed; it does not backfill activity from before then.
