import os
import sys
import json
import asyncio
import urllib.parse
import io
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add current directory to path to enable local module imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import database
import parser



app = FastAPI(title="Gmail Reminder System API")

# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global list of SSE listeners (async queues)
listeners: List[asyncio.Queue] = []

# Pydantic Schemas
class SettingsSchema(BaseModel):
    email: str
    app_password: str
    imap_server: str
    smtp_server: str
    imap_port: int
    smtp_port: int
    sandbox_mode: bool
    check_interval_mins: int
    auth_mode: Optional[str] = "sandbox"
    oauth_client_id: Optional[str] = ""
    oauth_client_secret: Optional[str] = ""
    oauth_access_token: Optional[str] = ""
    oauth_refresh_token: Optional[str] = ""
    oauth_token_expires_at: Optional[str] = ""


class ReminderCreateSchema(BaseModel):
    title: str
    content: Optional[str] = ""
    due_time: str # ISO8601 string
    source_email_id: Optional[str] = None
    source_email_subject: Optional[str] = None

class SnoozeSchema(BaseModel):
    minutes: int

class EmailActionCreateSchema(BaseModel):
    uid: str
    subject: str
    body: str

# SMTP email helper
def send_smtp_email(settings, reminder):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    
    try:
        sender = settings['email']
        password = settings['app_password']
        smtp_server = settings['smtp_server']
        smtp_port = int(settings['smtp_port'])
        
        if not sender or not password:
            print("SMTP configurations are incomplete. Skipping email dispatch.")
            return
            
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"🔔 REMINDER: {reminder['title']}"
        msg['From'] = f"Gmail Reminder System <{sender}>"
        msg['To'] = sender # Sends notification to user's own email
        
        html = f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f3f4f6; padding: 24px; margin: 0;">
            <div style="max-width: 580px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -4px rgba(0, 0, 0, 0.05); border: 1px solid #e5e7eb;">
                <div style="background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%); padding: 32px; text-align: center; color: #ffffff;">
                    <span style="font-size: 56px; line-height: 1;">🔔</span>
                    <h1 style="margin: 16px 0 0 0; font-size: 26px; font-weight: 800; letter-spacing: -0.025em;">Reminder Fired!</h1>
                    <p style="margin: 8px 0 0 0; color: #c7d2fe; font-size: 14px;">Your Gmail Reminder System is working</p>
                </div>
                <div style="padding: 32px; color: #374151; line-height: 1.6;">
                    <div style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #4f46e5; margin-bottom: 8px;">Task / Alert</div>
                    <h2 style="margin: 0 0 12px 0; color: #111827; font-size: 22px; font-weight: 700; line-height: 1.25;">{reminder['title']}</h2>
                    
                    {f'<p style="margin: 0 0 24px 0; font-size: 16px; color: #4b5563; background-color: #f9fafb; padding: 16px; border-radius: 8px; border-left: 4px solid #e5e7eb;">{reminder["content"]}</p>' if reminder["content"] else ''}
                    
                    <div style="background-color: #f3f4f6; border-radius: 12px; padding: 16px; margin-bottom: 28px;">
                        <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                            <tr>
                                <td style="color: #6b7280; font-weight: 500; padding: 6px 0;">Trigger Time</td>
                                <td style="color: #111827; font-weight: 600; text-align: right; padding: 6px 0;">{reminder['due_time'].replace('T', ' ')}</td>
                            </tr>
                            {f'<tr><td style="color: #6b7280; font-weight: 500; padding: 6px 0;">Email Source</td><td style="color: #111827; font-weight: 600; text-align: right; padding: 6px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 250px;">{reminder["source_email_subject"]}</td></tr>' if reminder.get('source_email_subject') else ''}
                        </table>
                    </div>
                    
                    <div style="text-align: center;">
                        <a href="http://localhost:8000" style="display: inline-block; background-color: #4f46e5; color: #ffffff; text-decoration: none; padding: 14px 32px; font-size: 15px; font-weight: 600; border-radius: 10px; box-shadow: 0 4px 10px rgba(79, 70, 229, 0.25); transition: background-color 0.2s;">Go to Dashboard</a>
                    </div>
                </div>
                <div style="background-color: #f9fafb; padding: 20px; text-align: center; font-size: 12px; color: #9ca3af; border-top: 1px solid #f3f4f6;">
                    This is an automated message sent by Gmail Reminder System.<br>
                    Running locally on <strong>http://localhost:8000</strong>
                </div>
            </div>
        </body>
        </html>
        """
        
        part1 = MIMEText(f"Reminder: {reminder['title']}\nDescription: {reminder['content']}\nDue: {reminder['due_time']}", 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)
        
        if smtp_port == 587:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
            
        server.login(sender, password)
        server.sendmail(sender, sender, msg.as_string())
        server.quit()
        print(f"[BG Worker] Successfully dispatched SMTP email for reminder #{reminder['id']}.")
    except Exception as e:
        print(f"[BG Worker] Error dispatching SMTP notification: {e}")

# Asynchronous Scheduler Loop
async def check_reminders_loop():
    print("[BG Worker] Active Reminder Scheduler starting...")
    while True:
        try:
            # Query pending reminders
            pending = database.get_reminders(status="pending")
            now_str = datetime.now().isoformat()
            
            for reminder in pending:
                if reminder['due_time'] <= now_str:
                    print(f"[BG Worker] Triggering reminder #{reminder['id']}: '{reminder['title']}'")
                    # Update status
                    updated = database.update_reminder_status(reminder['id'], "triggered")
                    
                    # Notify active SSE UI streams
                    event_msg = json.dumps({
                        "event": "reminder_triggered",
                        "reminder": updated
                    })
                    
                    for listener in list(listeners):
                        try:
                            await listener.put(event_msg)
                        except Exception as sse_err:
                            print(f"[BG Worker] SSE delivery error: {sse_err}")
                    
                    # Read current settings to check mode
                    settings = database.get_settings()
                    if settings:
                        auth_mode = settings.get('auth_mode', 'sandbox')
                        if auth_mode == "oauth" and settings.get('oauth_refresh_token'):
                            import gmail_api
                            # Dispatch secure HTML email via Gmail REST API in a separate executor
                            loop = asyncio.get_running_loop()
                            await loop.run_in_executor(None, gmail_api.gmail_send_email, settings, updated)
                        elif auth_mode == "app_password" or (auth_mode == "sandbox" and not settings['sandbox_mode']):
                            # Dispatch email via traditional SMTP in separate background executor
                            loop = asyncio.get_running_loop()
                            await loop.run_in_executor(None, send_smtp_email, settings, updated)
        except Exception as err:
            print(f"[BG Worker] Scheduler error: {err}")
            
        await asyncio.sleep(5) # Period checks every 5s


# Active Mode IMAP inbox scanner
def run_imap_scan(settings):
    import imaplib
    import email
    from email.header import decode_header
    
    results = []
    try:
        username = settings['email']
        password = settings['app_password']
        imap_server = settings['imap_server']
        imap_port = int(settings['imap_port'])
        
        if not username or not password:
            raise Exception("Gmail account settings are empty.")
            
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(username, password)
        mail.select("inbox")
        
        # Check standard unseen
        status, messages = mail.search(None, 'UNSEEN')
        if status != "OK":
            return []
            
        email_ids = messages[0].split()
        print(f"[Scanner] Found {len(email_ids)} unseen emails in inbox.")
        
        # Pull last 15 unread emails
        for eid in email_ids[-15:]:
            uid = eid.decode('utf-8')
            
            # Avoid re-scanning processed
            if database.is_email_processed(uid):
                continue
                
            status, msg_data = mail.fetch(eid, '(RFC822)')
            if status != "OK":
                continue
                
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            
            # Parse Subject
            subject_parts = decode_header(msg["Subject"] or "")
            subject = ""
            for part, encoding in subject_parts:
                if isinstance(part, bytes):
                    subject += part.decode(encoding or "utf-8", errors="ignore")
                else:
                    subject += str(part)
            
            # Parse From/Sender
            from_parts = decode_header(msg["From"] or "")
            from_str = ""
            for part, encoding in from_parts:
                if isinstance(part, bytes):
                    from_str += part.decode(encoding or "utf-8", errors="ignore")
                else:
                    from_str += str(part)
            
            # Parse Body Text
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
                    elif content_type == "text/html" and "attachment" not in content_disposition:
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
            
            # Filter HTML tags to clean up plain text preview
            plain_body = parser.clean_html(body)
            
            # Extract actionable elements
            action, suggested_due = parser.extract_action_items(plain_body, subject)
            
            results.append({
                "uid": uid,
                "subject": subject,
                "sender": from_str,
                "body": plain_body,
                "body_preview": plain_body[:180] + "..." if len(plain_body) > 180 else plain_body,
                "parsed_action": action,
                "parsed_due": suggested_due
            })
            
        mail.close()
        mail.logout()
    except Exception as e:
        print(f"[Scanner] IMAP scan failed: {e}")
        raise e
        
    return results

# FastAPI Lifecycle Events
@app.on_event("startup")
async def startup_event():
    database.init_db()
    # Create background scheduler loop task
    asyncio.create_task(check_reminders_loop())

# --- API ENDPOINTS ---

@app.get("/api/settings", response_model=SettingsSchema)
def get_settings():
    sets = database.get_settings()
    # map 0/1 integers to boolean for FastAPI / Pydantic schema compatibility
    sets['sandbox_mode'] = bool(sets.get('sandbox_mode', 1))
    if not sets.get('auth_mode'):
        sets['auth_mode'] = 'sandbox' if sets['sandbox_mode'] else 'app_password'
    return sets

@app.post("/api/settings", response_model=SettingsSchema)
def update_settings(payload: SettingsSchema):
    db_payload = payload.dict()
    db_payload['sandbox_mode'] = 1 if payload.sandbox_mode else 0
    if payload.auth_mode == 'sandbox':
        db_payload['sandbox_mode'] = 1
    else:
        db_payload['sandbox_mode'] = 0
        
    updated = database.save_settings(db_payload)
    updated['sandbox_mode'] = bool(updated.get('sandbox_mode', 1))
    return updated


@app.get("/api/reminders")
def get_reminders(status: Optional[str] = None):
    return database.get_reminders(status=status)

@app.post("/api/reminders")
def add_reminder(payload: ReminderCreateSchema):
    try:
        # Validate that due_time can be parsed or is in ISO format
        datetime.fromisoformat(payload.due_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ISO8601 date string format.")
        
    return database.create_reminder(
        title=payload.title,
        content=payload.content,
        due_time=payload.due_time,
        source_email_id=payload.source_email_id,
        source_email_subject=payload.source_email_subject
    )

@app.put("/api/reminders/{id}/status")
def edit_reminder_status(id: int, status: str):
    if status not in ["pending", "triggered", "completed"]:
        raise HTTPException(status_code=400, detail="Invalid status option.")
    rem = database.update_reminder_status(id, status)
    if not rem:
        raise HTTPException(status_code=404, detail="Reminder not found.")
    return rem

@app.post("/api/reminders/{id}/snooze")
def trigger_snooze(id: int, payload: SnoozeSchema):
    rem = database.snooze_reminder(id, payload.minutes)
    if not rem:
        raise HTTPException(status_code=404, detail="Reminder not found.")
    return rem

@app.delete("/api/reminders/{id}")
def remove_reminder(id: int):
    success = database.delete_reminder(id)
    if not success:
        raise HTTPException(status_code=404, detail="Reminder not found.")
    return {"message": "Reminder successfully removed."}

@app.post("/api/inbox/scan")
async def scan_inbox():
    settings = database.get_settings()
    auth_mode = settings.get('auth_mode', 'sandbox')
    
    if auth_mode == "sandbox":
        # Return mock sandbox data immediately
        mock_inbox = [
            {
                "uid": "sb_101",
                "subject": "📝 Urgent: Review and submit Q3 Sales Contract",
                "sender": "contracts@acmeglobal.com",
                "body": "Hi there, please review the final Q3 sales draft and submit it before tomorrow at 5 PM so that we can close the transaction. Let me know if you run into any formatting or pricing errors. Thanks, Amy.",
                "body_preview": "Hi there, please review the final Q3 sales draft and submit it before tomorrow at 5 PM so that we can close...",
                "parsed_action": "Review the final Q3 sales draft and submit it",
                "parsed_due": (datetime.now() + asyncio.subprocess.sys.modules['datetime'].timedelta(days=1)).replace(hour=17, minute=0, second=0).isoformat()
            },
            {
                "uid": "sb_102",
                "subject": "💻 Weekly Dev Team Sync Meeting Invitation",
                "sender": "shivam.lead@rentbike.com",
                "body": "Hi Team, let's connect for our weekly synchronization meeting on next Monday at 10:00 AM in the primary workspace room. Remember to update your sprint tasks before the start of the call.",
                "body_preview": "Hi Team, let's connect for our weekly synchronization meeting on next Monday at 10:00 AM in the primary...",
                "parsed_action": "Connect for our weekly synchronization meeting",
                "parsed_due": "" # Let parser engine re-generate dynamically
            },
            {
                "uid": "sb_103",
                "subject": "⚠️ Server Alert: High Memory Usage Warning",
                "sender": "noc-monitor@cloudplatform.org",
                "body": "Alert: Production Node #5 has exceeded 92% memory utilization. Please check memory leaks in our worker script immediately and resolve before we encounter crashing.",
                "body_preview": "Alert: Production Node #5 has exceeded 92% memory utilization. Please check memory leaks in our worker...",
                "parsed_action": "Check memory leaks in our worker script immediately",
                "parsed_due": (datetime.now() + asyncio.subprocess.sys.modules['datetime'].timedelta(minutes=30)).isoformat()
            },
            {
                "uid": "sb_104",
                "subject": "🎨 Client Feedback regarding Shivam Bike Rent portal",
                "sender": "client.consultant@bikediscover.com",
                "body": "Hi team, the client reviewed our newest interactive gravity features and requested minor typography improvements. Please send the updated layouts in 2 hours to avoid project delays.",
                "body_preview": "Hi team, the client reviewed our newest interactive gravity features and requested minor typography...",
                "parsed_action": "Send the updated layouts",
                "parsed_due": (datetime.now() + asyncio.subprocess.sys.modules['datetime'].timedelta(hours=2)).isoformat()
            }
        ]
        
        # Hydrate dynamic dates in the sandbox mock so it is always current relative to real time!
        for mock in mock_inbox:
            action, suggested = parser.extract_action_items(mock['body'], mock['subject'])
            mock['parsed_action'] = action
            mock['parsed_due'] = suggested
            
        return mock_inbox
    elif auth_mode == "oauth":
        if not settings.get('oauth_refresh_token'):
            raise HTTPException(status_code=400, detail="Google OAuth is not authorized. Please authorize in settings panel.")
        try:
            import gmail_api
            loop = asyncio.get_running_loop()
            scanned_emails = await loop.run_in_executor(None, gmail_api.gmail_scan_inbox, settings)
            return scanned_emails
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Gmail API retrieval error: {str(e)}")
    else:
        # Run active Gmail scanning via IMAP in separate executor
        if not settings.get('email') or not settings.get('app_password'):
            raise HTTPException(status_code=400, detail="Active Mode requires Email Address and App Password settings.")
            
        try:
            loop = asyncio.get_running_loop()
            scanned_emails = await loop.run_in_executor(None, run_imap_scan, settings)
            return scanned_emails
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"IMAP retrieval error: {str(e)}")


@app.post("/api/inbox/mark-processed/{uid}")
def mark_processed(uid: str):
    database.mark_email_processed(uid)
    return {"status": "success"}

# Server Sent Events endpoint for live toast notifications
@app.get("/api/realtime-events")
async def sse_events(request: Request):
    async def sse_generator():
        queue = asyncio.Queue()
        listeners.append(queue)
        print(f"[SSE] Frontend listener connected. Active connections: {len(listeners)}")
        try:
            while True:
                # Disconnect check
                if await request.is_disconnected():
                    break
                # Fetch pending event
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    # Send blank heartbeats to maintain connection
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in listeners:
                listeners.remove(queue)
            print(f"[SSE] Frontend listener disconnected. Active connections: {len(listeners)}")

    return StreamingResponse(sse_generator(), media_type="text/event-stream")

# --- GOOGLE OAUTH 2.0 HANDSHAKE ROUTING ---

@app.get("/api/auth/url")
def get_auth_url():
    settings = database.get_settings()
    client_id = settings.get('oauth_client_id')
    if not client_id:
        raise HTTPException(status_code=400, detail="OAuth Client ID is not configured. Go to Configurations to save your Client ID first.")
        
    redirect_uri = "http://localhost:8000/api/auth/callback"
    scopes = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send"
    
    url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        "response_type=code"
        f"&client_id={urllib.parse.quote(client_id)}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&scope={urllib.parse.quote(scopes)}"
        "&access_type=offline"
        "&prompt=consent"
    )
    return {"url": url}

@app.get("/api/auth/callback")
def auth_callback(code: Optional[str] = None, error: Optional[str] = None):
    if error:
        return StreamingResponse(
            io.BytesIO(f"""
            <html>
            <body style="font-family: sans-serif; text-align: center; padding: 50px; background-color: #0b0e22; color: #fff;">
                <h1 style="color: #ef4444;">❌ Authorization Failed!</h1>
                <p>Error details: {error}</p>
                <button onclick="window.close()" style="background-color: #ef4444; border: none; padding: 10px 20px; color: white; border-radius: 5px; cursor: pointer; margin-top: 20px;">Close Window</button>
            </body>
            </html>
            """.encode('utf-8')),
            media_type="text/html"
        )
        
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code is missing.")
        
    settings = database.get_settings()
    client_id = settings.get('oauth_client_id')
    client_secret = settings.get('oauth_client_secret')
    
    if not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="OAuth client credentials are not configured in settings.")
        
    # Exchange authorization code for tokens
    import gmail_api
    url = "https://oauth2.googleapis.com/token"
    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": "http://localhost:8000/api/auth/callback",
        "grant_type": "authorization_code"
    }
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    try:
        status, response_text = gmail_api.make_http_request(url, method="POST", data=payload, headers=headers)
        res_json = json.loads(response_text)
        
        access_token = res_json.get("access_token")
        refresh_token = res_json.get("refresh_token")
        expires_in = res_json.get("expires_in", 3600)
        
        if not access_token:
            raise Exception("Access token missing in token exchange response.")
            
        expires_at = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
        
        # Save tokens
        database.save_oauth_tokens(access_token, refresh_token, expires_at)
        
        # Switch authentication mode to OAuth automatically!
        db_settings = database.get_settings()
        db_settings['auth_mode'] = 'oauth'
        database.save_settings(db_settings)
        
    except Exception as exchange_err:
        return StreamingResponse(
            io.BytesIO(f"""
            <html>
            <body style="font-family: sans-serif; text-align: center; padding: 50px; background-color: #0b0e22; color: #fff;">
                <h1 style="color: #ef4444;">❌ Token Exchange Failed!</h1>
                <p>Details: {str(exchange_err)}</p>
                <button onclick="window.close()" style="background-color: #ef4444; border: none; padding: 10px 20px; color: white; border-radius: 5px; cursor: pointer; margin-top: 20px;">Close Window</button>
            </body>
            </html>
            """.encode('utf-8')),
            media_type="text/html"
        )
        
    success_html = """
    <html>
    <body style="font-family: sans-serif; text-align: center; padding: 60px; background-color: #0b0e22; color: #fff;">
        <div style="max-width: 450px; margin: 0 auto; background-color: #12183a; border-radius: 16px; padding: 30px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); border: 1px solid #4f46e5;">
            <span style="font-size: 60px; color: #10b981;">✔</span>
            <h1 style="color: #818cf8; margin-top: 10px;">Authorization Successful!</h1>
            <p style="color: #94a3b8; font-size: 15px; line-height: 1.5;">Your Gmail Reminder System is successfully authorized. Your browser dashboard is now active.</p>
            <p style="color: #6366f1; font-weight: bold; font-size: 14px;">Closing in 3 seconds...</p>
        </div>
        <script>
            // Tell dashboard to refresh
            if (window.opener) {
                window.opener.postMessage("oauth_authorized", "*");
            }
            setTimeout(function() { window.close(); }, 3000);
        </script>
    </body>
    </html>
    """
    return StreamingResponse(io.BytesIO(success_html.encode('utf-8')), media_type="text/html")

@app.get("/api/cron/check")
async def cron_check():
    """
    Special endpoint for Vercel Cron Jobs to trigger pending reminders.
    Since Vercel is serverless, persistent background tasks cannot run 24/7.
    A Vercel Cron Job hits this endpoint periodically to dispatch due alerts.
    """
    try:
        pending = database.get_reminders(status="pending")
        now_str = datetime.now().isoformat()
        triggered_count = 0
        
        for reminder in pending:
            if reminder['due_time'] <= now_str:
                print(f"[Cron] Triggering reminder #{reminder['id']}: '{reminder['title']}'")
                updated = database.update_reminder_status(reminder['id'], "triggered")
                triggered_count += 1
                
                # Send Event to SSE if any listener is active
                event_msg = json.dumps({
                    "event": "reminder_triggered",
                    "reminder": updated
                })
                for listener in list(listeners):
                    try:
                        await listener.put(event_msg)
                    except Exception:
                        pass
                
                # Send email
                settings = database.get_settings()
                if settings:
                    auth_mode = settings.get('auth_mode', 'sandbox')
                    if auth_mode == "oauth" and settings.get('oauth_refresh_token'):
                        import gmail_api
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(None, gmail_api.gmail_send_email, settings, updated)
                    elif auth_mode == "app_password" or (auth_mode == "sandbox" and not settings['sandbox_mode']):
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(None, send_smtp_email, settings, updated)
                        
        return {"status": "success", "triggered_reminders": triggered_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Mount frontend files dynamically *after* defining API routes

FRONTEND_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend"))
if os.path.exists(FRONTEND_PATH):
    app.mount("/", StaticFiles(directory=FRONTEND_PATH, html=True), name="frontend")
else:
    print(f"WARNING: Frontend path '{FRONTEND_PATH}' not found. APIs will work but UI dashboard won't serve from this server.")

