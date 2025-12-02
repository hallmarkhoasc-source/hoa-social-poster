"""
HOA Social Media Automation System
"""

import os
import sys
import base64
import time
import requests
import holidays
from io import BytesIO
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import google.generativeai as genai

# ============================================================================
# CONFIGURATION & INITIALIZATION
# ============================================================================

class Config:
    """Centralized configuration management"""
    
    def __init__(self):
        # Facebook
        self.fb_token = os.getenv('FACEBOOK_ACCESS_TOKEN')
        self.page_id = '882966761564424'
        
        # Google
        self.google_client_id = os.getenv('GOOGLE_CLIENT_ID')
        self.google_client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
        self.google_refresh_token = os.getenv('GOOGLE_REFRESH_TOKEN')
        self.drive_folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
        
        # Gemini
        self.gemini_api_key = os.getenv('GEMINI_API_KEY')
        
        # Security
        self.approved_senders = self._parse_approved_senders()
        
        # Runtime
        self.run_mode = os.getenv('RUN_MODE', 'calendar')
        self.post_topic = os.getenv('POST_TOPIC', 'General HOA update')
        self.post_context = os.getenv('POST_CONTEXT', '')
    
    def _parse_approved_senders(self) -> List[str]:
        """Parse approved email senders from environment"""
        senders = os.getenv('APPROVED_EMAIL_SENDERS', '')
        return [s.strip().lower() for s in senders.split(',') if s.strip()]
    
    def has_google_credentials(self) -> bool:
        """Check if all Google credentials are present"""
        return all([self.google_client_id, self.google_client_secret, self.google_refresh_token])
    
    def validate(self):
        """Validate critical configuration"""
        if not self.fb_token:
            raise ValueError("FACEBOOK_ACCESS_TOKEN is required")
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required")


# ============================================================================
# GOOGLE API CLIENT MANAGER
# ============================================================================

class GoogleAPIManager:
    """Manages Google API service initialization"""
    
    SCOPES = {
        'calendar': ['https://www.googleapis.com/auth/calendar.readonly'],
        'gmail': [
            'https://www.googleapis.com/auth/gmail.readonly',
            'https://www.googleapis.com/auth/gmail.modify'
        ],
        'drive': ['https://www.googleapis.com/auth/drive.file']
    }
    
    def __init__(self, config: Config):
        self.config = config
        self.services = {}
        
        if config.has_google_credentials():
            self._initialize_services()
    
    def _create_credentials(self, scopes: List[str]) -> Credentials:
        """Create Google OAuth credentials"""
        return Credentials(
            token=None,
            refresh_token=self.config.google_refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=self.config.google_client_id,
            client_secret=self.config.google_client_secret,
            scopes=scopes
        )
    
    def _initialize_services(self):
        """Initialize all Google API services"""
        all_scopes = []
        for scopes in self.SCOPES.values():
            all_scopes.extend(scopes)
        all_scopes = list(set(all_scopes))
        
        creds = self._create_credentials(all_scopes)
        
        try:
            self.services['calendar'] = build('calendar', 'v3', credentials=creds)
            self.services['gmail'] = build('gmail', 'v1', credentials=creds)
            self.services['drive'] = build('drive', 'v3', credentials=creds)
            print("✓ Google API services initialized")
        except Exception as e:
            print(f"✗ Error initializing Google services: {e}")
    
    def get(self, service_name: str):
        """Get a Google API service"""
        return self.services.get(service_name)


# ============================================================================
# GMAIL OPERATIONS
# ============================================================================

