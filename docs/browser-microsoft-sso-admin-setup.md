# Microsoft sign in from a web browser

## Purpose

Enrollment Assistant can let approved institutional users sign in from a normal browser with Microsoft Entra ID. The browser does not need to run inside Teams. Existing email/password login and optional Teams SSO remain separate paths into the same local cookie session.

Browser Microsoft SSO is disabled by default. Complete the Entra and application configuration below before enabling it.

## Required values

Choose deployment-specific values and keep secrets out of source control:

```text
Application name: Enrollment Assistant
Application client ID: <Entra application client ID>
Tenant ID: <Entra tenant ID>
Production URL: https://assistant.example.edu/
Web callback URL: https://assistant.example.edu/api/auth/microsoft/callback
Allowed email domain: example.edu
Approved group: <institution-managed Entra group>
```

The same Entra application may provide Teams SSO, but browser sign in does not require a Teams manifest or app-package change.

## Entra administrator setup

### 1. Add the Web callback

In **Identity > Applications > App registrations**, open the application, select **Authentication**, add a **Web** platform, and register the exact callback URL:

```text
https://assistant.example.edu/api/auth/microsoft/callback
```

Do not register it as a Single-page application callback. The backend exchanges the authorization code. Implicit access-token and ID-token grants are not required.

### 2. Register a certificate

Create a dedicated certificate for browser sign in. Upload only its public certificate under **Certificates & secrets > Certificates**. Store the private key in protected deployment configuration, never in source control, chat, or email.

Record the nonsecret thumbprint and expiration date. Browser sign in and SharePoint integrations, when present, should use independently rotatable certificates.

### 3. Restrict assignment

Under **Enterprise applications > Users and groups**, assign the approved institutional group. Then set **Assignment required?** to **Yes**. Assign the group before enabling the requirement so approved users do not lose access.

Test one assigned account and one unassigned account. Entra assignment is the authorization boundary; the backend's exact tenant/domain checks are defense in depth.

## Application configuration

Configure these backend settings:

```text
BROWSER_SSO_ENABLED=false
BROWSER_SSO_TENANT_ID=<tenant UUID>
BROWSER_SSO_CLIENT_ID=<application client UUID>
BROWSER_SSO_REDIRECT_URI=https://assistant.example.edu/api/auth/microsoft/callback
BROWSER_SSO_ALLOWED_EMAIL_DOMAIN=example.edu
BROWSER_SSO_CERTIFICATE_THUMBPRINT=<public certificate thumbprint>
BROWSER_SSO_CERTIFICATE_PRIVATE_KEY=<protected PEM private key>
BROWSER_SSO_CERTIFICATE_PRIVATE_KEY_PATH=
BROWSER_SSO_REQUEST_TIMEOUT_SECONDS=10
BROWSER_SSO_FLOW_EXPIRE_MINUTES=10
```

`BROWSER_SSO_CERTIFICATE_PRIVATE_KEY_PATH` may replace the inline key when the deployment provides a protected file.

Deploy the application and branch-native database migration while `BROWSER_SSO_ENABLED=false`. Confirm the callback, certificate, assignment policy, and allowed domain, then enable the setting and restart the application. The frontend reads `/api/auth/config`; no frontend build flag is needed.

## Runtime flow

```text
Browser
  -> Enrollment Assistant start route
  -> Microsoft Entra authorization
  -> Enrollment Assistant callback
  -> Local access/refresh cookies
  -> Requested relative application path
```

The backend stores short-lived flow state in PostgreSQL, binds it to an HttpOnly cookie, uses PKCE plus certificate client authentication, and consumes the flow before token exchange. It validates issuer, audience, expiry, tenant, object identity, and exact email domain. The browser never stores a Microsoft access token.

An unlinked Microsoft identity may link once to an existing local account with the same normalized email. The account keeps its local group and overrides. Later sign-ins use tenant ID plus object ID. New approved identities receive the normal `user` group.

## Acceptance checks

1. An assigned user with an existing Microsoft session enters without another password prompt when policy allows.
2. An assigned user without a session sees Microsoft's normal sign-in flow.
3. An unassigned tenant user is rejected.
4. A user outside the exact allowed domain is rejected.
5. Existing local account linking preserves group and overrides.
6. Email/password login still works.
7. Teams SSO still works when configured.
8. Invalid, expired, replayed, or browser-mismatched callbacks create no session.
9. Logout clears only Enrollment Assistant cookies, not the Microsoft 365 session.

## Rollback

Set `BROWSER_SSO_ENABLED=false` and restart. The Microsoft button disappears while password and Teams sign-in remain available. After confirming disablement, the Entra administrator may remove the browser Web callback and browser-specific certificate without removing Teams scopes or preauthorized applications.

## Microsoft references

- <https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow>
- <https://learn.microsoft.com/en-us/entra/identity-platform/security-best-practices-for-app-registration>
- <https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/assign-user-or-group-access-portal>
