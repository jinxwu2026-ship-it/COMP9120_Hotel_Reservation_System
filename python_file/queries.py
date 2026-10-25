"""SQL interface for service.py; positional parameters follow SQL_queries requirement.txt.

Transactions and business validation belong to service.py. Reads never take write locks.
"""

GET_TODAY = """
SELECT (statement_timestamp() AT TIME ZONE 'Australia/Sydney')::date
"""

EVENT_TIME = """
SELECT clock_timestamp()
"""

LIST_TYPES = """
SELECT room_type_id, type_name, max_guests, base_nightly_rate
FROM room_type ORDER BY room_type_id
"""

LIST_ROOMS = """
SELECT rm.room_id, rm.room_number, rt.type_name, rt.max_guests,
       rt.base_nightly_rate, rm.is_bookable, rm.housekeeping_status
FROM room rm JOIN room_type rt USING (room_type_id) ORDER BY rm.room_id
"""

GET_ROOM = """
SELECT rm.room_id, rm.room_number, rm.room_type_id, rm.is_bookable,
       rm.housekeeping_status, rt.max_guests, rt.base_nightly_rate, rt.type_name
FROM room rm JOIN room_type rt USING (room_type_id) WHERE rm.room_id = %s
"""

# Lock only the physical room, not every joined room-type row.
LOCK_ROOM = GET_ROOM + " FOR UPDATE OF rm"

GET_RESERVATION = """
SELECT reservation_id, guest_id, room_id, check_in_date, check_out_date,
       guest_count, booked_nightly_rate, status, actual_check_in_at,
       actual_check_out_at, previous_reservation_id
FROM reservation WHERE reservation_id = %s
"""

LOCK_RESERVATION = GET_RESERVATION + " FOR UPDATE"

GET_RES_ROOM = """
SELECT room_id FROM reservation WHERE reservation_id = %s
"""

GET_GUEST = """
SELECT guest_id, name, email, phone FROM guest WHERE guest_id = %s
"""

INSERT_GUEST = """
INSERT INTO guest (name, email, phone) VALUES (%s, %s, %s) RETURNING guest_id
"""

FIND_ROOMS = """
SELECT rm.room_id, rm.room_number, rt.type_name, rt.max_guests,
       rt.base_nightly_rate, (%s::date - %s::date) * rt.base_nightly_rate AS total_quote
FROM room rm JOIN room_type rt USING (room_type_id)
WHERE rm.is_bookable AND rt.max_guests >= %s
  AND (%s::integer IS NULL OR rm.room_type_id = %s)
  AND NOT EXISTS (
      SELECT 1 FROM reservation r WHERE r.room_id = rm.room_id
        AND r.status IN ('confirmed', 'checked_in')
        AND r.check_in_date < %s AND r.check_out_date > %s)
ORDER BY rm.room_id
"""

HAS_DATE_CONFLICT = """
SELECT 1 FROM reservation WHERE room_id = %s
  AND status IN ('confirmed', 'checked_in')
  AND check_in_date < %s AND check_out_date > %s LIMIT 1
"""

HAS_OTHER_OCCUPANT = """
SELECT 1 FROM reservation WHERE room_id = %s AND status = 'checked_in'
  AND reservation_id IS DISTINCT FROM %s LIMIT 1
"""

COUNT_STAYING_GUESTS = """
SELECT COUNT(*) FROM reservation_guest WHERE reservation_id = %s
"""

LIST_STAYING_GUESTS = """
SELECT reservation_guest_id, reservation_id, full_name
FROM reservation_guest WHERE reservation_id = %s ORDER BY reservation_guest_id
"""

INSERT_STAYING_GUEST = """
INSERT INTO reservation_guest (reservation_id, full_name) VALUES (%s, %s)
RETURNING reservation_guest_id
"""

DELETE_STAYING_GUEST = """
DELETE FROM reservation_guest WHERE reservation_id = %s AND reservation_guest_id = %s
RETURNING reservation_guest_id
"""

INSERT_RESERVATION = """
INSERT INTO reservation
 (guest_id, room_id, check_in_date, check_out_date, guest_count,
  booked_nightly_rate, previous_reservation_id)
VALUES (%s, %s, %s, %s, %s, %s, %s)
RETURNING reservation_id, booked_nightly_rate,
          (check_out_date-check_in_date)*booked_nightly_rate AS total_amount
"""

PERSONAL_RESERVATIONS = """
SELECT r.reservation_id, rm.room_number, rt.type_name, r.check_in_date,
       r.check_out_date, r.guest_count, r.booked_nightly_rate,
       (r.check_out_date-r.check_in_date)*r.booked_nightly_rate AS total_amount,
       r.status, r.actual_check_in_at, r.actual_check_out_at, r.previous_reservation_id
FROM reservation r JOIN room rm USING (room_id) JOIN room_type rt USING (room_type_id)
WHERE r.guest_id = %s ORDER BY r.reservation_id
"""

SEARCH_RESERVATIONS = """
SELECT r.reservation_id, g.guest_id, g.name, g.phone, rm.room_id, rm.room_number,
       rt.type_name, r.check_in_date, r.check_out_date, r.guest_count,
       r.booked_nightly_rate, (r.check_out_date-r.check_in_date)*r.booked_nightly_rate,
       r.status, r.actual_check_in_at, r.actual_check_out_at, r.previous_reservation_id
FROM reservation r JOIN guest g USING (guest_id) JOIN room rm USING (room_id)
JOIN room_type rt USING (room_type_id)
WHERE %s = '' OR r.reservation_id::text = %s OR g.name = %s OR g.phone = %s
ORDER BY r.reservation_id
"""

CANCEL_RESERVATION = """
UPDATE reservation SET status = 'cancelled' WHERE reservation_id = %s
"""

CHECK_IN = """
UPDATE reservation SET status = 'checked_in', actual_check_in_at = %s
WHERE reservation_id = %s
"""

CHECK_OUT = """
UPDATE reservation SET status = 'checked_out', actual_check_out_at = %s
WHERE reservation_id = %s
"""

SET_HOUSEKEEPING = """
UPDATE room SET housekeeping_status = %s WHERE room_id = %s
"""

SET_ROOM_OPEN = """
UPDATE room SET is_bookable = %s WHERE room_id = %s
"""

HAS_ACTIVE_SUCCESSOR = """
SELECT 1 FROM reservation WHERE previous_reservation_id = %s AND status <> 'cancelled' LIMIT 1
"""

BOOKING_STATISTICS = """
SELECT rt.type_name, COUNT(r.reservation_id),
       COUNT(*) FILTER (WHERE r.status = 'cancelled'),
       COALESCE(SUM(CASE WHEN r.status <> 'cancelled'
           THEN (r.check_out_date-r.check_in_date)*r.booked_nightly_rate ELSE 0 END), 0)
FROM room_type rt LEFT JOIN room rm USING (room_type_id)
LEFT JOIN reservation r ON r.room_id = rm.room_id
GROUP BY rt.room_type_id, rt.type_name ORDER BY rt.room_type_id
"""
