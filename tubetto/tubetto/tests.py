from django.test import TestCase, Client
from django.contrib.auth.models import User, Group
from django.urls import reverse
from tubetto.auth import KeycloakOIDCBackend


class InternalUserAuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.username = "internal_admin"
        self.password = "securepassword123"
        self.user = User.objects.create_user(
            username=self.username,
            password=self.password,
            is_staff=True,
            is_superuser=True
        )

    def test_login_page_renders_successfully(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')
        self.assertContains(response, "Sign In")
        self.assertContains(response, "Username")
        self.assertContains(response, "Password")

    def test_login_page_renders_oidc_error_banner(self):
        response = self.client.get(reverse('login') + '?oidc_error=1')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SSO Unavailable")
        self.assertContains(response, "The OIDC / Keycloak authentication service is unreachable or failed.")

    def test_internal_user_login_success(self):
        response = self.client.post(reverse('login'), {
            'username': self.username,
            'password': self.password,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['user'].is_authenticated)
        self.assertEqual(response.context['user'].username, self.username)

    def test_internal_user_login_invalid_password(self):
        response = self.client.post(reverse('login'), {
            'username': self.username,
            'password': "wrongpassword",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Login Failed")
        self.assertFalse(response.context['user'].is_authenticated)

    def test_login_required_redirects_to_login(self):
        response = self.client.get(reverse('scheduled_task'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('login')))
        self.assertIn('next=', response.url)

    def test_logout_redirects_and_clears_session(self):
        self.client.login(username=self.username, password=self.password)
        response = self.client.post(reverse('logout'), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['user'].is_authenticated)


class KeycloakOIDCBackendTests(TestCase):
    def setUp(self):
        self.backend = KeycloakOIDCBackend()

    def test_update_roles_assigns_valid_groups(self):
        user = User.objects.create_user(username="oidc_user", email="oidc@example.com")
        claims = {
            "realm_access": {
                "roles": ["admin", "user", "unknown-role"]
            }
        }
        self.backend.update_roles(user, claims)
        user_groups = list(user.groups.values_list('name', flat=True))
        self.assertIn("admin", user_groups)
        self.assertIn("user", user_groups)
        self.assertNotIn("unknown-role", user_groups)

