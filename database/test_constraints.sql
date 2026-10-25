/* verify database constraints in an isolated test database */
BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

DO $$
BEGIN
  IF current_database() NOT LIKE '%\_test' ESCAPE '\' THEN
    RAISE EXCEPTION 'Use a dedicated database ending in _test';
  END IF;
END;
$$;

/* temporary results and helper for expected failures */
CREATE TEMP TABLE constraint_results (
  test_name  TEXT,
  result     TEXT NOT NULL,
  PRIMARY KEY (test_name)
);

CREATE FUNCTION pg_temp.expect_error(command TEXT, expected TEXT, label TEXT)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  actual TEXT;
BEGIN
  BEGIN
    EXECUTE command;
  EXCEPTION WHEN OTHERS THEN
    GET STACKED DIAGNOSTICS actual = RETURNED_SQLSTATE;
    IF actual <> expected THEN
      RAISE EXCEPTION '%: expected SQLSTATE %, got %: %', label, expected, actual, SQLERRM;
    END IF;
    INSERT INTO constraint_results VALUES (label, 'PASS ' || actual);
    RETURN;
  END;
  RAISE EXCEPTION '%: statement unexpectedly succeeded', label;
END;
$$;

/* create temporary test records */
INSERT INTO guest VALUES (-1, 'Test contact', NULL, '00123');
INSERT INTO room_type VALUES (-1, 'Test type', 2, 0);
INSERT INTO room VALUES (-1, 'TEST-1', -1, DEFAULT, 'clean');

INSERT INTO reservation (
  reservation_id, guest_id, room_id, check_in_date, check_out_date,
  guest_count, booked_nightly_rate
)
VALUES (-1, -1, -1, CURRENT_DATE + 30, CURRENT_DATE + 32, 2, 0);

INSERT INTO reservation_guest VALUES (-1, -1, 'Same name');
INSERT INTO reservation_guest VALUES (-2, -1, 'Same name');
INSERT INTO guest VALUES (-2, 'Test contact', NULL, '00123');
INSERT INTO guest VALUES (-3, 'Email one', 'shared@example.com', '00123');

/* verify valid records and defaults */
DO $$
BEGIN
  IF (SELECT is_bookable FROM room WHERE room_id = -1) IS NOT TRUE THEN
    RAISE EXCEPTION 'Room default failed';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM reservation
    WHERE reservation_id = -1
      AND status = 'confirmed'
      AND created_at IS NOT NULL
  ) THEN
    RAISE EXCEPTION 'Reservation defaults failed';
  END IF;
  IF (SELECT COUNT(*) FROM reservation_guest WHERE reservation_id = -1) <> 2 THEN
    RAISE EXCEPTION 'Equal names must be allowed';
  END IF;
END;
$$;

INSERT INTO constraint_results VALUES ('P01 zero price allowed', 'PASS');
INSERT INTO constraint_results VALUES ('P02 nullable duplicate contacts allowed', 'PASS');
INSERT INTO constraint_results VALUES ('P03 same-name occupants allowed', 'PASS');
INSERT INTO constraint_results VALUES ('P04 defaults', 'PASS');

/* C01 guest PK */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO guest
    VALUES (-1, 'Duplicate', NULL, '123')
  $q$,
  '23505',
  'C01 guest PK'
);

/* C02 name required */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO guest
    VALUES (-4, NULL, NULL, '123')
  $q$,
  '23502',
  'C02 name required'
);

/* C03 blank name */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO guest
    VALUES (-4, '  ', NULL, '123')
  $q$,
  '23514',
  'C03 blank name'
);

/* C04 phone required */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO guest
    VALUES (-4, 'A', NULL, NULL)
  $q$,
  '23502',
  'C04 phone required'
);

/* C05 whitespace phone */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO guest
    VALUES (-4, 'A', NULL, E' \t\n')
  $q$,
  '23514',
  'C05 whitespace phone'
);

/* C06 type unique */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO room_type
    VALUES (-2, 'Test type', 2, 10)
  $q$,
  '23505',
  'C06 type unique'
);

