# Implementation Plan - Fallback Login with Internal Django Users When OIDC Server Is Unreachable

Enable seamless fallback authentication using internal Django users when the OpenID Connect (OIDC / Keycloak) server is unreachable or authentication fails.

## Summary of Changes

- `LOGIN_URL` is updated from `/oidc/authenticate/` to `/login/`.
- Protected views (`@login_required`) redirect unauthenticated users to `/login/`.
- The new `/login/` page presents both:
  1. **Standard Username/Password login** for internal Django users (via `django.contrib.auth.backends.ModelBackend`).
  2. **Single Sign-On (SSO / Keycloak)** button linking to `/oidc/authenticate/`.
- If OIDC authentication fails or the OIDC provider is unreachable, users are redirected to `/login/?oidc_error=1` with a warning prompt to use internal Django credentials.

