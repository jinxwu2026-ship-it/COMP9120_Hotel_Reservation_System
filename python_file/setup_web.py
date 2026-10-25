"""One-time local provisioning using the existing database owner connection."""
import json
import os
from pathlib import Path
import secrets

from psycopg2 import sql

import auth
import db

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
ROLE = 'hotel_app'
MARKER = 'COMP9120 local web application role'


def private_file(path, value):
    path.write_text(value, encoding='utf-8')
    os.chmod(path, 0o600)


def grant_app_access(cur, role):
    cur.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(
        sql.Identifier(db.SCHEMA),sql.Identifier(role)))
    for table in ['guest', 'room_type', 'room', 'reservation', 'reservation_guest', 'staff']:
        privileges = ['SELECT']
        if table in ['guest', 'reservation', 'reservation_guest', 'staff']:
            privileges.append('INSERT')
        if table in ['room', 'reservation', 'staff']:
            privileges.append('UPDATE')
        if table == 'reservation_guest':
            privileges.append('DELETE')
        cur.execute(sql.SQL('GRANT {} ON TABLE {} TO {}').format(sql.SQL(','.join(privileges)),
                    sql.Identifier(db.SCHEMA, table), sql.Identifier(role)))
        if 'INSERT' in privileges:
            cur.execute('SELECT pg_get_serial_sequence(%s,%s)', (db.SCHEMA+'.'+table, table+'_id'))
            sequence = cur.fetchone()[0]
            cur.execute(sql.SQL('GRANT USAGE ON SEQUENCE {} TO {}')
                        .format(sql.SQL(sequence), sql.Identifier(role)))
    cur.execute(sql.SQL('REVOKE ALL ON TABLE {} FROM {}').format(
        sql.Identifier(db.SCHEMA,'reservation_audit'),sql.Identifier(role)))
    cur.execute(sql.SQL('GRANT SELECT,INSERT ON TABLE {} TO {}').format(
        sql.Identifier(db.SCHEMA,'reservation_audit'),sql.Identifier(role)))
    cur.execute('SELECT pg_get_serial_sequence(%s,%s)',(db.SCHEMA+'.reservation_audit','audit_id'))
    cur.execute(sql.SQL('GRANT USAGE ON SEQUENCE {} TO {}').format(
        sql.SQL(cur.fetchone()[0]),sql.Identifier(role)))


def main():
    LOCAL.mkdir(exist_ok=True)
    migration = '\n'.join((ROOT / 'database' / filename).read_text(encoding='utf-8')
                          for filename in ['staff.sql','reservation_audit.sql'])
    migration = '\n'.join(line for line in migration.splitlines() if line.strip() not in ('BEGIN;', 'COMMIT;'))
    credentials = []
    app_password = secrets.token_urlsafe(32)
    with auth.cursor() as cur:
        cur.execute(migration)
        cur.execute('SELECT COUNT(*) FROM staff')
        if cur.fetchone()[0] == 0:
            for username, display, role in [('manager', 'Hotel Manager', 'manager'),
                                            ('reception', 'Front Desk', 'receptionist')]:
                password = secrets.token_urlsafe(18)
                auth.insert_staff(cur, username, display, password, role)
                credentials.append((username, password))
            # Save recoverable initial credentials before committing the first staff accounts.
            private_file(LOCAL / 'web_first_login.txt',
                'Local use only. Do not share or package this file. Change the temporary password on first sign-in.\n'
                + '\n'.join(f'{username}: {password}' for username, password in credentials)+'\n')
        cur.execute('SELECT shobj_description(oid,\'pg_authid\') FROM pg_roles WHERE rolname=%s', (ROLE,))
        existing = cur.fetchone()
        if existing and existing[0] != MARKER:
            raise RuntimeError('hotel_app already exists and is not this project role; refusing to modify it.')
        if not existing:
            cur.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE').format(sql.Identifier(ROLE)))
            cur.execute(sql.SQL('COMMENT ON ROLE {} IS %s').format(sql.Identifier(ROLE)), (MARKER,))
        cur.execute(sql.SQL('ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %s')
                    .format(sql.Identifier(ROLE)), (app_password,))
        cur.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(db.DATABASE), sql.Identifier(ROLE)))
        cur.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(db.SCHEMA), sql.Identifier(ROLE)))
        grant_app_access(cur, ROLE)
    passfile = LOCAL / 'pgpass_web.conf'
    def field(value):
        return str(value).replace('\\', '\\\\').replace(':', '\\:')
    private_file(passfile, ':'.join(map(field, [db.HOST, db.PORT, db.DATABASE, ROLE, app_password]))+'\n')
    private_file(LOCAL / 'web_database.json', json.dumps({
        'PGHOST': db.HOST, 'PGPORT': str(db.PORT), 'PGDATABASE': db.DATABASE,
        'PGUSER': ROLE, 'HOTEL_SCHEMA': db.SCHEMA, 'PGPASSFILE': str(passfile),
    }, indent=2)+'\n')
    key = LOCAL / 'web_session.key'
    if not key.exists():
        private_file(key, secrets.token_hex(32))
    if credentials:
        print('Created manager and reception accounts. Temporary passwords: .local/web_first_login.txt')
    else:
        print('Existing staff accounts preserved; no staff password was reset.')
    print('Staff and reservation history migrations applied. hotel_app connection saved privately; restart any running web server.')
    print('Start: python python_file/run_web.py')


if __name__ == '__main__':
    main()
