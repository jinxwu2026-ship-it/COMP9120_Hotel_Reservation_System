# Database report material


**顾客入口与日期更新：** 已复用Guest联系人表加入无需账号的标准价直接预订，并将全部日期输入/日历改为英文；仍为7表/48列。说明见 [顾客预订与英文日期.md](../顾客预订与英文日期.md)。当前测试合计54项（17+14+18+5），另有Node日历自检。

**2026-10-25功能更新：** 已实现入住前修改、多房原子预订、经理固定优惠晚价和预订操作历史。升级/使用方法见根目录 [本次功能更新.md](../本次功能更新.md)。当前7表/48列；旧验证记录按其日期保留。
Author work package: Jinxing Wu. Implementation and SQL evidence: 24 October 2026. Merge the following text into Sections 3 and 4 of the teaching-team report template. The initial database evidence and subsequent Python integration evidence are distinguished below.

Staff/web implementation update: the current installation has seven relations and 48 columns. The original five-table hotel model is retained; the separate `staff.sql` migration adds Staff, with non-null unique username as an additional candidate key, a scrypt password hash, role, active/temporary-password flags and session/lockout state. The additive reservation_audit.sql migration links reservation events to Reservation and optionally Staff, preserving before/after snapshots and operator identity in the same transaction. Its stated determinants are staff_id and username, so its declared FDs satisfy BCNF. The current RM uses `evidence/web_schema_columns.json`; the 28-column snapshot below is historical core evidence. Reservation's conditional continuation analysis remains unchanged.

The local Flask/Waitress portal reuses the original service transactions and 28 hotel SQL templates. Staff HTTP and CLI entry points authenticate individuals and check roles; reception cannot manage staff or room-opening policy. The actual web database role hotel_app has no superuser, CREATEDB, CREATEROLE or schema CREATE privilege and only the necessary table/sequence grants. Fourteen real-database web/authentication tests and the existing seventeen service tests passed, covering CSRF, lockout, forced password change, session revocation, privilege refusal, concurrent last-manager protection and HTTP transaction rollback. See `../tianyishen/evidence/web_validation.txt`, `web_service_regression.txt` and `evidence/web_setup.json`. This is a local deployment, not evidence of public HTTPS operation, customer authentication or comprehensive auditing of room-policy and staff-account administration.

Integration update: the original Tianyi service has now been connected through 28 positional SQL templates in `tianyishen/queries.py`. The 25 named templates below remain the standalone database test interface. Seventeen real-driver service integration tests passed, including both continuation paths, rollback and two-connection competition; the CLI read-only smoke check also passed. See `tianyishen/evidence/INTEGRATION_RESULTS.md`. Ordinary manual arrival follows Tianyi's current relaxed date policy; continuation activation still checks its planned window.

## 3 Logical Design and Normalisation

### 3.1 Relational Schema

Our five core hotel relations are Guest, RoomType, Room, Reservation and ReservationGuest, using physical names `guest`, `room_type`, `room`, `reservation` and `reservation_guest`. Staff is the identity relation and ReservationAudit the event relation, giving seven relations and 48 columns in the current installation. The updated `Hotel_Database_RM.drawio` and PNG match `evidence/web_schema_columns.json`; `evidence/schema_columns.json` preserves the earlier 28-column core snapshot.

Each relation has an identity primary key; ReservationAudit uses BIGINT and the remaining six use INTEGER. Room number, room-type name and staff username are additional non-null unique candidate keys in their respective relations. Email is optional and nonunique; contact names and phone numbers are also nonunique. Actual guest names are not identifiers. Reservation's optional predecessor references another Reservation. A conditional unique index allows multiple cancelled successor attempts but at most one non-cancelled successor. This is not a candidate key over the whole relation.

All seven foreign keys use restricted deletion, including the audit links to Reservation and Staff. Required text values reject whitespace-only strings. Prices use fixed-precision NUMERIC(10,2), and dates and timestamp fields have distinct roles. Planned dates determine the priced segment; actual timestamps record its operational start and end.

