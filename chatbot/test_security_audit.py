import json
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings

from . import llm, views


class AuditRegressionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('ana', 'ana@example.com', 'clave-segura-123')
        self.client.force_login(self.user)
        self.client.raise_request_exception = False

    def test_invalid_json_shapes_are_client_errors(self):
        with mock.patch.object(llm, 'complete_json') as provider:
            for payload in ('[]', 'null', '"hola"', '{', '{"text": []}', '{"text": {}}',
                            '{"text": 7}', '{"duration": NaN}'):
                with self.subTest(payload=payload):
                    response = self.client.post('/api/gramatica/revisar', payload,
                                                content_type='application/json')
                    self.assertEqual(response.status_code, 400)
            provider.assert_not_called()

    def test_invalid_total_is_client_error(self):
        response = self.client.post('/api/entrevista/iniciar', {'role': 'Web', 'total': 'abc'})
        self.assertEqual(response.status_code, 400)

    def test_oversized_or_deep_json_is_client_error(self):
        values = [json.dumps({'text': 'a' * 4001}),
                  json.dumps({'other': 'a' * (65*1024)}),
                  '[' * 1500 + '0' + ']' * 1500]
        for value in values:
            response = self.client.post('/api/gramatica/revisar', value, content_type='application/json')
            self.assertEqual(response.status_code, 400)

    def test_direct_requests_ignore_forwarded_ip(self):
        request = RequestFactory().get('/', REMOTE_ADDR='203.0.113.10',
                                        HTTP_X_FORWARDED_FOR='198.51.100.123')
        self.assertEqual(views.client_ip(request), '203.0.113.10')

    def test_login_aliases_share_account_lock(self):
        self.client.logout()
        for i in range(5):
            self.client.post('/login', {'username': 'ana', 'password': 'incorrecta'},
                             REMOTE_ADDR=f'192.0.2.{i+1}')
        response = self.client.post('/login', {'username': 'ana@example.com',
                                             'password': 'clave-segura-123'}, REMOTE_ADDR='192.0.2.100')
        self.assertContains(response, 'Demasiados intentos')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_private_reports_are_scoped_to_owner(self):
        from .models import PracticeSession, Message
        other = User.objects.create_user('beto', password='otra-clave-segura-123')
        session = PracticeSession.objects.create(user=other, mode='interview', finished=True)
        message = Message.objects.create(session=session, sender='bot', kind='correction', text='privado')
        self.assertEqual(self.client.get(f'/reporte/{session.id}').status_code, 404)
        self.assertEqual(self.client.get(f'/expresion/practica/claridad/{message.id}').status_code, 404)

    def test_admin_login_uses_shared_lockout(self):
        self.client.logout()
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        for _ in range(5):
            self.client.post('/admin/login/', {'username': 'ana', 'password': 'incorrecta'})
        response = self.client.post('/admin/login/', {'username': 'ana', 'password': 'clave-segura-123'})
        self.assertEqual(response.status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_admin_valid_login_still_works(self):
        self.client.logout()
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        response = self.client.post('/admin/login/', {'username': 'ana', 'password': 'clave-segura-123'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    @override_settings(TRUSTED_PROXY_CIDRS=['10.0.0.0/8'])
    def test_trusted_proxy_ignores_spoofed_prefix(self):
        request = RequestFactory().get('/', REMOTE_ADDR='10.0.0.2',
                    HTTP_X_FORWARDED_FOR='192.0.2.99, 203.0.113.10, 10.0.0.1')
        self.assertEqual(views.client_ip(request), '203.0.113.10')

    def test_counter_keeps_expiry_and_resets_after_expiration(self):
        from datetime import timedelta
        from django.utils import timezone
        from . import limits
        from .models import RateLimitCounter
        now = timezone.now()
        with mock.patch('chatbot.limits.timezone.now', return_value=now):
            self.assertEqual(limits.hit('daily-test', 86400), 1)
        with mock.patch('chatbot.limits.timezone.now', return_value=now+timedelta(minutes=10)):
            self.assertEqual(limits.hit('daily-test', 86400), 2)
            self.assertEqual(limits.count('daily-test'), 2)
        self.assertEqual(RateLimitCounter.objects.get().expires_at, now+timedelta(days=1))
        with mock.patch('chatbot.limits.timezone.now', return_value=now+timedelta(days=2)):
            self.assertEqual(limits.count('daily-test'), 0)
            self.assertEqual(limits.hit('daily-test', 86400), 1)

    def test_invalid_spelling_payload_is_client_error(self):
        for value in ('[]', '{"id": 1, "correct": "false"}'):
            response = self.client.post('/api/expresion/ortografia', value, content_type='application/json')
            self.assertEqual(response.status_code, 400)

    def test_non_finite_scores_are_rejected(self):
        from .common import clamp
        for value in (float('nan'), float('inf'), -float('inf'), 10**400):
            self.assertIsNone(clamp(value, 0, 100))

    def test_progress_queries_do_not_grow_per_recent_session(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from . import progress
        from .models import Message, PracticeSession
        def add_session():
            session = PracticeSession.objects.create(user=self.user, mode='grammar')
            Message.objects.create(session=session, sender='bot', kind='correction',
                                   data={'score': 80, 'errors': [], 'fillers': []})
        add_session()
        with CaptureQueriesContext(connection) as initial:
            progress.build(self.user)
        for _ in range(5):
            add_session()
        with CaptureQueriesContext(connection) as several:
            data = progress.build(self.user)
        self.assertEqual(len(data['recent']), 6)
        self.assertEqual(len(initial), len(several))
