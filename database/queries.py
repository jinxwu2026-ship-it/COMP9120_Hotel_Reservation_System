"""Jinxing's SQL only. Named psycopg parameters; transaction/validation contract in SQL_CONTRACT.md.

No connection, input handling, commit or rollback belongs here. Lists are ordered;
conditional writes return zero rows on refusal. Each RETURNING list defines tuple order.
"""

GET_HOTEL_CLOCK = """
SELECT CURRENT_TIMESTAMP AS hotel_now,
       (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date AS hotel_today
"""

ADD_GUEST = """
INSERT INTO guest (name, email, phone) VALUES (%(name)s, %(email)s, %(phone)s)
RETURNING guest_id
"""

LIST_TYPES = """
SELECT room_type_id, type_name, max_guests, base_nightly_rate
FROM room_type ORDER BY room_type_id
"""

LIST_ROOMS = """
SELECT rm.room_id, rm.room_number, rt.room_type_id, rt.type_name,
       rt.max_guests, rt.base_nightly_rate, rm.is_bookable, rm.housekeeping_status
FROM room rm JOIN room_type rt USING (room_type_id) ORDER BY rm.room_id
"""

FIND_ROOMS = """
SELECT rm.room_id, rm.room_number, rt.room_type_id, rt.type_name,
       rt.max_guests, rt.base_nightly_rate
FROM room rm JOIN room_type rt USING (room_type_id)
WHERE rm.is_bookable AND rt.max_guests >= %(guests)s AND %(guests)s > 0
  AND %(check_out)s::date > %(check_in)s::date
  AND %(check_in)s::date >= (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date
  AND (%(room_type_id)s::integer IS NULL OR rt.room_type_id = %(room_type_id)s)
  AND NOT EXISTS (
    SELECT 1 FROM reservation r WHERE r.room_id = rm.room_id
      AND r.status IN ('confirmed', 'checked_in')
      AND r.check_in_date < %(check_out)s AND r.check_out_date > %(check_in)s)
ORDER BY rt.base_nightly_rate, rm.room_number
"""

LOCK_ROOMS = """
SELECT room_id FROM room WHERE room_id = ANY(%(room_ids)s::integer[])
ORDER BY room_id FOR UPDATE
"""

LOCK_RESERVATIONS = """
SELECT reservation_id FROM reservation
WHERE reservation_id = ANY(%(reservation_ids)s::integer[])
ORDER BY reservation_id FOR UPDATE
"""

GET_ROOM = """
SELECT rm.room_id, rm.room_number, rt.room_type_id, rt.type_name,
       rt.max_guests, rt.base_nightly_rate, rm.is_bookable, rm.housekeeping_status
FROM room rm JOIN room_type rt USING (room_type_id) WHERE rm.room_id = %(room_id)s
"""

GET_RESERVATION = """
SELECT reservation_id, guest_id, room_id, check_in_date, check_out_date,
       guest_count, booked_nightly_rate, created_at, status,
       actual_check_in_at, actual_check_out_at, previous_reservation_id
FROM reservation WHERE reservation_id = %(reservation_id)s
"""

ROOM_DATE_CONFLICTS = """
SELECT reservation_id, check_in_date, check_out_date, status FROM reservation
WHERE room_id = %(room_id)s AND status IN ('confirmed', 'checked_in')
  AND reservation_id IS DISTINCT FROM %(exclude_reservation_id)s::integer
  AND check_in_date < %(check_out)s AND check_out_date > %(check_in)s
ORDER BY reservation_id
"""

CURRENT_OCCUPANTS = """
SELECT reservation_id FROM reservation WHERE room_id = %(room_id)s
  AND status = 'checked_in'
  AND reservation_id IS DISTINCT FROM %(exclude_reservation_id)s::integer
ORDER BY reservation_id
"""

INSERT_RESERVATION = """
INSERT INTO reservation
 (guest_id, room_id, check_in_date, check_out_date, guest_count,
  booked_nightly_rate, previous_reservation_id)
VALUES (%(guest_id)s, %(room_id)s, %(check_in)s, %(check_out)s, %(guests)s,
        %(booked_nightly_rate)s, %(previous_reservation_id)s)
RETURNING reservation_id, booked_nightly_rate,
          (check_out_date-check_in_date)*booked_nightly_rate AS total_amount, status
"""

PERSONAL_RESERVATIONS = """
SELECT r.reservation_id, rm.room_number, rt.type_name, r.check_in_date,
       r.check_out_date, r.guest_count, r.booked_nightly_rate,
       (r.check_out_date-r.check_in_date)*r.booked_nightly_rate AS total_amount,
       r.status, r.actual_check_in_at, r.actual_check_out_at, r.previous_reservation_id
FROM reservation r JOIN room rm USING (room_id) JOIN room_type rt USING (room_type_id)
WHERE r.guest_id = %(guest_id)s ORDER BY r.created_at DESC, r.reservation_id DESC
"""

CANCEL_RESERVATION = """
UPDATE reservation SET status = 'cancelled'
WHERE reservation_id = %(reservation_id)s AND guest_id = %(guest_id)s
  AND status = 'confirmed'
  AND check_in_date > (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date
RETURNING reservation_id, status
"""

