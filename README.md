# Harbour House hotel database prototype

COMP9120 Database Management Systems, Semester 2, 2026 
**Group number : 60 SID1:560555079 SID2: 550593111 SID3: 560025675**

This PostgreSQL/Python prototype manages booking contacts, rooms, reservations, occupants, individual staff accounts and reservation history. Its English web interface and CLI use the same service layer. Run the commands below from the folder containing this README, `database/` and `python_file/`.

## 1. Contents

| Item | Purpose |
| --- | --- |
| `database/schema.sql` | Five core tables, keys, checks and indexes |
| `database/seed.sql`, `seed_more.sql` | Minimal fixture and expanded synthetic data |
| `database/staff.sql`, `reservation_audit.sql` | Two additive migrations, giving seven tables |
| `database/queries.py`, `sql_examples.sql` | Standalone SQL interface and executable examples |
| `database/test_constraints.sql`, `verify_database.py` | Constraint, SQL, rollback and lock checks |
| `database/verify_expanded_data.py` | Data counts, preservation and consistency checks |
| `database/Hotel_Report_RM.drawio`, matching PNG panels | Editable implemented RM and report figures |
| `database/Hotel_ERD.pgerd` | Editable pgAdmin ERD project |
| `python_file/` | Application, pinned dependencies, templates, static assets and tests |
| Both `evidence/` directories | Dated validation records and screenshots |
| Report PDF | Project report |
| `Participation Statement.pdf` | Group contribution statement |
| `Poster.pdf`, `Poster.pptx` | One-page poster and editable PowerPoint source |


## 2. Requirements

1. PostgreSQL 16 with its server running and pgAdmin 4. Optional standalone checks also require `psql`.
2. Python 3.12. Pinned dependencies: psycopg2-binary 2.9.13, Flask 3.1.3, Waitress 3.0.2.
3. A local database administrator/owner account able to create databases, own tables and create roles; the installation account `postgres` is suitable for a fresh local setup.
4. A browser; Node.js is optional for the calendar self-check.

No PostgreSQL data directory, virtual environment, database password or generated staff password is included.

## 3. Create the database through pgAdmin

1. In pgAdmin, register your server through **Servers → Register → Server**. Under **Connection**, use host `127.0.0.1`, your server's actual port, maintenance database `postgres`, your PostgreSQL account and its password. A typical installation uses port `5432`; the author's separate instance uses `55432`. Use your own port.
2. Right-click **Databases → Create → Database** and create two **new empty** databases: `comp9120_hotel` and `comp9120_hotel_test`, owned by the account above. Keep existing databases containing valuable work.
3. From the `postgres` database's **Query Tool**, execute:

   ```sql
   ALTER DATABASE comp9120_hotel SET timezone TO 'Australia/Sydney';
   ALTER DATABASE comp9120_hotel_test SET timezone TO 'Australia/Sydney';
   ```

4. Open **Query Tool** on `comp9120_hotel`. Use **Open File → Execute script** for each file separately, in this order; check successful completion each time:

   ```text
   database/schema.sql
   database/seed.sql
   database/seed_more.sql
   database/staff.sql
   database/reservation_audit.sql
   ```

5. On `comp9120_hotel_test`, import only `schema.sql` followed by `seed.sql`. Do not import `seed_more.sql` there. Python suites create their own complete schemas inside the test database.
6. Refresh **Schemas → public → Tables** in the demonstration database. Seven tables should appear. Use **View/Edit Data → All Rows**, or execute:

   ```sql
   SELECT 'guest' AS relation, count(*) FROM public.guest
   UNION ALL SELECT 'room_type', count(*) FROM public.room_type
   UNION ALL SELECT 'room', count(*) FROM public.room
   UNION ALL SELECT 'reservation', count(*) FROM public.reservation
   UNION ALL SELECT 'reservation_guest', count(*) FROM public.reservation_guest;
   ```

Expanded seed counts are respectively **50, 8, 40, 200, 351**; minimal seed counts are **4, 3, 6, 14, 11**. Staff accounts are provisioned next; application actions generate audit events.

