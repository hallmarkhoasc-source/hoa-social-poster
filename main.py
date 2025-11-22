import os
import sys
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import google.generativeai as genai
import requests

class HOAPoster:
    def __init__(self):
    # Facebook credentials
    self.fb_token = os.getenv('FACEBOOK_ACCESS_TOKEN')
    self.page_id = None
    
    # Get Page ID
    if self.fb_token:
        self.page_id = self.get_page_id()
    
    # Gemini API setup
    genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
    self.model = genai.GenerativeModel('gemini-2.0-flash-lite')
    
    # Google Calendar setup
    self.calendar_service = None
    if self.has_google_credentials():
        self.calendar_service = self.setup_google_calendar()

    def get_page_id(self):
        """Get the Facebook Page ID"""
        try:
            url = f"https://graph.facebook.com/v21.0/me?access_token={self.fb_token}"
            response = requests.get(url)
            if response.status_code == 200:
                page_id = response.json().get('id')
                print(f"Page ID: {page_id}")
                return page_id
            else:
                print(f"Error getting Page ID: {response.json()}")
                return None
        except Exception as e:
            print(f"Error getting Page ID: {e}")
            return None
  
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
        """Use Gemini to generate post content"""
        prompt = f"""Generate a friendly, professional Facebook post for Hallmark HOA community about: {topic}

Additional context: {context}

Requirements:
- Write in a warm, neighborly tone appropriate for a homeowners association
- Keep it conversational but professional
- Include relevant details clearly
- Keep it under 250 words
- End with a call to action if appropriate
- Use 1-2 relevant hashtags maximum (like #HallmarkHOA)
- Do NOT use placeholder text or brackets
- Do NOT mention virtual events unless specifically requested
- Do NOT use excessive emojis (1-2 maximum)"""

        try:
            response = self.model.generate_content(prompt)
            return response.text
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
        
        prompt = f"""You are writing social media posts for Hallmark HOA, a residential community. 
Your posts should be friendly, professional, and informative - helping neighbors stay connected 
and informed about community matters.

Generate a Facebook post announcing this HOA community event:

Event: {event_name}
Time: {formatted_time}
Location: {event_location}
Details: {event_description}

Requirements:
- Warm, neighborly tone
- Include all key details (what, when, where)
- Under 200 words
- Clear call to action (e.g., "See you there!" or "Mark your calendars!")
- Maximum 2-3 hashtags (like #HallmarkHOA #CommunityEvent)
- No placeholder text or virtual event mentions
- 1-2 emojis maximum"""

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"Error generating event post: {e}")
            return None
    
    def create_facebook_event(self, event):
    """Create a Facebook Event from a calendar event"""
    
    if not self.page_id:
        print("Page ID not available")
        return False
    
    event_name = event.get('summary', 'HOA Event')
    event_start = event.get('start', {})
    event_end = event.get('end', {})
    event_location = event.get('location', '')
    event_description = event.get('description', '')
    
    # Parse start time
    start_time = event_start.get('dateTime', event_start.get('date', ''))
    end_time = event_end.get('dateTime', event_end.get('date', ''))
    
    # Convert to Unix timestamp if dateTime, or keep as date string
    try:
        if 'T' in start_time:  # DateTime format
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            start_timestamp = int(start_dt.timestamp())
        else:  # All-day event
            start_dt = datetime.fromisoformat(start_time)
            start_timestamp = start_time  # Facebook accepts YYYY-MM-DD for all-day
            
        if end_time:
            if 'T' in end_time:
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                end_timestamp = int(end_dt.timestamp())
            else:
                end_timestamp = end_time
        else:
            # Default to 2 hours after start if no end time
            if isinstance(start_timestamp, int):
                end_timestamp = start_timestamp + 7200
            else:
                end_timestamp = start_timestamp
    except Exception as e:
        print(f"Error parsing event times: {e}")
        return False
    
    # Generate a description using AI
    description_prompt = f"""Write a brief, friendly description for this HOA community event (2-3 sentences):

Event: {event_name}
Location: {event_location}
Details: {event_description}

Keep it informative and welcoming. Use a warm, neighborly tone."""
    
    try:
        response = self.model.generate_content(description_prompt)
        ai_description = response.text
    except:
        ai_description = event_description or f"Join us for {event_name}!"
    
    # Create the Facebook Event using Page ID
    url = f"https://graph.facebook.com/v21.0/{self.page_id}/events"
    
    payload = {
        'name': event_name,
        'start_time': start_timestamp,
        'end_time': end_timestamp,
        'description': ai_description,
        'access_token': self.fb_token
    }
    
    # Add location if available
    if event_location:
        payload['location'] = event_location
    
    try:
        response = requests.post(url, data=payload)
        
        if response.status_code == 200:
            event_id = response.json().get('id')
            print(f"✓ Created Facebook Event! Event ID: {event_id}")
            return True
        else:
            error_data = response.json()
            print(f"✗ Error creating event: {error_data}")
            return False
    except Exception as e:
        print(f"✗ Error creating Facebook event: {e}")
        return False
    
    def post_to_facebook(self, message):
        """Post message to Facebook Page"""
        # Post to the Page's feed
        url = f"https://graph.facebook.com/v21.0/me/feed"
        
        payload = {
            'message': message,
            'access_token': self.fb_token
        }
        
        try:
            response = requests.post(url, data=payload)
            
            if response.status_code == 200:
                post_id = response.json().get('id')
                print(f"✓ Posted successfully to Page! Post ID: {post_id}")
                return True
            else:
                error_data = response.json()
                print(f"✗ Error posting: {error_data}")
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
        """Check for upcoming events and create Facebook Events + posts"""
        print("\n" + "="*60)
        print("Checking for upcoming events...")
        print("="*60 + "\n")
        
        events = self.get_upcoming_events(days_ahead=7)
        
        if not events:
            print("No upcoming events found in the next 7 days")
            return
        
        print(f"Found {len(events)} upcoming event(s)")
        
        for event in events:
            event_name = event.get('summary', 'Unnamed Event')
            print(f"\nProcessing event: {event_name}")
            
            # Create the Facebook Event
            event_created = self.create_facebook_event(event)
            
            if event_created:
                print(f"✓ Created Facebook Event for: {event_name}")
                
                # Also post an announcement about it
                announcement = self.generate_event_post(event)
                if announcement:
                    print("\nGenerated announcement:")
                    print("-" * 60)
                    print(announcement)
                    print("-" * 60)
                    
                    post_success = self.post_to_facebook(announcement)
                    if post_success:
                        print(f"✓ Posted announcement for: {event_name}")
                    else:
                        print(f"✗ Failed to post announcement for: {event_name}")
                else:
                    print(f"✗ Failed to generate announcement for: {event_name}")
            else:
                print(f"✗ Failed to create Facebook Event for: {event_name}")

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

