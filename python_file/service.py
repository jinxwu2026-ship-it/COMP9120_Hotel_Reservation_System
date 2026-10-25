from datetime import date
from decimal import Decimal, InvalidOperation
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
from psycopg2.extras import Json
from db import get_connection
import queries


class BookingError(Exception):
    pass


class StaleReservation(BookingError):
    pass


# ContextVar keeps individual identities separate across Waitress worker threads.
operation_actor = ContextVar('operation_actor', default=None)


@contextmanager
def staff_actor(staff_id, session_version):
    token = operation_actor.set(('staff', staff_id, session_version))
    try:
        yield
    finally:
        operation_actor.reset(token)


def _staff_identity(cur, required=False, manager=False):
    actor = operation_actor.get()
    if actor and actor[0] == 'public_booking' and not required and not manager:
        return None
    if actor is None or actor[0] != 'staff':
        if required or manager:
            raise BookingError('An authenticated staff session is required.')
        cur.execute('SELECT current_user')
        if cur.fetchone()[0] == 'hotel_app':
            raise BookingError('An authenticated staff session is required.')
        return None
    cur.execute('''SELECT staff_id, role FROM staff WHERE staff_id=%s
        AND session_version=%s AND is_active AND NOT must_change_password FOR SHARE''', actor[1:])
    person = cur.fetchone()
    if not person:
        raise BookingError('Your staff session has expired. Sign in again.')
    if manager and person[1] != 'manager':
        raise BookingError('Manager access is required to confirm a discounted rate.')
    return person


def _snapshot(cur, reservation_id):
    cur.execute('''SELECT to_jsonb(r) || jsonb_build_object('staying_guests',
        (SELECT COALESCE(jsonb_agg(to_jsonb(g) ORDER BY g.reservation_guest_id),'[]'::jsonb)
         FROM reservation_guest g WHERE g.reservation_id=r.reservation_id))
        FROM reservation r WHERE reservation_id=%s''', (reservation_id,))
    row = cur.fetchone()
    if row is None:
        raise BookingError('Reservation not found.')
    return row[0]


def _revision(snapshot):
    return sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _history(cur, reservation_id, action, before=None, reason='', details=None):
    identity = _staff_identity(cur)
    actor = operation_actor.get()
    source = 'staff' if identity else (actor[0] if actor else 'database')
    after = _snapshot(cur, reservation_id)
    if details:
        after['operation_details'] = details
    cur.execute('''INSERT INTO reservation_audit
        (reservation_id,staff_id,source,action,reason,before_data,after_data)
        VALUES(%s,%s,%s,%s,%s,%s,%s)''',
        (reservation_id, identity[0] if identity else None, source, action, reason,
         Json(before) if before is not None else None, Json(after)))


def reservation_history(reservation_id):
    rows = _read_rows('''SELECT a.audit_id,a.action,a.occurred_at,a.reason,a.source,
        s.username,s.display_name,a.before_data,a.after_data
        FROM reservation_audit a LEFT JOIN staff s USING(staff_id)
        WHERE a.reservation_id=%s ORDER BY a.audit_id DESC''', (reservation_id,))
    fields = ('audit_id','action','occurred_at','reason','source','username','display_name','before','after')
    return [dict(zip(fields, row)) for row in rows]


def _room(cur, room_id, lock=False):
    if lock == True:
        cur.execute(queries.LOCK_ROOM, (room_id,))
    else:
        cur.execute(queries.GET_ROOM, (room_id,))
    row = cur.fetchone()
    if row is None:
        raise BookingError('Room not found.')

    room = {}
    room['room_id'] = row[0]
    room['room_number'] = row[1]
    room['room_type_id'] = row[2]
    room['is_bookable'] = row[3]
    room['housekeeping_status'] = row[4]
    room['max_guests'] = row[5]
    room['base_nightly_rate'] = row[6]
    room['type_name'] = row[7]
    return room


