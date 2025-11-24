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
            
            # Extract and upload document attachment (PDF or Word)
            doc_filename, doc_data, mime_type = self.extract_document_attachment(message)
            drive_link = None
            document_text = ""
            
            if doc_filename and doc_data:
                print(f"Found document attachment: {doc_filename}")
                
                # Extract text from document
                document_text = self.extract_document_text(doc_filename, doc_data)
                if document_text:
                    print(f"Extracted {len(document_text)} characters from document")
                else:
                    print("Warning: Could not extract text from document")
                
                # Upload to Drive
                drive_link = self.upload_to_drive(doc_filename, doc_data, mime_type)
            else:
                print("No document attachment found")
            
            # Generate post from meeting minutes
            # Use document text if available, otherwise fall back to email body
            content_for_summary = document_text if document_text else body
            post_content = self.generate_meeting_minutes_post(
                subject, 
                content_for_summary, 
                drive_link,
                is_from_document=(len(document_text) > 0)
            )
            
            if post_content:
                print("\nGenerated post:")
                print("-" * 60)
                print(post_content)
                print("-" * 60)
                
                # Post to Facebook
                success = self.post_to_facebook(post_content)
                
                if success:
                    print("✓ Posted meeting minutes announcement")
                    
                    # Get or create the "Meeting Minutes" label
                    label_id = self.get_or_create_gmail_label("Meeting Minutes")
                    
                    if label_id:
                        # Apply label and remove from inbox
                        self.gmail_service.users().messages().modify(
                            userId='me',
                            id=message_id,
                            body={
                                'removeLabelIds': ['UNREAD', 'INBOX'],
                                'addLabelIds': [label_id]
                            }
                        ).execute()
                        print("✓ Marked as read, labeled, and moved to Meeting Minutes folder")
                    else:
                        # Fallback: just mark as read if label creation fails
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
            import traceback
            traceback.print_exc()

    def check_facebook_post_emails(self):
        """Check for emails requesting Facebook posts"""
        if not hasattr(self, 'gmail_service') or not self.gmail_service:
            print("Gmail not configured")
            return
        
        print("\n" + "="*60)
        print("Checking for Facebook post request emails...")
        print("="*60 + "\n")
        
        try:
            # Search for unread emails with "Post to Facebook" in subject
            query = 'subject:"Post to Facebook" is:unread'
            results = self.gmail_service.users().messages().list(
                userId='me',
                q=query,
                maxResults=5
            ).execute()
            
            messages = results.get('messages', [])
            
            if not messages:
                print("No Facebook post request emails found")
                return
            
            print(f"Found {len(messages)} post request email(s)")
            
            for msg in messages:
                self.process_facebook_post_email(msg['id'])
                
        except Exception as e:
            print(f"Error checking emails: {e}")
    
    def is_approved_sender(self, email_address):
        """Check if sender is in approved list"""
        approved_senders = os.getenv('APPROVED_EMAIL_SENDERS', '')
        
        if not approved_senders:
            print("Warning: No approved senders configured")
            return False
        
        # Split by comma and clean whitespace
        approved_list = [sender.strip().lower() for sender in approved_senders.split(',')]
        
        return email_address.lower() in approved_list
    
    def extract_sender_email(self, message):
        """Extract sender email address from message"""
        try:
            headers = message['payload']['headers']
            from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
            
            # Extract email from "Name <email@domain.com>" format
            if '<' in from_header and '>' in from_header:
                email = from_header.split('<')[1].split('>')[0]
            else:
                email = from_header
            
            return email.strip()
        except Exception as e:
            print(f"Error extracting sender: {e}")
            return ""
    
    def extract_images_from_email(self, message):
        """Extract all images from email (attached or inline)"""
        images = []
        
        try:
            parts = message.get('payload', {}).get('parts', [])
            
            # Also check if the payload itself is an image
            if 'mimeType' in message.get('payload', {}):
                main_mime = message['payload']['mimeType']
                if main_mime.startswith('image/'):
                    parts = [message['payload']]
            
            def process_part(part):
                mime_type = part.get('mimeType', '')
                filename = part.get('filename', '')
                
                # Check for images
                if mime_type.startswith('image/'):
                    attachment_id = part['body'].get('attachmentId')
                    data = part['body'].get('data')
                    
                    if attachment_id:
                        # Get attachment
                        attachment = self.gmail_service.users().messages().attachments().get(
                            userId='me',
                            messageId=message['id'],
                            id=attachment_id
                        ).execute()
                        data = attachment['data']
                    
                    if data:
                        import base64
                        image_data = base64.urlsafe_b64decode(data)
                        images.append({
                            'filename': filename or f'image_{len(images)}.jpg',
                            'data': image_data,
                            'mime_type': mime_type
                        })
                
                # Recursively process multipart
                if 'parts' in part:
                    for subpart in part['parts']:
                        process_part(subpart)
            
            for part in parts:
                process_part(part)
            
            return images
            
        except Exception as e:
            print(f"Error extracting images: {e}")
            return []
    
    def generate_facebook_post_from_email(self, subject, body):
        """Generate a Facebook post from email content using Gemini"""
        import time
        
        prompt = f"""You are writing a Facebook post for Hallmark HOA based on an email request.

Email Subject: {subject}
Email Content:
{body[:3000]}

Requirements:
- Transform the email content into an engaging, friendly Facebook post
- Keep the key information and message
- Use a warm, community-focused tone appropriate for an HOA
- Keep it concise (under 300 words)
- Make it conversational and suitable for social media
- Use appropriate paragraph breaks for readability
- Add 1-2 relevant hashtags (like #HallmarkHOA)
- Use 1-2 emojis maximum if appropriate
- Do NOT mention that this came from an email
- Write as if the HOA is speaking directly to residents"""

        # Retry logic for rate limits
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(prompt)
                return response.text
                
            except Exception as e:
                error_message = str(e)
                
                if '429' in error_message or 'Resource exhausted' in error_message:
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        print(f"Rate limit hit. Waiting {wait_time} seconds before retry {attempt + 2}/{max_retries}...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"Error after {max_retries} attempts: {e}")
                        return None
                else:
                    print(f"Error generating post: {e}")
                    return None
        
        return None
    
    def post_to_facebook_with_images(self, message, images):
        """Post message with images to Facebook Page"""
        
        if not images:
            # No images, use regular text post
            return self.post_to_facebook(message)
        
        try:
            # Facebook requires images to be uploaded first, then posted
            uploaded_photo_ids = []
            
            # Upload each image
            for idx, image in enumerate(images[:10]):  # Max 10 images
                print(f"Uploading image {idx + 1}/{min(len(images), 10)}...")
                
                # Upload photo without publishing
                url = f"https://graph.facebook.com/v21.0/me/photos"
                
                files = {
                    'source': (image['filename'], image['data'], image['mime_type'])
                }
                
                data = {
                    'access_token': self.fb_token,
                    'published': 'false'  # Don't publish yet
                }
                
                response = requests.post(url, files=files, data=data)
                
                if response.status_code == 200:
                    photo_id = response.json().get('id')
                    uploaded_photo_ids.append({'media_fbid': photo_id})
                    print(f"✓ Uploaded image {idx + 1}")
                else:
                    print(f"✗ Error uploading image {idx + 1}: {response.json()}")
            
            if not uploaded_photo_ids:
                print("No images uploaded successfully, posting text only")
                return self.post_to_facebook(message)
            
            # Now create post with all uploaded images
            url = f"https://graph.facebook.com/v21.0/me/feed"
            
            payload = {
                'message': message,
                'attached_media': uploaded_photo_ids,
                'access_token': self.fb_token
            }
            
            # Need to send as JSON for attached_media
            import json
            headers = {'Content-Type': 'application/json'}
            response = requests.post(url, data=json.dumps(payload), headers=headers)
            
            if response.status_code == 200:
                post_id = response.json().get('id')
                print(f"✓ Posted successfully with {len(uploaded_photo_ids)} image(s)! Post ID: {post_id}")
                return True
            else:
                error_data = response.json()
                print(f"✗ Error posting: {error_data}")
                return False
                
        except Exception as e:
            print(f"✗ Error posting with images: {e}")
            return False
    
    def process_facebook_post_email(self, message_id):
        """Process an email requesting a Facebook post"""
        try:
            # Get the full message
            message = self.gmail_service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            # Extract sender
            sender_email = self.extract_sender_email(message)
            print(f"\nProcessing post request from: {sender_email}")
            
            # Check if sender is approved
            if not self.is_approved_sender(sender_email):
                print(f"✗ Sender {sender_email} is not in approved list - ignoring")
                # Mark as read but don't post
                self.gmail_service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={'removeLabelIds': ['UNREAD']}
                ).execute()
                return
            
            print(f"✓ Sender approved")
            
            # Extract subject and body
            headers = message['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'Facebook Post')
            body = self.get_email_body(message)
            
            print(f"Subject: {subject}")
            print(f"Body preview: {body[:200]}...")
            
            # Extract images
            images = self.extract_images_from_email(message)
            print(f"Found {len(images)} image(s)")
            
            # Generate Facebook post content
            post_content = self.generate_facebook_post_from_email(subject, body)
            
            if not post_content:
                print("✗ Failed to generate post content")
                return
            
            print("\nGenerated post:")
            print("-" * 60)
            print(post_content)
            print("-" * 60)
            
            # Post to Facebook with images
            success = self.post_to_facebook_with_images(post_content, images)
            
            if success:
                print("✓ Posted to Facebook")
                
                # Label as "Posted" and archive
                label_id = self.get_or_create_gmail_label("Posted")
                
                if label_id:
                    self.gmail_service.users().messages().modify(
                        userId='me',
                        id=message_id,
                        body={
                            'removeLabelIds': ['UNREAD', 'INBOX'],
                            'addLabelIds': [label_id]
                        }
                    ).execute()
                    print("✓ Marked as read, labeled, and archived")
                else:
                    self.gmail_service.users().messages().modify(
                        userId='me',
                        id=message_id,
                        body={'removeLabelIds': ['UNREAD']}
                    ).execute()
                    print("✓ Marked as read")
            else:
                print("✗ Failed to post to Facebook")
                
        except Exception as e:
            print(f"Error processing Facebook post email: {e}")
            import traceback
            traceback.print_exc()
            
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
            
    def extract_text_from_pdf(self, file_data):
        """Extract text from PDF file"""
        try:
            from io import BytesIO
            import PyPDF2
            
            pdf_file = BytesIO(file_data)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            
            return text.strip()
        except Exception as e:
            print(f"Error extracting text from PDF: {e}")
            return ""
    
    def extract_text_from_word(self, file_data):
        """Extract text from Word document"""
        try:
            from io import BytesIO
            from docx import Document
            
            doc_file = BytesIO(file_data)
            doc = Document(doc_file)
            
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            
            return text.strip()
        except Exception as e:
            print(f"Error extracting text from Word: {e}")
            return ""
    
    def extract_document_text(self, filename, file_data):
        """Extract text from document based on file type"""
        if filename.lower().endswith('.pdf'):
            return self.extract_text_from_pdf(file_data)
        elif filename.lower().endswith('.docx'):
            return self.extract_text_from_word(file_data)
        elif filename.lower().endswith('.doc'):
            # Old .doc format is harder to parse, try as docx
            text = self.extract_text_from_word(file_data)
            if not text:
                print("Warning: .doc format may not be fully supported. Consider using .docx")
            return text
        else:
            return ""
            
    def get_or_create_gmail_label(self, label_name):
        """Get or create a Gmail label, return its ID"""
        try:
            # Check if label already exists
            results = self.gmail_service.users().labels().list(userId='me').execute()
            labels = results.get('labels', [])
            
            for label in labels:
                if label['name'] == label_name:
                    print(f"Found existing label: {label_name}")
                    return label['id']
            
            # Label doesn't exist, create it
            label_object = {
                'name': label_name,
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show'
            }
            
            created_label = self.gmail_service.users().labels().create(
                userId='me',
                body=label_object
            ).execute()
            
            print(f"Created new label: {label_name}")
            return created_label['id']
            
        except Exception as e:
            print(f"Error getting/creating label: {e}")
            return None
            
    def generate_meeting_minutes_post(self, subject, content, drive_link=None, is_from_document=False):
        """Generate a Facebook post about meeting minutes"""
        
        # Limit content length for API (Gemini has token limits)
        max_content_length = 8000  # characters
        if len(content) > max_content_length:
            content = content[:max_content_length] + "...\n[Content truncated]"
        
        content_type = "meeting minutes document" if is_from_document else "email"
        
        prompt = f"""Generate a friendly Facebook post for Hallmark HOA announcing that meeting minutes are available.

Email Subject: {subject}
Content from {content_type}:
{content}

Requirements:
- Announce that the meeting minutes are now available
- Identify and briefly summarize 2-3 of the MOST IMPORTANT topics that were actually discussed in the meeting
- Base your summary ONLY on the content provided - do NOT make up or assume topics
- If you cannot identify specific topics from the content, just announce that minutes are available without listing topics
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
                post_text += f"\n\n📋 Read the full minutes: {drive_link}"
            
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
    
    def upload_to_drive(self, filename, file_data, mime_type):
        """Upload document to Google Drive and return shareable link"""
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
                mimetype=mime_type,
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
        
        elif mode == 'facebook_posts':
            print("Running Facebook post mode...")
            poster.check_facebook_post_emails()
        
        elif mode == 'both':
            print("Running both calendar and meeting minutes modes...")
            poster.check_and_post_event_reminders()
            poster.check_meeting_minutes_emails()
            poster.check_facebook_post_emails()
        
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












