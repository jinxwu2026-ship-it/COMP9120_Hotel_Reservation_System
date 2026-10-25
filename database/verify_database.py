"""Database SQL checks only, not Tianyi's service or Zirui's acceptance tests.

Uses the installed psql and standard library; no Python driver is required here.
SQL expressions below are fixed test fixtures, never user-input binding code.
"""
from pathlib import Path
import argparse
import json
import os
import re
import shutil
import subprocess
import time
from textwrap import indent
import queries

HERE = Path(__file__).resolve().parent
P = re.compile(r'%\((\w+)\)s')
CASES = [
    ('clock', 'GET_HOTEL_CLOCK', {}, '', lambda r: len(r) == 1 and r[0]['hotel_today']),
    ('new contact', 'ADD_GUEST', dict(name="'测试联系人'", email='NULL', phone="'00123'"), '', lambda r: len(r) == 1),
    ('room types', 'LIST_TYPES', {}, '', lambda r: len(r) == 3),
    ('rooms', 'LIST_ROOMS', {}, '', lambda r: len(r) == 6),
    ('availability and cancelled history', 'FIND_ROOMS', dict(check_in='CURRENT_DATE+2', check_out='CURRENT_DATE+3', guests='1', room_type_id='NULL'), '', lambda r: [x['room_id'] for x in r] == [3, 4]),
    ('invalid date availability', 'FIND_ROOMS', dict(check_in='CURRENT_DATE+2', check_out='CURRENT_DATE+2', guests='1', room_type_id='NULL'), '', lambda r: r == []),
    ('type and capacity filter', 'FIND_ROOMS', dict(check_in='CURRENT_DATE+2', check_out='CURRENT_DATE+3', guests='3', room_type_id='3'), '', lambda r: r == []),
    ('room lock order', 'LOCK_ROOMS', dict(room_ids='ARRAY[5,3,3]'), '', lambda r: [x['room_id'] for x in r] == [3, 5]),
    ('reservation lock order', 'LOCK_RESERVATIONS', dict(reservation_ids='ARRAY[1003,1001]'), '', lambda r: [x['reservation_id'] for x in r] == [1001, 1003]),
    ('room details', 'GET_ROOM', dict(room_id='3'), '', lambda r: len(r) == 1 and r[0]['room_number'] == '201'),
    ('reservation details', 'GET_RESERVATION', dict(reservation_id='1001'), '', lambda r: r[0]['status'] == 'checked_in'),
    ('overlap detection', 'ROOM_DATE_CONFLICTS', dict(room_id='3', check_in='CURRENT_DATE', check_out='CURRENT_DATE+1', exclude_reservation_id='NULL'), '', lambda r: [x['reservation_id'] for x in r] == [1001]),
    ('adjacent dates', 'ROOM_DATE_CONFLICTS', dict(room_id='3', check_in='CURRENT_DATE+1', check_out='CURRENT_DATE+2', exclude_reservation_id='NULL'), '', lambda r: r == []),
    ('physical occupant', 'CURRENT_OCCUPANTS', dict(room_id='1', exclude_reservation_id='NULL'), '', lambda r: [x['reservation_id'] for x in r] == [1013]),
    ('same-room predecessor exception', 'CURRENT_OCCUPANTS', dict(room_id='1', exclude_reservation_id='1013'), '', lambda r: r == []),
    ('insert and amount', 'INSERT_RESERVATION', dict(guest_id='1', room_id='2', check_in='CURRENT_DATE+20', check_out='CURRENT_DATE+22', guests='1', booked_nightly_rate='120.00', previous_reservation_id='NULL'), '', lambda r: len(r) == 1 and r[0]['total_amount'] == 240 and r[0]['status'] == 'confirmed'),
    ('all contact states', 'PERSONAL_RESERVATIONS', dict(guest_id='1'), '', lambda r: {x['reservation_id'] for x in r} == {1001, 1002, 1009, 1012}),
    ('cancellation', 'CANCEL_RESERVATION', dict(reservation_id='1003', guest_id='2'), '', lambda r: r[0]['status'] == 'cancelled'),
    ('wrong contact cancellation', 'CANCEL_RESERVATION', dict(reservation_id='1003', guest_id='1'), '', lambda r: r == []),
    ('same day cancellation refused', 'CANCEL_RESERVATION', dict(reservation_id='1014', guest_id='3'), '', lambda r: r == []),
    ('add occupant', 'ADD_STAYING_GUEST', dict(reservation_id='1004', full_name="'Alex'"), '', lambda r: len(r) == 1),
    ('frozen occupant additions', 'ADD_STAYING_GUEST', dict(reservation_id='1001', full_name="'Alex'"), '', lambda r: r == []),
    ('remove occupant', 'REMOVE_STAYING_GUEST', dict(reservation_id='1004', reservation_guest_id='-8001'), "INSERT INTO reservation_guest VALUES (-8001,1004,'Alex');", lambda r: len(r) == 1),
    ('list occupants', 'LIST_STAYING_GUESTS', dict(reservation_id='1001'), '', lambda r: [x['full_name'] for x in r] == ['Bob Chen', 'Carol Chen']),
    ('copy occupants without moving history', 'COPY_STAYING_GUESTS', dict(previous_reservation_id='1001', next_reservation_id='1002'), 'DELETE FROM reservation_guest WHERE reservation_id=1002;', lambda r: [x['full_name'] for x in r] == ['Bob Chen', 'Carol Chen']),
    ('copy already populated refused', 'COPY_STAYING_GUESTS', dict(previous_reservation_id='1001', next_reservation_id='1002'), '', lambda r: r == []),
    ('check-in update after prerequisites', 'MARK_CHECKED_IN', dict(reservation_id='1010', actual_at='CURRENT_TIMESTAMP'), "UPDATE reservation SET check_in_date=CURRENT_DATE WHERE reservation_id=1010; UPDATE room SET housekeeping_status='clean' WHERE room_id=2; INSERT INTO reservation_guest(reservation_id,full_name) VALUES(1010,'Daniel Lee');", lambda r: r[0]['status'] == 'checked_in'),
    ('checkout update', 'MARK_CHECKED_OUT', dict(reservation_id='1001', actual_at='CURRENT_TIMESTAMP'), '', lambda r: r[0]['status'] == 'checked_out' and r[0]['actual_check_out_at']),
    ('open flag independent', 'SET_ROOM_OPEN', dict(room_id='6', is_open='TRUE'), '', lambda r: r[0]['is_bookable'] is True),
    ('cleaning transition', 'SET_HOUSEKEEPING_STATUS', dict(room_id='2', new_status="'cleaning'"), '', lambda r: r[0]['housekeeping_status'] == 'cleaning'),
    ('occupied room cannot be dirtied', 'SET_HOUSEKEEPING_STATUS', dict(room_id='3', new_status="'dirty'"), '', lambda r: r == []),
    ('noncancelled successor', 'GET_SUCCESSORS', dict(reservation_id='1001'), '', lambda r: [x['reservation_id'] for x in r] == [1002]),
    ('extension already exists', 'EXTENSION_OPTIONS', dict(reservation_id='1001', new_check_out='CURRENT_DATE+3'), '', lambda r: r == []),
    ('extension option order', 'EXTENSION_OPTIONS', dict(reservation_id='1001', new_check_out='CURRENT_DATE+3'), "UPDATE reservation SET status='cancelled' WHERE reservation_id=1002;", lambda r: [(x['room_id'], x['preference']) for x in r] == [(3, 0), (4, 1), (5, 2)]),
    ('statistics not multiplied by occupant rows', 'BOOKING_STATISTICS', {}, '', lambda r: [(x['bookings'], x['cancelled'], x['booking_value']) for x in r] == [(6, 0, 1300), (4, 1, 1080), (4, 2, 940)]),
]