/* C07 capacity positive */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO room_type
    VALUES (-2, 'Capacity zero', 0, 10)
  $q$,
  '23514',
  'C07 capacity positive'
);

/* C08 base price nonnegative */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO room_type
    VALUES (-2, 'Negative price', 1, -1)
  $q$,
  '23514',
  'C08 base price nonnegative'
);

/* C09 finite base price */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO room_type
    VALUES (-2, 'NaN price', 1, 'NaN')
  $q$,
  '23514',
  'C09 finite base price'
);

/* C10 room number unique */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO room
    VALUES (-2, 'TEST-1', -1, TRUE, 'clean')
  $q$,
  '23505',
  'C10 room number unique'
);

/* C11 room type FK */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO room
    VALUES (-2, 'TEST-2', -999, TRUE, 'clean')
  $q$,
  '23503',
  'C11 room type FK'
);

/* C12 cleaning explicit */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO room
    VALUES (-2, 'TEST-2', -1, TRUE, NULL)
  $q$,
  '23502',
  'C12 cleaning explicit'
);

/* C13 cleaning domain */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO room
    VALUES (-2, 'TEST-2', -1, TRUE, 'ready')
  $q$,
  '23514',
  'C13 cleaning domain'
);

/* C14 guest FK */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET guest_id = -999
    WHERE reservation_id = -1
  $q$,
  '23503',
  'C14 guest FK'
);

/* C15 room FK */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET room_id = -999
    WHERE reservation_id = -1
  $q$,
  '23503',
  'C15 room FK'
);

/* C16 predecessor FK */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET previous_reservation_id = -999
    WHERE reservation_id = -1
  $q$,
  '23503',
  'C16 predecessor FK'
);

/* C17 no self link */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET previous_reservation_id = reservation_id
    WHERE reservation_id = -1
  $q$,
  '23514',
  'C17 no self link'
);

/* C18 positive nights */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET check_out_date = check_in_date
    WHERE reservation_id = -1
  $q$,
  '23514',
  'C18 positive nights'
);

/* C19 finite dates */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET check_in_date = 'infinity'
    WHERE reservation_id = -1
  $q$,
  '23514',
  'C19 finite dates'
);

/* C20 party positive */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET guest_count = 0
    WHERE reservation_id = -1
  $q$,
  '23514',
  'C20 party positive'
);

/* C21 agreed price nonnegative */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET booked_nightly_rate = -1
    WHERE reservation_id = -1
  $q$,
  '23514',
  'C21 agreed price nonnegative'
);

/* C22 finite agreed price */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET booked_nightly_rate = 'NaN'
    WHERE reservation_id = -1
  $q$,
  '23514',
  'C22 finite agreed price'
);

/* C23 status domain */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET status = 'no_show'
    WHERE reservation_id = -1
  $q$,
  '23514',
  'C23 status domain'
);

/* C24 status required */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET status = NULL
    WHERE reservation_id = -1
  $q$,
  '23502',
  'C24 status required'
);

/* C25 arrival time required */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET status = 'checked_in'
    WHERE reservation_id = -1
  $q$,
  '23514',
  'C25 arrival time required'
);

/* C26 confirmed has no actual time */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET actual_check_in_at = CURRENT_TIMESTAMP
    WHERE reservation_id = -1
  $q$,
  '23514',
  'C26 confirmed has no actual time'
);

/* C27 cancelled has no actual time */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET status = 'cancelled', actual_check_out_at = CURRENT_TIMESTAMP
    WHERE reservation_id = -1
  $q$,
  '23514',
  'C27 cancelled has no actual time'
);

/* C28 departure time required */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET status = 'checked_out', actual_check_in_at = CURRENT_TIMESTAMP
    WHERE reservation_id = -1
  $q$,
  '23514',
  'C28 departure time required'
);

/* C29 actual time order */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET status = 'checked_out', actual_check_in_at = CURRENT_TIMESTAMP, actual_check_out_at = CURRENT_TIMESTAMP-INTERVAL '1 hour'
    WHERE reservation_id = -1
  $q$,
  '23514',
  'C29 actual time order'
);

