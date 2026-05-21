import re
from datetime import datetime, timedelta

def clean_html(html_text):
    """
    Simplifies HTML content to plain text.
    """
    if not html_text:
        return ""
    # Strip scripts and style
    text = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', html_text, flags=re.IGNORECASE)
    text = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', text, flags=re.IGNORECASE)
    # Replace HTML linebreaks with newlines
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode basic entities
    text = text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    # Clean up whitespace
    lines = [line.strip() for line in text.split('\n')]
    return "\n".join([l for l in lines if l])

def parse_date_expression(text, base_time=None):
    """
    Parses natural language date patterns and returns a datetime object.
    Supports:
    - 'in X minutes', 'in Y hours', 'in Z days'
    - 'tomorrow at 5 PM', 'tomorrow at 10:30 am'
    - 'today at 4 PM', 'by 6:00 pm'
    - 'next monday at 11 am', 'next friday'
    - 'on 2026-05-25' or 'May 25'
    """
    if not base_time:
        base_time = datetime.now()
        
    text = text.lower().strip()
    
    # 1. "in X minutes" / "in Y hours" / "in Z days"
    in_pattern = re.search(r'\bin\s+(\d+)\s+(minute|min|hour|hr|day|wk|week)s?\b', text)
    if in_pattern:
        amount = int(in_pattern.group(1))
        unit = in_pattern.group(2)
        if 'minute' in unit or 'min' in unit:
            return base_time + timedelta(minutes=amount)
        elif 'hour' in unit or 'hr' in unit:
            return base_time + timedelta(hours=amount)
        elif 'day' in unit:
            return base_time + timedelta(days=amount)
        elif 'week' in unit or 'wk' in unit:
            return base_time + timedelta(weeks=amount)
            
    # Helper to parse time strings like "5:30 pm", "10 am", "15:00"
    def parse_time_str(time_str):
        time_str = time_str.strip().lower()
        match = re.match(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', time_str)
        if not match:
            return 9, 0  # Default 9:00 AM
        
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else 0
        ampm = match.group(3)
        
        if ampm == 'pm' and hour < 12:
            hour += 12
        elif ampm == 'am' and hour == 12:
            hour = 0
            
        return hour, minute

    # 2. "tomorrow" / "today" + optional time
    # e.g., "tomorrow at 3 PM", "tomorrow at 15:00", "tomorrow"
    day_match = re.search(r'\b(today|tomorrow)\b(?:\s+(?:at|by)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?', text)
    if day_match:
        day_type = day_match.group(1)
        time_str = day_match.group(2)
        
        target_date = base_time
        if day_type == 'tomorrow':
            target_date = base_time + timedelta(days=1)
            
        if time_str:
            h, m = parse_time_str(time_str)
            return target_date.replace(hour=h, minute=m, second=0, microsecond=0)
        else:
            # Fallback to tomorrow/today at same hour or +1 hour
            return target_date + timedelta(hours=1)

    # 3. "next [weekday]"
    # e.g., "next monday at 10 AM", "next friday"
    weekdays = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6
    }
    weekday_pattern = r'\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b(?:\s+(?:at|by)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?'
    weekday_match = re.search(weekday_pattern, text)
    if weekday_match:
        target_day_name = weekday_match.group(1)
        time_str = weekday_match.group(2)
        
        target_day_num = weekdays[target_day_name]
        curr_day_num = base_time.weekday()
        
        days_ahead = target_day_num - curr_day_num
        if days_ahead <= 0: # Target is next week
            days_ahead += 7
            
        target_date = base_time + timedelta(days=days_ahead)
        if time_str:
            h, m = parse_time_str(time_str)
            return target_date.replace(hour=h, minute=m, second=0, microsecond=0)
        else:
            return target_date.replace(hour=9, minute=0, second=0, microsecond=0)

    # 4. Standard ISO / exact date: "YYYY-MM-DD"
    iso_match = re.search(r'\b(\d{4})-(\d{2})-(\d{2})\b(?:\s+(?:at|by)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?', text)
    if iso_match:
        y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        time_str = iso_match.group(4)
        target_date = datetime(y, m, d)
        if time_str:
            h, m_val = parse_time_str(time_str)
            return target_date.replace(hour=h, minute=m_val, second=0, microsecond=0)
        else:
            return target_date.replace(hour=9, minute=0, second=0, microsecond=0)

    # 5. Month name: "May 25", "25 May", "May 25th at 3pm"
    months = {
        'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
        'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
        'aug': 8, 'august': 8, 'sep': 9, 'september': 9, 'oct': 10, 'october': 10,
        'nov': 11, 'november': 11, 'dec': 12, 'december': 12
    }
    month_pattern = r'\b(jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|september|oct|october|nov|november|dec|december)\b\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s+(?:at|by)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?'
    month_match = re.search(month_pattern, text)
    if month_match:
        m_name = month_match.group(1)
        day_num = int(month_match.group(2))
        time_str = month_match.group(3)
        
        m_num = months[m_name]
        # Assume current year, or next year if month already passed
        year = base_time.year
        if m_num < base_time.month or (m_num == base_time.month and day_num < base_time.day):
            year += 1
            
        try:
            target_date = datetime(year, m_num, day_num)
            if time_str:
                h, m_val = parse_time_str(time_str)
                return target_date.replace(hour=h, minute=m_val, second=0, microsecond=0)
            else:
                return target_date.replace(hour=9, minute=0, second=0, microsecond=0)
        except ValueError:
            pass # Invalid day of month (e.g. Feb 30)

    # Fallback to tomorrow if none matches but date references exist
    if any(keyword in text for keyword in ['due', 'deadline', 'remind', 'before', 'by the time', 'meeting at']):
        # Scan for just a plain time e.g. "at 4 PM" -> assume today or tomorrow
        time_only_match = re.search(r'\b(?:at|by)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b', text)
        if time_only_match:
            h, m = parse_time_str(time_only_match.group(1))
            candidate = base_time.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidate < base_time: # If past, assume tomorrow
                candidate += timedelta(days=1)
            return candidate

    return None

