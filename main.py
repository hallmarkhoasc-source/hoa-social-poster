import os
import sys
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import google.generativeai as genai
import requests

class HOAPoster:
    def __init__(self):
        print("Initializing HOAPoster class...")
        # Facebook credentials
        self.fb_token = os.getenv('FACEBOOK_ACCESS_TOKEN')
        print(f"Facebook token present: {bool(self.fb_token)}")
        self.page_id = '882966761564424'
        print(f"Page ID: {self.page_id}")
        
        # Facebook credentials
        self.fb_token = os.getenv('FACEBOOK_ACCESS_TOKEN')
        self.page_id = '882966761564424'  # Hallmark HOA Page
    
        # Gemini API setup
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        self.model = genai.GenerativeModel('gemini-2.0-flash-lite')
    
        # Google Calendar setup
        self.calendar_service = None
        if self.has_google_credentials():
            self.calendar_service = self.setup_google_calendar()
    
        # Gmail setup
        self.gmail_service = None
        if self.has_google_credentials():
            self.gmail_service = self.setup_gmail()

        # Google Drive setup
        self.drive_service = None
        if self.has_google_credentials():
            self.drive_service = self.setup_google_drive()
        
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
- Start with a clear event announcement (e.g., "Join us for...")
- Include the date and time on its own line or clearly stated
- Mention the location clearly
- Warm, neighborly tone
- Under 200 words
- Clear call to action (e.g., "See you there!" or "Mark your calendars!")
- Maximum 2-3 hashtags (like #HallmarkHOA #CommunityEvent)
- No placeholder text or virtual event mentions
- 1-2 emojis maximum
- Format should help Facebook detect this as an event (clear date/time/location)"""

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"Error generating event post: {e}")
            return None
    
    def post_to_facebook(self, message):
        """Post message to Facebook Page"""
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
        """Check for upcoming events and post announcements"""
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
            
            # Generate and post announcement
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

    def setup_gmail(self):
        """Initialize Gmail API"""
        try:
            creds = Credentials(
                token=None,
                refresh_token=os.getenv('GOOGLE_REFRESH_TOKEN'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=os.getenv('GOOGLE_CLIENT_ID'),
                client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
                scopes=[
                    'https://www.googleapis.com/auth/calendar.readonly',
                    'https://www.googleapis.com/auth/gmail.readonly',
                    'https://www.googleapis.com/auth/gmail.modify'
                ]
            )
            return build('gmail', 'v1', credentials=creds)
        except Exception as e:
            print(f"Error setting up Gmail: {e}")
            return None
    
    def setup_google_drive(self):
        """Initialize Google Drive API"""
        try:
            creds = Credentials(
                token=None,
                refresh_token=os.getenv('GOOGLE_REFRESH_TOKEN'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=os.getenv('GOOGLE_CLIENT_ID'),
                client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
                scopes=[
                    'https://www.googleapis.com/auth/calendar.readonly',
                    'https://www.googleapis.com/auth/gmail.readonly',
                    'https://www.googleapis.com/auth/gmail.modify',
                    'https://www.googleapis.com/auth/drive.file'
                ]
            )
            return build('drive', 'v3', credentials=creds)
        except Exception as e:
            print(f"Error setting up Google Drive: {e}")
            return None
    
    def check_meeting_minutes_emails(self):
        """Check for new meeting minutes emails and create posts"""
        if not hasattr(self, 'gmail_service') or not self.gmail_service:
            print("Gmail not configured")
            return
    
        print("\n" + "="*60)
        print("Checking for meeting minutes emails...")
        print("="*60 + "\n")
    
        try:
            # Search for unread emails with "meeting minutes" in subject
            query = 'subject:"meeting minutes" is:unread'
            results = self.gmail_service.users().messages().list(
                userId='me',
                q=query,
                maxResults=5
            ).execute()
        
            messages = results.get('messages', [])
        
            if not messages:
                print("No new meeting minutes emails found")
                return
        
            print(f"Found {len(messages)} meeting minutes email(s)")
        
            for msg in messages:
                self.process_meeting_minutes_email(msg['id'])
            
        except Exception as e:
            print(f"Error checking emails: {e}")

    def process_meeting_minutes_email(self, message_id):
        """Process a single meeting minutes email"""
        try:
            # Get the full message
            message = self.gmail_service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            # Extract subject and body
            headers = message['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'Meeting Minutes')
            
            # Get email body
            body = self.get_email_body(message)
            
            print(f"\nProcessing email: {subject}")
            print(f"Body preview: {body[:200]}...")
            
            # Extract and upload PDF attachment
            pdf_filename, pdf_data = self.extract_pdf_attachment(message)
            drive_link = None
            
            if pdf_filename and pdf_data:
                print(f"Found PDF attachment: {pdf_filename}")
                drive_link = self.upload_to_drive(pdf_filename, pdf_data)
            else:
                print("No PDF attachment found")
            
            # Generate post from meeting minutes
            post_content = self.generate_meeting_minutes_post(subject, body, drive_link)
            
            if post_content:
                print("\nGenerated post:")
                print("-" * 60)
                print(post_content)
                print("-" * 60)
                
                # Post to Facebook
                success = self.post_to_facebook(post_content)
                
                if success:
                    print("✓ Posted meeting minutes announcement")
                    # Mark email as read
                    self.gmail_service.users().messages().modify(
                        userId='me',
                        id=message_id,
                        body={'removeLabelIds': ['UNREAD']}
                    ).execute()
                    print("✓ Marked email as read")
                else:
                    print("✗ Failed to post")
            else:
                print("✗ Failed to generate post")
                
        except Exception as e:
            print(f"Error processing email: {e}")

    def get_email_body(self, message):
        """Extract email body text"""
        try:
            if 'parts' in message['payload']:
                # Multipart message
                for part in message['payload']['parts']:
                    if part['mimeType'] == 'text/plain':
                        data = part['body'].get('data', '')
                        if data:
                            import base64
                            return base64.urlsafe_b64decode(data).decode('utf-8')
            else:
                # Simple message
                data = message['payload']['body'].get('data', '')
                if data:
                    import base64
                    return base64.urlsafe_b64decode(data).decode('utf-8')
            return ""
        except Exception as e:
            print(f"Error extracting email body: {e}")
            return ""

    def generate_meeting_minutes_post(self, subject, body, drive_link=None):
        """Generate a Facebook post about meeting minutes"""
        
        link_text = ""
        if drive_link:
            link_text = f"\n\nView the full meeting minutes here: {drive_link}"
        
        prompt = f"""Generate a friendly Facebook post for Hallmark HOA announcing that meeting minutes are available.

Email Subject: {subject}
Email Content (summary): {body[:1000]}

Requirements:
- Announce that the meeting minutes are now available
- Briefly summarize 2-3 key topics discussed (extract from the email content)
- Warm, professional tone
- Keep it under 200 words
- Include a call to action encouraging residents to read the full minutes
- Use 1-2 hashtags like #HallmarkHOA
- 1 emoji maximum
- Do NOT include a link in your response - it will be added automatically"""

        try:
            response = self.model.generate_content(prompt)
            post_text = response.text
            
            # Add the Drive link at the end
            if drive_link:
                post_text += f"\n\n📄 Read the full minutes: {drive_link}"
            
            return post_text
        except Exception as e:
            print(f"Error generating meeting minutes post: {e}")
            return None
            
    def extract_document_attachment(self, message):
        """Extract document attachment (PDF or Word) from email"""
        try:
            parts = message.get('payload', {}).get('parts', [])
            
            for part in parts:
                filename = part.get('filename', '')
                
                # Check if it's a PDF or Word document
                if (filename.lower().endswith('.pdf') or 
                    filename.lower().endswith('.docx') or 
                    filename.lower().endswith('.doc')):
                    
                    attachment_id = part['body'].get('attachmentId')
                    
                    if attachment_id:
                        # Get the attachment
                        attachment = self.gmail_service.users().messages().attachments().get(
                            userId='me',
                            messageId=message['id'],
                            id=attachment_id
                        ).execute()
                        
                        # Decode the attachment data
                        import base64
                        file_data = base64.urlsafe_b64decode(attachment['data'])
                        
                        # Determine MIME type
                        if filename.lower().endswith('.pdf'):
                            mime_type = 'application/pdf'
                        elif filename.lower().endswith('.docx'):
                            mime_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                        else:  # .doc
                            mime_type = 'application/msword'
                        
                        return filename, file_data, mime_type
            
            return None, None, None
        except Exception as e:
            print(f"Error extracting document: {e}")
            return None, None, None
    
    def upload_to_drive(self, filename, file_data):
        """Upload PDF to Google Drive and return shareable link"""
        try:
            from io import BytesIO
            from googleapiclient.http import MediaIoBaseUpload
            
            folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
            
            if not folder_id:
                print("No Google Drive folder ID configured")
                return None
            
            # Create file metadata
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            
            # Upload file
            media = MediaIoBaseUpload(
                BytesIO(file_data),
                mimetype='application/pdf',
                resumable=True
            )
            
            file = self.drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            
            file_id = file.get('id')
            web_link = file.get('webViewLink')
            
            # Make file publicly viewable
            self.drive_service.permissions().create(
                fileId=file_id,
                body={
                    'type': 'anyone',
                    'role': 'reader'
                }
            ).execute()
            
            print(f"✓ Uploaded to Google Drive: {web_link}")
            return web_link
            
        except Exception as e:
            print(f"Error uploading to Drive: {e}")
            return None

def main():
    """Main execution function"""
    print("=" * 60)
    print("HOA POSTER STARTING")
    print("=" * 60)
    
    # Check environment
    mode = os.getenv('RUN_MODE', 'calendar')
    print(f"Run mode: {mode}")
    
    try:
        print("Initializing HOAPoster...")
        poster = HOAPoster()
        print("HOAPoster initialized successfully")
        
        if mode == 'calendar':
            print("Running calendar mode...")
            poster.check_and_post_event_reminders()
        
        elif mode == 'meeting_minutes':
            print("Running meeting minutes mode...")
            poster.check_meeting_minutes_emails()
        
        elif mode == 'both':
            print("Running both calendar and meeting minutes modes...")
            poster.check_and_post_event_reminders()
            poster.check_meeting_minutes_emails()
        
        elif mode == 'custom':
            print("Running custom mode...")
            topic = os.getenv('POST_TOPIC', 'General HOA update')
            context = os.getenv('POST_CONTEXT', '')
            poster.create_and_post(topic, context)
        
        else:
            print(f"Unknown mode: {mode}")
            print("Set RUN_MODE to 'calendar', 'meeting_minutes', 'both', or 'custom'")
        
        print("\n" + "=" * 60)
        print("HOA POSTER COMPLETED")
        print("=" * 60)
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    print("Script started")
    main()
    print("Script ended")