class GmailHandler:
    """Handles Gmail operations"""
    
    def __init__(self, gmail_service, config: Config):
        self.service = gmail_service
        self.config = config
    
    def get_messages(self, query: str, max_results: int = 5) -> List[Dict]:
        """Get messages matching a query"""
        if not self.service:
            return []
        
        try:
            results = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            return results.get('messages', [])
        except Exception as e:
            print(f"Error fetching messages: {e}")
            return []
    
    def get_message_full(self, message_id: str) -> Optional[Dict]:
        """Get full message details"""
        try:
            return self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
        except Exception as e:
            print(f"Error fetching message {message_id}: {e}")
            return None
    
    def extract_header(self, message: Dict, header_name: str) -> str:
        """Extract a specific header from message"""
        headers = message.get('payload', {}).get('headers', [])
        return next((h['value'] for h in headers if h['name'].lower() == header_name.lower()), '')
    
    def extract_body(self, message: Dict) -> str:
        """Extract email body text"""
        try:
            payload = message.get('payload', {})
            
            # Check for multipart
            if 'parts' in payload:
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain':
                        data = part.get('body', {}).get('data', '')
                        if data:
                            return base64.urlsafe_b64decode(data).decode('utf-8')
            
            # Single part
            data = payload.get('body', {}).get('data', '')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8')
            
            return ""
        except Exception as e:
            print(f"Error extracting body: {e}")
            return ""
    
    def extract_sender_email(self, message: Dict) -> str:
        """Extract sender email address"""
        from_header = self.extract_header(message, 'from')
        
        if '<' in from_header and '>' in from_header:
            return from_header.split('<')[1].split('>')[0].strip()
        return from_header.strip()
    
    def is_approved_sender(self, email: str) -> bool:
        """Check if sender is approved"""
        if not self.config.approved_senders:
            print("Warning: No approved senders configured")
            return False
        return email.lower() in self.config.approved_senders
    
    def get_or_create_label(self, label_name: str) -> Optional[str]:
        """Get or create a Gmail label, return its ID"""
        try:
            # Check existing labels
            results = self.service.users().labels().list(userId='me').execute()
            for label in results.get('labels', []):
                if label['name'] == label_name:
                    print(f"Found existing label: {label_name}")
                    return label['id']
            
            # Create new label
            label_object = {
                'name': label_name,
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show'
            }
            created = self.service.users().labels().create(
                userId='me',
                body=label_object
            ).execute()
            
            print(f"Created new label: {label_name}")
            return created['id']
        except Exception as e:
            print(f"Error with label: {e}")
            return None
    
    def modify_message(self, message_id: str, add_labels: List[str] = None,
                      remove_labels: List[str] = None):
        """Modify message labels"""
        try:
            body = {}
            if add_labels:
                body['addLabelIds'] = add_labels
            if remove_labels:
                body['removeLabelIds'] = remove_labels
            
            self.service.users().messages().modify(
                userId='me',
                id=message_id,
                body=body
            ).execute()
        except Exception as e:
            print(f"Error modifying message: {e}")
    
    def mark_as_processed(self, message_id: str, label_name: str):
        """Mark message as read, labeled, and archived"""
        label_id = self.get_or_create_label(label_name)
        
        if label_id:
            self.modify_message(
                message_id,
                add_labels=[label_id],
                remove_labels=['UNREAD', 'INBOX']
            )
            print(f"✓ Labeled as '{label_name}' and archived")
        else:
            self.modify_message(message_id, remove_labels=['UNREAD'])
            print("✓ Marked as read")


# ============================================================================
# DOCUMENT PROCESSING
# ============================================================================

