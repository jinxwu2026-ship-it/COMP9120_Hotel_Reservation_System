"""Start the local-only staff portal with its provisioned low-privilege connection."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = ROOT / '.local/web_database.json'
    if not config.exists():
        raise SystemExit('Run python python_file/setup_web.py using your database administrator connection first.')
    settings = json.loads(config.read_text(encoding='utf-8'))
    for key in ['PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'HOTEL_SCHEMA', 'PGPASSFILE']:
        os.environ[key] = settings[key]
    # The owner password may still be set in the terminal; use only the provisioned app passfile.
    os.environ.pop('PGPASSWORD', None)
    from waitress import serve
    import db
    from web import create_app
    conn = db.get_connection(read_only=True)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user')
            if any(cur.fetchone()):
                raise SystemExit('The web server requires a separate low-privilege database account. Run setup again.')
    finally:
        conn.close()
    print('Hotel staff portal: http://127.0.0.1:8080', flush=True)
    serve(create_app(), host='127.0.0.1', port=8080, threads=4)


if __name__ == '__main__':
    main()