ADD_STAYING_GUEST = """
INSERT INTO reservation_guest (reservation_id, full_name)
SELECT reservation_id, %(full_name)s FROM reservation
WHERE reservation_id = %(reservation_id)s AND status = 'confirmed'
RETURNING reservation_guest_id
"""

REMOVE_STAYING_GUEST = """
DELETE FROM reservation_guest rg USING reservation r
WHERE rg.reservation_guest_id = %(reservation_guest_id)s
  AND rg.reservation_id = %(reservation_id)s AND r.reservation_id = rg.reservation_id
  AND r.status = 'confirmed'
RETURNING rg.reservation_guest_id
"""

LIST_STAYING_GUESTS = """
SELECT reservation_guest_id, full_name FROM reservation_guest
WHERE reservation_id = %(reservation_id)s ORDER BY reservation_guest_id
"""

COPY_STAYING_GUESTS = """
INSERT INTO reservation_guest (reservation_id, full_name)
SELECT %(next_reservation_id)s, rg.full_name
FROM reservation_guest rg JOIN reservation n ON n.reservation_id = %(next_reservation_id)s
WHERE rg.reservation_id = %(previous_reservation_id)s AND n.status = 'confirmed'
  AND n.previous_reservation_id = rg.reservation_id
  AND NOT EXISTS (SELECT 1 FROM reservation_guest WHERE reservation_id = n.reservation_id)
ORDER BY rg.reservation_guest_id
RETURNING reservation_guest_id, full_name
"""

MARK_CHECKED_IN = """
UPDATE reservation SET status = 'checked_in', actual_check_in_at = %(actual_at)s
WHERE reservation_id = %(reservation_id)s AND status = 'confirmed'
RETURNING reservation_id, status, actual_check_in_at
"""

MARK_CHECKED_OUT = """
UPDATE reservation SET status = 'checked_out', actual_check_out_at = %(actual_at)s
WHERE reservation_id = %(reservation_id)s AND status = 'checked_in'
RETURNING reservation_id, status, actual_check_out_at
"""

SET_ROOM_OPEN = """
UPDATE room SET is_bookable = %(is_open)s WHERE room_id = %(room_id)s
RETURNING room_id, is_bookable
"""

SET_HOUSEKEEPING_STATUS = """
UPDATE room SET housekeeping_status = %(new_status)s
WHERE room_id = %(room_id)s AND NOT EXISTS (
    SELECT 1 FROM reservation r WHERE r.room_id = room.room_id AND r.status = 'checked_in')
RETURNING room_id, housekeeping_status
"""

GET_SUCCESSORS = """
SELECT reservation_id, room_id, check_in_date, check_out_date, status
FROM reservation WHERE previous_reservation_id = %(reservation_id)s
  AND status <> 'cancelled' ORDER BY reservation_id
"""

EXTENSION_OPTIONS = """
WITH parent AS (
    SELECT r.room_id, rm.room_type_id, r.check_out_date, r.guest_count
    FROM reservation r JOIN room rm USING (room_id)
    WHERE r.reservation_id = %(reservation_id)s AND r.status = 'checked_in'
      AND %(new_check_out)s::date > r.check_out_date
      AND r.check_out_date >= (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date
      AND NOT EXISTS (SELECT 1 FROM reservation s
        WHERE s.previous_reservation_id = r.reservation_id AND s.status <> 'cancelled')
)
SELECT rm.room_id, rm.room_number, rt.room_type_id, rt.type_name,
       rt.base_nightly_rate, p.check_out_date AS check_in_date,
       %(new_check_out)s::date AS check_out_date, p.guest_count,
       CASE WHEN rm.room_id = p.room_id THEN 0
            WHEN rt.room_type_id = p.room_type_id THEN 1 ELSE 2 END AS preference
FROM parent p CROSS JOIN room rm JOIN room_type rt ON rt.room_type_id = rm.room_type_id
WHERE rm.is_bookable AND rt.max_guests >= p.guest_count
  AND NOT EXISTS (SELECT 1 FROM reservation r WHERE r.room_id = rm.room_id
    AND r.status IN ('confirmed', 'checked_in')
    AND r.check_in_date < %(new_check_out)s AND r.check_out_date > p.check_out_date)
ORDER BY preference, rt.base_nightly_rate, rm.room_number
"""

BOOKING_STATISTICS = """
SELECT rt.room_type_id, rt.type_name, COUNT(r.reservation_id) AS bookings,
       COUNT(*) FILTER (WHERE r.status = 'cancelled') AS cancelled,
       COALESCE(SUM(CASE WHEN r.status <> 'cancelled'
           THEN (r.check_out_date-r.check_in_date)*r.booked_nightly_rate ELSE 0 END), 0)
           AS booking_value
FROM room_type rt LEFT JOIN room rm USING (room_type_id)
LEFT JOIN reservation r ON r.room_id = rm.room_id
GROUP BY rt.room_type_id, rt.type_name ORDER BY rt.room_type_id
"""