class DocumentProcessor:
    """Handles document extraction and processing"""
    
    def __init__(self, gmail_service):
        self.service = gmail_service
    
    def extract_attachment(self, message: Dict) -> Tuple[Optional[str], Optional[bytes], Optional[str]]:
        """Extract document attachment (PDF or Word) from email"""
        try:
            parts = message.get('payload', {}).get('parts', [])
            
            for part in parts:
                filename = part.get('filename', '')
                
                if self._is_supported_document(filename):
                    attachment_id = part['body'].get('attachmentId')
                    
                    if attachment_id:
                        attachment = self.service.users().messages().attachments().get(
                            userId='me',
                            messageId=message['id'],
                            id=attachment_id
                        ).execute()
                        
                        file_data = base64.urlsafe_b64decode(attachment['data'])
                        mime_type = self._get_mime_type(filename)
                        
                        return filename, file_data, mime_type
            
            return None, None, None
        except Exception as e:
            print(f"Error extracting attachment: {e}")
            return None, None, None
    
    def extract_images(self, message: Dict) -> List[Dict]:
        """Extract all images from email"""
        images = []
        
        try:
            parts = message.get('payload', {}).get('parts', [])
            
            # Check if main payload is an image
            if message.get('payload', {}).get('mimeType', '').startswith('image/'):
                parts = [message['payload']]
            
            def process_part(part):
                mime_type = part.get('mimeType', '')
                
                if mime_type.startswith('image/'):
                    data = self._get_part_data(message['id'], part)
                    if data:
                        images.append({
                            'filename': part.get('filename', f'image_{len(images)}.jpg'),
                            'data': data,
                            'mime_type': mime_type
                        })
                
                # Recursively process nested parts
                if 'parts' in part:
                    for subpart in part['parts']:
                        process_part(subpart)
            
            for part in parts:
                process_part(part)
            
            return images
        except Exception as e:
            print(f"Error extracting images: {e}")
            return []
    
    def _get_part_data(self, message_id: str, part: Dict) -> Optional[bytes]:
        """Get data from message part"""
        attachment_id = part['body'].get('attachmentId')
        data = part['body'].get('data')
        
        if attachment_id:
            attachment = self.service.users().messages().attachments().get(
                userId='me',
                messageId=message_id,
                id=attachment_id
            ).execute()
            data = attachment['data']
        
        if data:
            return base64.urlsafe_b64decode(data)
        return None
    
    def extract_text(self, filename: str, file_data: bytes) -> str:
        """Extract text from document based on file type"""
        if filename.lower().endswith('.pdf'):
            return self._extract_from_pdf(file_data)
        elif filename.lower().endswith(('.docx', '.doc')):
            return self._extract_from_word(file_data)
        return ""
    
    def _extract_from_pdf(self, file_data: bytes) -> str:
        """Extract text from PDF"""
        try:
            import PyPDF2
            pdf_file = BytesIO(file_data)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            
            return text.strip()
        except Exception as e:
            print(f"Error extracting from PDF: {e}")
            return ""
    
    def _extract_from_word(self, file_data: bytes) -> str:
        """Extract text from Word document"""
        try:
            from docx import Document
            doc_file = BytesIO(file_data)
            doc = Document(doc_file)
            
            return "\n".join(p.text for p in doc.paragraphs).strip()
        except Exception as e:
            print(f"Error extracting from Word: {e}")
            return ""
    
    @staticmethod
    def _is_supported_document(filename: str) -> bool:
        """Check if file is a supported document type"""
        return filename.lower().endswith(('.pdf', '.docx', '.doc'))
    
    @staticmethod
    def _get_mime_type(filename: str) -> str:
        """Get MIME type for filename"""
        ext = filename.lower()
        if ext.endswith('.pdf'):
            return 'application/pdf'
        elif ext.endswith('.docx'):
            return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        elif ext.endswith('.doc'):
            return 'application/msword'
        return 'application/octet-stream'


# ============================================================================
# GOOGLE CALENDAR OPERATIONS
# ============================================================================

