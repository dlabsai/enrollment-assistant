# Deployment guide

The app embedded in Teams is hosted wherever the operator deploys this Demo University demo app.

- Azure portal: your Azure Web App resource
- Hosted URL: `https://<your-app>.azurewebsites.net`

## Step 1: Create the Entra app registration

Create a **single-tenant** Microsoft Entra app registration for a **Teams tab SSO** app.

Use Microsoft’s official Teams tab SSO registration guidance for the exact portal settings:

- <https://learn.microsoft.com/en-us/microsoftteams/platform/tabs/how-to/authentication/tab-sso-register-aad>

This app only needs:

- Teams SSO bootstrap
- basic identity claims from the Teams token

After the Entra app is created, record these values:

### 1. Directory (tenant) ID

Where to find it:

- **Microsoft Entra admin center**
- **App registrations**
- select the app
- **Overview**
- copy **Directory (tenant) ID**

### 2. Application (client) ID

Where to find it:

- **Microsoft Entra admin center**
- **App registrations**
- select the app
- **Overview**
- copy **Application (client) ID**

### 3. Application ID URI

Where to find it:

- **Microsoft Entra admin center**
- **App registrations**
- select the app
- **Expose an API**
- copy **Application ID URI**

## Step 2: Fill the manifest values

Unzip the Teams app package and open `manifest.json`.

Fill these fields:

### `webApplicationInfo.id`

Set this to the Entra **Application (client) ID** from **App registrations > Overview**.

### `webApplicationInfo.resource`

Set this to the Entra **Application ID URI** from **App registrations > Expose an API**.

## Step 3: Re-zip the package

Zip these files together:

- `manifest.json`
- `color.png`
- `outline.png`

## Step 4: Upload the app to Teams Admin Center

In **Teams Admin Center**:

- go to **Teams apps > Manage apps**
- upload the app package zip
- allow the app if it is blocked

If custom app upload/use is disabled in the tenant, enable it first.

## Step 5: Restrict the app to `Enrollment Assistant AD group`

Do this in **both** places.

### A. Entra Enterprise Application access

This is the real access gate.

In **Microsoft Entra admin center**:

- go to **Enterprise applications**
- open the Enterprise Application for this app
- set **User assignment required** = **Yes**
- go to **Users and groups**
- assign only:
  - the Enrollment Assistant AD group

### B. Teams app availability

This controls who can see/use the app in Teams.

In **Teams Admin Center**:

- go to **Teams apps > Manage apps**
- open this app
- use **app centric management**
- set access to **Specific users or groups**
- add only:
  - the Enrollment Assistant AD group

Optional:

- pin or preinstall the app for that same group

## Value mapping and source

- `TEAMS_SSO_TENANT_ID`
  - source: **App registrations > your app > Overview > Directory (tenant) ID**
- `TEAMS_SSO_CLIENT_ID`
  - source: **App registrations > your app > Overview > Application (client) ID**
- `TEAMS_SSO_RESOURCE`
  - source: **App registrations > your app > Expose an API > Application ID URI**
- `TEAMS_SSO_ALLOWED_AUDIENCES`
  - source: combine both values below into a comma-separated list:
    - **App registrations > your app > Overview > Application (client) ID**
    - **App registrations > your app > Expose an API > Application ID URI**
  - format: `<application-client-id>,<application-id-uri>`
