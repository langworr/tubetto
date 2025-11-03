from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from django.contrib.auth.models import Group

class KeycloakOIDCBackend(OIDCAuthenticationBackend):
    def create_user(self, claims):
        user = super().create_user(claims)
        self.update_roles(user, claims)
        return user

    def update_user(self, user, claims):
        user = super().update_user(user, claims)
        self.update_roles(user, claims)
        return user

    def update_roles(self, user, claims):
        # I ruoli Keycloak arrivano in "realm_access"
        roles = claims.get("realm_access", {}).get("roles", [])
        # Assicurati che i gruppi esistano in Django
        for role in ["admin", "user"]:
            Group.objects.get_or_create(name=role)
        # Svuota i gruppi attuali
        user.groups.clear()
        # Assegna i gruppi corrispondenti
        for role in roles:
            try:
                group = Group.objects.get(name=role)
                user.groups.add(group)
            except Group.DoesNotExist:
                pass
        user.save()
