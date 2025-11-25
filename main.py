import os
import sys
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import google.generativeai as genai
import requests
import time
import base64
from io import BytesIO

class HOAPoster:
    def __init__(self):
        print("Initializing HOAPoster class...")
        
        # Facebook credentials
        self.fb_token = os.getenv('FACEBOOK_ACCESS_TOKEN')
        self.page_id = '882966761564424'  # Hallmark HOA Page
        print(f"Facebook token present: {bool(self.fb_token)}")
        print(f"Page ID: {self.page_id}")
        
        # Gemini API setup
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        self.model = genai.GenerativeModel('gemini-2.0-flash-lite')
        
        # Initialize Google services if credentials available
        if self.has_google_credentials():
            self.calendar_service = self.setup_google_service('calendar', 'v3', 
                ['https://www.googleapis.com/auth/calendar.readonly'])
            self.gmail_service = self.setup_google_service('gmail', 'v1', [
                'https://www.googleapis.com/auth/calendar.readonly',
                'https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/gmail.modify'
            ])
            self.drive_service = self.setup_google_service('drive', 'v3', [
                'https://www.googleapis.com/auth/calendar.readonly',
                'https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/gmail.modify',
                'https://www.googleapis.com/auth/drive.file'
            ])
        else:
            self.calendar_service = None
            self.gmail_service = None
            self.drive_service = None
    
    # ==================== GOOGLE API SETUP ====================
    
    def has_google_credentials(self):
        """Check if Google credentials are available"""
        return all([
            os.getenv('GOOGLE_CLIENT_ID'),
            os.getenv('GOOGLE_CLIENT_SECRET'),
            os.getenv('GOOGLE_REFRESH_TOKEN')
        ])
    
    def setup_google_service(self, service_name, version, scopes):
        """Initialize a Google API service with credentials"""
        try:
            creds = Credentials(
                token=None,
                refresh_token=os.getenv('GOOGLE_REFRESH_TOKEN'),
                token_uri='https://oauth2.googleapis.com/token',
                client_id=os.getenv('GOOGLE_CLIENT_ID'),
                client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
                scopes=scopes
            )
            return build(service_name, version, credentials=creds)
        except Exception as e:
            print(f"Error setting up {service_name}: {e}")
            return None
    
    # ==================== CALENDAR FUNCTIONS ====================
    
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
            
            announcement = self.generate_event_post(event)
            if announcement:
                print("\nGenerated announcement:")
                print("-" * 60)
                print(announcement)
                print("-" * 60)
                
                if self.post_to_facebook(announcement):
                    print(f"✓ Posted announcement for: {event_name}")
                else:
                    print(f"✗ Failed to post announcement for: {event_name}")
            else:
                print(f"✗ Failed to generate announcement for: {event_name}")
    
    # ==================== GMAIL FUNCTIONS ====================
    
    def get_email_body(self, message):
        """Extract email body text"""
        try:
            if 'parts' in message['payload']:
                for part in message['payload']['parts']:
                    if part['mimeType'] == 'text/plain':
                        data = part['body'].get('data', '')
                        if data:
                            return base64.urlsafe_b64decode(data).decode('utf-8')
            else:
                data = message['payload']['body'].get('data', '')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8')
            return ""
        except Exception as e:
            print(f"Error extracting email body: {e}")
            return ""
    
    def extract_sender_email(self, message):
        """Extract sender email address from message"""
        try:
            headers = message['payload']['headers']
            from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
            
            if '<' in from_header and '>' in from_header:
                email = from_header.split('<')[1].split('>')[0]
            else:
                email = from_header
            
            return email.strip()
        except Exception as e:
            print(f"Error extracting sender: {e}")
            return ""
    
    def is_approved_sender(self, email_address):
        """Check if sender is in approved list"""
        approved_senders = os.getenv('APPROVED_EMAIL_SENDERS', '')
        
        if not approved_senders:
            print("Warning: No approved senders configured")
            return False
        
        approved_list = [sender.strip().lower() for sender in approved_senders.split(',')]
        return email_address.lower() in approved_list
    
    def get_or_create_gmail_label(self, label_name):
        """Get or create a Gmail label, return its ID"""
        try:
            results = self.gmail_service.users().labels().list(userId='me').execute()
            labels = results.get('labels', [])
            
            for label in labels:
                if label['name'] == label_name:
                    print(f"Found existing label: {label_name}")
                    return label['id']
            
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
    
    # ==================== DOCUMENT EXTRACTION ====================
    
    def extract_document_attachment(self, message):
        """Extract document attachment (PDF or Word) from email"""
        try:
            parts = message.get('payload', {}).get('parts', [])
            
            for part in parts:
                filename = part.get('filename', '')
                
                if (filename.lower().endswith('.pdf') or 
                    filename.lower().endswith('.docx') or 
                    filename.lower().endswith('.doc')):
                    
                    attachment_id = part['body'].get('attachmentId')
                    
                    if attachment_id:
                        attachment = self.gmail_service.users().messages().attachments().get(
                            userId='me',
                            messageId=message['id'],
                            id=attachment_id
                        ).execute()
                        
                        file_data = base64.urlsafe_b64decode(attachment['data'])
                        
                        if filename.lower().endswith('.pdf'):
                            mime_type = 'application/pdf'
                        elif filename.lower().endswith('.docx'):
                            mime_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                        else:
                            mime_type = 'application/msword'
                        
                        return filename, file_data, mime_type
            
            return None, None, None
        except Exception as e:
            print(f"Error extracting document: {e}")
            return None, None, None
    
    def extract_text_from_pdf(self, file_data):
        """Extract text from PDF file"""
        try:
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
            text = self.extract_text_from_word(file_data)
            if not text:
                print("Warning: .doc format may not be fully supported. Consider using .docx")
            return text
        else:
            return ""
    
    def extract_images_from_email(self, message):
        """Extract all images from email (attached or inline)"""
        images = []
        
        try:
            parts = message.get('payload', {}).get('parts', [])
            
            if 'mimeType' in message.get('payload', {}):
                main_mime = message['payload']['mimeType']
                if main_mime.startswith('image/'):
                    parts = [message['payload']]
            
            def process_part(part):
                mime_type = part.get('mimeType', '')
                filename = part.get('filename', '')
                
                if mime_type.startswith('image/'):
                    attachment_id = part['body'].get('attachmentId')
                    data = part['body'].get('data')
                    
                    if attachment_id:
                        attachment = self.gmail_service.users().messages().attachments().get(
                            userId='me',
                            messageId=message['id'],
                            id=attachment_id
                        ).execute()
                        data = attachment['data']
                    
                    if data:
                        image_data = base64.urlsafe_b64decode(data)
                        images.append({
                            'filename': filename or f'image_{len(images)}.jpg',
                            'data': image_data,
                            'mime_type': mime_type
                        })
                
                if 'parts' in part:
                    for subpart in part['parts']:
                        process_part(subpart)
            
            for part in parts:
                process_part(part)
            
            return images
            
        except Exception as e:
            print(f"Error extracting images: {e}")
            return []
    
    # ==================== GOOGLE DRIVE ====================
    
    def upload_to_drive(self, filename, file_data, mime_type):
        """Upload document to Google Drive and return shareable link"""
        try:
            from googleapiclient.http import MediaIoBaseUpload
            
            folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
            
            if not folder_id:
                print("No Google Drive folder ID configured")
                return None
            
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            
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
            
            self.drive_service.permissions().create(
                fileId=file_id,
                body={'type': 'anyone', 'role': 'reader'}
            ).execute()
            
            print(f"✓ Uploaded to Google Drive: {web_link}")
            return web_link
            
        except Exception as e:
            print(f"Error uploading to Drive: {e}")
            return None
    
    # ==================== GEMINI AI CONTENT GENERATION ====================
    
    def generate_with_retry(self, prompt, max_retries=3):
        """Generate content with Gemini, including retry logic for rate limits"""
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
                    print(f"Error generating content: {e}")
                    return None
        
        return None
    
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

        return self.generate_with_retry(prompt)
    
    def generate_event_post(self, event):
        """Generate a post about a calendar event"""
        event_name = event.get('summary', 'HOA Event')
        event_start = event.get('start', {})
        event_time = event_start.get('dateTime', event_start.get('date', ''))
        event_location = event.get('location', '')
        event_description = event.get('description', '')
        
        try:
            if 'T' in event_time:
                dt = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
                formatted_time = dt.strftime('%A, %B %d at %I:%M %p')
            else:
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

        return self.generate_with_retry(prompt)
    
    def generate_meeting_minutes_post(self, subject, content, drive_link=None, is_from_document=False):
        """Generate a Facebook post about meeting minutes"""
        max_content_length = 8000
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

        post_text = self.generate_with_retry(prompt)
        
        if post_text and drive_link:
            post_text += f"\n\n📋 Read the full minutes: {drive_link}"
        
        return post_text
    
    def generate_facebook_post_from_email(self, subject, body):
        """Generate a Facebook post from email content using Gemini"""
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

        return self.generate_with_retry(prompt)
    
    # ==================== FACEBOOK POSTING ====================
    
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
    
    def post_to_facebook_with_images(self, message, images):
        """Post message with images to Facebook Page"""
        if not images:
            return self.post_to_facebook(message)
        
        try:
            uploaded_photo_ids = []
            
            for idx, image in enumerate(images[:10]):
                print(f"Uploading image {idx + 1}/{min(len(images), 10)}...")
                
                url = f"https://graph.facebook.com/v21.0/me/photos"
                
                files = {'source': (image['filename'], image['data'], image['mime_type'])}
                data = {'access_token': self.fb_token, 'published': 'false'}
                
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
            
            url = f"https://graph.facebook.com/v21.0/me/feed"
            
            payload = {
                'message': message,
                'attached_media': uploaded_photo_ids,
                'access_token': self.fb_token
            }
            
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
    
    # ==================== WORKFLOW: MEETING MINUTES ====================
    
    def check_meeting_minutes_emails(self):
        """Check for new meeting minutes emails and create posts"""
        if not self.gmail_service:
            print("Gmail not configured")
            return
        
        print("\n" + "="*60)
        print("Checking for meeting minutes emails...")
        print("="*60 + "\n")
        
        try:
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
            message = self.gmail_service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            headers = message['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'Meeting Minutes')
            body = self.get_email_body(message)
            
            print(f"\nProcessing email: {subject}")
            print(f"Body preview: {body[:200]}...")
            
            doc_filename, doc_data, mime_type = self.extract_document_attachment(message)
            drive_link = None
            document_text = ""
            
            if doc_filename and doc_data:
                print(f"Found document attachment: {doc_filename}")
                
                document_text = self.extract_document_text(doc_filename, doc_data)
                if document_text:
                    print(f"Extracted {len(document_text)} characters from document")
                else:
                    print("Warning: Could not extract text from document")
                
                drive_link = self.upload_to_drive(doc_filename, doc_data, mime_type)
            else:
                print("No document attachment found")
            
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
                
                success = self.post_to_facebook(post_content)
                
                if success:
                    print("✓ Posted meeting minutes announcement")
                    
                    label_id = self.get_or_create_gmail_label("Meeting Minutes")
                    
                    if label_id:
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
    
    # ==================== WORKFLOW: CUSTOM FACEBOOK POSTS ====================
    
    def check_facebook_post_emails(self):
        """Check for emails requesting Facebook posts"""
        if not self.gmail_service:
            print("Gmail not configured")
            return
        
        print("\n" + "="*60)
        print("Checking for Facebook post request emails...")
        print("="*60 + "\n")
        
        try:
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
    
    def process_facebook_post_email(self, message_id):
        """Process an email requesting a Facebook post"""
        try:
            message = self.gmail_service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            sender_email = self.extract_sender_email(message)
            print(f"\nProcessing post request from: {sender_email}")
            
            if not self.is_approved_sender(sender_email):
                print(f"✗ Sender {sender_email} is not in approved list - ignoring")
                self.gmail_service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={'removeLabelIds': ['UNREAD']}
                ).execute()
                return
            
            print(f"✓ Sender approved")
            
            headers = message['payload']['headers']
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'Facebook Post')
            body = self.get_email_body(message)
            
            print(f"Subject: {subject}")
            print(f"Body preview: {body[:200]}...")
            
            images = self.extract_images_from_email(message)
            print(f"Found {len(images)} image(s)")
            
            post_content = self.generate_facebook_post_from_email(subject, body)
            
            if not post_content:
                print("✗ Failed to generate post content")
                return
            
            print("\nGenerated post:")
            print("-" * 60)
            print(post_content)
            print("-" * 60)
            
            success = self.post_to_facebook_with_images(post_content, images)
            
            if success:
                print("✓ Posted to Facebook")
                
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
    
    # ==================== WORKFLOW: CUSTOM MODE ====================
    
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
    
def main():
    """Main execution function"""
    print("=" * 60)
    print("HOA POSTER STARTING")
    print("=" * 60)
    
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
            print("Running calendar, meeting minutes, and Facebook post modes...")
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
            print("Set RUN_MODE to 'calendar', 'meeting_minutes', 'facebook_posts', 'both', or 'custom'")
    
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



