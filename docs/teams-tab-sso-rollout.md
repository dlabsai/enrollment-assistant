# Microsoft Teams Tab + SSO Rollout Plan

## Purpose

This document describes the recommended Microsoft Teams rollout for this project and the current implementation status in this repository.

The default operating model is:

- we host and operate the application,
- the customer controls the Microsoft Entra app registration in their tenant,
- the app is exposed in Teams as a personal app with a static tab,
- Teams SSO is used only to bootstrap the app's normal backend session.

---

## Recommended design

### App shape

Use a **Microsoft Teams personal app** with a **static tab**.

This fits the product because it is a user-centric internal application, not a team- or channel-specific workspace.

### Identity ownership

Use a **customer-controlled Entra app registration** in the customer's tenant.

This keeps tenant-side identity ownership with the customer while we continue to own application code, hosting, deployment, and backend behavior.

### Authentication model

Use **Teams SSO** in the frontend and exchange the Teams token in the backend for the app's normal session.

Flow:

1. User opens the app inside Teams.
2. Frontend initializes the Teams SDK.
3. Frontend requests a Teams SSO token.
4. Frontend sends that token to our backend.
5. Backend validates the token and maps it to a local user.
6. Backend issues the app's normal session cookies.
7. The rest of the app continues to use the existing backend auth flow.

### Access control model

Use the customer's existing Entra group in two places:

1. **Enterprise Application assignment** for real access control.
2. **Teams app availability / pinning** for rollout and UX.

The real security gate is the Enterprise Application assignment, not Teams visibility.

---

## Current implementation status

### Backend

Implemented:

- `POST /api/auth/teams-sso`
- validation of the Microsoft token against Microsoft OpenID metadata / JWKS
- validation of:
  - signature
  - issuer
  - tenant
  - audience
  - expiry
- local user provisioning / linking
- issuance of the app's normal session after successful Teams SSO
- Teams/M365 `frame-ancestors` CSP header when Teams SSO is enabled

Current local identity behavior:

- stable identity key: `tid + oid`
- stored on the local user as:
  - `entra_tenant_id`
  - `entra_object_id`
- first sign-in may link to an existing local user by email if that local user is not already linked to another Entra identity
- newly created Teams users default to role `user`
- already existing linked users keep their existing local role

### Frontend

Implemented in the internal app:

- Teams SDK integration via `@microsoft/teams-js`
- automatic Teams SSO bootstrap attempt on load when the app is running inside Teams
- manual **Continue with Microsoft Teams** button on the auth page
- normal email/password login outside Teams
- explicit Teams sign-in failure instead of silent fallback inside Teams

### Data model

Implemented:

- `user.entra_tenant_id`
- `user.entra_object_id`
- unique index on `(entra_tenant_id, entra_object_id)`
- migration:
  - `backend/app/alembic/versions/9c1d2e3f4a5b_add_teams_sso_identity_to_user.py`

---

## Required configuration

### Backend env

Set these values in the backend environment:

- `TEAMS_SSO_ENABLED`
- `TEAMS_SSO_TENANT_ID`
- `TEAMS_SSO_CLIENT_ID`
- `TEAMS_SSO_RESOURCE`
- `TEAMS_SSO_ALLOWED_AUDIENCES`

Notes:

- `TEAMS_SSO_TENANT_ID` must be the customer tenant ID.
- accepted audiences are built from the configured client ID, resource, and optional extra audience list.
- if Teams SSO is disabled, the app continues to use the existing login flow only.

### Frontend env

Set this in the internal frontend build:

- `VITE_TEAMS_SSO_ENABLED=true`

If the frontend flag is off, the Teams button and automatic Teams bootstrap stay disabled even if the backend endpoint exists.

---

## Customer admin steps

### 1. Create or configure the Entra app registration

The customer should configure an Entra app registration for Teams tab SSO in their tenant and share these final values with us:

- tenant ID
- Application (client) ID
- Application ID URI / resource

The registration should be configured according to Microsoft Teams tab SSO guidance, including the required preauthorization entries.

### 2. Restrict access in Enterprise Applications

In the customer's tenant:

1. open the Enterprise Application for the app,
2. set **User assignment required = Yes**, 
3. assign the approved Entra group.

This is the primary access gate.

### 3. Upload the Teams app package

In Teams Admin Center:

1. upload the Teams app package,
2. scope availability to the same approved group,
3. optionally pin the app for that group.

This controls visibility and rollout, but it is not the main security layer.

---

## Teams manifest requirements

The repo no longer stores a Teams manifest/package directory. Prepare the tenant-specific Teams package outside this repository because the Entra values are tenant-specific.

---

## Security rules

Keep these rules unchanged:

- use `tid + oid` as the stable identity key,
- do not use email as the primary long-term identity key,
- validate tenant and audience in the backend,
- keep Teams SSO as a bootstrap step only,
- keep Enterprise Application assignment as the main authorization gate,
- do not treat Teams app visibility as real authorization.

If we later need multiple in-app authorization levels, prefer **app roles** over raw group-claim parsing.

---

## Remaining work

Still tenant-specific / rollout-specific:

- prepare the final Teams app manifest package for the customer tenant,
- confirm the final production Entra values,
- validate the flow in the real customer Teams tenant,
- optionally document the exact customer-facing setup package delivery process,
- decide the final product behavior after an explicit logout inside Teams.

Current note:

- logout currently clears the backend session, but the long-term Teams-specific post-logout behavior is still under review and should not be treated as finalized yet.

Not part of the current implementation:

- Microsoft Graph On-Behalf-Of flow,
- group-claim-based authorization,
- app-role-based local authorization mapping beyond existing local roles.

---

## Final recommendation

Use:

- **Teams personal static tab**,
- **customer-controlled Entra app registration**,
- **Teams SSO token exchange into the app's normal session**,
- **Enterprise Application assignment to the approved customer group**,
- **Teams app visibility and pinning scoped to the same group**.

This gives the cleanest ownership model, the best user experience, and the simplest long-term security model for this product.

---

## Official references

- Teams tab SSO overview: <https://learn.microsoft.com/en-us/microsoftteams/platform/tabs/how-to/authentication/tab-sso-overview>
- Add code for tab SSO: <https://learn.microsoft.com/en-us/microsoftteams/platform/tabs/how-to/authentication/tab-sso-code>
- Teams manifest `webApplicationInfo`: <https://learn.microsoft.com/en-us/microsoftteams/platform/tabs/how-to/authentication/tab-sso-manifest>
- Register the Entra app for tab SSO: <https://learn.microsoft.com/en-us/microsoftteams/platform/tabs/how-to/authentication/tab-sso-register-aad>
- Teams JS SDK: <https://learn.microsoft.com/en-us/javascript/api/%40microsoft/teams-js/app?view=msteams-client-js-latest>
- Create a personal tab: <https://learn.microsoft.com/en-us/microsoftteams/platform/tabs/how-to/create-personal-tab>
- Manage apps in Teams admin center: <https://learn.microsoft.com/en-us/microsoftteams/manage-apps>
- Assign users or groups to an application: <https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/assign-user-or-group-access-portal>
- Access token claims reference: <https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference>
- Group overage guidance: <https://learn.microsoft.com/en-us/troubleshoot/entra/entra-id/app-integration/get-signed-in-users-groups-in-access-token>
