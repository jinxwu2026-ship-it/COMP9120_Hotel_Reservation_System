import os
from pathlib import Path

import psycopg2
from psycopg2 import sql

# Database settings.
HOST = os.environ.get('PGHOST', '127.0.0.1')
PORT = int(os.environ.get('PGPORT', '55432'))
DATABASE = os.environ.get('PGDATABASE', 'comp9120_hotel')
USER = os.environ.get('PGUSER', 'hotel_owner')
SCHEMA = os.environ.get('HOTEL_SCHEMA', 'public')

PASSWORD = os.environ.get('PGPASSWORD', '')
_local_passfile = Path(__file__).resolve().parents[1] / '.local' / 'pgpass.conf'
PASSFILE = os.environ.get('PGPASSFILE') or (str(_local_passfile) if _local_passfile.is_file() else None)


def get_connection(read_only=False):
    conn = psycopg2.connect(
        host=HOST,
        port=PORT,
        database=DATABASE,
        user=USER,
        password=PASSWORD or None,
        passfile=PASSFILE,
        connect_timeout=5,
    )

    cur = None
    try:
        conn.set_session(
            isolation_level="READ COMMITTED",
            readonly=read_only,
            autocommit=False
        )
        cur = conn.cursor()

        cur.execute("SET TIME ZONE 'Australia/Sydney'")

        # Table schema.
        cur.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(SCHEMA)))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    finally:
        if cur is not None:
            cur.close()

    return conn
