"""
OIDC authentication backend for Keycloak integration.

This module provides a custom OIDC authentication backend that extends
mozilla-django-oidc to synchronize Keycloak roles with Django user groups.
"""

from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from django.contrib.auth.models import Group


class KeycloakOIDCBackend(OIDCAuthenticationBackend):
    """
    Custom OIDC authentication backend for Keycloak.

    Extends the mozilla-django-oidc OIDCAuthenticationBackend to automatically
    synchronize Keycloak realm roles with Django user groups during user creation
    and updates.

    Methods:
        create_user: Creates a new user and assigns roles from Keycloak claims.
        update_user: Updates an existing user and syncs their Keycloak roles.
        update_roles: Synchronizes Keycloak roles to Django groups.
    """

    def create_user(self, claims):
        """
        Create a new Django user from OIDC claims and assign Keycloak roles.

        Calls the parent create_user method to generate the user object,
        then synchronizes the user's Keycloak roles to Django groups.

        Args:
            claims (dict): OIDC token claims containing user information and roles.

        Returns:
            User: The newly created Django user with assigned groups.
        """
        user = super().create_user(claims)
        self.update_roles(user, claims)
        return user

    def update_user(self, user, claims):
        """
        Update an existing Django user from OIDC claims and sync Keycloak roles.

        Calls the parent update_user method to refresh user information,
        then synchronizes the user's current Keycloak roles to Django groups.

        Args:
            user (User): The existing Django user to update.
            claims (dict): OIDC token claims containing updated user information and roles.

        Returns:
            User: The updated Django user with synchronized groups.
        """
        user = super().update_user(user, claims)
        self.update_roles(user, claims)
        return user

    def update_roles(self, user, claims):
        """
        Synchronize Keycloak realm roles to Django user groups.

        Extracts roles from Keycloak's "realm_access" claim, ensures corresponding
        Django groups exist, and assigns them to the user. Clears any previously
        assigned groups before applying the new ones.

        Supported roles: 'admin', 'user', 'power-user'.
        Unknown roles from Keycloak are silently ignored.

        Args:
            user (User): The Django user whose groups should be updated.
            claims (dict): OIDC token claims containing realm_access with roles.

       Returns:
            None
        """
        # Extract Keycloak roles from realm_access claim
        roles = claims.get("realm_access", {}).get("roles", [])

        # Ensure predefined groups exist in Django
        for role in ["admin", "user", "power-user"]:
            Group.objects.get_or_create(name=role)

        # Clear existing group memberships
        user.groups.clear()

        # Assign groups corresponding to Keycloak roles
        for role in roles:
            try:
                group = Group.objects.get(name=role)
                user.groups.add(group)
            except Group.DoesNotExist:
                # Silently skip roles that don't have a corresponding Django group
                pass

        user.save()