def _reservation(cur, reservation_id, lock=False):
    if lock == True:
        cur.execute(queries.LOCK_RESERVATION, (reservation_id,))
    else:
        cur.execute(queries.GET_RESERVATION, (reservation_id,))
    row = cur.fetchone()
    if row is None:
        raise BookingError('Reservation not found.')

    reservation = {}
    reservation['reservation_id'] = row[0]
    reservation['guest_id'] = row[1]
    reservation['room_id'] = row[2]
    reservation['check_in_date'] = row[3]
    reservation['check_out_date'] = row[4]
    reservation['guest_count'] = row[5]
    reservation['booked_nightly_rate'] = row[6]
    reservation['status'] = row[7]
    reservation['actual_check_in_at'] = row[8]
    reservation['actual_check_out_at'] = row[9]
    reservation['previous_reservation_id'] = row[10]
    return reservation


def _today(cur):
    cur.execute(queries.GET_TODAY)
    return cur.fetchone()[0]


def _event_time(cur):
    cur.execute(queries.EVENT_TIME)
    return cur.fetchone()[0]


def _lock_reservation(cur, reservation_id):
    cur.execute(queries.GET_RES_ROOM, (reservation_id,))
    found = cur.fetchone()
    if not found:
        raise BookingError('Reservation not found.')
    room = _room(cur, found[0], lock=True)
    reservation = _reservation(cur, reservation_id, lock=True)
    if reservation['room_id'] != room['room_id']:
        raise BookingError('Reservation room changed; retry the operation.')
    return room, reservation


def _lock_rooms(cur, room_ids):
    unique_room_ids = []
    for room_id in room_ids:
        if room_id not in unique_room_ids:
            unique_room_ids.append(room_id)
    unique_room_ids.sort()

    # Lock rooms in ID order.
    rooms = {}
    for room_id in unique_room_ids:
        room = _room(cur, room_id, lock=True)
        rooms[room_id] = room
    return rooms


def _read_rows(statement, parameters=()):
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    try:
        cur.execute(statement, parameters)
        rows = []
        row = cur.fetchone()
        while row is not None:
            rows.append(row)
            row = cur.fetchone()
        conn.rollback()
        return rows
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _text(value, label):
    if not isinstance(value, str):
        raise BookingError(label + ' is required.')
    value = value.strip()
    if value == '':
        raise BookingError(label + ' is required.')
    return value


def validate_stay(check_in, check_out, guests, today):
    if type(check_in) is not date:
        raise BookingError('Dates must be date values.')
    if type(check_out) is not date:
        raise BookingError('Dates must be date values.')
    if check_in < today:
        raise BookingError('Check-in cannot be earlier than the hotel date.')
    if check_out <= check_in:
        raise BookingError('Check-out must be after check-in.')
    if type(guests) is not int:
        raise BookingError('Guest count must be a positive integer.')
    if guests <= 0:
        raise BookingError('Guest count must be a positive integer.')


def _check_capacity(room, guests):
    if guests > room['max_guests']:
        raise BookingError('Guest count exceeds this room type capacity.')


def _check_availability(cur, room_id, check_in, check_out):
    cur.execute(queries.HAS_DATE_CONFLICT, (room_id, check_out, check_in))
    if cur.fetchone():
        raise BookingError('This room has an overlapping confirmed or checked-in reservation.')


def _check_roster(cur, reservation, room):
    _check_capacity(room, reservation['guest_count'])
    cur.execute(queries.COUNT_STAYING_GUESTS, (reservation['reservation_id'],))
    if cur.fetchone()[0] != reservation['guest_count']:
        raise BookingError('The staying-guest list must match the reserved guest count.')


def _check_ready(cur, room, excluded_reservation_id):
    if not room['is_bookable']:
        raise BookingError('Room is closed for check-in.')
    if room['housekeeping_status'] != 'clean':
        raise BookingError('Room must be clean before check-in.')
    cur.execute(queries.HAS_OTHER_OCCUPANT, (room['room_id'], excluded_reservation_id))
    if cur.fetchone():
        raise BookingError('Another reservation is still checked in to this room.')