/* C30 occupant FK */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO reservation_guest
    VALUES (-3, -999, 'Unknown parent')
  $q$,
  '23503',
  'C30 occupant FK'
);

/* C31 occupant nonblank */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO reservation_guest
    VALUES (-3, -1, E'\t\n')
  $q$,
  '23514',
  'C31 occupant nonblank'
);

/* C32 contact deletion restricted */
SELECT pg_temp.expect_error(
  $q$
    DELETE FROM guest
    WHERE guest_id = -1
  $q$,
  '23503',
  'C32 contact deletion restricted'
);

/* C33 type deletion restricted */
SELECT pg_temp.expect_error(
  $q$
    DELETE FROM room_type
    WHERE room_type_id = -1
  $q$,
  '23503',
  'C33 type deletion restricted'
);

/* C34 room deletion restricted */
SELECT pg_temp.expect_error(
  $q$
    DELETE FROM room
    WHERE room_id = -1
  $q$,
  '23503',
  'C34 room deletion restricted'
);

/* C35 reservation deletion restricted */
SELECT pg_temp.expect_error(
  $q$
    DELETE FROM reservation
    WHERE reservation_id = -1
  $q$,
  '23503',
  'C35 reservation deletion restricted'
);

/* verify cancelled and non-cancelled successors */
INSERT INTO reservation (
  reservation_id, guest_id, room_id, check_in_date, check_out_date,
  guest_count, booked_nightly_rate, status, previous_reservation_id
)
VALUES
  (-10, -1, -1, CURRENT_DATE + 32, CURRENT_DATE + 34, 2, 0, 'cancelled', -1),
  (-11, -1, -1, CURRENT_DATE + 32, CURRENT_DATE + 34, 2, 0, 'confirmed', -1);

/* C36 one noncancelled successor */
SELECT pg_temp.expect_error(
  $q$
    INSERT INTO reservation (reservation_id, guest_id, room_id, check_in_date, check_out_date, guest_count, booked_nightly_rate, previous_reservation_id)
    VALUES (-12, -1, -1, CURRENT_DATE + 32, CURRENT_DATE + 34, 2, 0, -1)
  $q$,
  '23505',
  'C36 one noncancelled successor'
);

INSERT INTO constraint_results VALUES ('P05 cancelled successor retry allowed', 'PASS');

/* verify actual occupancy uniqueness */
UPDATE reservation
SET status = 'checked_in', actual_check_in_at = CURRENT_TIMESTAMP
WHERE reservation_id = -1;

/* C37 one actual occupant reservation */
SELECT pg_temp.expect_error(
  $q$
    UPDATE reservation
    SET status = 'checked_in', actual_check_in_at = CURRENT_TIMESTAMP
    WHERE reservation_id = -11
  $q$,
  '23505',
  'C37 one actual occupant reservation'
);

UPDATE reservation
SET status = 'checked_out', actual_check_out_at = CURRENT_TIMESTAMP
WHERE reservation_id = -1;

INSERT INTO constraint_results VALUES ('P06 valid actual timestamps', 'PASS');

/* record direct-write boundaries that the service must enforce */
INSERT INTO reservation (
  reservation_id, guest_id, room_id, check_in_date, check_out_date,
  guest_count, booked_nightly_rate
)
VALUES
  (-20, -1, -1, CURRENT_DATE + 40, CURRENT_DATE + 42, 99, 0),
  (-21, -1, -1, CURRENT_DATE + 41, CURRENT_DATE + 43, 1, 0);

INSERT INTO constraint_results
  VALUES ('B01 capacity and overlap are service boundaries', 'CONFIRMED BOUNDARY');

/* display results, then discard all test records */
TABLE constraint_results;

SELECT COUNT(*) FILTER (WHERE result LIKE 'PASS%') AS passed,
       COUNT(*) FILTER (WHERE result = 'CONFIRMED BOUNDARY') AS documented_boundaries
FROM constraint_results;

ROLLBACK;
