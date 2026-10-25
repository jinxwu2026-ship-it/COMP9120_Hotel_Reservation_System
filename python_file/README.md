# Python hotel prototype

See the [package README](../README.md) for pgAdmin setup, dependencies, connection variables, staff provisioning, browser/CLI operation and tests. Run its commands from the package root.

- `db.py`: psycopg2 connection, transaction isolation, Sydney time and schema selection.
- `queries.py`: 28 positional SQL templates for the application contract.
- `service.py`: hotel validation, shared Room locking, commit/rollback and reservation events.
- `auth.py`: Staff credentials, roles and account state.
- `web.py`, `templates/`, `static/`: Flask routes and English browser interface.
- `main.py`: CLI using the same services.
- `setup_web.py`: owner-run provisioning and restricted application connection.
- `run_web.py`: local Waitress entry point on 127.0.0.1:8080.
- `test_*.py`, `test_calendar.cjs`: application tests and optional calendar self-check.
- `evidence/`: dated validation records and screenshots.

The current folder is `python_file`. Older evidence may show the former name `tianyishen`; use the current paths in the root README. `../database/queries.py` is a separate named-parameter interface and must not replace this directory's module.