class CalendarHandler:
    """Handles Google Calendar operations"""
    
    def __init__(self, calendar_service):
        self.service = calendar_service
    
    def get_upcoming_events(self, days_ahead: int = 7) -> List[Dict]:
        """Fetch upcoming events from Google Calendar"""
        if not self.service:
            return []
        
        try:
            now = datetime.utcnow().isoformat() + 'Z'
            future = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + 'Z'
            
            results = self.service.events().list(
                calendarId='primary',
                timeMin=now,
                timeMax=future,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            return results.get('items', [])
        except Exception as e:
            print(f"Error fetching calendar events: {e}")
            return []
    
    @staticmethod
    def format_event_time(event: Dict) -> str:
        """Format event time for display"""
        event_start = event.get('start', {})
        event_time = event_start.get('dateTime', event_start.get('date', ''))
        
        try:
            if 'T' in event_time:
                dt = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
                return dt.strftime('%A, %B %d at %I:%M %p')
            else:
                dt = datetime.fromisoformat(event_time)
                return dt.strftime('%A, %B %d')
        except:
            return event_time


# ============================================================================
# GOOGLE DRIVE OPERATIONS
# ============================================================================

class DriveHandler:
    """Handles Google Drive operations"""
    
    def __init__(self, drive_service, config: Config):
        self.service = drive_service
        self.config = config
    
    def upload_file(self, filename: str, file_data: bytes, mime_type: str) -> Optional[str]:
        """Upload file to Google Drive and return shareable link"""
        if not self.service or not self.config.drive_folder_id:
            print("Google Drive not configured")
            return None
        
        try:
            file_metadata = {
                'name': filename,
                'parents': [self.config.drive_folder_id]
            }
            
            media = MediaIoBaseUpload(
                BytesIO(file_data),
                mimetype=mime_type,
                resumable=True
            )
            
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()
            
            # Make publicly readable
            self.service.permissions().create(
                fileId=file['id'],
                body={'type': 'anyone', 'role': 'reader'}
            ).execute()
            
            web_link = file.get('webViewLink')
            print(f"✓ Uploaded to Google Drive: {web_link}")
            return web_link
        except Exception as e:
            print(f"Error uploading to Drive: {e}")
            return None


# ============================================================================
# AI CONTENT GENERATION
# ============================================================================

class AIContentGenerator:
    """Handles AI-powered content generation using Gemini"""
    
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.0-flash-lite')
    
    def generate(self, prompt: str, max_retries: int = 3) -> Optional[str]:
        """Generate content with retry logic for rate limits"""
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(prompt)
                return response.text
            except Exception as e:
                if '429' in str(e) or 'Resource exhausted' in str(e):
                    if attempt < max_retries - 1:
                        wait_time = 5 * (2 ** attempt)
                        print(f"Rate limit hit. Waiting {wait_time}s (retry {attempt + 2}/{max_retries})...")
                        time.sleep(wait_time)
                        continue
                print(f"Error generating content: {e}")
                return None
        return None
    
    def generate_event_post(self, event: Dict, formatted_time: str) -> Optional[str]:
        """Generate Facebook post for calendar event"""
        prompt = f"""You are writing social media posts for Hallmark HOA, a residential community.

Generate a Facebook post announcing this HOA community event:

Event: {event.get('summary', 'HOA Event')}
Time: {formatted_time}
Location: {event.get('location', '')}
Details: {event.get('description', '')}

Requirements:
- Start with clear event announcement (e.g., "Join us for...")
- Include date/time on its own line or clearly stated
- Mention location clearly
- Warm, neighborly tone
- Under 200 words
- Clear call to action (e.g., "See you there!")
- Maximum 2-3 hashtags (like #HallmarkHOA #CommunityEvent)
- No placeholder text
- 1-2 emojis maximum
- Format for Facebook event detection (clear date/time/location)"""
        
        return self.generate(prompt)
    
    def generate_meeting_minutes_post(self, subject: str, content: str, 
                                     drive_link: Optional[str] = None,
                                     is_from_document: bool = False) -> Optional[str]:
        """Generate post announcing meeting minutes"""
        # Truncate long content
        if len(content) > 8000:
            content = content[:8000] + "...\n[Content truncated]"
        
        content_type = "meeting minutes document" if is_from_document else "email"
        
        prompt = f"""Generate a friendly Facebook post for Hallmark HOA announcing meeting minutes are available.

Email Subject: {subject}
Content from {content_type}:
{content}

Requirements:
- Announce that meeting minutes are now available
- Identify and briefly summarize 2-3 of the MOST IMPORTANT topics actually discussed
- Base your summary ONLY on the content provided - do NOT make up topics
- If you cannot identify specific topics, just announce minutes are available
- Warm, professional tone
- Under 200 words
- Include call to action encouraging residents to read full minutes
- Use 1-2 hashtags like #HallmarkHOA
- 1 emoji maximum
- Do NOT include a link - it will be added automatically"""
        
        post_text = self.generate(prompt)
        
        if post_text and drive_link:
            post_text += f"\n\n📋 Read the full minutes: {drive_link}"
        
        return post_text
    
    def generate_facebook_post(self, subject: str, body: str) -> Optional[str]:
        """Generate Facebook post from email content"""
        prompt = f"""You are writing a Facebook post for Hallmark HOA based on an email request.

Email Subject: {subject}
Email Content:
{body[:3000]}

Requirements:
- Transform email content into engaging, friendly Facebook post
- Keep key information and message
- Use warm, community-focused tone appropriate for HOA
- Keep concise (under 300 words)
- Make it conversational and suitable for social media
- Use appropriate paragraph breaks
- Add 1-2 relevant hashtags (like #HallmarkHOA)
- Use 1-2 emojis maximum if appropriate
- Do NOT mention this came from an email
- Write as if HOA is speaking directly to residents"""
        
        return self.generate(prompt)
    
    def generate_holiday_post(self, holiday_name: str) -> Optional[str]:
        """Generate holiday greeting post"""
        prompt = f"""Generate a warm, friendly holiday greeting post for Hallmark HOA's Facebook page.

Holiday: {holiday_name}

Requirements:
- Write brief, heartfelt greeting appropriate for {holiday_name}
- Keep it inclusive and community-focused
- Mention the Hallmark HOA community
- Keep it under 150 words
- Use warm, neighborly tone
- Include 1-2 relevant emojis if appropriate
- Add 1-2 hashtags (like #HallmarkHOA and holiday-specific)
- Make it feel genuine, not corporate"""
        
        return self.generate(prompt)
    
    def generate_custom_post(self, topic: str, context: str = "") -> Optional[str]:
        """Generate custom post on any topic"""
        prompt = f"""Generate a friendly, professional Facebook post for Hallmark HOA community about: {topic}

Additional context: {context}

Requirements:
- Write in warm, neighborly tone appropriate for HOA
- Keep it conversational but professional
- Include relevant details clearly
- Keep it under 250 words
- End with call to action if appropriate
- Use 1-2 relevant hashtags maximum (like #HallmarkHOA)
- Do NOT use placeholder text or brackets
- Do NOT mention virtual events unless specifically requested
- Do NOT use excessive emojis (1-2 maximum)"""
        
        return self.generate(prompt)


# ============================================================================
# FACEBOOK API OPERATIONS
# ============================================================================

class FacebookPoster:
    """Handles Facebook Graph API posting"""
    
    API_VERSION = 'v21.0'
    
    def __init__(self, access_token: str, page_id: str):
        self.token = access_token
        self.page_id = page_id
    
    def post_text(self, message: str) -> bool:
        """Post text message to Facebook Page"""
        url = f"https://graph.facebook.com/v21.0/{self.page_id}/feed"
        
        payload = {
            'message': message,
            'access_token': self.token
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
    
    def post_with_images(self, message: str, images: List[Dict]) -> bool:
        """Post message with images to Facebook Page"""
        if not images:
            return self.post_text(message)
        
        try:
            # Upload images (max 10)
            uploaded_ids = []
            for idx, image in enumerate(images[:10]):
                print(f"Uploading image {idx + 1}/{min(len(images), 10)}...")
                photo_id = self._upload_image(image)
                if photo_id:
                    uploaded_ids.append({'media_fbid': photo_id})
            
            if not uploaded_ids:
                print("No images uploaded successfully, posting text only")
                return self.post_text(message)
            
            # Post with images
            url = url = f"https://graph.facebook.com/v21.0/{self.page_id}/feed"
            
            import json
            payload = {
                'message': message,
                'attached_media': uploaded_ids,
                'access_token': self.token
            }
            
            response = requests.post(
                url,
                data=json.dumps(payload),
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                post_id = response.json().get('id')
                print(f"✓ Posted with {len(uploaded_ids)} image(s)! Post ID: {post_id}")
                return True
            else:
                print(f"✗ Error posting: {response.json()}")
                return False
        except Exception as e:
            print(f"✗ Error posting with images: {e}")
            return False
    
    def _upload_image(self, image: Dict) -> Optional[str]:
        """Upload single image and return photo ID"""
        try:
            url = f"https://graph.facebook.com/{self.API_VERSION}/me/photos"
            
            files = {'source': (image['filename'], image['data'], image['mime_type'])}
            data = {'access_token': self.token, 'published': 'false'}
            
            response = requests.post(url, files=files, data=data)
            
            if response.status_code == 200:
                return response.json().get('id')
            else:
                print(f"✗ Error uploading image: {response.json()}")
                return None
        except Exception as e:
            print(f"✗ Error uploading image: {e}")
            return None


# ============================================================================
# HOLIDAY MANAGEMENT
# ============================================================================

class HolidayManager:
    """Manages holiday detection and tracking"""
    
    MAJOR_HOLIDAYS = [
        "New Year's Day", "Martin Luther King Jr. Day", "Presidents' Day",
        "Mother's Day", "Father's Day", "Memorial Day", "Independence Day",
        "Labor Day", "Halloween", "Veterans Day", "Thanksgiving",
        "Christmas Day", "Easter Sunday"
    ]
    
    def __init__(self):
        self.us_holidays = holidays.US()
    
    def get_todays_holiday(self) -> Optional[str]:
        """Check if today is a major US holiday"""
        today = datetime.now().date()
        return self.us_holidays.get(today)
    
    def should_post_holiday(self) -> Tuple[bool, Optional[str]]:
        """Determine if we should post for today's holiday"""
        holiday_name = self.get_todays_holiday()
        
        if not holiday_name:
            return False, None
        
        # Check if it's a major holiday
        for major in self.MAJOR_HOLIDAYS:
            if major.lower() in holiday_name.lower():
                return True, holiday_name
        
        return False, holiday_name
    
    @staticmethod
    def already_posted_today(post_type: str) -> bool:
        """Check if we already posted this type today"""
        try:
            flag_file = f'/tmp/hoa_posted_{post_type}_{datetime.now().date()}.flag'
            return os.path.exists(flag_file)
        except:
            return False
    
    @staticmethod
    def mark_posted_today(post_type: str):
        """Mark that we posted this type today"""
        try:
            flag_file = f'/tmp/hoa_posted_{post_type}_{datetime.now().date()}.flag'
            with open(flag_file, 'w') as f:
                f.write(str(datetime.now()))
        except Exception as e:
            print(f"Warning: Could not create tracking file: {e}")


# ============================================================================
# WORKFLOW ORCHESTRATORS
# ============================================================================

class HOAPoster:
    """Main orchestrator for HOA social media automation"""
    
    def __init__(self):
        print("Initializing HOAPoster...")
        
        # Initialize configuration
        self.config = Config()
        self.config.validate()
        print(f"✓ Configuration loaded (mode: {self.config.run_mode})")
        
        # Initialize Google APIs
        self.google = GoogleAPIManager(self.config)
        
        # Initialize handlers
        self.gmail = GmailHandler(self.google.get('gmail'), self.config)
        self.calendar = CalendarHandler(self.google.get('calendar'))
        self.drive = DriveHandler(self.google.get('drive'), self.config)
        self.doc_processor = DocumentProcessor(self.google.get('gmail'))
        
        # Initialize AI and Facebook
        self.ai = AIContentGenerator(self.config.gemini_api_key)
        self.facebook = FacebookPoster(self.config.fb_token, self.config.page_id)
        
        # Initialize holiday manager
        self.holidays = HolidayManager()
        
        print("✓ HOAPoster initialized successfully\n")
    
    # ----- Calendar Workflow -----
    
    def run_calendar_workflow(self):
        """Check for upcoming events and post announcements"""
        print("=" * 60)
        print("CALENDAR WORKFLOW: Checking for upcoming events")
        print("=" * 60 + "\n")
        
        events = self.calendar.get_upcoming_events(days_ahead=7)
        
        if not events:
            print("No upcoming events found")
            return
        
        print(f"Found {len(events)} upcoming event(s)\n")
        
        for event in events:
            event_name = event.get('summary', 'Unnamed Event')
            print(f"Processing: {event_name}")
            
            formatted_time = self.calendar.format_event_time(event)
            post_content = self.ai.generate_event_post(event, formatted_time)
            
            if post_content:
                print("\n" + "-" * 60)
                print(post_content)
                print("-" * 60 + "\n")
                
                if self.facebook.post_text(post_content):
                    print(f"✓ Posted announcement for: {event_name}\n")
                else:
                    print(f"✗ Failed to post for: {event_name}\n")
            else:
                print(f"✗ Failed to generate post for: {event_name}\n")
    
    # ----- Holiday Workflow -----
    
    def run_holiday_workflow(self):
        """Check for holidays and post greetings"""
        print("=" * 60)
        print("HOLIDAY WORKFLOW: Checking for holidays")
        print("=" * 60 + "\n")
        
        should_post, holiday_name = self.holidays.should_post_holiday()
        
        if not should_post:
            print("No major holiday today")
            return
        
        print(f"Today is: {holiday_name}")
        
        if self.holidays.already_posted_today('holiday'):
            print("Already posted a holiday greeting today")
            return
        
        post_content = self.ai.generate_holiday_post(holiday_name)
        
        if post_content:
            print("\n" + "-" * 60)
            print(post_content)
            print("-" * 60 + "\n")
            
            if self.facebook.post_text(post_content):
                print(f"✓ Posted holiday greeting for {holiday_name}")
                self.holidays.mark_posted_today('holiday')
            else:
                print("✗ Failed to post holiday greeting")
        else:
            print("✗ Failed to generate holiday post")
    
    # ----- Meeting Minutes Workflow -----
    
    def run_meeting_minutes_workflow(self):
        """Check for meeting minutes emails and create posts"""
        print("=" * 60)
        print("MEETING MINUTES WORKFLOW: Checking emails")
        print("=" * 60 + "\n")
        
        messages = self.gmail.get_messages('subject:"meeting minutes" is:unread')
        
        if not messages:
            print("No new meeting minutes emails found")
            return
        
        print(f"Found {len(messages)} meeting minutes email(s)\n")
        
        for msg in messages:
            self._process_meeting_minutes(msg['id'])
    
    def _process_meeting_minutes(self, message_id: str):
        """Process a single meeting minutes email"""
        message = self.gmail.get_message_full(message_id)
        if not message:
            return
        
        subject = self.gmail.extract_header(message, 'subject')
        body = self.gmail.extract_body(message)
        
        print(f"Processing: {subject}")
        
        # Extract document attachment
        filename, file_data, mime_type = self.doc_processor.extract_attachment(message)
        drive_link = None
        document_text = ""
        
        if filename and file_data:
            print(f"Found document: {filename}")
            document_text = self.doc_processor.extract_text(filename, file_data)
            
            if document_text:
                print(f"Extracted {len(document_text)} characters from document")
            
            drive_link = self.drive.upload_file(filename, file_data, mime_type)
        
        # Generate post from document or email body
        content = document_text if document_text else body
        post_content = self.ai.generate_meeting_minutes_post(
            subject, content, drive_link, bool(document_text)
        )
        
        if post_content:
            print("\n" + "-" * 60)
            print(post_content)
            print("-" * 60 + "\n")
            
            if self.facebook.post_text(post_content):
                print("✓ Posted meeting minutes announcement")
                self.gmail.mark_as_processed(message_id, "Meeting Minutes")
            else:
                print("✗ Failed to post")
        else:
            print("✗ Failed to generate post")
        
        print()
    
    # ----- Facebook Post Request Workflow -----
    
    def run_facebook_post_workflow(self):
        """Check for Facebook post request emails"""
        print("=" * 60)
        print("FACEBOOK POST WORKFLOW: Checking emails")
        print("=" * 60 + "\n")
        
        messages = self.gmail.get_messages('subject:"Post to Facebook" is:unread')
        
        if not messages:
            print("No Facebook post request emails found")
            return
        
        print(f"Found {len(messages)} post request email(s)\n")
        
        for msg in messages:
            self._process_facebook_post_request(msg['id'])
    
    def _process_facebook_post_request(self, message_id: str):
        """Process an email requesting a Facebook post"""
        message = self.gmail.get_message_full(message_id)
        if not message:
            return
        
        sender = self.gmail.extract_sender_email(message)
        print(f"Processing request from: {sender}")
        
        # Security check
        if not self.gmail.is_approved_sender(sender):
            print(f"✗ Sender not approved - ignoring")
            self.gmail.modify_message(message_id, remove_labels=['UNREAD'])
            print()
            return
        
        print("✓ Sender approved")
        
        subject = self.gmail.extract_header(message, 'subject')
        body = self.gmail.extract_body(message)
        images = self.doc_processor.extract_images(message)
        
        print(f"Subject: {subject}")
        print(f"Found {len(images)} image(s)")
        
        post_content = self.ai.generate_facebook_post(subject, body)
        
        if not post_content:
            print("✗ Failed to generate post content")
            print()
            return
        
        print("\n" + "-" * 60)
        print(post_content)
        print("-" * 60 + "\n")
        
        if self.facebook.post_with_images(post_content, images):
            print("✓ Posted to Facebook")
            self.gmail.mark_as_processed(message_id, "Posted")
        else:
            print("✗ Failed to post to Facebook")
        
        print()
    
    # ----- Custom Post Workflow -----
    
    def run_custom_workflow(self):
        """Generate and post custom content"""
        print("=" * 60)
        print(f"CUSTOM WORKFLOW: Generating post about '{self.config.post_topic}'")
        print("=" * 60 + "\n")
        
        post_content = self.ai.generate_custom_post(
            self.config.post_topic,
            self.config.post_context
        )
        
        if not post_content:
            print("✗ Failed to generate content")
            return
        
        print("-" * 60)
        print(post_content)
        print("-" * 60 + "\n")
        
        if self.facebook.post_text(post_content):
            print("✓ Posted successfully")
        else:
            print("✗ Failed to post")


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main execution function"""
    print("=" * 60)
    print("HOA SOCIAL MEDIA AUTOMATION SYSTEM")
    print("=" * 60 + "\n")
    
    try:
        poster = HOAPoster()
        mode = poster.config.run_mode
        
        # Execute workflow based on mode
        workflows = {
            'calendar': poster.run_calendar_workflow,
            'holidays': poster.run_holiday_workflow,
            'meeting_minutes': poster.run_meeting_minutes_workflow,
            'facebook_posts': poster.run_facebook_post_workflow,
            'custom': poster.run_custom_workflow
        }
        
        if mode == 'both':
            # Run all automated workflows
            poster.run_holiday_workflow()
            poster.run_calendar_workflow()
            poster.run_meeting_minutes_workflow()
            poster.run_facebook_post_workflow()
        elif mode in workflows:
            workflows[mode]()
        else:
            print(f"Unknown mode: {mode}")
            print("Valid modes: calendar, holidays, meeting_minutes, facebook_posts, both, custom")
            return
        
        print("\n" + "=" * 60)
        print("SYSTEM COMPLETED SUCCESSFULLY")
        print("=" * 60)
    
    except Exception as e:
        print(f"\n✗ SYSTEM ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