def extract_action_items(text, subject=""):
    """
    Parses text content to identify core actions and descriptions.
    Returns: (title, suggested_due_time)
    """
    clean_text = clean_html(text)
    
    # Let's search line by line or phrase by phrase for strong actionable tasks
    action_prefixes = [
        r'\bplease\s+(?:review|check|send|call|email|submit|update|complete|fix|schedule|buy|create)\b',
        r'\bremember\s+to\b',
        r'\bneed\s+to\b',
        r'\baction\s+item:?\b',
        r'\bdue\s+date:?\b',
        r'\bdeadline\s+is\b',
        r'\bmeeting\s+about\b'
    ]
    
    # Try to find a specific task line
    sentences = re.split(r'[.!?\n]', clean_text)
    best_task = ""
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        
        # Check action prefixes
        for prefix in action_prefixes:
            match = re.search(prefix, sentence, flags=re.IGNORECASE)
            if match:
                # Capture the rest of the sentence as the task
                task_content = sentence[match.start():].strip()
                if len(task_content) > 5 and len(task_content) < 80:
                    best_task = task_content
                    break
        if best_task:
            break
            
    # Capitalize first letter
    if best_task:
        best_task = best_task[0].upper() + best_task[1:]
    else:
        # Fallback to subject line if available, else first line
        if subject:
            best_task = subject
        else:
            first_line = next((line.strip() for line in clean_text.split('\n') if line.strip()), "Email Task")
            best_task = first_line[:50] + "..." if len(first_line) > 50 else first_line
            
    # Try to find date/time in the email text
    due_time = parse_date_expression(clean_text)
    if not due_time and subject:
        # Check subject as well
        due_time = parse_date_expression(subject)
        
    # If still no due_time, default to tomorrow at 9 AM
    if not due_time:
        due_time = datetime.now() + timedelta(days=1)
        due_time = due_time.replace(hour=9, minute=0, second=0, microsecond=0)
        
    return best_task, due_time.isoformat()
