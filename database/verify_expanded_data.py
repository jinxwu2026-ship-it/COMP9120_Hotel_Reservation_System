"""Load and verify the larger demo in a disposable test schema, never the demo database."""
from datetime import timedelta
from pathlib import Path
import sys

import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_file'))
from test_integration import ServiceIntegrationTests as Fixture
import service

TABLES = ['guest', 'room_type', 'room', 'reservation', 'reservation_guest']
EXPECTED = [50, 8, 40, 200, 351]


def snapshot():
    return [Fixture.execute(f'SELECT * FROM {table} ORDER BY 1') for table in TABLES]


def load(name):
    source = (ROOT / 'database' / name).read_text(encoding='utf-8')
    # The shared helper owns commit/rollback; the complete file stays in one transaction.
    source = '\n'.join(line for line in source.splitlines()
                       if line.strip() not in ('BEGIN;', 'COMMIT;'))
    Fixture.execute(source)


def main():
    try:
        Fixture.setUpClass()
        load('seed.sql')
        original = snapshot()
        load('seed_more.sql')
        expanded = snapshot()
        assert [len(rows) for rows in expanded] == EXPECTED
        assert all(set(old).issubset(set(new)) for old, new in zip(original, expanded))
        checks = {
            'capacity': '''SELECT COUNT(*) FROM reservation r JOIN room rm USING(room_id)
                JOIN room_type t USING(room_type_id) WHERE r.guest_count > t.max_guests''',
            'active date overlaps': '''SELECT COUNT(*) FROM reservation a JOIN reservation b
                ON a.room_id=b.room_id AND a.reservation_id<b.reservation_id
                AND a.check_in_date<b.check_out_date AND a.check_out_date>b.check_in_date
                WHERE a.status IN ('confirmed','checked_in')
                AND b.status IN ('confirmed','checked_in')''',
            'historical planned overlaps': '''SELECT COUNT(*) FROM reservation a JOIN reservation b
                ON a.room_id=b.room_id AND a.reservation_id<b.reservation_id
                AND a.check_in_date<b.check_out_date AND a.check_out_date>b.check_in_date
                WHERE a.status<>'cancelled' AND b.status<>'cancelled' ''',
            'actual occupancy overlaps': '''SELECT COUNT(*) FROM reservation a JOIN reservation b
                ON a.room_id=b.room_id AND a.reservation_id<b.reservation_id
                AND a.actual_check_in_at<COALESCE(b.actual_check_out_at,'infinity'::timestamptz)
                AND b.actual_check_in_at<COALESCE(a.actual_check_out_at,'infinity'::timestamptz)
                WHERE a.actual_check_in_at IS NOT NULL AND b.actual_check_in_at IS NOT NULL''',
            'new roster completeness': '''SELECT COUNT(*) FROM reservation r
                WHERE r.reservation_id>=2001 AND r.guest_count<>(SELECT COUNT(*)
                FROM reservation_guest g WHERE g.reservation_id=r.reservation_id)''',
            'continuation boundary and contact': '''SELECT COUNT(*) FROM reservation child
                JOIN reservation parent ON child.previous_reservation_id=parent.reservation_id
                WHERE child.guest_id<>parent.guest_id OR child.check_in_date<>parent.check_out_date''',
            'historical handover time': '''SELECT COUNT(*) FROM reservation child
                JOIN reservation parent ON child.previous_reservation_id=parent.reservation_id
                WHERE child.reservation_id>=3001
                AND child.actual_check_in_at IS DISTINCT FROM parent.actual_check_out_at''',
            'occupied room ready': '''SELECT COUNT(*) FROM reservation r JOIN room rm USING(room_id)
                WHERE r.status='checked_in' AND (NOT rm.is_bookable OR rm.housekeeping_status<>'clean')''',
            'new actual times and creation order': '''SELECT COUNT(*) FROM reservation
                WHERE reservation_id>=2001 AND (actual_check_in_at>CURRENT_TIMESTAMP
                OR actual_check_out_at>CURRENT_TIMESTAMP OR created_at>actual_check_in_at)''',
            'all new contacts used': '''SELECT COUNT(*) FROM guest g WHERE guest_id>=5
                AND NOT EXISTS (SELECT 1 FROM reservation r WHERE r.guest_id=g.guest_id)''',
        }
        for label, statement in checks.items():
            assert Fixture.execute(statement)[0][0] == 0, label
            print('PASS:', label)
        try:
            load('seed_more.sql')
        except psycopg2.errors.UniqueViolation:
            pass
        else:
            raise AssertionError('Repeated append must reject duplicate IDs')
        assert snapshot() == expanded, 'Repeated import changed data'
        print('PASS: repeated import rejected and rolled back without row changes')
        assert len(service.list_types()) == 8 and len(service.list_rooms()) == 40
        assert len(service.search_reservations()) == 200
        today = Fixture.execute('SELECT CURRENT_DATE')[0][0]
        # Room 7 already has a confirmed reservation at D+30.
        try:
            service.create_reservation(5, 7, today + timedelta(days=30), today + timedelta(days=31), 1)
        except service.BookingError:
            pass
        else:
            raise AssertionError('Expanded data must reject overlapping booking through service')
        booking = service.create_reservation(5, 7, today + timedelta(days=80), today + timedelta(days=82), 1)[0]
        assert booking > 3022, 'Identity sequence was not advanced'
        service.cancel_reservation(5, booking)
        print('PASS: service lists, overlap rejection, generated ID, booking and cancellation')
        print('Totals before disposable service write:', dict(zip(TABLES, EXPECTED)))
        print('PASS: original rows preserved; only disposable test schema was modified')
    finally:
        Fixture.doClassCleanups()


if __name__ == '__main__':
    main()
