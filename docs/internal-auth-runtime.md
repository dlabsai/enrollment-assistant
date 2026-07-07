# Internal Auth Runtime Model

## TL;DR

- Use **cookie-based auth** for the browser app.
- **Auto-login with Teams SSO** only when the app is actually running inside Teams.
- If Teams SSO fails, **fail visibly**. Do not silently downgrade to another auth path.
- Outside Teams, show the normal login screen.
- Do not silently switch identities.
- Auto-refresh of the same cookie session is okay.

## Rules

### 1. One real browser auth mechanism

For the browser app, the real session is the **backend cookie session**.

That means:

- protected internal app routes use the cookie session only
- no `localStorage` auth token
- no in-memory browser token fallback
- no auth token in login JSON responses
- no hidden split between Teams auth and non-Teams auth

### 2. Existing session wins

On app startup:

1. Try `GET /auth/me`
2. If needed, try `POST /auth/refresh`
3. If there is still no valid session, continue based on environment

This is session restoration, not identity switching.

### 3. Teams should auto-login for best UX

If there is no valid session **and the app is running inside Teams**, automatically attempt Teams SSO.

This is good UX and should be the default behavior for the Teams-hosted internal app.

### 4. Teams failure must be explicit

If automatic Teams SSO fails:

- show an explicit error or explicit Teams sign-in action
- do not silently fall back to another auth mode
- do not pretend the app is outside Teams
- do not silently continue with a weaker or different auth path

### 5. Outside Teams, use normal login

If the app is **not** running inside Teams:

- do not auto-attempt Teams SSO
- show the normal login/register screen

### 6. No silent identity replacement

A manual login must not later be silently replaced by Teams SSO.

A Teams login must not later be silently replaced by some other fallback.

Authentication behavior must be predictable.

## Desired startup behavior

### Inside Teams

1. Restore existing cookie session if present
2. If no valid session, auto-attempt Teams SSO
3. If Teams SSO succeeds, enter the app
4. If Teams SSO fails, show explicit failure

### Outside Teams

1. Restore existing cookie session if present
2. If no valid session, show normal login screen

## Desired auth UX principles

- **KISS**: one browser session model
- **Explicit**: Teams-only behavior happens only in Teams
- **Fail-fast**: no silent fallback chains
- **Predictable**: no unexpected identity switches
- **Good UX**: Teams users get auto-login

## Non-goals

These are explicitly not desired:

- hidden auth fallbacks
- mixed browser token + cookie auth in the frontend
- local token persistence hacks
- Teams-specific secret session modes
- silent downgrade from Teams auth to non-Teams auth
- silent upgrade from manual login to Teams login after reload
