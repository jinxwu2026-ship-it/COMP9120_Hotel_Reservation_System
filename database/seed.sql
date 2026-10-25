BEGIN;
SET LOCAL TIME ZONE 'Australia/Sydney';

/* add booking contacts; email and phone are not unique */
INSERT INTO guest VALUES (1, 'Alice Chen',  'alice@example.com',  '+61 400 000 001');
INSERT INTO guest VALUES (2, 'Daniel Lee',  NULL,                 '+61 400 000 002');
INSERT INTO guest VALUES (3, 'Evelyn Wang', 'shared@example.com', '+61 400 000 003');
INSERT INTO guest VALUES (4, 'Hana Kim',    'shared@example.com', '+61 400 000 003');

/* add room types */
INSERT INTO room_type VALUES (1, 'Single', 1, 120.00);
INSERT INTO room_type VALUES (2, 'Double', 2, 180.00);
INSERT INTO room_type VALUES (3, 'Family', 4, 240.00);

/* add physical rooms */
INSERT INTO room VALUES (1, '101', 1, TRUE,  'clean');
INSERT INTO room VALUES (2, '102', 1, TRUE,  'dirty');
INSERT INTO room VALUES (3, '201', 2, TRUE,  'clean');
INSERT INTO room VALUES (4, '202', 2, TRUE,  'dirty');
INSERT INTO room VALUES (5, '301', 3, TRUE,  'clean');
INSERT INTO room VALUES (6, '302', 3, FALSE, 'cleaning');

/* add reservations with dates relative to the Sydney seed date */
/* shortcut: relative fixtures age after midnight; initialise a new empty test database for a new demonstration day */
INSERT INTO reservation (
  reservation_id, guest_id, room_id, check_in_date, check_out_date,
  guest_count, booked_nightly_rate, status, actual_check_in_at, actual_check_out_at
)
VALUES
  (1001, 1, 3, CURRENT_DATE - 1, CURRENT_DATE + 1, 2, 180, 'checked_in',
   CURRENT_DATE - 1 + TIME '14:00', NULL),
  (1003, 2, 1, CURRENT_DATE + 2, CURRENT_DATE + 4, 1, 120, 'confirmed', NULL, NULL),
  (1004, 3, 1, CURRENT_DATE + 4, CURRENT_DATE + 6, 1, 120, 'confirmed', NULL, NULL),
  (1005, 2, 4, CURRENT_DATE + 2, CURRENT_DATE + 4, 2, 180, 'cancelled', NULL, NULL),
  (1006, 3, 2, CURRENT_DATE - 4, CURRENT_DATE - 2, 1, 110, 'checked_out',
   CURRENT_DATE - 4 + TIME '15:00', CURRENT_DATE - 2 + TIME '10:00'),
  (1007, 4, 5, CURRENT_DATE - 5, CURRENT_DATE - 3, 3, 230, 'checked_out',
   CURRENT_DATE - 5 + TIME '15:00', CURRENT_DATE - 3 + TIME '10:00'),
  (1008, 4, 4, CURRENT_DATE + 4, CURRENT_DATE + 6, 2, 180, 'confirmed', NULL, NULL),
  (1009, 1, 3, CURRENT_DATE + 3, CURRENT_DATE + 5, 2, 180, 'confirmed', NULL, NULL),
  (1010, 2, 2, CURRENT_DATE + 1, CURRENT_DATE + 3, 1, 120, 'confirmed', NULL, NULL),
  (1011, 4, 6, CURRENT_DATE + 5, CURRENT_DATE + 7, 4, 240, 'cancelled', NULL, NULL),
  (1013, 3, 1, CURRENT_DATE - 1, CURRENT_DATE, 1, 120, 'checked_in',
   CURRENT_DATE - 1 + TIME '15:00', NULL);

/* add cancelled and confirmed continuation segments */
INSERT INTO reservation (
  reservation_id, guest_id, room_id, check_in_date, check_out_date,
  guest_count, booked_nightly_rate, status, previous_reservation_id
)
VALUES
  (1012, 1, 5, CURRENT_DATE + 1, CURRENT_DATE + 3, 2, 240, 'cancelled', 1001),
  (1002, 1, 5, CURRENT_DATE + 1, CURRENT_DATE + 3, 2, 240, 'confirmed', 1001),
  (1014, 3, 1, CURRENT_DATE, CURRENT_DATE + 2, 1, 120, 'confirmed', 1013);

/* add actual staying guests */
INSERT INTO reservation_guest (reservation_id, full_name) VALUES (1001, 'Bob Chen');
INSERT INTO reservation_guest (reservation_id, full_name) VALUES (1001, 'Carol Chen');
INSERT INTO reservation_guest (reservation_id, full_name) VALUES (1002, 'Bob Chen');
INSERT INTO reservation_guest (reservation_id, full_name) VALUES (1002, 'Carol Chen');
INSERT INTO reservation_guest (reservation_id, full_name) VALUES (1003, 'Daniel Lee');
INSERT INTO reservation_guest (reservation_id, full_name) VALUES (1006, 'Evelyn Wang');
INSERT INTO reservation_guest (reservation_id, full_name) VALUES (1007, 'Hana Kim');
INSERT INTO reservation_guest (reservation_id, full_name) VALUES (1007, 'Min Kim');
INSERT INTO reservation_guest (reservation_id, full_name) VALUES (1007, 'Ji Kim');
INSERT INTO reservation_guest (reservation_id, full_name) VALUES (1013, 'Evelyn Wang');
INSERT INTO reservation_guest (reservation_id, full_name) VALUES (1014, 'Evelyn Wang');

/* continue generated IDs after the explicitly numbered sample rows */
SELECT setval(
  pg_get_serial_sequence('guest', 'guest_id'),
  (SELECT MAX(guest_id) FROM guest)
);
SELECT setval(
  pg_get_serial_sequence('room_type', 'room_type_id'),
  (SELECT MAX(room_type_id) FROM room_type)
);
SELECT setval(
  pg_get_serial_sequence('room', 'room_id'),
  (SELECT MAX(room_id) FROM room)
);
SELECT setval(
  pg_get_serial_sequence('reservation', 'reservation_id'),
  (SELECT MAX(reservation_id) FROM reservation)
);
SELECT setval(
  pg_get_serial_sequence('reservation_guest', 'reservation_guest_id'),
  (SELECT MAX(reservation_guest_id) FROM reservation_guest)
);

COMMIT;
