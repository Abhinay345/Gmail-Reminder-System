import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminder_system.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Settings table with OAuth fields
    cursor.execute("""
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
    cursor.execute("PRAGMA table_info(settings)")
    columns = [row[1] for row in cursor.fetchall()]
    
    migrations = [
        ("auth_mode", "TEXT DEFAULT 'sandbox'"),
        ("oauth_client_id", "TEXT"),
        ("oauth_client_secret", "TEXT"),
        ("oauth_access_token", "TEXT"),
        ("oauth_refresh_token", "TEXT"),
        ("oauth_token_expires_at", "TEXT")
    ]
    
    for col_name, col_def in migrations:
        if col_name not in columns:
            cursor.execute(f"ALTER TABLE settings ADD COLUMN {col_name} {col_def}")
            print(f"[Migration] Added column '{col_name}' to settings table.")
            
    # Insert default settings if empty
    cursor.execute("SELECT COUNT(*) FROM settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO settings (email, app_password, imap_server, smtp_server, imap_port, smtp_port, sandbox_mode, check_interval_mins, auth_mode)
            VALUES ('', '', 'imap.gmail.com', 'smtp.gmail.com', 993, 587, 1, 5, 'sandbox')
        """)
    
    # 2. Reminders table
    cursor.execute("""
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_emails (
            uid TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()

def get_settings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM settings ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {}

def save_settings(settings_dict):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
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
    cursor = conn.cursor()
    # We update access token, refresh token (if present), and expiry
    cursor.execute("""
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
    cursor = conn.cursor()
    if status:
        cursor.execute("SELECT * FROM reminders WHERE status = ? ORDER BY datetime(due_time) ASC", (status,))
    else:
        cursor.execute("SELECT * FROM reminders ORDER BY datetime(due_time) ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_reminder_by_id(reminder_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def create_reminder(title, content, due_time, source_email_id=None, source_email_subject=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    created_at = datetime.now().isoformat()
    cursor.execute("""
        INSERT INTO reminders (title, content, due_time, status, snooze_count, source_email_id, source_email_subject, created_at)
        VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)
    """, (title, content, due_time, source_email_id, source_email_subject, created_at))
    reminder_id = cursor.lastrowid
    conn.commit()
    
    cursor.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
    new_reminder = dict(cursor.fetchone())
    conn.close()
    return new_reminder

def update_reminder_status(reminder_id, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
    conn.commit()
    conn.close()
    return get_reminder_by_id(reminder_id)

def snooze_reminder(reminder_id, minutes):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Get current reminder
    cursor.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    
    reminder = dict(row)
    # Calculate new due time from now or current due time (from now is better to avoid piling up)
    new_due = (datetime.now() + timedelta(minutes=minutes)).isoformat()
    new_snooze_count = reminder['snooze_count'] + 1
    
    cursor.execute("""
        UPDATE reminders
        SET due_time = ?, status = 'pending', snooze_count = ?
        WHERE id = ?
    """, (new_due, new_snooze_count, reminder_id))
    
    conn.commit()
    conn.close()
    return get_reminder_by_id(reminder_id)

def delete_reminder(reminder_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()
    return True

def is_email_processed(uid):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM processed_emails WHERE uid = ?", (uid,))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

def mark_email_processed(uid):
    conn = get_db_connection()
    cursor = conn.cursor()
    processed_at = datetime.now().isoformat()
    try:
        cursor.execute("INSERT INTO processed_emails (uid, processed_at) VALUES (?, ?)", (uid, processed_at))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # Already exists
    conn.close()