def bind_fixture(sql, params):
    assert set(P.findall(sql)) == set(params), 'Fixture parameter mismatch'
    return P.sub(lambda m: '(' + params[m[1]] + ')', sql).strip().rstrip(';')


def prepare(sql, params):
    keys = list(dict.fromkeys(P.findall(sql)))
    prepared = P.sub(lambda m: '$' + str(keys.index(m[1]) + 1), sql)
    return 'PREPARE example_query AS\n' + indent(example_sql(prepared.strip()), '  ') + ';\nEXECUTE example_query' + (
        '(' + ', '.join(example_sql(params[k]) for k in keys) + ')' if keys else '') + ';\nDEALLOCATE example_query;'


def example_sql(statement):
    parts = re.split(r"('(?:''|[^'])*')", statement)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r'[ \t]*(>=|<=|<>|=|>|<)[ \t]*', r' \1 ', parts[i])
        parts[i] = re.sub(r'\bCURRENT_DATE\s*([+-])\s*(\d+)', r'CURRENT_DATE \1 \2', parts[i])
        parts[i] = re.sub(r',[ \t]*(?=\S|$)', ', ', parts[i])
    return ''.join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', default='comp9120_hotel_test')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', default='55432')
    parser.add_argument('--user', default='hotel_owner')
    parser.add_argument('--psql', default=shutil.which('psql') or 'psql')
    parser.add_argument('--write-examples', action='store_true')
    args = parser.parse_args()
    if not args.database.endswith('_test'):
        parser.error('Only a dedicated database ending in _test is allowed')
    env = os.environ.copy()
    env['PGCLIENTENCODING'] = 'UTF8'
    local_password_file = HERE.parent / '.local' / 'pgpass.conf'
    if 'PGPASSFILE' not in env and local_password_file.exists():
        env['PGPASSFILE'] = str(local_password_file)
    command = [args.psql, '-X', '-w', '-v', 'ON_ERROR_STOP=1', '-qAt', '-h', args.host,
               '-p', args.port, '-U', args.user, '-d', args.database]

    def run(sql, app=None, timeout=20):
        this_env = dict(env, PGAPPNAME=app) if app else env
        result = subprocess.run(command, input=sql, capture_output=True, text=True,
                                encoding='utf-8', env=this_env, timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout.strip()

    evidence = HERE / 'evidence'
    evidence.mkdir(exist_ok=True)
    if run("SELECT (created_at AT TIME ZONE 'Australia/Sydney')::date = (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date FROM reservation WHERE reservation_id=1001;") != 't':
        raise RuntimeError('Use fixtures initialised today in a fresh isolated test database')
    template_names = {k for k, v in vars(queries).items() if k.isupper() and isinstance(v, str)}
    assert {case[1] for case in CASES} == template_names, 'Every SQL template needs a case'
    context = run("SELECT current_database(), version(), CURRENT_TIMESTAMP, current_setting('TimeZone');")
    log = [context]
    constraints = run((HERE / 'test_constraints.sql').read_text(encoding='utf-8'))
    log += ['\nCONSTRAINTS', constraints, '\nPARAMETERISED SQL TEMPLATES']
    examples = ['/* standalone SQL examples generated from queries.py; all changes are rolled back */',
                "DO $$\nBEGIN\n  IF RIGHT(current_database(), 5) <> '_test' THEN\n    RAISE EXCEPTION 'Use a dedicated _test database';\n  END IF;\nEND;\n$$;"]
    for label, name, params, setup, predicate in CASES:
        sql = getattr(queries, name)
        # EXECUTE validates actual server-side parameter inference as well as SQL syntax.
        example = f'\n/* {label}: {name} */\nBEGIN;\nSET LOCAL TIME ZONE \'Australia/Sydney\';\n{example_sql(setup)}\n{prepare(sql, params)}\nROLLBACK;\n'
        run(example)
        query = bind_fixture(sql, params)
        output = run(f"BEGIN; SET LOCAL TIME ZONE 'Australia/Sydney';\n{setup}\n"
                     f"WITH result AS ({query}) SELECT COALESCE(json_agg(result), '[]'::json) FROM result;\nROLLBACK;")
        rows = json.loads(output)
        if not predicate(rows):
            raise AssertionError(f'{label}: {rows}')
        log.append(f'PASS {label} [{name}]: {json.dumps(rows, ensure_ascii=False)}')
        examples.append(example)
    if args.write_examples:
        (HERE / 'sql_examples.sql').write_text('\n'.join(examples), encoding='utf-8')

    # SQL-level protocol test: both sessions must lock Room before checking its bookings.
    race_ids = '(-9001,-9002)'
    if run(f'SELECT COUNT(*) FROM reservation WHERE reservation_id IN {race_ids};') != '0':
        raise RuntimeError('Reserved race fixture IDs already exist; refusing cleanup of unknown data')
    def race_sql(identifier, delay):
        return f"""BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';
SET LOCAL lock_timeout='8s';
SELECT room_id FROM room WHERE room_id=2 FOR UPDATE;
SELECT pg_sleep({delay});
INSERT INTO reservation(reservation_id,guest_id,room_id,check_in_date,check_out_date,guest_count,booked_nightly_rate)
SELECT {identifier},1,2,CURRENT_DATE+30,CURRENT_DATE+32,1,120
WHERE NOT EXISTS(SELECT 1 FROM reservation WHERE room_id=2
  AND status IN ('confirmed','checked_in')
  AND check_in_date<CURRENT_DATE+32 AND check_out_date>CURRENT_DATE+30);
COMMIT;
"""
    first = None
    try:
        first = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                 env=dict(env, PGAPPNAME='hotel_db_race_A'))
        first.stdin.write(race_sql(-9001, 2))
        first.stdin.close()
        deadline = time.monotonic() + 6
        while run("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name='hotel_db_race_A' AND wait_event='PgSleep');") != 't':
            if first.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Race A did not reach its locked pause')
            time.sleep(0.1)
        started = time.monotonic()
        run(race_sql(-9002, 0), 'hotel_db_race_B')
        waited = time.monotonic() - started
        first.wait(timeout=10)
        error = first.stderr.read()
        if first.returncode:
            raise RuntimeError(error)
        count = run(f'SELECT COUNT(*) FROM reservation WHERE reservation_id IN {race_ids};')
        if count != '1' or waited < 0.5:
            raise AssertionError(f'Race result count={count}, wait={waited}')
        log += ['\nCONCURRENCY', f'PASS Room lock race: 2 independent connections, 1 booking; B waited {waited:.2f}s.']
    finally:
        if first is not None and first.poll() is None:
            first.kill()
            first.wait()
        run(f'DELETE FROM reservation WHERE reservation_id IN {race_ids};')

    # Inject a statement failure between checkout and dirty marking in one transaction.
    failed = subprocess.run(command, input="BEGIN; UPDATE reservation SET status='checked_out', actual_check_out_at=CURRENT_TIMESTAMP WHERE reservation_id=1001; SELECT 1/0; UPDATE room SET housekeeping_status='dirty' WHERE room_id=3; COMMIT;",
                            capture_output=True, text=True, encoding='utf-8', env=env, timeout=20)
    unchanged = run("SELECT r.status || ':' || rm.housekeeping_status FROM reservation r JOIN room rm USING(room_id) WHERE reservation_id=1001;")
    if failed.returncode == 0 or unchanged != 'checked_in:clean':
        raise AssertionError('Injected failure did not preserve both original states')
    log += ['\nROLLBACK', 'PASS injected division-by-zero: checkout and room state unchanged.',
            f'\nSUMMARY: 43 constraint/positive checks + 1 documented boundary; {len(CASES)} SQL cases; 1 two-connection race; 1 rollback case.',
            'Not tested: Python driver adaptation, service functions, menus, complete continuation transaction or service acceptance tests.']
    (evidence / 'database_validation.txt').write_text('\n'.join(log) + '\n', encoding='utf-8')
    print('\n'.join(log[-5:]))
    print('Evidence:', evidence / 'database_validation.txt')


if __name__ == '__main__':
    main()
