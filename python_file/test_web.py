"""Real database + Flask client tests, using only a disposable schema in the _test DB."""
from datetime import timedelta
from pathlib import Path
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

import auth
import db
import service
import test_integration as fixtures
from web import create_app

PASSWORD = 'Fixture-password-2026!'
NEW_PASSWORD = 'Fixture-new-password-2026!'


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = fixtures.ServiceIntegrationTests
        cls.fixture.setUpClass()
        cls.addClassCleanup(cls.fixture.doClassCleanups)
        migration = (Path(__file__).resolve().parents[1] / 'database/staff.sql').read_text(encoding='utf-8')
        cls.fixture.execute('\n'.join(line for line in migration.splitlines()
                                     if line.strip() not in ('BEGIN;', 'COMMIT;')))
        cls.hashed = generate_password_hash(PASSWORD, method='scrypt')
        cls.app = create_app({'TESTING': True, 'SECRET_KEY': 'isolated-test-secret-32-characters-long'})

    def setUp(self):
        fixtures.ServiceIntegrationTests().setUp()
        self.fixture.execute('''TRUNCATE staff RESTART IDENTITY CASCADE;
            INSERT INTO staff(username,display_name,password_hash,role,must_change_password)
            VALUES('manager','Test Manager',%s,'manager',FALSE),
                  ('reception','Test Reception',%s,'receptionist',FALSE)''', (self.hashed, self.hashed))
        self.client = self.app.test_client()
        self.today = self.fixture.execute('SELECT CURRENT_DATE')[0][0]

    def post(self, path, data=None, client=None, **kwargs):
        client = client or self.client
        with client.session_transaction() as state:
            token = state.setdefault('csrf_token', 'test-csrf-token')
        return client.post(path, data=dict(data or {}, csrf_token=token), **kwargs)

    def login(self, username='manager', password=PASSWORD, client=None):
        return self.post('/login', {'username': username, 'password': password}, client=client)

    def test_public_search_no_private_data_and_all_staff_routes_require_login(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'Alice', response.data)
        for path in ['/dashboard', '/rooms', '/reservations', '/reservations/new', '/contacts/new',
                     '/reservations/1', '/reservations/1/extend', '/staff', '/password']:
            self.assertEqual(self.client.get(path).status_code, 302, path)
        result = self.client.get('/', query_string={'check_in': self.today.isoformat(),
            'check_out': (self.today+timedelta(days=2)).isoformat(), 'guests': 1})
        self.assertEqual(result.status_code, 200)

    def test_csrf_rejects_login_and_every_write_and_host_is_restricted(self):
        self.assertEqual(self.client.post('/login', data={'username':'manager','password':PASSWORD}).status_code, 400)
        self.client.get('/login')
        self.assertEqual(self.client.post('/login', data={'csrf_token':'无效令牌'}).status_code, 400)
        self.login()
        for path in ['/logout', '/password', '/staff', '/reservations/new', '/contacts/new',
                     '/rooms/1/open', '/rooms/1/housekeeping', '/reservations/1/action', '/reservations/1/extend']:
            self.assertEqual(self.client.post(path).status_code, 400, path)
        self.assertEqual(self.client.get('/', headers={'Host':'untrusted.example'}).status_code, 400)

    def test_wrong_password_lockout_and_parameter_binding(self):
        for _ in range(5):
            self.assertEqual(self.login(password='incorrect').status_code, 401)
        self.assertEqual(self.login().status_code, 401)
        self.fixture.execute('UPDATE staff SET locked_until=CURRENT_TIMESTAMP-INTERVAL \'1 second\' WHERE staff_id=1')
        self.assertEqual(self.login().status_code, 302)
        self.post('/logout')
        self.assertEqual(self.login(username="' OR 1=1 --").status_code, 401)

    def test_reception_cannot_manage_staff_or_room_open_but_can_clean(self):
        self.login('reception')
        self.assertEqual(self.client.get('/staff').status_code, 403)
        self.assertEqual(self.post('/staff', {'action':'create'}).status_code, 403)
        self.assertEqual(self.post('/rooms/1/open', {'is_open':'false'}).status_code, 403)
        self.assertEqual(self.post('/rooms/5/housekeeping', {'status':'cleaning'}).status_code, 302)
        self.assertEqual(self.fixture.execute('SELECT housekeeping_status FROM room WHERE room_id=5')[0][0], 'cleaning')

    def test_manager_staff_creation_hash_force_password_change_and_reset(self):
        self.login()
        self.assertEqual(self.post('/staff', {'action':'create','username':'alex','display_name':'Alex',
            'role':'receptionist','password':PASSWORD,'confirm_password':PASSWORD}).status_code, 302)
        row = self.fixture.execute("SELECT password_hash,must_change_password FROM staff WHERE username='alex'")[0]
        self.assertTrue(row[0].startswith('scrypt:'))
        self.assertNotIn(PASSWORD, row[0])
        self.assertTrue(row[1])
        alex = self.app.test_client()
        self.assertTrue(self.login('alex', client=alex).location.endswith('/password'))
        self.assertTrue(alex.get('/dashboard').location.endswith('/password'))
        self.assertEqual(self.post('/reservations/new', {}, client=alex).status_code, 302)
        self.assertEqual(self.post('/password', {'old_password':PASSWORD,'new_password':NEW_PASSWORD,
            'confirm_password':NEW_PASSWORD}, client=alex).status_code, 302)
        self.assertEqual(alex.get('/dashboard').status_code, 200)
        target = self.fixture.execute("SELECT staff_id FROM staff WHERE username='alex'")[0][0]
        self.post('/staff', {'action':'reset','staff_id':target,'password':PASSWORD,'confirm_password':PASSWORD})
        self.assertEqual(alex.get('/dashboard').status_code, 302)

    def test_disable_revokes_session_and_last_manager_cannot_be_disabled(self):
        self.login()
        other = self.app.test_client()
        self.login('reception', client=other)
        self.assertEqual(self.post('/staff', {'action':'active','staff_id':2,'active':'false'}).status_code, 302)
        self.assertEqual(other.get('/dashboard').status_code, 302)
        self.assertEqual(self.login('reception', client=other).status_code, 401)
        self.assertEqual(self.post('/staff', {'action':'active','staff_id':1,'active':'false'}).status_code, 400)
        self.assertTrue(self.fixture.execute('SELECT is_active FROM staff WHERE staff_id=1')[0][0])

    def test_logout_revokes_replayed_cookie_and_sensitive_pages_not_cached(self):
        self.login()
        page = self.client.get('/dashboard')
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", page.headers['Content-Security-Policy'])
        old = self.client.get_cookie('hotel_staff').value
        self.assertEqual(self.post('/logout').status_code, 302)
        self.client.set_cookie('hotel_staff', old)
        self.assertEqual(self.client.get('/dashboard').status_code, 302)

    def test_staff_pages_render_and_escape_guest_input(self):
        self.login()
        guest = service.add_guest('<script>alert(1)</script>', None, '000')
        reservation = service.create_reservation(guest, 1, self.today, self.today+timedelta(days=1), 1)[0]
        for path in ['/dashboard','/rooms','/staff','/reservations','/reservations/new','/contacts/new',
                     f'/reservations/{reservation}', f'/reservations/{reservation}/extend','/password']:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        body = self.client.get(f'/reservations/{reservation}').data
        self.assertIn(b'&lt;script&gt;', body)
        self.assertNotIn(b'<script>alert', body)

    def test_http_booking_roster_checkin_checkout_and_cleaning(self):
        self.login('reception')
        response = self.post('/reservations/new', {'guest_id':1,'room_id':1,'check_in':self.today.isoformat(),
            'check_out':(self.today+timedelta(days=2)).isoformat(),'guests':2})
        self.assertEqual(response.status_code, 302)
        rid = int(response.location.rsplit('/',1)[1])
        path = f'/reservations/{rid}/action'
        self.assertEqual(self.post(path, {'action':'check_in'}).status_code, 400)
        for name in ['One', 'Two']:
            self.assertEqual(self.post(path, {'action':'add_guest','full_name':name}).status_code, 302)
        self.assertEqual(self.post(path, {'action':'check_in'}).status_code, 302)
        self.assertEqual(self.post(path, {'action':'check_out'}).status_code, 302)
        self.assertEqual(self.fixture.execute('SELECT housekeeping_status FROM room WHERE room_id=1')[0][0], 'dirty')

    def test_http_continuation_quote_activation_and_atomic_rollback(self):
        self.login()
        helper = fixtures.ServiceIntegrationTests()
        helper.today = self.today
        parent = helper.parent(checkout=self.today)
        end = self.today+timedelta(days=2)
        self.assertEqual(self.client.get(f'/reservations/{parent}/extend', query_string={'new_check_out':str(end)}).status_code, 200)
        post = {'room_id':2,'new_check_out':str(end),'accepted_rate':'180.00'}
        response = self.post(f'/reservations/{parent}/extend', post)
        self.assertEqual(response.status_code, 302)
        child = int(response.location.rsplit('/',1)[1])
        import queries
        with patch.object(queries, 'CHECK_IN', queries.CHECK_IN+'; SELECT 1/0'):
            self.assertEqual(self.post(f'/reservations/{child}/action', {'action':'activate'}).status_code, 503)
        self.assertEqual(self.fixture.execute('SELECT status FROM reservation WHERE reservation_id=%s', (parent,))[0][0], 'checked_in')
        self.assertEqual(self.post(f'/reservations/{child}/action', {'action':'activate'}).status_code, 302)
        self.assertEqual(self.fixture.execute('SELECT status FROM reservation WHERE reservation_id=%s', (child,))[0][0], 'checked_in')

    def test_invalid_input_and_invalid_actions_do_not_write(self):
        self.login()
        for path, data in [('/reservations/new', {'guest_id':'oops'}),
                           ('/rooms/1/open', {'is_open':'invalid'}),
                           ('/staff', {'action':'unknown'}),
                           ('/staff', {'action':'create','username':'bad','display_name':'Bad','role':'manager',
                                        'password':'short','confirm_password':'short'})]:
            self.assertEqual(self.post(path,data).status_code, 400)
        self.assertEqual(self.fixture.execute('SELECT COUNT(*) FROM reservation')[0][0], 0)
        self.assertEqual(self.fixture.execute('SELECT COUNT(*) FROM staff')[0][0], 2)

    def test_contact_creation_roster_removal_and_cancellation(self):
        self.login()
        result = self.post('/contacts/new', {'name':'New Contact','phone':'123','email':''})
        self.assertEqual(result.status_code, 302)
        contact = self.fixture.execute("SELECT guest_id FROM guest WHERE name='New Contact'")[0][0]
        rid = service.create_reservation(contact, 1, self.today+timedelta(days=3), self.today+timedelta(days=5), 1)[0]
        registration = service.add_staying_guest(rid, 'Guest')
        self.assertEqual(self.post(f'/reservations/{rid}/action',
            {'action':'remove_guest','registration_id':registration}).status_code, 302)
        self.assertEqual(service.list_staying_guests(rid), [])
        self.assertEqual(self.post(f'/reservations/{rid}/action', {'action':'cancel','guest_id':999}).status_code, 302)
        self.assertEqual(self.fixture.execute('SELECT status FROM reservation WHERE reservation_id=%s', (rid,))[0][0], 'cancelled')

    def test_concurrent_manager_disables_preserve_an_active_manager(self):
        from concurrent.futures import ThreadPoolExecutor
        self.fixture.execute("UPDATE staff SET role='manager' WHERE staff_id=2")
        def disable(actor, target):
            try:
                auth.set_active(actor, 0, target, False)
                return 'ok'
            except auth.AuthError:
                return 'refused'
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda pair: disable(*pair), [(1,2),(2,1)]))
        self.assertEqual(sorted(results), ['ok','refused'])
        self.assertEqual(self.fixture.execute("SELECT COUNT(*) FROM staff WHERE role='manager' AND is_active")[0][0], 1)

    def test_cli_staff_adapter_enforces_authentication_and_manager_permission(self):
        import main
        with self.assertRaises(auth.AuthError):
            main.run_staff_option('2', None)
        reception = auth.authenticate('reception', PASSWORD)
        with self.assertRaises(auth.AuthError):
            main.run_staff_option('13', reception)
        with patch('builtins.print'):
            main.run_staff_option('2', reception)


if __name__ == '__main__':
    unittest.main(verbosity=2)