### 3.2 Mapping from ER Model to Relations

The four ordinary one-to-many relationships place mandatory foreign keys on their many sides: Reservation references its contact and room, Room references RoomType, and ReservationGuest references Reservation. A nullable predecessor foreign key maps the recursive continuation relationship. A root segment has no predecessor; each successor has at most one predecessor.

Actual occupants are separate from the booking contact because the contact may not stay. The registration relation can be empty when booking, while the service must check its count at arrival. This separates conceptual participation from a condition that applies only at a particular business stage.

### 3.3 Functional Dependencies

The main whole-relation dependencies are: guest_id determines all Guest attributes; room_type_id and type_name each determine all RoomType attributes; room_id and room_number each determine all Room attributes; reservation_id determines all Reservation attributes; and reservation_guest_id determines all registration attributes. The right-hand sides and candidate keys appear in `RM_AND_NORMALISATION.md`. These dependencies do not exhaust the conditional semantics of continuation rows.

Neither room_id nor room_type_id determines the nightly rate of all historical reservations, because the agreed rate is a booking-time snapshot. Nonunique contact details and occupant names do not determine identifiers. The predecessor's conditional uniqueness also does not imply an unconditional key dependency.

### 3.4 Normalisation Analysis

Guest, RoomType, Room and ReservationGuest satisfy BCNF under the stated whole-relation dependencies, and therefore satisfy 3NF. Reservation's core attributes have the same structure before adding the optional predecessor. Column count does not determine normal form, and a surrogate primary key alone does not establish BCNF.

Continuation needs a qualification. Among rows with a non-null predecessor, previous_reservation_id determines the contact and planned start date: the contact must equal the predecessor's contact, and the start must equal its planned departure. Multiple cancelled attempts may share that predecessor, so it is not a superkey of this continuation subrelation. Its dependencies to these non-prime attributes violate 3NF and BCNF when that non-null subrelation is analysed using ordinary FDs. Root rows have null predecessors and do not obey the same unconditional determinant rule. A blanket claim that every business subrelation is BCNF would therefore be too strong; the final report must state the NULL convention, analysis scope and retained conditional redundancy. Consistency checks in the service do not eliminate the redundancy.

Separating RoomType avoids repeating its capacity and current price in each physical room. If a wide Room relation were decomposed into Room and RoomType, their intersection would be room_type_id, which determines all RoomType attributes; this provides the binary lossless-join argument. The relevant dependencies remain enforceable in the respective relations. A separate continuation-link relation is a possible later refinement, but has not been implemented or presented as an existing sixth table.

Occupants are represented by separate registration rows rather than repeated columns or a delimited list. A full name is treated as a display value, not a globally identifying attribute. Normalisation does not itself enforce interval exclusion, state transitions or occupancy-count matching.

### 3.5 Final Design Decisions and Trade-offs

We preserve the booked nightly rate while deriving total booking value as planned nights multiplied by that rate. We do not duplicate room number, contact name, room type or total amount in Reservation. Party size describes the plan and can precede an actual guest list. Continuation uses a new Reservation linked to the previous segment, preserving both room and price history. Housekeeping is independent of whether the room accepts future bookings. Room-type maintenance is frozen during the prototype demonstration; concurrent maintenance would require an expanded locking policy.

## 4 SQL Integrity and Transactions

### 4.1 PostgreSQL Implementation

The database was created and populated on PostgreSQL 16.14 in an independent local instance at 127.0.0.1:55432. The demonstration database is `comp9120_hotel`; tests use the separate `comp9120_hotel_test`. Both use Australia/Sydney. The setup does not modify the pre-existing PostgreSQL service.

`schema.sql` and `seed.sql` successfully initialise an empty database with four contacts, three room types, six rooms, fourteen reservations and eleven occupant registrations. Fixtures include all four reservation statuses, all three housekeeping states, adjacent bookings, cancelled history, a different-room continuation and a same-room continuation. Dates are relative to the seed date. Structure and counts are captured in `evidence/database_snapshot.txt`.

