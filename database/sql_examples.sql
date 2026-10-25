/* standalone SQL examples generated from queries.py; all changes are rolled back */
DO $$
BEGIN
  IF RIGHT(current_database(), 5) <> '_test' THEN
    RAISE EXCEPTION 'Use a dedicated _test database';
  END IF;
END;
$$;

/* clock: GET_HOTEL_CLOCK */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT CURRENT_TIMESTAMP AS hotel_now,
         (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date AS hotel_today;
EXECUTE example_query;
DEALLOCATE example_query;
ROLLBACK;


/* new contact: ADD_GUEST */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  INSERT INTO guest (name, email, phone) VALUES ($1, $2, $3)
  RETURNING guest_id;
EXECUTE example_query('测试联系人', NULL, '00123');
DEALLOCATE example_query;
ROLLBACK;


/* room types: LIST_TYPES */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT room_type_id, type_name, max_guests, base_nightly_rate
  FROM room_type ORDER BY room_type_id;
EXECUTE example_query;
DEALLOCATE example_query;
ROLLBACK;


/* rooms: LIST_ROOMS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT rm.room_id, rm.room_number, rt.room_type_id, rt.type_name,
         rt.max_guests, rt.base_nightly_rate, rm.is_bookable, rm.housekeeping_status
  FROM room rm JOIN room_type rt USING (room_type_id) ORDER BY rm.room_id;
EXECUTE example_query;
DEALLOCATE example_query;
ROLLBACK;


/* availability and cancelled history: FIND_ROOMS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT rm.room_id, rm.room_number, rt.room_type_id, rt.type_name,
         rt.max_guests, rt.base_nightly_rate
  FROM room rm JOIN room_type rt USING (room_type_id)
  WHERE rm.is_bookable AND rt.max_guests >= $1 AND $1 > 0
    AND $2::date > $3::date
    AND $3::date >= (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date
    AND ($4::integer IS NULL OR rt.room_type_id = $4)
    AND NOT EXISTS (
      SELECT 1 FROM reservation r WHERE r.room_id = rm.room_id
        AND r.status IN ('confirmed', 'checked_in')
        AND r.check_in_date < $2 AND r.check_out_date > $3)
  ORDER BY rt.base_nightly_rate, rm.room_number;
EXECUTE example_query(1, CURRENT_DATE + 3, CURRENT_DATE + 2, NULL);
DEALLOCATE example_query;
ROLLBACK;


/* invalid date availability: FIND_ROOMS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT rm.room_id, rm.room_number, rt.room_type_id, rt.type_name,
         rt.max_guests, rt.base_nightly_rate
  FROM room rm JOIN room_type rt USING (room_type_id)
  WHERE rm.is_bookable AND rt.max_guests >= $1 AND $1 > 0
    AND $2::date > $3::date
    AND $3::date >= (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date
    AND ($4::integer IS NULL OR rt.room_type_id = $4)
    AND NOT EXISTS (
      SELECT 1 FROM reservation r WHERE r.room_id = rm.room_id
        AND r.status IN ('confirmed', 'checked_in')
        AND r.check_in_date < $2 AND r.check_out_date > $3)
  ORDER BY rt.base_nightly_rate, rm.room_number;
EXECUTE example_query(1, CURRENT_DATE + 2, CURRENT_DATE + 2, NULL);
DEALLOCATE example_query;
ROLLBACK;


/* type and capacity filter: FIND_ROOMS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT rm.room_id, rm.room_number, rt.room_type_id, rt.type_name,
         rt.max_guests, rt.base_nightly_rate
  FROM room rm JOIN room_type rt USING (room_type_id)
  WHERE rm.is_bookable AND rt.max_guests >= $1 AND $1 > 0
    AND $2::date > $3::date
    AND $3::date >= (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date
    AND ($4::integer IS NULL OR rt.room_type_id = $4)
    AND NOT EXISTS (
      SELECT 1 FROM reservation r WHERE r.room_id = rm.room_id
        AND r.status IN ('confirmed', 'checked_in')
        AND r.check_in_date < $2 AND r.check_out_date > $3)
  ORDER BY rt.base_nightly_rate, rm.room_number;
EXECUTE example_query(3, CURRENT_DATE + 3, CURRENT_DATE + 2, 3);
DEALLOCATE example_query;
ROLLBACK;


/* room lock order: LOCK_ROOMS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT room_id FROM room WHERE room_id = ANY($1::integer[])
  ORDER BY room_id FOR UPDATE;
EXECUTE example_query(ARRAY[5, 3, 3]);
DEALLOCATE example_query;
ROLLBACK;


/* reservation lock order: LOCK_RESERVATIONS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT reservation_id FROM reservation
  WHERE reservation_id = ANY($1::integer[])
  ORDER BY reservation_id FOR UPDATE;
EXECUTE example_query(ARRAY[1003, 1001]);
DEALLOCATE example_query;
ROLLBACK;


/* room details: GET_ROOM */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT rm.room_id, rm.room_number, rt.room_type_id, rt.type_name,
         rt.max_guests, rt.base_nightly_rate, rm.is_bookable, rm.housekeeping_status
  FROM room rm JOIN room_type rt USING (room_type_id) WHERE rm.room_id = $1;
EXECUTE example_query(3);
DEALLOCATE example_query;
ROLLBACK;


/* reservation details: GET_RESERVATION */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT reservation_id, guest_id, room_id, check_in_date, check_out_date,
         guest_count, booked_nightly_rate, created_at, status,
         actual_check_in_at, actual_check_out_at, previous_reservation_id
  FROM reservation WHERE reservation_id = $1;
EXECUTE example_query(1001);
DEALLOCATE example_query;
ROLLBACK;


/* overlap detection: ROOM_DATE_CONFLICTS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT reservation_id, check_in_date, check_out_date, status FROM reservation
  WHERE room_id = $1 AND status IN ('confirmed', 'checked_in')
    AND reservation_id IS DISTINCT FROM $2::integer
    AND check_in_date < $3 AND check_out_date > $4
  ORDER BY reservation_id;
EXECUTE example_query(3, NULL, CURRENT_DATE + 1, CURRENT_DATE);
DEALLOCATE example_query;
ROLLBACK;


/* adjacent dates: ROOM_DATE_CONFLICTS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT reservation_id, check_in_date, check_out_date, status FROM reservation
  WHERE room_id = $1 AND status IN ('confirmed', 'checked_in')
    AND reservation_id IS DISTINCT FROM $2::integer
    AND check_in_date < $3 AND check_out_date > $4
  ORDER BY reservation_id;
EXECUTE example_query(3, NULL, CURRENT_DATE + 2, CURRENT_DATE + 1);
DEALLOCATE example_query;
ROLLBACK;


/* physical occupant: CURRENT_OCCUPANTS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT reservation_id FROM reservation WHERE room_id = $1
    AND status = 'checked_in'
    AND reservation_id IS DISTINCT FROM $2::integer
  ORDER BY reservation_id;
EXECUTE example_query(1, NULL);
DEALLOCATE example_query;
ROLLBACK;


/* same-room predecessor exception: CURRENT_OCCUPANTS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT reservation_id FROM reservation WHERE room_id = $1
    AND status = 'checked_in'
    AND reservation_id IS DISTINCT FROM $2::integer
  ORDER BY reservation_id;
EXECUTE example_query(1, 1013);
DEALLOCATE example_query;
ROLLBACK;


/* insert and amount: INSERT_RESERVATION */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  INSERT INTO reservation
   (guest_id, room_id, check_in_date, check_out_date, guest_count,
    booked_nightly_rate, previous_reservation_id)
  VALUES ($1, $2, $3, $4, $5,
          $6, $7)
  RETURNING reservation_id, booked_nightly_rate,
            (check_out_date-check_in_date)*booked_nightly_rate AS total_amount, status;
EXECUTE example_query(1, 2, CURRENT_DATE + 20, CURRENT_DATE + 22, 1, 120.00, NULL);
DEALLOCATE example_query;
ROLLBACK;


/* all contact states: PERSONAL_RESERVATIONS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT r.reservation_id, rm.room_number, rt.type_name, r.check_in_date,
         r.check_out_date, r.guest_count, r.booked_nightly_rate,
         (r.check_out_date-r.check_in_date)*r.booked_nightly_rate AS total_amount,
         r.status, r.actual_check_in_at, r.actual_check_out_at, r.previous_reservation_id
  FROM reservation r JOIN room rm USING (room_id) JOIN room_type rt USING (room_type_id)
  WHERE r.guest_id = $1 ORDER BY r.created_at DESC, r.reservation_id DESC;
EXECUTE example_query(1);
DEALLOCATE example_query;
ROLLBACK;


/* cancellation: CANCEL_RESERVATION */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  UPDATE reservation SET status = 'cancelled'
  WHERE reservation_id = $1 AND guest_id = $2
    AND status = 'confirmed'
    AND check_in_date > (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date
  RETURNING reservation_id, status;
EXECUTE example_query(1003, 2);
DEALLOCATE example_query;
ROLLBACK;


/* wrong contact cancellation: CANCEL_RESERVATION */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  UPDATE reservation SET status = 'cancelled'
  WHERE reservation_id = $1 AND guest_id = $2
    AND status = 'confirmed'
    AND check_in_date > (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date
  RETURNING reservation_id, status;
EXECUTE example_query(1003, 1);
DEALLOCATE example_query;
ROLLBACK;


/* same day cancellation refused: CANCEL_RESERVATION */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  UPDATE reservation SET status = 'cancelled'
  WHERE reservation_id = $1 AND guest_id = $2
    AND status = 'confirmed'
    AND check_in_date > (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date
  RETURNING reservation_id, status;
EXECUTE example_query(1014, 3);
DEALLOCATE example_query;
ROLLBACK;


/* add occupant: ADD_STAYING_GUEST */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  INSERT INTO reservation_guest (reservation_id, full_name)
  SELECT reservation_id, $1 FROM reservation
  WHERE reservation_id = $2 AND status = 'confirmed'
  RETURNING reservation_guest_id;
EXECUTE example_query('Alex', 1004);
DEALLOCATE example_query;
ROLLBACK;


/* frozen occupant additions: ADD_STAYING_GUEST */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  INSERT INTO reservation_guest (reservation_id, full_name)
  SELECT reservation_id, $1 FROM reservation
  WHERE reservation_id = $2 AND status = 'confirmed'
  RETURNING reservation_guest_id;
EXECUTE example_query('Alex', 1001);
DEALLOCATE example_query;
ROLLBACK;


/* remove occupant: REMOVE_STAYING_GUEST */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';
INSERT INTO reservation_guest VALUES (-8001, 1004, 'Alex');
PREPARE example_query AS
  DELETE FROM reservation_guest rg USING reservation r
  WHERE rg.reservation_guest_id = $1
    AND rg.reservation_id = $2 AND r.reservation_id = rg.reservation_id
    AND r.status = 'confirmed'
  RETURNING rg.reservation_guest_id;
EXECUTE example_query(-8001, 1004);
DEALLOCATE example_query;
ROLLBACK;


/* list occupants: LIST_STAYING_GUESTS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT reservation_guest_id, full_name FROM reservation_guest
  WHERE reservation_id = $1 ORDER BY reservation_guest_id;
EXECUTE example_query(1001);
DEALLOCATE example_query;
ROLLBACK;


/* copy occupants without moving history: COPY_STAYING_GUESTS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';
DELETE FROM reservation_guest WHERE reservation_id = 1002;
PREPARE example_query AS
  INSERT INTO reservation_guest (reservation_id, full_name)
  SELECT $1, rg.full_name
  FROM reservation_guest rg JOIN reservation n ON n.reservation_id = $1
  WHERE rg.reservation_id = $2 AND n.status = 'confirmed'
    AND n.previous_reservation_id = rg.reservation_id
    AND NOT EXISTS (SELECT 1 FROM reservation_guest WHERE reservation_id = n.reservation_id)
  ORDER BY rg.reservation_guest_id
  RETURNING reservation_guest_id, full_name;
EXECUTE example_query(1002, 1001);
DEALLOCATE example_query;
ROLLBACK;


/* copy already populated refused: COPY_STAYING_GUESTS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  INSERT INTO reservation_guest (reservation_id, full_name)
  SELECT $1, rg.full_name
  FROM reservation_guest rg JOIN reservation n ON n.reservation_id = $1
  WHERE rg.reservation_id = $2 AND n.status = 'confirmed'
    AND n.previous_reservation_id = rg.reservation_id
    AND NOT EXISTS (SELECT 1 FROM reservation_guest WHERE reservation_id = n.reservation_id)
  ORDER BY rg.reservation_guest_id
  RETURNING reservation_guest_id, full_name;
EXECUTE example_query(1002, 1001);
DEALLOCATE example_query;
ROLLBACK;


/* check-in update after prerequisites: MARK_CHECKED_IN */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';
UPDATE reservation SET check_in_date = CURRENT_DATE WHERE reservation_id = 1010; UPDATE room SET housekeeping_status = 'clean' WHERE room_id = 2; INSERT INTO reservation_guest(reservation_id, full_name) VALUES(1010, 'Daniel Lee');
PREPARE example_query AS
  UPDATE reservation SET status = 'checked_in', actual_check_in_at = $1
  WHERE reservation_id = $2 AND status = 'confirmed'
  RETURNING reservation_id, status, actual_check_in_at;
EXECUTE example_query(CURRENT_TIMESTAMP, 1010);
DEALLOCATE example_query;
ROLLBACK;


/* checkout update: MARK_CHECKED_OUT */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  UPDATE reservation SET status = 'checked_out', actual_check_out_at = $1
  WHERE reservation_id = $2 AND status = 'checked_in'
  RETURNING reservation_id, status, actual_check_out_at;
EXECUTE example_query(CURRENT_TIMESTAMP, 1001);
DEALLOCATE example_query;
ROLLBACK;


/* open flag independent: SET_ROOM_OPEN */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  UPDATE room SET is_bookable = $1 WHERE room_id = $2
  RETURNING room_id, is_bookable;
EXECUTE example_query(TRUE, 6);
DEALLOCATE example_query;
ROLLBACK;


/* cleaning transition: SET_HOUSEKEEPING_STATUS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  UPDATE room SET housekeeping_status = $1
  WHERE room_id = $2 AND NOT EXISTS (
      SELECT 1 FROM reservation r WHERE r.room_id = room.room_id AND r.status = 'checked_in')
  RETURNING room_id, housekeeping_status;
EXECUTE example_query('cleaning', 2);
DEALLOCATE example_query;
ROLLBACK;


/* occupied room cannot be dirtied: SET_HOUSEKEEPING_STATUS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  UPDATE room SET housekeeping_status = $1
  WHERE room_id = $2 AND NOT EXISTS (
      SELECT 1 FROM reservation r WHERE r.room_id = room.room_id AND r.status = 'checked_in')
  RETURNING room_id, housekeeping_status;
EXECUTE example_query('dirty', 3);
DEALLOCATE example_query;
ROLLBACK;


/* noncancelled successor: GET_SUCCESSORS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT reservation_id, room_id, check_in_date, check_out_date, status
  FROM reservation WHERE previous_reservation_id = $1
    AND status <> 'cancelled' ORDER BY reservation_id;
EXECUTE example_query(1001);
DEALLOCATE example_query;
ROLLBACK;


/* extension already exists: EXTENSION_OPTIONS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  WITH parent AS (
      SELECT r.room_id, rm.room_type_id, r.check_out_date, r.guest_count
      FROM reservation r JOIN room rm USING (room_id)
      WHERE r.reservation_id = $1 AND r.status = 'checked_in'
        AND $2::date > r.check_out_date
        AND r.check_out_date >= (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date
        AND NOT EXISTS (SELECT 1 FROM reservation s
          WHERE s.previous_reservation_id = r.reservation_id AND s.status <> 'cancelled')
  )
  SELECT rm.room_id, rm.room_number, rt.room_type_id, rt.type_name,
         rt.base_nightly_rate, p.check_out_date AS check_in_date,
         $2::date AS check_out_date, p.guest_count,
         CASE WHEN rm.room_id = p.room_id THEN 0
              WHEN rt.room_type_id = p.room_type_id THEN 1 ELSE 2 END AS preference
  FROM parent p CROSS JOIN room rm JOIN room_type rt ON rt.room_type_id = rm.room_type_id
  WHERE rm.is_bookable AND rt.max_guests >= p.guest_count
    AND NOT EXISTS (SELECT 1 FROM reservation r WHERE r.room_id = rm.room_id
      AND r.status IN ('confirmed', 'checked_in')
      AND r.check_in_date < $2 AND r.check_out_date > p.check_out_date)
  ORDER BY preference, rt.base_nightly_rate, rm.room_number;
EXECUTE example_query(1001, CURRENT_DATE + 3);
DEALLOCATE example_query;
ROLLBACK;


/* extension option order: EXTENSION_OPTIONS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';
UPDATE reservation SET status = 'cancelled' WHERE reservation_id = 1002;
PREPARE example_query AS
  WITH parent AS (
      SELECT r.room_id, rm.room_type_id, r.check_out_date, r.guest_count
      FROM reservation r JOIN room rm USING (room_id)
      WHERE r.reservation_id = $1 AND r.status = 'checked_in'
        AND $2::date > r.check_out_date
        AND r.check_out_date >= (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Sydney')::date
        AND NOT EXISTS (SELECT 1 FROM reservation s
          WHERE s.previous_reservation_id = r.reservation_id AND s.status <> 'cancelled')
  )
  SELECT rm.room_id, rm.room_number, rt.room_type_id, rt.type_name,
         rt.base_nightly_rate, p.check_out_date AS check_in_date,
         $2::date AS check_out_date, p.guest_count,
         CASE WHEN rm.room_id = p.room_id THEN 0
              WHEN rt.room_type_id = p.room_type_id THEN 1 ELSE 2 END AS preference
  FROM parent p CROSS JOIN room rm JOIN room_type rt ON rt.room_type_id = rm.room_type_id
  WHERE rm.is_bookable AND rt.max_guests >= p.guest_count
    AND NOT EXISTS (SELECT 1 FROM reservation r WHERE r.room_id = rm.room_id
      AND r.status IN ('confirmed', 'checked_in')
      AND r.check_in_date < $2 AND r.check_out_date > p.check_out_date)
  ORDER BY preference, rt.base_nightly_rate, rm.room_number;
EXECUTE example_query(1001, CURRENT_DATE + 3);
DEALLOCATE example_query;
ROLLBACK;


/* statistics not multiplied by occupant rows: BOOKING_STATISTICS */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

PREPARE example_query AS
  SELECT rt.room_type_id, rt.type_name, COUNT(r.reservation_id) AS bookings,
         COUNT(*) FILTER (WHERE r.status = 'cancelled') AS cancelled,
         COALESCE(SUM(CASE WHEN r.status <> 'cancelled'
             THEN (r.check_out_date-r.check_in_date)*r.booked_nightly_rate ELSE 0 END), 0)
             AS booking_value
  FROM room_type rt LEFT JOIN room rm USING (room_type_id)
  LEFT JOIN reservation r ON r.room_id = rm.room_id
  GROUP BY rt.room_type_id, rt.type_name ORDER BY rt.room_type_id;
EXECUTE example_query;
DEALLOCATE example_query;
ROLLBACK;
