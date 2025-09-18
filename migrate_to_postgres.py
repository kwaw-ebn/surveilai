
"""
migrate_to_postgres.py

Usage:
    Set environment variable DATABASE_URL to your Postgres connection, e.g.:
    export DATABASE_URL=postgresql://user:password@host:5432/dbname

Then run:
    python migrate_to_postgres.py

The script will read from the local SQLite surveilai.db and copy tables to Postgres.
"""
import os
from sqlalchemy import create_engine, text
import pandas as pd
import sqlite3

SQLITE_DB = "surveilai.db"
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("Please set DATABASE_URL env var to your Postgres connection string.")

# read sqlite tables
conn = sqlite3.connect(SQLITE_DB)
tables = pd.read_sql_query("SELECT name FROM sqlite_master WHERE type='table';", conn)
engine = create_engine(DATABASE_URL)

for t in tables['name']:
    if t.startswith('sqlite_'):
        continue
    df = pd.read_sql_query(f"SELECT * FROM {t}", conn)
    print(f"Migrating table {t} ({len(df)} rows) to Postgres...")
    df.to_sql(t, engine, if_exists='replace', index=False)
print("Migration complete.")
