import sqlite3
import os
from datetime import datetime, timedelta

# Try importing psycopg2 for PostgreSQL support
try:
    import psycopg2
    import psycopg2.extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

DB_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
IS_POSTGRES = HAS_POSTGRES and (DB_URL is not None)

# Determine database path (use read-write /tmp directory on Vercel/Serverless environments)
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or not os.access(os.path.dirname(os.path.abspath(__file__)), os.W_OK):
    DB_PATH = "/tmp/reminder_system.db"
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminder_system.db")

def get_db_connection():
    if IS_POSTGRES:
        conn = psycopg2.connect(DB_URL)
        return conn
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

def get_cursor(conn):
    if IS_POSTGRES:
        return conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    return conn.cursor()

def run_query(cursor, query, params=()):
    if IS_POSTGRES:
        query = query.replace('?', '%s')
        # Replace dynamic types for PostgreSQL in DDL
        query = query.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
        query = query.replace('datetime(due_time)', 'due_time')
    else:
        query = query.replace('datetime(due_time)', 'due_time')
    cursor.execute(query, params)
    return cursor

def init_db():
    conn = get_db_connection()
    cursor = get_cursor(conn)
    
    # 1. Settings table
    run_query(cursor, """
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            app_password TEXT,
            imap_server TEXT DEFAULT 'imap.gmail.com',
            smtp_server TEXT DEFAULT 'smtp.gmail.com',
            imap_port INTEGER DEFAULT 993,
            smtp_port INTEGER DEFAULT 587,
            sandbox_mode INTEGER DEFAULT 1,
            check_interval_mins INTEGER DEFAULT 5,
            auth_mode TEXT DEFAULT 'sandbox',
            oauth_client_id TEXT,
            oauth_client_secret TEXT,
            oauth_access_token TEXT,
            oauth_refresh_token TEXT,
            oauth_token_expires_at TEXT
        )
    """)
    
    # Run dynamic schema migrations to add columns if database already existed
    if IS_POSTGRES:
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'settings'")
        columns = [row[0].lower() for row in cursor.fetchall()]
    else:
        cursor.execute("PRAGMA table_info(settings)")
        columns = [row[1].lower() for row in cursor.fetchall()]
    
    migrations = [
        ("auth_mode", "TEXT DEFAULT 'sandbox'"),
        ("oauth_client_id", "TEXT"),
        ("oauth_client_secret", "TEXT"),
        ("oauth_access_token", "TEXT"),
        ("oauth_refresh_token", "TEXT"),
        ("oauth_token_expires_at", "TEXT")
    ]
    
    for col_name, col_def in migrations:
        if col_name.lower() not in columns:
            run_query(cursor, f"ALTER TABLE settings ADD COLUMN {col_name} {col_def}")
            print(f"[Migration] Added column '{col_name}' to settings table.")
            
    # Insert default settings if empty
    cursor.execute("SELECT COUNT(*) FROM settings")
    if cursor.fetchone()[0] == 0:
        run_query(cursor, """
            INSERT INTO settings (email, app_password, imap_server, smtp_server, imap_port, smtp_port, sandbox_mode, check_interval_mins, auth_mode)
            VALUES ('', '', 'imap.gmail.com', 'smtp.gmail.com', 993, 587, 1, 5, 'sandbox')
        """)
    
    # 2. Reminders table
    run_query(cursor, """
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT,
            due_time TEXT NOT NULL, -- ISO8601 string
            status TEXT DEFAULT 'pending', -- pending, triggered, completed
            snooze_count INTEGER DEFAULT 0,
            source_email_id TEXT,
            source_email_subject TEXT,
            created_at TEXT NOT NULL
        )
    """)
    
    # 3. Processed Emails table
    run_query(cursor, """
        CREATE TABLE IF NOT EXISTS processed_emails (
            uid TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()

def get_settings():
    conn = get_db_connection()
    cursor = get_cursor(conn)
    run_query(cursor, "SELECT * FROM settings ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {}

def save_settings(settings_dict):
    conn = get_db_connection()
    cursor = get_cursor(conn)
    
    run_query(cursor, """
        UPDATE settings
        SET email = ?,
            app_password = ?,
            imap_server = ?,
            smtp_server = ?,
            imap_port = ?,
            smtp_port = ?,
            sandbox_mode = ?,
            check_interval_mins = ?,
            auth_mode = ?,
            oauth_client_id = ?,
            oauth_client_secret = ?
        WHERE id = (SELECT id FROM settings ORDER BY id DESC LIMIT 1)
    """, (
        settings_dict.get('email', ''),
        settings_dict.get('app_password', ''),
        settings_dict.get('imap_server', 'imap.gmail.com'),
        settings_dict.get('smtp_server', 'smtp.gmail.com'),
        int(settings_dict.get('imap_port', 993)),
        int(settings_dict.get('smtp_port', 587)),
        1 if settings_dict.get('sandbox_mode') else 0,
        int(settings_dict.get('check_interval_mins', 5)),
        settings_dict.get('auth_mode', 'sandbox'),
        settings_dict.get('oauth_client_id', ''),
        settings_dict.get('oauth_client_secret', '')
    ))
    
    conn.commit()
    conn.close()
    return get_settings()

def save_oauth_tokens(access_token, refresh_token, expires_at):
    conn = get_db_connection()
    cursor = get_cursor(conn)
    run_query(cursor, """
        UPDATE settings
        SET oauth_access_token = ?,
            oauth_refresh_token = COALESCE(?, oauth_refresh_token),
            oauth_token_expires_at = ?
        WHERE id = (SELECT id FROM settings ORDER BY id DESC LIMIT 1)
    """, (access_token, refresh_token, expires_at))
    conn.commit()
    conn.close()

def get_reminders(status=None):
    conn = get_db_connection()
    cursor = get_cursor(conn)
    if status:
        run_query(cursor, "SELECT * FROM reminders WHERE status = ? ORDER BY datetime(due_time) ASC", (status,))
    else:
        run_query(cursor, "SELECT * FROM reminders ORDER BY datetime(due_time) ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_reminder_by_id(reminder_id):
    conn = get_db_connection()
    cursor = get_cursor(conn)
    run_query(cursor, "SELECT * FROM reminders WHERE id = ?", (reminder_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def create_reminder(title, content, due_time, source_email_id=None, source_email_subject=None):
    conn = get_db_connection()
    cursor = get_cursor(conn)
    created_at = datetime.now().isoformat()
    
    query = """
        INSERT INTO reminders (title, content, due_time, status, snooze_count, source_email_id, source_email_subject, created_at)
        VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)
    """
    
    if IS_POSTGRES:
        query = query.replace('?', '%s') + " RETURNING id"
        cursor.execute(query, (title, content, due_time, source_email_id, source_email_subject, created_at))
        reminder_id = cursor.fetchone()[0]
    else:
        cursor.execute(query, (title, content, due_time, source_email_id, source_email_subject, created_at))
        reminder_id = cursor.lastrowid
        
    conn.commit()
    
    # Fetch new reminder
    new_query = "SELECT * FROM reminders WHERE id = ?"
    run_query(cursor, new_query, (reminder_id,))
    row = cursor.fetchone()
    new_reminder = dict(row)
    conn.close()
    return new_reminder

def update_reminder_status(reminder_id, status):
    conn = get_db_connection()
    cursor = get_cursor(conn)
    run_query(cursor, "UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
    conn.commit()
    conn.close()
    return get_reminder_by_id(reminder_id)

def snooze_reminder(reminder_id, minutes):
    conn = get_db_connection()
    cursor = get_cursor(conn)
    
    run_query(cursor, "SELECT * FROM reminders WHERE id = ?", (reminder_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    
    reminder = dict(row)
    new_due = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    new_snooze_count = reminder['snooze_count'] + 1
    
    run_query(cursor, """
        UPDATE reminders
        SET due_time = ?, status = 'pending', snooze_count = ?
        WHERE id = ?
    """, (new_due, new_snooze_count, reminder_id))
    
    conn.commit()
    conn.close()
    return get_reminder_by_id(reminder_id)

def delete_reminder(reminder_id):
    conn = get_db_connection()
    cursor = get_cursor(conn)
    run_query(cursor, "DELETE FROM reminders WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()
    return True

def is_email_processed(uid):
    conn = get_db_connection()
    cursor = get_cursor(conn)
    run_query(cursor, "SELECT count(*) FROM processed_emails WHERE uid = ?", (uid,))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

def mark_email_processed(uid):
    conn = get_db_connection()
    cursor = get_cursor(conn)
    processed_at = datetime.now().isoformat()
    try:
        run_query(cursor, "INSERT INTO processed_emails (uid, processed_at) VALUES (?, ?)", (uid, processed_at))
        conn.commit()
    except (sqlite3.IntegrityError, Exception):
        pass # Already exists or unique constraint violation on PG
    conn.close()
