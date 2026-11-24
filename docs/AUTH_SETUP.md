# Registration and OAuth setup

No new tables or migrations are needed. The existing PostgreSQL schema (including
`users` and `user_oauth_accounts`) must already be installed. OAuth credentials
are optional: password login/registration work without them. No live credentials
are needed for the mocked tests. Validation uses mocked providers and the guarded
local test database only. **Live Google/Discord OAuth has not been tested**: no
real client secrets were supplied and no provider network calls were made. Verify
the console settings and complete a real sign-in for each provider before release.

## Environment and local server

Use `.env.example` as a template for a local, untracked `.env`, or set environment
variables before starting the app. `app.config` loads the root `.env` without
overwriting variables already in the process environment. Restart the server
after changing settings.

Required existing application settings:

- `DATABASE_URL`: PostgreSQL SQLAlchemy URL, using `postgresql+psycopg2://...`.
- `JWT_SECRET`: a private, high-entropy random signing key (at least 32 random
  bytes). Generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
  Keep this stable across workers; changing it invalidates existing JWTs.

Existing OAuth configuration names in `app/security.py`:

| Provider | Client ID | Client secret | Redirect URI |
| --- | --- | --- | --- |
| Google | `GOOGLE_CLIENT_ID` | `GOOGLE_CLIENT_SECRET` | `GOOGLE_REDIRECT_URI` |
| Discord | `DISCORD_CLIENT_ID` | `DISCORD_CLIENT_SECRET` | `DISCORD_REDIRECT_URI` |

Browser kickoff requires **both** the selected provider's client ID and secret.
Missing configuration returns HTTP 501 with a friendly `detail` message. A complete
OAuth sign-in, including the legacy API flow's code exchange, requires both a
client ID and a client secret for that provider, plus an exactly registered
redirect URI. Legacy kickoff alone still accepts a client ID without a secret
for compatibility; that does not mean sign-in is configured. Secrets belong only
on the server, never in templates, frontend code, or source control.

Start locally with `uvicorn app.main:app --host localhost --port 8000` and open
`http://localhost:8000/pos`. Use `localhost` consistently, not a mixture of
`localhost` and `127.0.0.1`: browser cookies are host-bound.

### Google Cloud console

1. Create/select a Google Cloud project and configure its OAuth consent screen.
   Request the `openid`, `email`, and `profile` scopes. Add test users if the
   consent screen is in testing mode.
2. Create an OAuth client ID of type **Web application**.
3. Add authorized redirect URI, exactly:
   `http://localhost:8000/auth/oauth/google/callback`.
   If the console asks for an authorized JavaScript origin, use
   `http://localhost:8000`; authorization/code exchange is still server-side.
4. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and
   `GOOGLE_REDIRECT_URI=http://localhost:8000/auth/oauth/google/callback`.

### Discord Developer Portal

1. Create/select an application, then open its **OAuth2** settings.
2. Add redirect URI, exactly:
   `http://localhost:8000/auth/oauth/discord/callback`.
3. Set `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, and
   `DISCORD_REDIRECT_URI=http://localhost:8000/auth/oauth/discord/callback`.
4. The backend requests `identify email` with the authorization-code grant.
   A bot token is not used. The Discord account must expose a verified email.

The Google account must likewise expose a verified email. Scheme, host, port,
path, and trailing-slash choices must match between the console and configured
redirect URI. Do not append `flow` or frontend URLs to the console callback URI.

## Public registration and activation

`POST /auth/register` accepts JSON with **only** these required fields:

```json
{
  "full_name": "New Barista",
  "email": "new.barista@example.com",
  "username": "newbarista",
  "password": "a-long-private-password"
}
```

Names are trimmed and must be nonempty, with a maximum length of 100. New
usernames must be 1–50 characters and contain **no `@` or whitespace**, including
leading/trailing whitespace, tabs, newlines, and Unicode whitespace. Unicode
letters and other non-whitespace characters are preserved; usernames are not
case-folded or normalized. This restriction also applies to admin `POST /users`.
Email must be valid and at most 150 characters. Password length is 8–128
characters and passwords are hashed using the existing Argon2 password hasher.
Unknown registration fields, including `role` and `is_active`, return 422.

