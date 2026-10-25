"""Real PostgreSQL service tests in a disposable schema of a dedicated _test database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import os
import re
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg2
from psycopg2 import sql

import db
import queries
import service


class ServiceIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = (db.DATABASE, db.SCHEMA)
        test_database = os.environ.get('HOTEL_TEST_DATABASE', 'comp9120_hotel_test')
        if not test_database.endswith('_test'):
            raise RuntimeError('HOTEL_TEST_DATABASE must end in _test')
        db.DATABASE = test_database
        db.SCHEMA = 'hotel_integration_' + uuid4().hex
        cls.schema = db.SCHEMA
        cls.addClassCleanup(cls.cleanup_schema)
        cls.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(cls.schema)))
        for filename in ['schema.sql','staff.sql','reservation_audit.sql']:
            source = Path(__file__).resolve().parents[1] / 'database' / filename
            ddl = '\n'.join(line for line in source.read_text(encoding='utf-8').splitlines()
                            if not line.startswith('\\') and line.strip() not in ('BEGIN;', 'COMMIT;'))
            cls.execute(ddl)

    @classmethod
    def cleanup_schema(cls):
        try:
            if db.DATABASE.endswith('_test') and re.fullmatch(r'hotel_integration_[0-9a-f]{32}', cls.schema):
                cls.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(cls.schema)))
        finally:
            db.DATABASE, db.SCHEMA = cls.original

    @staticmethod
    def execute(statement, params=None):
        conn = db.get_connection()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(statement, params)
                    if cur.description:
                        return cur.fetchall()
        finally:
            conn.close()

    def setUp(self):
        self.assertEqual(self.execute('SELECT current_schema()')[0][0], self.schema)
        self.execute('''TRUNCATE reservation_guest, reservation, room, room_type, guest RESTART IDENTITY CASCADE;
            INSERT INTO guest(name,email,phone) VALUES ('Alice',NULL,'00123'),('Other',NULL,'00123');
            INSERT INTO room_type(type_name,max_guests,base_nightly_rate)
                VALUES ('Double',2,180),('Family',4,240),('Single',1,120);
            INSERT INTO room(room_number,room_type_id,is_bookable,housekeeping_status)
                VALUES ('201',1,TRUE,'clean'),('202',1,TRUE,'clean'),('301',2,TRUE,'clean'),
                       ('101',3,TRUE,'clean'),('102',3,TRUE,'dirty'),('302',2,FALSE,'cleaning');''')
        self.today = self.execute(queries.GET_TODAY)[0][0]

    def booking(self, room=1, start=None, nights=2, guests=2, contact=1):
        start = start if start is not None else self.today
        return service.create_reservation(contact, room, start, start + timedelta(days=nights), guests)[0]

    def parent(self, room=1, checkout=None):
        end = checkout if checkout is not None else self.today
        # Historical planned dates are fixtures; check-in itself uses the public manual-arrival policy.
        reservation = self.execute('''INSERT INTO reservation
            (guest_id,room_id,check_in_date,check_out_date,guest_count,booked_nightly_rate)
            VALUES (1,%s,%s,%s,2,180) RETURNING reservation_id''',
            (room, end - timedelta(days=1), end))[0][0]
        service.add_staying_guest(reservation, 'Alex')
        service.add_staying_guest(reservation, 'Alex')
        service.check_in(reservation)
        return reservation

    def state(self, reservation):
        return self.execute('''SELECT r.status, rm.housekeeping_status,
            r.actual_check_in_at,r.actual_check_out_at FROM reservation r
            JOIN room rm USING(room_id) WHERE reservation_id=%s''', (reservation,))[0]

    def test_all_28_sql_interfaces_match_requirement(self):
        document = Path(__file__).with_name('SQL_queries requirement.txt').read_text(encoding='utf-8')
        required = set(re.findall(r'^\d+\. ([A-Z_]+) ', document, re.MULTILINE))
        actual = {name for name, value in vars(queries).items() if name.isupper() and isinstance(value, str)}
        self.assertEqual(len(required), 28)
        self.assertEqual(actual, required)

    def test_connection_readonly_and_execution_time(self):
        conn = db.get_connection(read_only=True)
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT current_setting(\'transaction_read_only\'), CURRENT_TIMESTAMP')
                readonly, transaction_start = cur.fetchone()
                self.assertEqual(readonly, 'on')
                cur.execute('SELECT pg_sleep(0.03)')
                self.assertGreater(service._event_time(cur), transaction_start)
                self.assertEqual(service._today(cur), self.today)
                with self.assertRaises(psycopg2.errors.ReadOnlySqlTransaction):
                    cur.execute("INSERT INTO guest(name,phone) VALUES('No','0')")
        finally:
            conn.rollback()
            conn.close()

    def test_contacts_types_and_result_shapes(self):
        contact = service.add_guest("  O'Reilly; SELECT 1  ", ' ', ' 00100 ')
        self.assertEqual(self.execute(queries.GET_GUEST, (contact,))[0][1:],
                         ("O'Reilly; SELECT 1", None, '00100'))
        with self.assertRaises(service.BookingError):
            service.add_guest(' ', None, '1')
        self.assertEqual(len(service.list_types()[0]), 4)
        self.assertEqual(len(service.list_rooms()[0]), 7)
        self.assertEqual(len(service.booking_statistics()[0]), 4)
        self.assertTrue(all(row[1:] == (0, 0, Decimal('0')) for row in service.booking_statistics()))

    def test_search_overlap_adjacency_capacity_and_dirty_future_room(self):
        start = self.today + timedelta(days=10)
        self.booking(start=start)
        rows = service.find_rooms(start + timedelta(days=1), start + timedelta(days=3), 1)
        self.assertNotIn(1, [r[0] for r in rows])
        self.assertIn(5, [r[0] for r in rows])
        self.assertNotIn(6, [r[0] for r in rows])
        self.assertTrue(all(len(row) == 6 and isinstance(row[4], Decimal) for row in rows))
        adjacent = service.find_rooms(start + timedelta(days=2), start + timedelta(days=4), 2, 1)
        self.assertEqual([r[0] for r in adjacent], [1, 2])
        self.assertEqual([r[0] for r in service.find_rooms(start, start + timedelta(days=2), 3)], [3])

    def test_booking_validation_and_price_snapshot(self):
        for args in [(1, 1, self.today, self.today, 1),
                     (1, 1, self.today - timedelta(days=1), self.today, 1),
                     (1, 1, self.today, self.today + timedelta(days=1), True),
                     (1, 4, self.today, self.today + timedelta(days=1), 2),
                     (1, 6, self.today, self.today + timedelta(days=1), 2),
                     (999, 1, self.today, self.today + timedelta(days=1), 1)]:
            with self.subTest(args=args), self.assertRaises(service.BookingError):
                service.create_reservation(*args)
        reservation = self.booking()
        with self.assertRaises(service.BookingError):
            self.booking()
        self.execute('UPDATE room_type SET base_nightly_rate=200 WHERE room_type_id=1')
        row = service.personal_reservations(1)[0]
        self.assertEqual((row[0], row[6], row[7]), (reservation, Decimal('180'), Decimal('360')))

    def test_cancellation_ownership_deadline_and_history(self):
        future = self.booking(start=self.today + timedelta(days=2))
        with self.assertRaises(service.BookingError):
            service.cancel_reservation(2, future)
        service.cancel_reservation(1, future)
        self.assertEqual(service.personal_reservations(1)[0][8], 'cancelled')
        with self.assertRaises(service.BookingError):
            service.cancel_reservation(1, future)
        current = self.booking(room=2)
        with self.assertRaises(service.BookingError):
            service.cancel_reservation(1, current)

    def test_staff_exact_search_all_and_duplicate_phone(self):
        first = self.booking(room=1, contact=1)
        second = self.booking(room=2, contact=2)
        self.assertEqual(len(service.search_reservations()[0]), 16)
        self.assertEqual([r[0] for r in service.search_reservations('00123')], [first, second])
        self.assertEqual([r[0] for r in service.search_reservations('Alice')], [first])
        self.assertEqual([r[0] for r in service.search_reservations(str(second))], [second])
        self.assertEqual(service.search_reservations("' OR TRUE --"), [])

    def test_roster_arrival_checkout_and_cleaning_lifecycle(self):
        reservation = self.booking(start=self.today + timedelta(days=5))
        with self.assertRaises(service.BookingError):
            service.check_in(reservation)
        registration = service.add_staying_guest(reservation, 'Same Name')
        service.add_staying_guest(reservation, 'Same Name')
        with self.assertRaises(service.BookingError):
            service.add_staying_guest(reservation, 'Third')
        self.assertEqual(len(service.list_staying_guests(reservation)[0]), 3)
        with self.assertRaises(service.BookingError):
            service.remove_staying_guest(reservation + 999, registration)
        service.remove_staying_guest(reservation, registration)
        service.add_staying_guest(reservation, 'Replacement')
        # Manual ordinary arrivals intentionally have no planned-date restriction.
        service.check_in(reservation)
        self.assertEqual(self.state(reservation)[:2], ('checked_in', 'clean'))
        self.assertIsNotNone(self.state(reservation)[2].tzinfo)
        with self.assertRaises(service.BookingError):
            service.add_staying_guest(reservation, 'Late edit')
        with self.assertRaises(service.BookingError):
            service.set_housekeeping_status(1, 'dirty')
        service.check_out(reservation)
        self.assertEqual(self.state(reservation)[:2], ('checked_out', 'dirty'))
        self.assertGreaterEqual(self.state(reservation)[3], self.state(reservation)[2])
        with self.assertRaises(service.BookingError):
            service.check_out(reservation)
        service.set_room_open(1, False)
        with self.assertRaises(service.BookingError):
            service.set_housekeeping_status(1, 'clean')
        service.set_housekeeping_status(1, 'cleaning')
        service.set_housekeeping_status(1, 'clean')
        self.assertEqual(self.execute('SELECT is_bookable FROM room WHERE room_id=1')[0][0], False)
        row = service.personal_reservations(1)[0]
        self.assertEqual((row[3], row[4], row[6]),
                         (self.today + timedelta(days=5), self.today + timedelta(days=7), Decimal('180')))

    def test_dirty_closed_and_physically_occupied_arrivals_refused(self):
        reservation = self.booking(room=5, guests=1)
        service.add_staying_guest(reservation, 'Solo')
        with self.assertRaises(service.BookingError):
            service.check_in(reservation)
        service.set_housekeeping_status(5, 'cleaning')
        service.set_housekeeping_status(5, 'clean')
        service.set_room_open(5, False)
        with self.assertRaises(service.BookingError):
            service.check_in(reservation)
        first = self.booking(room=1, start=self.today + timedelta(days=1))
        second = self.booking(room=1, start=self.today + timedelta(days=3))
        for item in (first, second):
            service.add_staying_guest(item, 'One')
            service.add_staying_guest(item, 'Two')
        service.check_in(first)
        with self.assertRaises(service.BookingError):
            service.check_in(second)

    def test_same_room_continuation_keeps_room_clean_and_roster_history(self):
        parent = self.parent()
        options = service.find_extension_options(parent, self.today + timedelta(days=2))
        self.assertEqual(options[0][0], 1)
        self.assertEqual(options[0][6], 'Original room')
        child = service.create_extension(parent, 1, self.today + timedelta(days=2), Decimal('180'))[0]
        with self.assertRaises(service.BookingError):
            service.check_in(child)
        with self.assertRaises(service.BookingError):
            service.check_out(parent)
        service.activate_continuation(child)
        self.assertEqual(self.state(parent)[:2], ('checked_out', 'clean'))
        self.assertEqual(self.state(child)[:2], ('checked_in', 'clean'))
        self.assertEqual(self.state(parent)[3], self.state(child)[2])
        self.assertEqual(len(service.list_staying_guests(parent)), 2)
        self.assertEqual(len(service.list_staying_guests(child)), 2)
        self.assertTrue({r[0] for r in service.list_staying_guests(parent)}.isdisjoint(
                        {r[0] for r in service.list_staying_guests(child)}))

    def test_room_change_and_quote_preference(self):
        parent = self.parent()
        self.booking(room=1)
        options = service.find_extension_options(parent, self.today + timedelta(days=2))
        self.assertEqual(options[0][0], 2)
        self.assertEqual(options[0][6], 'Same room type')
        child = service.create_extension(parent, 3, self.today + timedelta(days=2), Decimal('240'))[0]
        service.activate_continuation(child)
        self.assertEqual(self.state(parent)[:2], ('checked_out', 'dirty'))
        self.assertEqual(self.state(child)[:2], ('checked_in', 'clean'))
        self.assertEqual(self.state(parent)[3], self.state(child)[2])
        self.assertEqual(service.personal_reservations(1)[-1][6], Decimal('240'))

    def test_continuation_activation_window_dirty_target_and_quote_change(self):
        parent = self.parent(checkout=self.today + timedelta(days=1))
        with self.assertRaises(service.BookingError):
            service.create_extension(parent, 2, self.today + timedelta(days=3), Decimal('170'))
        child = service.create_extension(parent, 2, self.today + timedelta(days=3), Decimal('180'))[0]
        with self.assertRaises(service.BookingError):
            service.activate_continuation(child)
        self.assertEqual(self.state(parent)[0], 'checked_in')
        self.assertEqual(self.state(child)[0], 'confirmed')
        with self.assertRaises(service.BookingError):
            service.create_extension(parent, 3, self.today + timedelta(days=3), Decimal('240'))
        service.cancel_reservation(1, child)
        self.assertEqual(service.personal_reservations(1)[-1][8], 'cancelled')
        replacement = service.create_extension(parent, 3, self.today + timedelta(days=3), Decimal('240'))[0]
        self.assertNotEqual(replacement, child)

    def test_dirty_continuation_target_preserves_old_stay(self):
        parent = self.parent()
        child = service.create_extension(parent, 2, self.today + timedelta(days=2), Decimal('180'))[0]
        service.set_housekeeping_status(2, 'dirty')
        with self.assertRaises(service.BookingError):
            service.activate_continuation(child)
        self.assertEqual(self.state(parent)[:2], ('checked_in', 'clean'))
        self.assertEqual(self.state(child)[:2], ('confirmed', 'dirty'))

    def test_checkout_failure_rolls_back_both_updates(self):
        parent = self.parent()
        with patch.object(queries, 'SET_HOUSEKEEPING', queries.SET_HOUSEKEEPING + '; SELECT 1/0'):
            with self.assertRaises(psycopg2.errors.DivisionByZero):
                service.check_out(parent)
        self.assertEqual(self.state(parent)[:2], ('checked_in', 'clean'))
        self.assertIsNone(self.state(parent)[3])

    def test_room_change_failure_rolls_back_all_updates(self):
        parent = self.parent()
        child = service.create_extension(parent, 2, self.today + timedelta(days=2), Decimal('180'))[0]
        with patch.object(queries, 'CHECK_IN', queries.CHECK_IN + '; SELECT 1/0'):
            with self.assertRaises(psycopg2.errors.DivisionByZero):
                service.activate_continuation(child)
        self.assertEqual(self.state(parent)[:2], ('checked_in', 'clean'))
        self.assertEqual(self.state(child)[:2], ('confirmed', 'clean'))
        self.assertIsNone(self.state(parent)[3])
        self.assertIsNone(self.state(child)[2])

    def race(self, operations):
        blocker = db.get_connection()
        observer = db.get_connection()
        observer.autocommit = True
        tag = 'hotel_integration_' + uuid4().hex
        try:
            with blocker.cursor() as cur:
                cur.execute('SELECT room_id FROM room WHERE room_id=1 FOR UPDATE')
            def attempt(operation):
                try:
                    return ('success', operation())
                except service.BookingError as exc:
                    return ('refused', str(exc))
            with patch.dict(os.environ, {'PGAPPNAME': tag}), ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(attempt, operation) for operation in operations]
                try:
                    deadline = time.monotonic() + 8
                    blocked = 0
                    while time.monotonic() < deadline:
                        with observer.cursor() as cur:
                            cur.execute("SELECT COUNT(*) FROM pg_stat_activity WHERE application_name=%s AND wait_event_type='Lock'", (tag,))
                            blocked = cur.fetchone()[0]
                        if blocked == 2:
                            break
                        time.sleep(0.05)
                finally:
                    blocker.rollback()
                results = [future.result(timeout=10) for future in futures]
            self.assertEqual(blocked, 2, 'Both independent service connections must demonstrably wait')
            self.assertEqual(sorted(result[0] for result in results), ['refused', 'success'])
        finally:
            blocker.rollback()
            blocker.close()
            observer.close()

    def test_concurrent_bookings_only_one_success(self):
        self.race([lambda: self.booking(), lambda: self.booking()])
        self.assertEqual(self.execute('SELECT COUNT(*) FROM reservation')[0][0], 1)

    def test_concurrent_extensions_only_one_successor(self):
        parent = self.parent()
        self.race([lambda: service.create_extension(parent, 2, self.today + timedelta(days=2), Decimal('180')),
                   lambda: service.create_extension(parent, 3, self.today + timedelta(days=2), Decimal('240'))])
        self.assertEqual(self.execute("SELECT COUNT(*) FROM reservation WHERE previous_reservation_id=%s AND status<>'cancelled'", (parent,))[0][0], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