Seed dates are relative to the Sydney date of import and do not refresh automatically. Import each seed once. The core schema and seeds reject duplicate initialisation rather than erase existing data. For a later repeat of fixed-date checks, use another fresh database ending in `_test`. `create_database.sql` is an optional alternative to the Create Database dialog: execute each `CREATE DATABASE` separately with autocommit enabled, from `postgres`.

## 4. Install Python and provision staff accounts

In PowerShell at this package root:

```powershell
python -m venv .venv
$py = '.\.venv\Scripts\python.exe'
& $py -m pip install -r .\python_file\requirements.txt

$env:PGHOST = '127.0.0.1'
$env:PGPORT = '5432'  # Your server's actual port.
$env:PGUSER = 'postgres'  # Your administrator/owner account.
$env:PGDATABASE = 'comp9120_hotel'
$env:HOTEL_SCHEMA = 'public'
$password = Read-Host 'Your PostgreSQL account password' -AsSecureString
$env:PGPASSWORD = [System.Net.NetworkCredential]::new('', $password).Password
& $py .\python_file\setup_web.py
```

pgAdmin's saved login is not automatically passed to Python. Explicitly set these values rather than relying on the author-specific defaults in `db.py`.

Setup safely reapplies the two additive migrations, creates the restricted PostgreSQL role `hotel_app`, and creates `manager` and `reception` staff accounts when Staff is empty. Read **your own** `.local/web_first_login.txt` locally for their random temporary passwords. First sign-in requires a password change. There is no shared default password.

The website's Staff login differs from pgAdmin's PostgreSQL login. The server connects through `hotel_app`, while personal Staff accounts have `manager` or `receptionist` roles. Private files are generated under `.local/`: `web_database.json`, `pgpass_web.conf`, `web_session.key` and `web_first_login.txt`. Keep that folder private. After moving the installation, provision it again because the generated password-file path is absolute.

Setup preserves existing Staff passwords but rotates the database role password, so restart running servers afterwards. Provision one demonstration installation per cluster; rerunning setup for another database in that cluster changes the shared `hotel_app` password.

## 5. Run and demonstrate the application

```powershell
Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
& $py .\python_file\run_web.py
```

Keep the terminal running and visit **http://127.0.0.1:8080/**. A waiting terminal after the URL appears means the server is running. Stop it with **Ctrl+C**. Waitress listens on localhost with debugging disabled.

1. **Public booking:** search future dates, choose a room and provide contact information. Guest stores an unverified booking contact, not an account. Standard-price booking and a session-bound receipt are available; a guest ID does not authenticate access to another person's orders.
2. **Staff:** visit **http://127.0.0.1:8080/login**, use locally generated credentials and change the temporary password. Reception manages contacts, reservations, occupant lists, check-in/out and housekeeping.
3. **Amendments and multiple rooms:** modify an eligible pre-arrival booking or create several room reservations atomically. Occupants must be complete at check-in, and the room must be clean, bookable and unoccupied.
4. **Continuation:** prepare a following segment in the same or another room and activate it during the next segment's planned interval. Old checkout, new check-in and room-state changes commit together; a failed step rolls back the related changes.
5. **Manager:** manage Staff, change room bookability and approve a fixed discounted nightly price with a reason.
6. **History:** open the reservation detail page to view operation history, actor/source, time, reason and before/after snapshots.

In a new PowerShell window, change to this package root, set `$py = '.\.venv\Scripts\python.exe'` again, and repeat the required connection settings; variables do not carry between terminals.

The optional CLI is `& $py .\python_file\main.py` in a separate terminal configured with the owner connection variables from Section 4. Its Staff menu authenticates individual accounts. Its original Customer menu is a local developer interface; use the browser for public booking.

## 6. Structure and integrity

```text
Browser → web.py → service.py / auth.py → queries.py + db.py → PostgreSQL
CLI     → main.py → the same services
```

| Relation | Information |
| --- | --- |
| guest | Booking contact and contact details |
| room_type | Capacity and current base nightly price |
| room | Physical room, type, bookability and housekeeping |
| reservation | One priced room/date segment, state, actual times and optional predecessor |
| reservation_guest | Separate occupant registrations |
| staff | Personal credentials, role and account state |
| reservation_audit | Reservation events, staff/source and historical JSON snapshots |