Password login chooses **only** the email lookup when `identifier` contains `@`;
otherwise it chooses only the username lookup. It never falls back to the other
namespace after a password mismatch. Existing usernames containing `@` are not
rewritten and can no longer be used as login identifiers: those users must sign
in with their **actual email address**, not their legacy username. No data
migration is required, and an old username/email collision cannot shadow the
real email owner's login.

Successful registration returns HTTP 201:

```json
{"status":"pending","message":"Account created. Please wait for admin activation before signing in."}
```

Duplicate email or username returns 409 with
`{"detail":"Email or username already registered"}`. Uniqueness follows the
existing database's case-sensitive constraints; no email/username migration or
case-folding change is introduced.

New registrations and new Google/Discord users are always inactive cashiers.
They receive **no** access token before activation. An existing admin can find
them using `GET /users`, then send:

```http
PATCH /users/USER_ID
Authorization: Bearer ADMIN_ACCESS_TOKEN
Content-Type: application/json

{"is_active":true}
```

Role changes, when appropriate, also go through this existing admin-only endpoint.
There is no public admin bootstrap. After activation, repeat password login or
OAuth sign-in. Activation does not verify email ownership or link social accounts.
Public password registration does not verify the email address, so admins must
verify the person's identity/ownership out of band before approving or recovering
an account; do not approve a pending account solely because its email looks right.

### Password-account and social-account linking policy

A verified provider email is not proof that the user created an existing local
password account. If a provider identity is not already linked and its email
matches any account with a non-null `password_hash`, the callback rejects the
merge **before** adding a provider link or issuing credentials, regardless of
whether the password account is active. API callbacks return HTTP 409 with
static guidance to sign in with the password, or contact an administrator to
verify ownership if the account is unfamiliar or inaccessible. Browser callbacks
retain `/pos?oauth=error`, clear state/stale handoff cookies, and use the existing
generic password-sign-in feedback rather than exposing account/provider details.

There is **no authenticated account-link endpoint** in this implementation.
Signing in with a password or activating an account does not enable linking.
Admins should verify identity and resolve account access through their trusted
support process; do not simply clear a password hash to work around the rejection.
A future password-account linking flow must explicitly authenticate the existing
account and verify ownership before attaching another identity.

OAuth-only accounts (no password hash) may link another provider with the same
verified email, preserving the existing user ID, role, and activation status.
Already-linked provider identities can return even if an admin later adds a
password; their current role and active status are still checked. Existing links
are not retroactively removed: audit historical automatic links to password
accounts and deactivate suspicious accounts pending ownership verification.

### Operator-only first-admin bootstrap

A clean schema does not create an admin, so registrations cannot be activated
until an operator provisions one. There is no HTTP bootstrap route. On the
intended initialized database, stop public application traffic and use a trusted,
access-restricted server terminal with the project's virtual environment and
`DATABASE_URL`/`JWT_SECRET` configured. Never run this from a browser, expose it as
an endpoint, or promote an existing public registration merely by matching email.

Save the following as a temporary, access-restricted Python script in the project
root and run it locally with the project's Python interpreter. It prompts for
credentials (passwords are not echoed or placed in shell history), validates
against the application schema, and **inserts a new account only**. It refuses if
any admin already exists, including an inactive one, or if the proposed email or
username is already taken. Resolve such cases through a verified operator recovery
process, not by weakening these guards. Remove the temporary script after use.