The additive `seed_more.sql` expands the demonstration database to 50 contacts, 8 room types, 40 rooms, 200 reservations and 351 occupant registrations, preserving every original row. The larger synthetic dataset includes eleven historical continuation pairs, current occupancy, future bookings and cancellation history. Isolated validation covers capacity, active and historical interval conflicts, actual occupancy, roster counts, continuation consistency, duplicate-import rollback and real service calls. The live import, preservation comparison and subsequent correction of the new historical dates are recorded in `evidence/data_expansion.json`; the final data follows the revised expansion script. The original database verifier retains the minimal fixture and its fixed expected outputs. These 200 reservations support demonstration, not a production performance claim.

### 4.2 Representative SQL Operations

The integrated application uses 28 positional parameterised SQL templates in `tianyishen/queries.py`, with names, placeholder order and result-column order fixed by its interface requirement file. SQL performs no connection handling or transaction commits; the service owns transaction boundaries and business checks. The 25 named templates in `database/queries.py` remain a separate standalone database-verification interface. Final report excerpts should identify which interface they demonstrate.

Availability uses joins, room openness, capacity and NOT EXISTS to remove active interval conflicts. The strict comparisons permit adjacent stays: existing.check_in_date < requested.check_out and existing.check_out_date > requested.check_in. Cancelled and checked-out reservations do not block planned availability; dirty status alone does not exclude future dates.

In the original minimal fixture at seeded date D, searching D+2 to D+3 for one person returns room IDs 3 and 4, corresponding to rooms 201 and 202. Cancellation history in 202 does not block that interval. The expanded dataset can return additional rooms. The integrated service rejects a zero-night request before executing the availability query; the standalone verification interface instead returns no availability rows for this invalid input.

Personal history joins Reservation, Room and RoomType and derives each segment's amount. The integrated cancellation service locks the room and reservation, checks contact ownership, confirmed status and that the hotel date precedes planned arrival, and then executes its status update. Wrong-contact and same-day cancellation requests were rejected in service integration tests. The older standalone SQL interface enforces these checks within its conditional UPDATE and returns no rows when refused; the two interfaces should not be conflated.

Statistics uses LEFT JOIN, grouping and conditional aggregation, preserving empty room types and avoiding joins to occupant rows. The minimal-fixture output was Single: 6 bookings, 0 cancelled, non-cancelled value 1300; Double: 4, 1, 1080; Family: 4, 2, 940. The total 3320 represents planned non-cancelled booking value, not payment revenue, and is not the current expanded demonstration total. Standalone PREPARE/EXECUTE examples and their outputs are provided.

### 4.3 Integrity Constraints

Primary keys, foreign keys, NOT NULL and unique constraints protect identifiers, references and required attributes. CHECK constraints protect nonblank required text, positive capacities and party sizes, nonnegative non-NaN prices, valid statuses, finite dates, positive planned durations, non-self predecessors, and consistent actual timestamp combinations. Confirmed and cancelled rows have no actual timestamps; checked-in rows have only an actual arrival; checked-out rows have ordered arrival and departure timestamps.

Two conditional unique indexes enforce at most one checked-in reservation per physical room and at most one non-cancelled successor per predecessor. These rules are distinct from preventing planned interval overlap. The active-date index is an access-path optimisation, not an interval exclusion constraint.

The database constraint suite passed 43 positive and negative checks, including SQLSTATE 23502 for required values, 23503 for references and restricted deletions, 23505 for uniqueness, and 23514 for domain checks. It also deliberately confirmed one documented boundary: direct INSERTs can still exceed capacity and overlap dates. These cross-table rules require all service writes to follow the common Room-lock protocol; this implementation does not claim protection against arbitrary manual SQL.

### Database evidence for Sections 4.4 to 4.6

