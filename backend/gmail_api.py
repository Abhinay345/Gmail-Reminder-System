import os
import json
import urllib.request
import urllib.parse
import base64
from datetime import datetime, timedelta
import database
import parser

def make_http_request(url, method="GET", data=None, headers=None):
    """
    Utility function to make HTTP requests using native Python urllib.
    Avoids third-party dependencies like 'requests' for maximum reliability.
    """
    if headers is None:
        headers = {}
        
    req_data = None
    if data is not None:
        if isinstance(data, dict):
            # Encode form-urlencoded data or json based on Content-Type
            if headers.get("Content-Type") == "application/json":
                req_data = json.dumps(data).encode("utf-8")
            else:
                req_data = urllib.parse.urlencode(data).encode("utf-8")
        elif isinstance(data, str):
            req_data = data.encode("utf-8")
        else:
            req_data = data
            
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = response.read()
            # Decode response
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, res_data.decode(charset, errors="ignore")
    except urllib.error.HTTPError as http_err:
        err_msg = http_err.read().decode("utf-8", errors="ignore")
        print(f"[HTTP Error] {http_err.code} {http_err.reason}: {err_msg}")
        raise Exception(f"HTTP {http_err.code}: {err_msg}")
    except Exception as e:
        print(f"[Network Error] {e}")
        raise e

def refresh_oauth_token(settings):
    """
    Validates the active access token expiration.
    Refreshes automatically if expired using stored refresh_token.
    """
    access_token = settings.get("oauth_access_token")
    expires_at_str = settings.get("oauth_token_expires_at")
    refresh_token = settings.get("oauth_refresh_token")
    client_id = settings.get("oauth_client_id")
    client_secret = settings.get("oauth_client_secret")
    
    if not refresh_token or not client_id or not client_secret:
        raise Exception("Google OAuth settings are incomplete or unauthorized.")
        
    is_expired = True
    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            # Add a 60-second buffer to prevent mid-operation expiration
            if expires_at > datetime.now() + timedelta(seconds=60):
                is_expired = False
        except ValueError:
            pass
            
    if not is_expired and access_token:
        return access_token
        
    print("[OAuth] Access token expired or near-expiry. Refreshing token silently...")
    
    # Execute Token Exchange request
    url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    status, response_text = make_http_request(url, method="POST", data=payload, headers=headers)
    res_json = json.loads(response_text)
    
    new_access_token = res_json.get("access_token")
    expires_in = res_json.get("expires_in", 3600)
    
    if not new_access_token:
        raise Exception(f"Could not refresh access token. Response: {response_text}")
        
    new_expires_at = (datetime.now() + timedelta(seconds=expires_in)).isoformat()
    
    # Save back to database
    database.save_oauth_tokens(new_access_token, None, new_expires_at)
    print("[OAuth] Silently refreshed and saved new Access Token.")
    
    return new_access_token

def decode_gmail_body_part(part_data):
    """
    Recursively decodes nested message body parts from Gmail API format.
    """
    body_data = part_data.get("body", {})
    mime_type = part_data.get("mimeType", "")
    
    # If this part contains nested sub-parts, crawl them
    if "parts" in part_data:
        text_content = ""
        html_content = ""
        for sub_part in part_data["parts"]:
            sub_mime, sub_text = decode_gmail_body_part(sub_part)
            if sub_mime == "text/plain":
                text_content += sub_text
            elif sub_mime == "text/html":
                html_content += sub_text
                
        # Prefer plain text if both exist, otherwise return html
        if text_content:
            return "text/plain", text_content
        return "text/html", html_content
        
    # Standard leaf node part
    raw_b64 = body_data.get("data")
    if not raw_b64:
        return mime_type, ""
        
    # Decode Gmail's base64url encoding
    decoded_bytes = base64.urlsafe_b64decode(raw_b64.encode("utf-8"))
    decoded_str = decoded_bytes.decode("utf-8", errors="ignore")
    return mime_type, decoded_str

def gmail_scan_inbox(settings):
    """
    Connects to the official Google Gmail REST API to retrieve
    actionable unseen inbox messages.
    """
    access_token = refresh_oauth_token(settings)
    
    # Step 1: List all unread message IDs in user's inbox
    list_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages?q=is:unread"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    status, response_text = make_http_request(list_url, method="GET", headers=headers)
    res_json = json.loads(response_text)
    
    messages = res_json.get("messages", [])
    print(f"[Gmail API] Found {len(messages)} unread messages in inbox.")
    
    results = []
    # Fetch content for the last 15 unread messages to keep it fast
    for item in messages[:15]:
        msg_id = item.get("id")
        
        # Prevent re-scanning already scheduled emails
        if database.is_email_processed(msg_id):
            continue
            
        # Step 2: Retrieve full email content details
        msg_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}"
        try:
            msg_status, msg_text = make_http_request(msg_url, method="GET", headers=headers)
            msg_json = json.loads(msg_text)
            
            headers_list = msg_json.get("payload", {}).get("headers", [])
            
            # Extract Subject & Sender fields
            subject = ""
            sender = ""
            for h in headers_list:
                name = h.get("name", "").lower()
                if name == "subject":
                    subject = h.get("value", "")
                elif name == "from":
                    sender = h.get("value", "")
                    
            # Extract message body
            payload = msg_json.get("payload", {})
            mime_type, body = decode_gmail_body_part(payload)
            
            clean_body = parser.clean_html(body)
            action, suggested_due = parser.extract_action_items(clean_body, subject)
            
            results.append({
                "uid": msg_id,
                "subject": subject,
                "sender": sender,
                "body": clean_body,
                "body_preview": clean_body[:180] + "..." if len(clean_body) > 180 else clean_body,
                "parsed_action": action,
                "parsed_due": suggested_due
            })
        except Exception as msg_err:
            print(f"[Gmail API] Error fetching message {msg_id}: {msg_err}")
            
    return results

def gmail_send_email(settings, reminder):
    """
    Constructs a styled HTML email and sends it securely via Google's official Gmail REST API.
    """
    access_token = refresh_oauth_token(settings)
    sender = settings.get("email")
    
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    
    # 1. Construct MIME multipart email
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"🔔 REMINDER: {reminder['title']}"
    msg['From'] = f"Gmail Reminder System <{sender}>"
    msg['To'] = sender  # Self-reminder
    
    html = f"""
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f3f4f6; padding: 24px; margin: 0;">
        <div style="max-width: 580px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -4px rgba(0, 0, 0, 0.05); border: 1px solid #e5e7eb;">
            <div style="background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%); padding: 32px; text-align: center; color: #ffffff;">
                <span style="font-size: 56px; line-height: 1;">🔔</span>
                <h1 style="margin: 16px 0 0 0; font-size: 26px; font-weight: 800; letter-spacing: -0.025em;">Gmail API OAuth Alert!</h1>
                <p style="margin: 8px 0 0 0; color: #c7d2fe; font-size: 14px;">Your secure OAuth 2.0 dispatch is successful</p>
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
                This secure message was dispatched via your local Google OAuth 2.0 integration.<br>
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
    
    # 2. Encode to base64url format required by Gmail API
    raw_bytes = msg.as_bytes()
    encoded_message = base64.urlsafe_b64encode(raw_bytes).decode('utf-8')
    
    send_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "raw": encoded_message
    }
    
    status, response_text = make_http_request(send_url, method="POST", data=payload, headers=headers)
    print(f"[Gmail API] Successfully sent HTML alert email for reminder #{reminder['id']}. Status code: {status}")
