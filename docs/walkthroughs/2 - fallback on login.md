# Walkthrough - Fallback Login with Internal Django Users

Implemented a resilient hybrid authentication flow allowing users to log in with internal Django credentials whenever the OpenID Connect (Keycloak / SSO) server is unreachable, down, or fails authentication.

## Changes Made

### 1. Settings & Authentication Configuration
- **`tubetto/settings.py`**:
  - Updated `LOGIN_URL = "/login/"`.
  - Configured `LOGIN_REDIRECT_URL_FAILURE = "/login/?oidc_error=1"`.
  - Retained `ModelBackend` alongside `KeycloakOIDCBackend` in `AUTHENTICATION_BACKENDS`.
  - Added safe fallback defaults for OIDC settings.

### 2. Views & Routing
- **`tubetto/views.py`**:
  - Added `CustomLoginView` and `logout_view`.
- **`tubetto/urls.py`**:
  - Added `/login/` and `/logout/` routes.

### 3. User Interface & Templates
- **`tubetto/templates/login.html`**:
  - Created responsive Bootstrap 5 login page with internal credentials form, SSO button, and OIDC error banner.
- **`tubetto/templates/base.html`**:
  - Added user account dropdown and login/logout actions in the top navbar.

### 4. Automated Tests
- **`tubetto/tests.py`**:
  - Added 7 unit and integration tests covering login, OIDC error banner, invalid credentials, `@login_required` redirects, logout, and role synchronization.