The database-level concurrency experiment used two independent connections. Both attempted the same future room interval, first locking the same Room row and then issuing a fresh conflict query at READ COMMITTED. Connection B waited about two seconds, and exactly one reservation was committed. Temporary race records were removed only from the dedicated test database.

A separate failure-injection test changed a checked-in order to checked-out inside a transaction and then raised a division-by-zero error before dirty marking. The client stopped and disconnected; the transaction rolled back. A fresh query confirmed both the original checked-in status and clean room status. This verifies database atomic rollback for the SQL sequence, not a completed service function.

All 25 database templates were executed through server-side PREPARE/EXECUTE, and 35 fixed-input SQL cases had asserted outputs. SQL parameter expressions in that verifier are trusted fixtures only. Subsequent service integration tested actual psycopg2 binding against the 28 positional application templates, roster checks, checkout, same-room and different-room activation, failure rollback and service-level races. All 17 integration tests passed in a disposable schema of the separate test database. Menu reads and normal exit also passed a real CLI smoke check. These two stages have separate evidence files and should be cited separately; independent final group acceptance and exhaustive menu-input testing are not claimed.

## Suggested 40 to 50 second database presentation

“Our database separates the booking contact from the people who actually stay, and separates room type from physical room. The five-table design preserves each reservation segment and its agreed price. Database constraints reject missing references, invalid dates, inconsistent timestamps and duplicate active successors. Here is the tested availability SQL: overlapping active reservations are excluded while adjacent dates remain valid. Two independent database sessions also demonstrate the shared room-lock protocol, with only one conflicting booking succeeding. Transaction and menu integration uses these same parameterised statements.”

This is a recording script, not a recorded video or a contribution declaration. AI assisted the preparation of SQL, tests and explanatory text; group members must verify, understand and acknowledge its use under course requirements.

## 2026-10-25 amendment, batch booking, discounts and audit implementation

A confirmed root reservation can be amended before its original arrival date, preserving its ID, contact, party size and guest registration IDs. Reservations participating in any continuation history are excluded. The service locks old and target rooms in ascending ID order, locks and rechecks the reservation, rejects stale form snapshots, excludes the current reservation from date-conflict detection, confirms the new rate, and commits the update and audit event together. Committing releases the previous planned allocation; failure preserves it. An unchanged request retains the agreed rate.

A multi-room submission shares one contact and date interval but creates separate reservations. Every selected room is locked in ascending order and checked before inserts; all inserts and events share one transaction. Failure in the second event rolls back the first reservation and event as well. No persistent booking-group relation or group-wide cancellation is implemented. Managers can confirm a nonnegative fixed nightly discount no higher than the current standard quote, with a reason; the base room-type price is not overwritten. Date/room amendments are repriced and do not implicitly retain an earlier discount.

ReservationAudit has nine attributes: audit_id (BIGINT identity PK), reservation_id (FK), nullable staff_id (FK), source, action, occurred_at, reason, before_data and after_data. The identity key determines the event attributes. Snapshots intentionally retain historical values; JSONB contents are treated as event payload, not a replacement for normalized business relations. The source/staff presence rule introduces conditional redundancy, so the report does not claim unconditional BCNF for every event subrelation. Original continuation normalization qualifications remain unchanged.

Validated employee identity comes from server/CLI context and is rechecked against active status, password-change flag and session version in the business transaction. Nonstaff developer calls are labelled separately. Application grants allow SELECT/INSERT on events, not UPDATE/DELETE. Direct owner SQL is outside this service audit boundary. Existing historical orders are not assigned invented staff identities.

Seventeen legacy service tests, fourteen web/auth tests and eighteen new booking checks passed (49 total). Actual hotel_app HTTP checks also passed in a disposable schema; audit UPDATE/DELETE was refused. Live migration preserved all pre-existing business and Staff rows. Evidence: ../tianyishen/evidence/booking_changes_validation.txt and evidence/booking_upgrade.json.