Seven relations contain **48 attributes and seven foreign keys**. The draw.io RM is separate from the conceptual ER in lecture notation. `Hotel_ERD.pgerd` is a saved pgAdmin project, not an exported image.

`python_file/queries.py` has 28 positional SQL templates (`%s`); additional workflow/authentication SQL is in `service.py` and `auth.py`. `database/queries.py` is a different 25-template named-parameter interface for standalone verification. Do not interchange the two modules. psycopg2 binds application parameters.

PK, unique, FK and CHECK rules enforce row/reference integrity. Partial unique indexes enforce one checked-in order per room and one non-cancelled successor per predecessor. Ordinary indexes help lookup speed; they do not prevent every date overlap. The service locks affected Room rows in a common order, rechecks availability, and commits related writes and audit events together. Capacity, roster, continuity and state transitions require this service path; owner SQL can bypass them. Agreed prices remain on reservation segments. Multiple-room creation is atomic but has no persistent group-order table.

## 7. Reproduce checks

Use an **owner connection**, with the connection/password settings from Section 4, not `hotel_app`. Ensure the test database exists, then run each suite separately:

```powershell
$env:HOTEL_TEST_DATABASE = 'comp9120_hotel_test'
& $py .\python_file\test_integration.py
& $py .\python_file\test_web.py
& $py .\python_file\test_booking_changes.py
& $py .\python_file\test_public_booking.py
& $py .\database\verify_expanded_data.py
```

The four application suites contain **17 + 14 + 18 + 5 = 54 tests** against real PostgreSQL. Each creates randomly named schemas in a database ending in `_test` and cleans up only its own schemas. Coverage includes authentication, permissions, bookings, amendments, batching, audit rollback and competing connections. The expanded-data check also verifies counts, original-row preservation, interval consistency and repeat-import rollback.

Optional calendar check:

```powershell
node .\python_file\test_calendar.cjs
```

For standalone SQL verification, the test database's **public** schema must have only the minimal `schema.sql` + `seed.sql` fixture imported on the current Sydney date. Random-schema Python tests do not initialise public. Supply your own host, port, owner and optional absolute `psql` path:

```powershell
& $py .\database\verify_database.py --host 127.0.0.1 --port 5432 --user postgres --database comp9120_hotel_test --psql 'C:\Program Files\PostgreSQL\16\bin\psql.exe'
```

This runs 43 constraint/positive checks, a documented direct-SQL boundary, 35 SQL cases, and lock/rollback checks, writing results to `database/evidence/`. Alternatively execute `test_constraints.sql` and `sql_examples.sql` through the test database's pgAdmin Query Tool. Do not run tests against the demonstration database. Rolled-back inserts can advance sequences, so ID gaps are normal.

Evidence files record dated test runs. Re-run checks for your environment.

## 8. Troubleshooting

| Symptom | Resolution |
| --- | --- |
| Connection refused | Start PostgreSQL; match pgAdmin and PGPORT to the actual server port. |
| Password rejected | Setup/tests need the PostgreSQL password; website login needs the generated Staff password. |
| Relation missing | Check database/schema, import order and pgAdmin refresh. |
| Staff/history tables missing | Import staff.sql then reservation_audit.sql, or provision after the core seed imports. |
| Module not found | Install requirements using the same Python executable as the application. |
| Private config absent or points to an old path | Provision from this installation using the owner connection, then restart. |
| Port 8080 busy | Stop the older server with Ctrl+C. |
| Fixture-date/count check fails | Use a fresh _test database with today's minimal seed. |
| Booking/check-in refused | Check dates, overlaps, capacity, bookability, housekeeping and occupant completeness. |

## 9. Scope and AI acknowledgement

This local coursework prototype does not implement payments, customer accounts, Internet/HTTPS deployment, automatic seasonal pricing, or auditing of arbitrary administrator SQL. Amounts have no agreed currency. The report explains the retained continuation dependency and audit snapshots rather than making an unconditional BCNF claim for every table.

OpenAI Codex assisted with SQL, code changes, tests, diagrams and documentation. 