```python
from getpass import getpass

from psycopg2.errors import UniqueViolation

from app.database import engine
from app.schemas import UserCreate
from app.security import hash_password

expected_database = input("Intended database name: ").strip()
full_name = input("New administrator full name: ")
email = input("New administrator email you control: ")
username = input("New administrator username (no @ or whitespace): ")
password = getpass("New unique administrator password (8+ characters): ")
if password != getpass("Confirm password: "):
    raise SystemExit("Passwords differ; no account was created.")
account = UserCreate(
    email=email, username=username, password=password,
    full_name=full_name, role="admin", is_active=True,
)
password_hash = hash_password(password)
raw = engine.raw_connection()
try:
    conn = raw.driver_connection
    with conn, conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        if cur.fetchone()[0] != expected_database:
            raise SystemExit("Wrong database; no account was created.")
        # Serialize the no-admin check with other bootstrap attempts/user writes.
        cur.execute("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE")
        cur.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1")
        if cur.fetchone():
            raise SystemExit("An admin already exists; use verified operator recovery.")
        cur.execute(
            """
            INSERT INTO users (email, username, password_hash, full_name, role, is_active)
            VALUES (%s, %s, %s, %s, 'admin', TRUE)
            RETURNING id
            """,
            (account.email, account.username, password_hash, account.full_name),
        )
        admin_id = cur.fetchone()[0]
    print(f"Created administrator ID {admin_id}. Sign in normally with your password.")
except UniqueViolation:
    raise SystemExit("Email or username already exists; no account was changed.")
finally:
    raw.close()
    engine.dispose()
```

Do not use the test fixture or its seeded test credentials to bootstrap a real
database. After bootstrap, use the normal admin-only APIs for approvals and role
changes, then restore public traffic.

## Exact browser/frontend contract

The split-screen sign-in/registration screen is available at `/pos`. Its Google
and Discord buttons use this same-origin flow and show inline feedback when a
provider is not configured. Password registration returns to sign-in with the
admin-activation message. The browser retains the OAuth cookies automatically.

1. Fetch `GET /auth/oauth/google?mode=json&flow=browser` (or `discord`) with
   `credentials: "same-origin"`. On 200, read `{ "authorize_url": "..." }` and
   navigate the browser to that URL. On 501, display the friendly `detail`.
   The response also sets the signed, random state in a host-only, HttpOnly,
   SameSite=Lax cookie with a 10-minute lifetime. `flow=browser` also works with
   the default redirect mode instead of `mode=json`.
2. The provider returns to its configured backend callback. Browser state must
   have a valid signature, expiration, purpose, provider, and nonce, and match
   the browser's cookie. A copied state without its cookie cannot log in another
   browser. An API-flow state cannot be substituted into a browser transaction.
3. The callback responds with HTTP 303 to exactly one of:
   - `/pos?oauth=success`: active user; a handoff cookie was set.
   - `/pos?oauth=pending`: inactive user; wait for admin activation, then retry.
   - `/pos?oauth=cancelled`: provider returned `access_denied` with valid state.
   - `/pos?oauth=error`: invalid/missing state or code, missing/mismatched cookie,
     other provider error, unverified email, or callback processing failure.
4. On `oauth=success`, immediately make an empty **POST** to
   `/auth/oauth/session` with `credentials: "same-origin"`. On 200 it returns:

   ```json
   {"access_token":"ACCESS_TOKEN","token_type":"bearer"}
   ```

   Use the bearer token with the existing API. Remove the feedback query
   parameter from browser history after handling it. Do not try to read either
   HttpOnly cookie from JavaScript. A failed/expired handoff returns 401; an
   inactive/deleted user or disallowed request origin returns 403. Start a new
   sign-in instead of retrying an already consumed exchange.

The successful callback sets `shika_oauth_handoff`, a host-only, HttpOnly,
SameSite=Strict cookie scoped to `/auth/oauth/session` for **60 seconds**. It is a
purpose-specific signed JWT containing a user ID, not an access token. Exchange
validates its purpose and expiry, re-reads the database's current active status
and role, then issues the usual access token. Handoff JWTs cannot authenticate
`/auth/me` or other bearer-protected APIs. Exchange clears the cookie on success,
invalid handoff, inactive user, or origin rejection. The callback clears state
and removes stale handoffs on pending/cancelled/error; a new browser kickoff also
removes any stale handoff.

