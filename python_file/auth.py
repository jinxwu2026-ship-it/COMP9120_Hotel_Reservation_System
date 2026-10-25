"""Individual staff identities shared by the web and CLI adapters."""
from contextlib import contextmanager
import re
import secrets

from werkzeug.security import check_password_hash, generate_password_hash

import db
from service import BookingError

FIELDS = 'staff_id, username, display_name, role, is_active, must_change_password, session_version'
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(24), method='scrypt')


class AuthError(BookingError):
    pass


@contextmanager
def cursor():
    conn = db.get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                yield cur
    finally:
        conn.close()


def person(row):
    return dict(zip([name.strip() for name in FIELDS.split(',')], row))


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise AuthError('Passwords must contain 12–128 characters.')
    return generate_password_hash(password, method='scrypt')


def require_staff(staff_id, version, manager=False, allow_password_change=False):
    with cursor() as cur:
        cur.execute(f'SELECT {FIELDS} FROM staff WHERE staff_id=%s', (staff_id,))
        row = cur.fetchone()
    if not row or not row[4] or row[6] != version:
        raise AuthError('Your session has expired. Please sign in again.')
    staff = person(row)
    if manager and staff['role'] != 'manager':
        raise AuthError('Manager access is required for this action.')
    if staff['must_change_password'] and not allow_password_change:
        raise AuthError('Please change your temporary password first.')
    return staff


def authenticate(username, password):
    username = username.strip().lower() if isinstance(username, str) else ''
    if not isinstance(password, str) or len(password) > 128 or len(username) > 40:
        raise AuthError('Invalid username or password, or the account is temporarily unavailable.')
    with cursor() as cur:
        cur.execute(f'''SELECT {FIELDS}, password_hash,
            locked_until IS NOT NULL AND locked_until>CURRENT_TIMESTAMP
            FROM staff WHERE username=%s FOR UPDATE''', (username,))
        row = cur.fetchone()
        usable = row and row[4] and not row[8]
        valid = check_password_hash(row[7] if usable else DUMMY_HASH, password)
        if usable and valid:
            cur.execute('UPDATE staff SET failed_attempts=0, locked_until=NULL WHERE staff_id=%s', (row[0],))
            return person(row[:7])
        if row and row[4] and not row[8]:
            cur.execute('''UPDATE staff SET
                locked_until=CASE WHEN failed_attempts+1>=5
                    THEN CURRENT_TIMESTAMP+INTERVAL '10 minutes' ELSE NULL END,
                failed_attempts=CASE WHEN failed_attempts+1>=5 THEN 0 ELSE failed_attempts+1 END
                WHERE staff_id=%s''', (row[0],))
    raise AuthError('Invalid username or password, or the account is temporarily unavailable.')


def insert_staff(cur, username, display_name, password, role):
    username = username.strip().lower()
    display_name = display_name.strip()
    if not re.fullmatch(r'[a-z0-9_.-]{3,40}', username):
        raise AuthError('Usernames must contain 3–40 lowercase letters, digits, dots, underscores or hyphens.')
    if not display_name or len(display_name) > 80 or role not in ('receptionist', 'manager'):
        raise AuthError('Enter a display name and select a valid role.')
    hashed = password_hash(password)
    cur.execute('''INSERT INTO staff(username,display_name,password_hash,role)
        VALUES(%s,%s,%s,%s) RETURNING staff_id''', (username, display_name, hashed, role))
    return cur.fetchone()[0]


def list_staff(actor_id, version):
    require_staff(actor_id, version, manager=True)
    with cursor() as cur:
        cur.execute(f'SELECT {FIELDS} FROM staff ORDER BY staff_id')
        return [person(row) for row in cur.fetchall()]


def create_staff(actor_id, version, username, display_name, password, role):
    require_staff(actor_id, version, manager=True)
    with cursor() as cur:
        return insert_staff(cur, username, display_name, password, role)


def set_active(actor_id, version, target_id, active):
    if type(active) is not bool:
        raise AuthError('Invalid staff account status.')
    with cursor() as cur:
        # Serialize manager-count checks so two concurrent disables cannot remove the last manager.
        cur.execute('LOCK TABLE staff IN SHARE ROW EXCLUSIVE MODE')
        require_staff(actor_id, version, manager=True)
        cur.execute('SELECT role,is_active FROM staff WHERE staff_id=%s', (target_id,))
        target = cur.fetchone()
        if not target:
            raise AuthError('Staff account not found.')
        if not active and target == ('manager', True):
            cur.execute("SELECT COUNT(*) FROM staff WHERE role='manager' AND is_active")
            if cur.fetchone()[0] <= 1:
                raise AuthError('The last active manager cannot be disabled.')
        cur.execute('''UPDATE staff SET is_active=%s,session_version=session_version+1,
            failed_attempts=0,locked_until=NULL WHERE staff_id=%s''', (active, target_id))


def reset_password(actor_id, version, target_id, password):
    require_staff(actor_id, version, manager=True)
    if actor_id == target_id:
        raise AuthError('Use your personal password page to change your own password.')
    hashed = password_hash(password)
    with cursor() as cur:
        cur.execute('''UPDATE staff SET password_hash=%s,must_change_password=TRUE,
            session_version=session_version+1,failed_attempts=0,locked_until=NULL
            WHERE staff_id=%s RETURNING staff_id''', (hashed, target_id))
        if not cur.fetchone():
            raise AuthError('Staff account not found.')


def change_password(staff_id, version, old_password, new_password):
    hashed = password_hash(new_password)
    if old_password == new_password:
        raise AuthError('Your new password must differ from your current password.')
    with cursor() as cur:
        cur.execute(f'SELECT {FIELDS},password_hash FROM staff WHERE staff_id=%s FOR UPDATE', (staff_id,))
        row = cur.fetchone()
        if not row or not row[4] or row[6] != version:
            raise AuthError('Your session has expired. Please sign in again.')
        if not isinstance(old_password, str) or len(old_password) > 128 or not check_password_hash(row[7], old_password):
            raise AuthError('The current password is incorrect.')
        cur.execute('''UPDATE staff SET password_hash=%s,must_change_password=FALSE,
            session_version=session_version+1 WHERE staff_id=%s RETURNING session_version''', (hashed, staff_id))
        return cur.fetchone()[0]


def logout(staff_id, version):
    with cursor() as cur:
        cur.execute('''UPDATE staff SET session_version=session_version+1
            WHERE staff_id=%s AND session_version=%s''', (staff_id, version))
