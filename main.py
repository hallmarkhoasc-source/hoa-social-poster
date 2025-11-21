import os
import sys
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from anthropic import Anthropic
import requests

class HOAPoster:
    def __init__(self):
        # Facebook credentials
        self.fb_token = os.getenv('FACEBOOK_ACCESS_TOKEN')
        self.group_id = os.getenv('FACEBOOK_GROUP_ID')
        
        # Anthropic API
        self.anthropic = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        
        # Google Calendar setup
        self.calendar_service = None
        if self.has_google_credentials():
            self.calendar_service = self.setup_google_calendar()
    
    def has_google_credentials(self):
        """Check if Google credentials are available"""
        return all([
            os.getenv('GOOGLE_CLIENT_ID'),
            os.getenv('GOOGLE_CLIENT_SECRET'),
            os.getenv('GOOGLE_REFRESH_TOKEN')
        ])
    
    def setup_google_calendar(self):
        """Initialize Google Calendar API"""
        try:
            creds = Credentials(
                token=None,
                refresh_token=os.getenv('GOOGLE_REFRESH_TOKEN'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=os.getenv('GOOGLE_CLIENT_ID'),
                client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
                scopes=['https://www.googleapis.com/auth/calendar.readonly']
            )
            return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            print(f"Error setting up Google Calendar: {e}")
            return None
    
    def get_upcoming_events(self, days_ahead=7):
        """Fetch upcoming events from Google Calendar"""
        if not self.calendar_service:
            print("Google Calendar not configured")
            return []
        
        try:
            now = datetime.utcnow().isoformat() + 'Z'
            future = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + 'Z'
            
            events_result = self.calendar_service.events().list(
                calendarId='primary',
                timeMin=now,
                timeMax=future,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            return events_result.get('items', [])
        except Exception as e:
            print(f"Error fetching calendar events: {e}")
            return []
    
    def generate_post_content(self, topic, context=""):
        """Use Claude to generate post content"""
        prompt = f"""Generate a friendly, concise Facebook post for an HOA community group about: {topic}

Additional context: {context}

Requirements:
- Keep it conversational and neighborly
- Include relevant details
- End with a call to action if appropriate
- Keep it under 300 words
- Don't use hashtags unless very relevant
- Use a warm, community-focused tone"""

        try:
            message = self.anthropic.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
        except Exception as e:
            print(f"Error generating content: {e}")
            return None
    
    def generate_event_post(self, event):
        """Generate a post about a calendar event"""
        event_name = event.get('summary', 'HOA Event')
        event_start = event.get('start', {})
        event_time = event_start.get('dateTime', event_start.get('date', ''))
        event_location = event.get('location', '')
        event_description = event.get('description', '')
        
        # Parse the date/time for better formatting
        try:
            if 'T' in event_time:  # DateTime
                dt = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
                formatted_time = dt.strftime('%A, %B %d at %I:%M %p')
            else:  # All-day event
                dt = datetime.fromisoformat(event_time)
                formatted_time = dt.strftime('%A, %B %d')
        except:
            formatted_time = event_time
        
        prompt = f"""Generate a friendly Facebook post announcing this HOA event:

Event: {event_name}
Time: {formatted_time}
Location: {event_location}
Details: {event_description}

Make it engaging and include key details residents need to know. Keep it under 250 words."""

        try:
            message = self.anthropic.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
        except Exception as e:
            print(f"Error generating event post: {e}")
            return None
    
    def post_to_facebook(self, message):
        """Post message to Facebook group"""
        url = f"https://graph.facebook.com/v21.0/{self.group_id}/feed"
        
        payload = {
            'message': message,
            'access_token': self.fb_token
        }
        
        try:
            response = requests.post(url, data=payload)
            
            if response.status_code == 200:
                post_id = response.json().get('id')
                print(f"✓ Posted successfully! Post ID: {post_id}")
                return True
            else:
                print(f"✗ Error posting: {response.json()}")
                return False
        except Exception as e:
            print(f"✗ Error posting to Facebook: {e}")
            return False
    
    def create_and_post(self, topic, context=""):
        """Generate content and post"""
        print(f"\n{'='*60}")
        print(f"Generating post about: {topic}")
        print(f"{'='*60}\n")
        
        content = self.generate_post_content(topic, context)
        
        if not content:
            print("Failed to generate content")
            return False
        
        print("Generated content:")
        print("-" * 60)
        print(content)
        print("-" * 60)
        
        return self.post_to_facebook(content)
    
    def check_and_post_event_reminders(self):
        """Check for upcoming events and post reminders"""
        print("\n" + "="*60)
        print("Checking for upcoming events...")
        print("="*60 + "\n")
        
        events = self.get_upcoming_events(days_ahead=3)
        
        if not events:
            print("No upcoming events found in the next 3 days")
            return
        
        print(f"Found {len(events)} upcoming event(s)")
        
        for event in events:
            event_name = event.get('summary', 'Unnamed Event')
            print(f"\nProcessing event: {event_name}")
            
            content = self.generate_event_post(event)
            
            if content:
                print("\nGenerated content:")
                print("-" * 60)
                print(content)
                print("-" * 60)
                
                success = self.post_to_facebook(content)
                if success:
                    print(f"✓ Posted reminder for: {event_name}")
                else:
                    print(f"✗ Failed to post reminder for: {event_name}")
            else:
                print(f"✗ Failed to generate content for: {event_name}")

def main():
    """Main execution function"""
    poster = HOAPoster()
    
    # Check what mode we're running in
    mode = os.getenv('RUN_MODE', 'calendar')  # default to calendar check
    
    if mode == 'calendar':
        # Check calendar and post about upcoming events
        poster.check_and_post_event_reminders()
    
    elif mode == 'custom':
        # Post a custom message
        topic = os.getenv('POST_TOPIC', 'General HOA update')
        context = os.getenv('POST_CONTEXT', '')
        poster.create_and_post(topic, context)
    
    else:
        print(f"Unknown mode: {mode}")
        print("Set RUN_MODE to 'calendar' or 'custom'")

if __name__ == "__main__":
    main()
```

### **Step 4: Upload main.py to GitHub**

1. Go to your GitHub repository
2. Click "Add file" → "Create new file"
3. Name it `main.py`
4. Paste the code above
5. Click "Commit changes"

### **Step 5: Connect Render to GitHub**

1. Log in to https://dashboard.render.com
2. Click "New +" button in top right
3. Select "Cron Job"
4. Click "Connect account" under GitHub
5. Authorize Render to access your GitHub
6. Select your `hoa-social-poster` repository

### **Step 6: Configure the Cron Job**

Fill in these settings:

**Basic Settings:**
- **Name:** `hoa-poster`
- **Region:** Oregon (US West) - or closest to you
- **Branch:** `main`
- **Runtime:** Python 3

**Build Settings:**
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python main.py`

**Schedule:**
- **Schedule:** `0 9 * * *` (runs daily at 9 AM UTC)
  - Or customize: `0 9,18 * * *` (9 AM and 6 PM UTC)
  - [Use this tool to help](https://crontab.guru/)

**Instance Type:**
- **Plan:** Free

Click "Create Cron Job" (don't worry, we'll add environment variables next)

### **Step 7: Add Environment Variables**

After creating the cron job:

1. You'll be on your cron job dashboard
2. Click "Environment" in the left sidebar
3. Click "Add Environment Variable"
4. Add each of these:
```
Key: FACEBOOK_ACCESS_TOKEN
Value: [your Facebook token]

Key: FACEBOOK_GROUP_ID
Value: [your Facebook group ID]

Key: ANTHROPIC_API_KEY
Value: [your Anthropic API key]

Key: GOOGLE_CLIENT_ID
Value: [from your tokens.txt file]

Key: GOOGLE_CLIENT_SECRET
Value: [from your tokens.txt file]

Key: GOOGLE_REFRESH_TOKEN
Value: [from your tokens.txt file]

Key: RUN_MODE
Value: calendar