def _check_chain(cur, reservation_id, guest_id):
    seen = []
    current = reservation_id
    while current is not None:
        if current in seen:
            raise BookingError('Continuation history contains a cycle; manual review is needed.')
        seen.append(current)
        item = _reservation(cur, current)
        if item['guest_id'] != guest_id:
            raise BookingError('Continuation segments must have the same booking contact.')
        current = item['previous_reservation_id']


def list_types():
    return _read_rows(queries.LIST_TYPES)


def list_rooms():
    return _read_rows(queries.LIST_ROOMS)


def add_guest(name, email, phone):
    name, phone = _text(name, 'Name'), _text(phone, 'Phone')
    if isinstance(email, str):
        email = email.strip()
        if email == '':
            email = None
    else:
        email = None
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(queries.INSERT_GUEST, (name, email, phone))
        guest_id = cur.fetchone()[0]
        conn.commit()
        return guest_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def find_rooms(check_in, check_out, guests, room_type_id=None):
    if room_type_id is not None:
        if type(room_type_id) is not int:
            raise BookingError('Room type ID must be positive.')
        if room_type_id <= 0:
            raise BookingError('Room type ID must be positive.')
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    try:
        validate_stay(check_in, check_out, guests, _today(cur))
        cur.execute(queries.FIND_ROOMS, (check_out, check_in, guests, room_type_id,
                                   room_type_id, check_out, check_in))
        rows = []
        row = cur.fetchone()
        while row is not None:
            rows.append(row)
            row = cur.fetchone()
        conn.rollback()
        return rows
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def create_reservation(guest_id, room_id, check_in, check_out, guests,
                       discount_rate=None, reason='', quoted_base=None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        room = _room(cur, room_id, lock=True)
        validate_stay(check_in, check_out, guests, _today(cur))
        if not room['is_bookable']:
            raise BookingError('Room is closed for booking.')
        _check_capacity(room, guests)
        cur.execute(queries.GET_GUEST, (guest_id,))
        if cur.fetchone() is None:
            raise BookingError('Booking contact not found. Register the contact first.')
        # Recheck availability after locking.
        _check_availability(cur, room_id, check_in, check_out)
        cur.execute('SELECT base_nightly_rate FROM room_type WHERE room_type_id=%s',
                    (room['room_type_id'],))
        room['base_nightly_rate'] = cur.fetchone()[0]
        rate, discount_reason = _confirmed_rate(cur, room, quoted_base, discount_rate, reason)
        cur.execute(queries.INSERT_RESERVATION, (guest_id, room_id, check_in, check_out,
                                         guests, rate, None))
        result = cur.fetchone()
        _history(cur, result[0], 'create', reason=discount_reason,
                 details={'reference_rate': str(room['base_nightly_rate']), 'discounted': discount_rate is not None})
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def personal_reservations(guest_id):
    return _read_rows(queries.PERSONAL_RESERVATIONS, (guest_id,))


def search_reservations(keyword=''):
    if not isinstance(keyword, str):
        raise BookingError('Search text must be a string.')
    keyword = keyword.strip()
    return _read_rows(
        queries.SEARCH_RESERVATIONS, (keyword, keyword, keyword, keyword),
    )


def cancel_reservation(guest_id, reservation_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        room, reservation = _lock_reservation(cur, reservation_id)
        before = _snapshot(cur, reservation_id)
        if reservation['guest_id'] != guest_id:
            raise BookingError('This reservation belongs to a different booking contact.')
        if reservation['status'] != 'confirmed':
            raise BookingError('Only confirmed reservations can be cancelled.')
        if _today(cur) >= reservation['check_in_date']:
            raise BookingError('Cancellation is allowed only before the check-in date.')
        cur.execute(queries.CANCEL_RESERVATION, (reservation_id,))
        _history(cur, reservation_id, 'cancel', before)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def list_staying_guests(reservation_id):
    return _read_rows(queries.LIST_STAYING_GUESTS, (reservation_id,))


def add_staying_guest(reservation_id, full_name):
    full_name = _text(full_name, 'Full name')
    conn = get_connection()
    cur = conn.cursor()
    try:
        room, reservation = _lock_reservation(cur, reservation_id)
        before = _snapshot(cur, reservation_id)
        if reservation['status'] != 'confirmed':
            raise BookingError('Demo policy: the guest list is editable only before check-in.')
        cur.execute(queries.COUNT_STAYING_GUESTS, (reservation_id,))
        if cur.fetchone()[0] >= reservation['guest_count']:
            raise BookingError('The guest list already contains the reserved number of people.')
        _check_capacity(room, reservation['guest_count'])
        cur.execute(queries.INSERT_STAYING_GUEST, (reservation_id, full_name))
        registration_id = cur.fetchone()[0]
        _history(cur, reservation_id, 'add_guest', before)
        conn.commit()
        return registration_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def remove_staying_guest(reservation_id, reservation_guest_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        room, reservation = _lock_reservation(cur, reservation_id)
        before = _snapshot(cur, reservation_id)
        if reservation['status'] != 'confirmed':
            raise BookingError('Demo policy: the guest list is editable only before check-in.')
        cur.execute(queries.DELETE_STAYING_GUEST, (reservation_id, reservation_guest_id))
        if cur.fetchone() is None:
            raise BookingError('That registration does not belong to this reservation.')
        _history(cur, reservation_id, 'remove_guest', before)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def check_in(reservation_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        room, reservation = _lock_reservation(cur, reservation_id)
        before = _snapshot(cur, reservation_id)
        if reservation['previous_reservation_id'] is not None:
            raise BookingError('Use Activate continuation to start a continuation segment.')
        if reservation['status'] != 'confirmed':
            raise BookingError('Only confirmed reservations can check in.')
        # Check-in dates are unrestricted.
        _check_ready(cur, room, reservation_id)
        _check_roster(cur, reservation, room)
        cur.execute(queries.CHECK_IN, (_event_time(cur), reservation_id))
        _history(cur, reservation_id, 'check_in', before)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def check_out(reservation_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        room, reservation = _lock_reservation(cur, reservation_id)
        before = _snapshot(cur, reservation_id)
        if reservation['status'] != 'checked_in':
            raise BookingError('Only checked-in reservations can check out.')
        cur.execute(queries.HAS_ACTIVE_SUCCESSOR, (reservation_id,))
        if cur.fetchone():
            raise BookingError('Demo guard: activate the continuation, or resolve it under the cancellation rules, before ordinary checkout.')
        cur.execute(queries.CHECK_OUT, (_event_time(cur), reservation_id))
        cur.execute(queries.SET_HOUSEKEEPING, ('dirty', room['room_id']))
        _history(cur, reservation_id, 'check_out', before)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def set_room_open(room_id, is_open):
    if type(is_open) is not bool:
        raise BookingError('The open setting must be true or false.')
    conn = get_connection()
    cur = conn.cursor()
    try:
        _room(cur, room_id, lock=True)
        cur.execute(queries.SET_ROOM_OPEN, (is_open, room_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def set_housekeeping_status(room_id, new_status):
    if new_status not in ('clean', 'dirty', 'cleaning'):
        raise BookingError('Choose clean, dirty or cleaning.')
    conn = get_connection()
    cur = conn.cursor()
    try:
        room = _room(cur, room_id, lock=True)
        current = room['housekeeping_status']
        if new_status in ('dirty', 'cleaning'):
            cur.execute(queries.HAS_OTHER_OCCUPANT, (room_id, -1))
            if cur.fetchone():
                raise BookingError('An occupied room cannot be set to dirty or cleaning.')
        if new_status != current:
            if current == 'clean' and new_status != 'dirty':
                raise BookingError('Demo cleaning sequence: dirty -> cleaning -> clean.')
            if current == 'dirty' and new_status != 'cleaning':
                raise BookingError('Demo cleaning sequence: dirty -> cleaning -> clean.')
            if current == 'cleaning' and new_status != 'clean':
                raise BookingError('Demo cleaning sequence: dirty -> cleaning -> clean.')
        cur.execute(queries.SET_HOUSEKEEPING, (new_status, room_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def find_extension_options(reservation_id, new_check_out):
    conn = get_connection(read_only=True)
    cur = conn.cursor()
    try:
        previous = _reservation(cur, reservation_id)
        if previous['status'] != 'checked_in':
            raise BookingError('Extensions require a currently checked-in reservation.')
        old_room = _room(cur, previous['room_id'])
        arrival = previous['check_out_date']
        validate_stay(arrival, new_check_out, previous['guest_count'], _today(cur))
        cur.execute(queries.HAS_ACTIVE_SUCCESSOR, (reservation_id,))
        if cur.fetchone():
            raise BookingError('This stay already has a non-cancelled continuation.')
        cur.execute(queries.FIND_ROOMS, (new_check_out, arrival, previous['guest_count'],
                                   None, None, new_check_out, arrival))

        ranked_rooms = []
        rows = []
        row = cur.fetchone()
        while row is not None:
            rows.append(row)
            row = cur.fetchone()
        for row in rows:
            if row[0] == previous['room_id']:
                rank = 0
                preference = 'Original room'
            elif row[2] == old_room['type_name']:
                rank = 1
                preference = 'Same room type'
            else:
                rank = 2
                preference = 'Alternative room type'
            ranked_room = (rank, row[4], row[0], row, preference)
            ranked_rooms.append(ranked_room)
        ranked_rooms.sort()

        options = []
        for ranked_room in ranked_rooms:
            row = ranked_room[3]
            preference = ranked_room[4]
            option = (row[0], row[1], row[2], row[3], row[4], row[5], preference)
            options.append(option)
        conn.rollback()
        return options
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def create_extension(reservation_id, target_room_id, new_check_out, accepted_rate,
                     discount_rate=None, reason=''):
    try:
        rate_text = str(accepted_rate)
        accepted_rate = Decimal(rate_text)
    except (InvalidOperation, ValueError):
        raise BookingError('Accepted rate must be a valid decimal amount.')
    if not accepted_rate.is_finite():
        raise BookingError('Accepted rate must be finite and nonnegative.')
    if accepted_rate < 0:
        raise BookingError('Accepted rate must be finite and nonnegative.')
    conn = get_connection()
    cur = conn.cursor()
    try:
        initial = _reservation(cur, reservation_id)
        rooms = _lock_rooms(cur, (initial['room_id'], target_room_id))
        previous = _reservation(cur, reservation_id, lock=True)
        if previous['room_id'] != initial['room_id']:
            raise BookingError('Reservation room changed; retry the operation.')
        if previous['status'] != 'checked_in':
            raise BookingError('Extensions require a currently checked-in reservation.')
        _check_chain(cur, reservation_id, previous['guest_id'])
        cur.execute(queries.HAS_ACTIVE_SUCCESSOR, (reservation_id,))
        if cur.fetchone():
            raise BookingError('This stay already has a non-cancelled continuation.')
        room = rooms[target_room_id]
        arrival = previous['check_out_date']
        validate_stay(arrival, new_check_out, previous['guest_count'], _today(cur))
        if not room['is_bookable']:
            raise BookingError('Selected continuation room is closed for booking.')
        _check_capacity(room, previous['guest_count'])
        if accepted_rate != room['base_nightly_rate']:
            raise BookingError('The quote changed. Obtain a new quote and confirm again.')
        confirmed_rate, discount_reason = _confirmed_rate(cur,room,accepted_rate,discount_rate,reason)
        _check_availability(cur, target_room_id, arrival, new_check_out)
        cur.execute(queries.LIST_STAYING_GUESTS, (reservation_id,))
        names = []
        rows = []
        row = cur.fetchone()
        while row is not None:
            rows.append(row)
            row = cur.fetchone()
        for row in rows:
            names.append(row[2])
        if len(names) != previous['guest_count']:
            raise BookingError('The current staying-guest list is incomplete.')
        cur.execute(queries.INSERT_RESERVATION,
                    (previous['guest_id'], target_room_id, arrival, new_check_out,
                     previous['guest_count'], confirmed_rate, reservation_id))
        result = cur.fetchone()
        for full_name in names:
            cur.execute(queries.INSERT_STAYING_GUEST, (result[0], full_name))
        _history(cur, result[0], 'create_continuation',reason=discount_reason,
            details={'reference_rate':str(room['base_nightly_rate']),'discounted':discount_rate is not None})
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def activate_continuation(next_reservation_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        initial_next = _reservation(cur, next_reservation_id)
        previous_id = initial_next['previous_reservation_id']
        if previous_id is None or previous_id == next_reservation_id:
            raise BookingError('Choose a valid continuation reservation.')
        initial_previous = _reservation(cur, previous_id)
        rooms = _lock_rooms(cur, (initial_previous['room_id'], initial_next['room_id']))
        locked = {}
        reservation_ids = [previous_id, next_reservation_id]
        reservation_ids.sort()
        for reservation_id in reservation_ids:
            locked[reservation_id] = _reservation(cur, reservation_id, lock=True)
        previous = locked[previous_id]
        next_stay = locked[next_reservation_id]
        before_previous = _snapshot(cur, previous_id)
        before_next = _snapshot(cur, next_reservation_id)
        if previous['room_id'] != initial_previous['room_id'] or next_stay['room_id'] != initial_next['room_id']:
            raise BookingError('Reservation room changed; retry the operation.')
        if next_stay['previous_reservation_id'] != previous_id:
            raise BookingError('Continuation link changed; retry the operation.')
        if previous['status'] != 'checked_in' or next_stay['status'] != 'confirmed':
            raise BookingError('The previous stay must be checked in and the next segment confirmed.')
        if previous['guest_id'] != next_stay['guest_id'] or previous['check_out_date'] != next_stay['check_in_date']:
            raise BookingError('Continuation contact or planned boundary does not match.')
        _check_chain(cur, next_reservation_id, next_stay['guest_id'])
        today = _today(cur)
        if today < next_stay['check_in_date']:
            raise BookingError('Activate only within the next segment planned stay dates.')
        if today >= next_stay['check_out_date']:
            raise BookingError('Activate only within the next segment planned stay dates.')
        target = rooms[next_stay['room_id']]
        _check_ready(cur, target, previous_id)
        _check_roster(cur, next_stay, target)
        event = _event_time(cur)
        cur.execute(queries.CHECK_OUT, (event, previous_id))
        if previous['room_id'] != next_stay['room_id']:
            cur.execute(queries.SET_HOUSEKEEPING, ('dirty', previous['room_id']))
        cur.execute(queries.CHECK_IN, (event, next_reservation_id))
        _history(cur, previous_id, 'activate_continuation', before_previous)
        _history(cur, next_reservation_id, 'activate_continuation', before_next)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def booking_statistics():
    return _read_rows(queries.BOOKING_STATISTICS)


def _money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or not 0 <= result <= Decimal('99999999.99'):
            raise ValueError
        if result != result.quantize(Decimal('0.01')):
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise BookingError('Enter a nonnegative amount with at most two decimal places.')


def _confirmed_rate(cur, room, quoted_base, discount_rate, reason):
    base = room['base_nightly_rate']
    if quoted_base is not None and _money(quoted_base) != base:
        raise BookingError('The quote changed. Obtain a new quote and confirm again.')
    if discount_rate is None:
        return base, ''
    _staff_identity(cur, required=True, manager=True)
    reason = _text(reason, 'Discount reason')
    if len(reason) > 500:
        raise BookingError('The reason must contain at most 500 characters.')
    rate = _money(discount_rate)
    if rate > base:
        raise BookingError('A discounted nightly rate cannot exceed the current standard rate.')
    return rate, reason


def _modifiable(cur, reservation):
    if reservation['status'] != 'confirmed' or reservation['check_in_date'] <= _today(cur):
        raise BookingError('Modify only confirmed reservations before their original arrival date.')
    cur.execute('SELECT 1 FROM reservation WHERE previous_reservation_id=%s LIMIT 1',
                (reservation['reservation_id'],))
    if reservation['previous_reservation_id'] is not None or cur.fetchone():
        raise BookingError('Reservations with continuation history cannot use this modification form.')


def amendment_options(reservation_id, check_in, check_out, room_type_id=None):
    conn = get_connection(read_only=True)
    try:
        conn.set_session(isolation_level='REPEATABLE READ',readonly=True)
        with conn.cursor() as cur:
            original = _reservation(cur, reservation_id)
            _modifiable(cur, original)
            validate_stay(check_in, check_out, original['guest_count'], _today(cur))
            cur.execute('''SELECT rm.room_id,rm.room_number,rt.type_name,rt.max_guests,
                rt.base_nightly_rate,(%s::date-%s::date)*rt.base_nightly_rate
                FROM room rm JOIN room_type rt USING(room_type_id)
                WHERE rm.is_bookable AND rt.max_guests >= %s
                  AND (%s::integer IS NULL OR rm.room_type_id=%s)
                  AND NOT EXISTS (SELECT 1 FROM reservation r WHERE r.room_id=rm.room_id
                    AND r.reservation_id<>%s AND r.status IN ('confirmed','checked_in')
                    AND r.check_in_date<%s AND r.check_out_date>%s)
                ORDER BY rm.room_id''', (check_out,check_in,original['guest_count'],room_type_id,
                    room_type_id,reservation_id,check_out,check_in))
            options = cur.fetchall()
            snapshot = _snapshot(cur, reservation_id)
            return options, _revision(snapshot)
    finally:
        conn.rollback()
        conn.close()


def amend_reservation(reservation_id, target_room_id, check_in, check_out,
                      expected_revision, quoted_base, reason, discount_rate=None):
    if quoted_base is None:
        raise BookingError('Obtain a new room quote before confirming the modification.')
    reason = _text(reason, 'Modification reason')
    if len(reason) > 500:
        raise BookingError('The reason must contain at most 500 characters.')
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                initial = _reservation(cur, reservation_id)
                rooms = _lock_rooms(cur, (initial['room_id'],target_room_id))
                original = _reservation(cur, reservation_id, lock=True)
                if original['room_id'] != initial['room_id']:
                    raise StaleReservation('The reservation changed. Reload it before modifying.')
                _staff_identity(cur, required=True)
                before = _snapshot(cur, reservation_id)
                if not expected_revision or expected_revision != _revision(before):
                    raise StaleReservation('The reservation or guest list changed. Reload and obtain a new quote.')
                _modifiable(cur, original)
                validate_stay(check_in,check_out,original['guest_count'],_today(cur))
                target = rooms[target_room_id]
                if not target['is_bookable']:
                    raise BookingError('The selected room is closed for booking.')
                _check_capacity(target, original['guest_count'])
                cur.execute('''SELECT 1 FROM reservation WHERE room_id=%s AND reservation_id<>%s
                    AND status IN ('confirmed','checked_in') AND check_in_date<%s AND check_out_date>%s LIMIT 1''',
                    (target_room_id,reservation_id,check_out,check_in))
                if cur.fetchone():
                    raise BookingError('The selected room has an overlapping reservation.')
                cur.execute('SELECT base_nightly_rate FROM room_type WHERE room_type_id=%s',
                            (target['room_type_id'],))
                target['base_nightly_rate'] = cur.fetchone()[0]
                rate, _ = _confirmed_rate(cur,target,quoted_base,discount_rate,reason)
                changed_stay = (target_room_id,check_in,check_out) != (
                    original['room_id'],original['check_in_date'],original['check_out_date'])
                if not changed_stay and discount_rate is None:
                    return reservation_id  # An unchanged form preserves the agreed rate, including an existing discount.
                if not changed_stay and rate == original['booked_nightly_rate']:
                    return reservation_id
                cur.execute('''UPDATE reservation SET room_id=%s,check_in_date=%s,check_out_date=%s,
                    booked_nightly_rate=%s WHERE reservation_id=%s''',
                    (target_room_id,check_in,check_out,rate,reservation_id))
                _history(cur,reservation_id,'amend' if changed_stay else 'discount',before,reason,
                    {'reference_rate':str(target['base_nightly_rate']),'discounted':discount_rate is not None})
                return reservation_id
    finally:
        conn.close()


def create_reservations(guest_id, check_in, check_out, selections):
    """One contact and date interval; all selected rooms commit or roll back together."""
    if not isinstance(selections,list) or not selections:
        raise BookingError('Select at least one room.')
    room_ids = []
    for item in selections:
        if not isinstance(item,dict) or type(item.get('room_id')) is not int or item['room_id'] <= 0:
            raise BookingError('Select valid room IDs.')
        room_ids.append(item['room_id'])
    if len(set(room_ids)) != len(room_ids):
        raise BookingError('Choose each room only once.')
    conn = get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                rooms = _lock_rooms(cur,room_ids)
                _staff_identity(cur,required=True)
                cur.execute(queries.GET_GUEST,(guest_id,))
                if cur.fetchone() is None:
                    raise BookingError('Booking contact not found.')
                cur.execute('''SELECT room_type_id,base_nightly_rate FROM room_type
                    WHERE room_type_id=ANY(%s) ORDER BY room_type_id''',
                    (sorted({room['room_type_id'] for room in rooms.values()}),))
                prices = dict(cur.fetchall())
                confirmed = []
                for item in selections:
                    room = rooms[item['room_id']]
                    room['base_nightly_rate'] = prices[room['room_type_id']]
                    validate_stay(check_in,check_out,item.get('guests'),_today(cur))
                    _check_capacity(room,item['guests'])
                    if not room['is_bookable']:
                        raise BookingError('One of the selected rooms is closed for booking.')
                    _check_availability(cur,room['room_id'],check_in,check_out)
                    if item.get('quoted_base') is None:
                        raise BookingError('Obtain a quote for every selected room.')
                    rate, reason = _confirmed_rate(cur,room,item['quoted_base'],item.get('discount_rate'),item.get('reason',''))
                    confirmed.append((room,item['guests'],rate,reason,item.get('discount_rate') is not None))
                results = []
                for room, guests, rate, reason, discounted in confirmed:
                    cur.execute(queries.INSERT_RESERVATION,(guest_id,room['room_id'],check_in,check_out,guests,rate,None))
                    result = cur.fetchone()
                    _history(cur,result[0],'create',reason=reason,
                        details={'reference_rate':str(room['base_nightly_rate']),'discounted':discounted,'multi_room_submission':True})
                    results.append(result)
                return results
    finally:
        conn.close()


def create_public_reservation(name, email, phone, room_id, check_in, check_out, guests, quoted_base):
    """An unverified booking contact, one standard-rate reservation and its event commit together."""
    name, phone = _text(name,'Name'), _text(phone,'Phone')
    email = email.strip() if isinstance(email,str) else ''
    if len(name)>120 or len(phone)>60 or len(email)>254:
        raise BookingError('Contact details are too long.')
    if quoted_base is None:
        raise BookingError('Obtain a room quote before booking.')
    token = operation_actor.set(('public_booking',None,None))
    conn = None
    try:
        conn = get_connection()
        with conn:
            with conn.cursor() as cur:
                room = _room(cur,room_id,lock=True)
                validate_stay(check_in,check_out,guests,_today(cur))
                if not room['is_bookable']:
                    raise BookingError('This room is closed for booking.')
                _check_capacity(room,guests)
                _check_availability(cur,room_id,check_in,check_out)
                cur.execute('SELECT base_nightly_rate FROM room_type WHERE room_type_id=%s',
                            (room['room_type_id'],))
                room['base_nightly_rate']=cur.fetchone()[0]
                rate,_ = _confirmed_rate(cur,room,quoted_base,None,'')
                cur.execute(queries.INSERT_GUEST,(name,email or None,phone))
                contact = cur.fetchone()[0]
                cur.execute(queries.INSERT_RESERVATION,(contact,room_id,check_in,check_out,guests,rate,None))
                result = cur.fetchone()
                _history(cur,result[0],'create',details={'reference_rate':str(rate),'discounted':False})
                return result
    finally:
        if conn is not None:conn.close()
        operation_actor.reset(token)
