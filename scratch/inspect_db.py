import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()
db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("DATABASE_URL not found in .env")
    exit(1)

try:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    # List all tables in public schema
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
    tables = cur.fetchall()
    print("Tables in database:", [t[0] for t in tables])
    
    for t_name in ['users', 'admins', 'bans', 'warns', 'tournaments', 'tournament_participants']:
        cur.execute(f"SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = '{t_name}');")
        exists = cur.fetchone()[0]
        print(f"Table '{t_name}' exists: {exists}")
        if exists:
            cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = '{t_name}';")
            cols = cur.fetchall()
            print(f"  Columns of '{t_name}':", {c[0]: c[1] for c in cols})
            
            # Check primary keys
            cur.execute(f"""
                SELECT a.attname
                FROM   pg_index i
                JOIN   pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE  i.indrelid = 'public.{t_name}'::regclass
                AND    i.indisprimary;
            """)
            pks = cur.fetchall()
            print(f"  Primary Keys of '{t_name}':", [p[0] for p in pks])
            
    conn.close()
except Exception as e:
    print("Error connecting/querying database:", e)
