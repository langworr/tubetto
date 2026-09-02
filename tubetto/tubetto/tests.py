from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from tubetto.auth import KeycloakOIDCBackend
from tubetto.models import ScheduledTaskHistory
from tubetto.tasks import (
    dispatch_async_task,
    execute_task,
    task_update_channels_metadata,
    task_scan_channel_videos,
    task_sync_channel_tabs,
    task_update_videos_metadata,
    task_update_music_tracks_metadata,
    task_run_all,
)
from videos.models import Channel


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


class ScheduledTaskAsyncTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username="task_admin",
            password="adminpassword123",
            is_staff=True,
            is_superuser=True
        )
        self.regular_user = User.objects.create_user(
            username="regular_user",
            password="userpassword123"
        )
        self.channel = Channel.objects.create(
            yt_channel_id="UC_TEST_1",
            title="Test Channel"
        )

    def test_dispatch_async_task_creates_history_and_queues(self):
        with patch('tubetto.tasks.async_task', return_value="django_q_task_123") as mock_async:
            history = dispatch_async_task(
                task_type="update_channels",
                user=self.admin_user,
                channel_ids=None
            )
            self.assertEqual(history.status, "running")
            self.assertEqual(history.task_type, "update_channels")
            self.assertEqual(history.user, self.admin_user)
            self.assertEqual(history.q_task_id, "django_q_task_123")
            mock_async.assert_called_once_with(
                "tubetto.tasks.execute_task",
                history.id,
                "update_channels",
                None
            )

    def test_dispatch_async_task_with_channel_ids(self):
        with patch('tubetto.tasks.async_task', return_value="django_q_task_456") as mock_async:
            history = dispatch_async_task(
                task_type="scan_videos",
                user=self.admin_user,
                channel_ids=[self.channel.id]
            )
            self.assertEqual(history.channels, [self.channel.id])
            mock_async.assert_called_once_with(
                "tubetto.tasks.execute_task",
                history.id,
                "scan_videos",
                [self.channel.id]
            )

    @patch('tubetto.tasks.update_channels_metadata')
    def test_execute_task_success(self, mock_service):
        mock_service.return_value = {"channels_processed": 1, "channels_updated": 1, "channels_errors": []}
        history = ScheduledTaskHistory.objects.create(
            task_type="update_channels",
            user=self.admin_user,
            status="running"
        )

        result = execute_task(history.id, "update_channels")
        history.refresh_from_db()

        self.assertEqual(history.status, "completed")
        self.assertIsNotNone(history.ended_at)
        self.assertIn("channels_updated", history.result)
        self.assertEqual(result["channels_updated"], 1)

    @patch('tubetto.tasks.update_channels_metadata', side_effect=RuntimeError("YouTube network error"))
    def test_execute_task_failure(self, _mock_service):
        history = ScheduledTaskHistory.objects.create(
            task_type="update_channels",
            user=self.admin_user,
            status="running"
        )

        result = execute_task(history.id, "update_channels")
        history.refresh_from_db()

        self.assertEqual(history.status, "failed")
        self.assertIsNotNone(history.ended_at)
        self.assertIn("YouTube network error", history.result)
        self.assertIn("error", result)

    def test_execute_task_unknown_type(self):
        history = ScheduledTaskHistory.objects.create(
            task_type="non_existent_task",
            user=self.admin_user,
            status="running"
        )
        execute_task(history.id, "non_existent_task")
        history.refresh_from_db()
        self.assertEqual(history.status, "failed")
        self.assertIn("Unknown task type", history.result)

    @patch('tubetto.tasks.sync_channel_tabs')
    def test_individual_task_wrappers(self, mock_tabs):
        mock_tabs.return_value = {"channels_scanned": 1}
        history = ScheduledTaskHistory.objects.create(
            task_type="scan_channel_tabs",
            status="running"
        )
        task_sync_channel_tabs(history.id, [self.channel.id])
        history.refresh_from_db()
        self.assertEqual(history.status, "completed")
        mock_tabs.assert_called_once_with(channel_ids=[self.channel.id])

    @patch('tubetto.tasks.update_channels_metadata')
    def test_task_update_channels_wrapper(self, mock_fn):
        mock_fn.return_value = {"channels_updated": 2}
        history = ScheduledTaskHistory.objects.create(task_type="update_channels", status="running")
        task_update_channels_metadata(history.id)
        history.refresh_from_db()
        self.assertEqual(history.status, "completed")
        mock_fn.assert_called_once()

    @patch('tubetto.tasks.scan_channel_videos')
    def test_task_scan_channel_videos_wrapper(self, mock_fn):
        mock_fn.return_value = {"videos_scanned": 5}
        history = ScheduledTaskHistory.objects.create(task_type="scan_videos", status="running")
        task_scan_channel_videos(history.id, [self.channel.id])
        history.refresh_from_db()
        self.assertEqual(history.status, "completed")
        mock_fn.assert_called_once_with(channel_ids=[self.channel.id])

    @patch('tubetto.tasks.update_videos_metadata')
    def test_task_update_videos_metadata_wrapper(self, mock_fn):
        mock_fn.return_value = {"videos_updated": 3}
        history = ScheduledTaskHistory.objects.create(task_type="update_videos_metadata", status="running")
        task_update_videos_metadata(history.id)
        history.refresh_from_db()
        self.assertEqual(history.status, "completed")
        mock_fn.assert_called_once()

    @patch('tubetto.tasks.update_music_tracks_metadata')
    def test_task_update_music_tracks_metadata_wrapper(self, mock_fn):
        mock_fn.return_value = {"tracks_updated": 4}
        history = ScheduledTaskHistory.objects.create(task_type="update_music_tracks", status="running")
        task_update_music_tracks_metadata(history.id)
        history.refresh_from_db()
        self.assertEqual(history.status, "completed")
        mock_fn.assert_called_once()

    @patch('tubetto.tasks.run_scheduled_task')
    def test_task_run_all_wrapper(self, mock_fn):
        mock_fn.return_value = {"all": "done"}
        history = ScheduledTaskHistory.objects.create(task_type="run_all", status="running")
        task_run_all(history.id)
        history.refresh_from_db()
        self.assertEqual(history.status, "completed")
        mock_fn.assert_called_once()

    def test_scheduled_task_view_permission_denied_for_regular_user(self):
        self.client.login(username="regular_user", password="userpassword123")
        response = self.client.get(reverse('scheduled_task'))
        self.assertEqual(response.status_code, 403)

    def test_scheduled_task_view_get_renders_for_admin(self):
        self.client.login(username="task_admin", password="adminpassword123")
        response = self.client.get(reverse('scheduled_task'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "scheduled_task.html")
        self.assertContains(response, "Scheduled Tasks")
        self.assertContains(response, "1. Update Channels Metadata")

    @patch('tubetto.views.dispatch_async_task')
    def test_scheduled_task_view_post_enqueues_task(self, mock_dispatch):
        self.client.login(username="task_admin", password="adminpassword123")
        response = self.client.post(reverse('scheduled_task'), {
            'update_channels': '1'
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        mock_dispatch.assert_called_once_with(
            task_type="update_channels",
            user=self.admin_user,
            channel_ids=None
        )
        self.assertContains(response, "has been scheduled and is running in the background")

    @patch('tubetto.views.dispatch_async_task')
    def test_scheduled_task_view_post_scan_videos_with_channel(self, mock_dispatch):
        self.client.login(username="task_admin", password="adminpassword123")
        response = self.client.post(reverse('scheduled_task'), {
            'scan_videos': '1',
            'scan_channels_selected': [str(self.channel.id)]
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        mock_dispatch.assert_called_once_with(
            task_type="scan_videos",
            user=self.admin_user,
            channel_ids=[self.channel.id]
        )

    @patch('tubetto.tasks.update_channels_metadata')
    def test_execute_task_writes_to_log_file(self, mock_service):
        from django.conf import settings
        mock_service.return_value = {"channels_processed": 1}
        history = ScheduledTaskHistory.objects.create(
            task_type="update_channels",
            user=self.admin_user,
            status="running"
        )
        execute_task(history.id, "update_channels")
        log_file = settings.LOGS_DIR / "tasks.log"
        self.assertTrue(log_file.exists())
        log_content = log_file.read_text(encoding="utf-8")
        self.assertIn("Starting task 'update_channels'", log_content)