No application access token or handoff token appears in callback URLs, URL
fragments, or HTML. Provider messages and `error_description` are never echoed
in browser feedback. State in the provider authorization URL is not a session
credential. All access-token responses (password login, legacy OAuth callback,
and browser session exchange) use `Cache-Control: no-store` and
`Pragma: no-cache`. Kickoff and browser redirects also use these headers;
callbacks use `Referrer-Policy: no-referrer`.

### Security and compatibility boundaries

- Session exchange rejects a mismatched `Origin` (including a different port)
  and cross-site/same-site-but-not-same-origin Fetch Metadata requests. Combined
  with the explicit Strict cookie and POST-only exchange, this prevents
  cross-origin form/fetch login CSRF. Same-origin requests without these optional
  headers still work. This flow intentionally does **not** support a frontend
  on another origin, even if that origin is in `CORS_ORIGINS`.
- Default OAuth kickoff/callback without `flow=browser` keeps the previous
  redirect-or-JSON kickoff, JSON bearer-token callback, and 403 pending response.
  It does not require a browser cookie and remains intended for API clients;
  **do not use the legacy flow to implement automatic browser login**. Kickoff
  retains its previous client-ID-only configuration check in legacy mode.
- A browser-flow state can never be downgraded into the legacy unbound flow by
  dropping the cookie. A browser with an outstanding state cookie cannot use an
  unrelated legacy callback to create a handoff. Completing/invalidating that
  browser transaction clears its cookie.
- A missing/invalid state with no state cookie is indistinguishable from an
  invalid legacy API call and returns a generic JSON error. Signed expired
  browser states are recognized for error presentation only, never authorization.
- One state cookie means one outstanding browser OAuth transaction per host.
  A second kickoff replaces the first; the older tab will get an error.
- The handoff is stateless: clearing the cookie consumes it in the browser, but
  a copied handoff could be replayed within its 60-second validity window. Global
  one-use enforcement would need shared server-side storage. Do not log cookies.
- Automatic verified-email linking is restricted to OAuth-only accounts. An
  unlinked provider cannot merge into an existing password account, before or
  after activation. See the password-account linking policy above.

## Production

Use HTTPS for the frontend, callback endpoints, and all API traffic. Register the
exact HTTPS production callback URLs in both consoles and set the corresponding
`*_REDIRECT_URI` values. Set `OAUTH_COOKIE_SECURE=true` in production so cookies
remain Secure even behind TLS termination. HTTPS requests also set Secure
automatically. Leave that setting false only for local HTTP development. Ensure
the reverse proxy forwards the public scheme/host and configure trusted proxy
headers correctly so same-origin checks use the public origin; do not trust
arbitrary forwarded headers from the internet.

Protect `.env`, use a secret manager for production credentials, keep a strong
stable `JWT_SECRET`, and avoid logging callback query strings or auth cookies.
Use deployment-level abuse/rate limiting for public registration/login endpoints.
OAuth sends the user to Google/Discord and retrieves their verified email and
profile; normal provider consent, quotas, and privacy policies apply.

## Tests

No provider network access or real OAuth secrets are required.

Mocked tests (no `seeded_db` fixture, database connection acquisition is blocked):

```sh
python -m pytest tests/test_auth_browser.py::TestAuthMocked -q
```

Existing test configuration still needs `DATABASE_URL` (or `TEST_DATABASE_URL`)
and a test `JWT_SECRET` at import time; a dummy local PostgreSQL URL suffices for
the mocked class. The engine is constructed but not connected.

Run database tests **sequentially**, never concurrently with other seed/truncate
tests:

```sh
python -m pytest tests/test_auth_browser.py tests/test_auth_rbac.py -q
python -m pytest tests/test_regressions.py -k 'oauth or user_crud_and_session_pool_reuse' -q
```

Those tests use the existing guarded `shika_coffee_test` seeded fixture and cover
registration, duplicate constraints, admin activation, both OAuth providers in
API/browser modes, rejection of pre-registered password-account merges before
and after activation, OAuth-only same-email linking and returning users,
deactivation between callback and exchange, legacy identity collisions, Unicode
usernames, public/admin username validation, role protections, and token-response
cache headers. Provider calls are mocked; these results do not establish live
Google or Discord interoperability.
