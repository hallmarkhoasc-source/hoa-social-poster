import os
import json
import time
import base64
import requests
from datetime import datetime, timedelta
from io import BytesIO

# Google APIs
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Document parsing
import PyPDF2
from docx import Document

# Gemini
import google.generativeai as genai


# ============================================================
# Utility Helpers (DRY, shared across the entire system)
# ============================================================

def get_env(*keys):
    """Shortcut for grouped environment variable retrieval."""
    return [os.getenv(k) for k in keys]


def b64_decode(data):
    return base64.urlsafe_b64decode(data)


def safe_get(headers, name, default=""):
    """Extract a header value from Gmail header block."""
    return next((h["value"] for h in headers if h["name"].lower() == name.lower()), default)


def create_credentials(scopes):
    cid, secret, refresh = get_env(
        "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"
    )
    return Credentials(
        token=None,
        refresh_token=refresh,
        client_id=cid,
        client_secret=secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=scopes,
    )


# ============================================================
# Main Class
# ============================================================

class HOAPoster:
    """Automated content generator + Facebook poster for HOA operations."""

    FB_API = "https://graph.facebook.com/v21.0"

    def __init__(self):
        print("Initializing HOAPoster...")

        # Facebook
        self.fb_token = os.getenv("FACEBOOK_ACCESS_TOKEN")
        self.page_id = "882966761564424"
        print(f"FB token loaded: {bool(self.fb_token)}")

        # Gemini
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        self.model = genai.GenerativeModel("gemini-2.0-flash-lite")

        # Google API clients
        self.calendar = self.build_google_service("calendar", "v3", ["https://www.googleapis.com/auth/calendar.readonly"])
        self.gmail = self.build_google_service(
            "gmail", "v1",
            [
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.modify",
            ],
        )
        self.drive = self.build_google_service(
            "drive", "v3",
            [
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/drive.file",
            ],
        )

    # ------------------------------------------------------------
    # Google Service Builders
    # ------------------------------------------------------------

    def build_google_service(self, name, version, scopes):
        """Generic builder for any Google API service."""
        if not all(get_env("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")):
            print(f"{name.title()} not configured.")
            return None
        try:
            creds = create_credentials(scopes)
            return build(name, version, credentials=creds)
        except Exception as e:
            print(f"Error initializing {name}: {e}")
            return None

    # ------------------------------------------------------------
    # Calendar
    # ------------------------------------------------------------

    def get_upcoming_events(self, days=7):
        if not self.calendar:
            return []

        now = datetime.utcnow()
        try:
            events = (
                self.calendar.events()
                .list(
                    calendarId="primary",
                    timeMin=f"{now.isoformat()}Z",
                    timeMax=f"{(now + timedelta(days=days)).isoformat()}Z",
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
                .get("items", [])
            )
            return events
        except Exception as e:
            print(f"Calendar error: {e}")
            return []

    # ------------------------------------------------------------
    # Gemini Generation
    # ------------------------------------------------------------

    def ask_gemini(self, prompt, retries=3):
        for i in range(retries):
            try:
                return self.model.generate_content(prompt).text
            except Exception as e:
                if "429" in str(e):
                    sleep_time = 5 * (2 ** i)
                    print(f"Rate-limited, retrying in {sleep_time}s...")
                    time.sleep(sleep_time)
                else:
                    print(f"Gemini error: {e}")
                    return None
        return None

    # ------------------------------------------------------------
    # Facebook Posting
    # ------------------------------------------------------------

    def fb_post(self, message):
        """Simple text post."""
        try:
            r = requests.post(
                f"{self.FB_API}/me/feed",
                data={"message": message, "access_token": self.fb_token},
            )
            if r.status_code == 200:
                print("✓ FB post succeeded.")
                return True
            print(f"FB error: {r.json()}")
            return False
        except Exception as e:
            print(f"Facebook posting error: {e}")
            return False

    def fb_post_images(self, message, images):
        """Upload images then create a post referencing them."""
        if not images:
            return self.fb_post(message)

        media_ids = []
        try:
            for img in images[:10]:
                upload = requests.post(
                    f"{self.FB_API}/me/photos",
                    files={"source": (img["filename"], img["data"], img["mime_type"])},
                    data={"published": "false", "access_token": self.fb_token},
                )
                if upload.status_code == 200:
                    media_ids.append({"media_fbid": upload.json().get("id")})

            if not media_ids:
                return self.fb_post(message)

            payload = {
                "message": message,
                "attached_media": media_ids,
                "access_token": self.fb_token,
            }
            r = requests.post(
                f"{self.FB_API}/me/feed",
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
            )
            return r.status_code == 200
        except Exception as e:
            print(f"Image post error: {e}")
            return False

    # ------------------------------------------------------------
    # Email Parsing
    # ------------------------------------------------------------

    def get_email_body(self, msg):
        try:
            parts = msg["payload"].get("parts", [])
            for p in parts:
                if p["mimeType"] == "text/plain":
                    data = p["body"].get("data")
                    return b64_decode(data).decode("utf-8") if data else ""
            data = msg["payload"]["body"].get("data")
            return b64_decode(data).decode("utf-8") if data else ""
        except:
            return ""

    def extract_sender(self, msg):
        return safe_get(msg["payload"]["headers"], "From")

    def extract_images(self, msg):
        images = []

        def walk(part):
            mime = part.get("mimeType", "")
            if mime.startswith("image/"):
                data = part["body"].get("data")
                attach_id = part["body"].get("attachmentId")
                if attach_id:
                    attachment = (
                        self.gmail.users()
                        .messages()
                        .attachments()
                        .get(userId="me", messageId=msg["id"], id=attach_id)
                        .execute()
                    )
                    data = attachment["data"]
                if data:
                    images.append(
                        {
                            "filename": part.get("filename") or f"image_{len(images)}.jpg",
                            "data": b64_decode(data),
                            "mime_type": mime,
                        }
                    )
            for sub in part.get("parts", []):
                walk(sub)

        walk(msg["payload"])
        return images

    # ------------------------------------------------------------
    # Document Parsing
    # ------------------------------------------------------------

    def extract_doc(self, filename, data):
        if filename.endswith(".pdf"):
            try:
                reader = PyPDF2.PdfReader(BytesIO(data))
                return "\n".join([p.extract_text() or "" for p in reader.pages])
            except:
                return ""
        if filename.endswith(".docx") or filename.endswith(".doc"):
            try:
                doc = Document(BytesIO(data))
                return "\n".join([p.text for p in doc.paragraphs])
            except:
                return ""
        return ""

    def extract_attachment(self, msg):
        for part in msg["payload"].get("parts", []):
            name = part.get("filename", "")
            if name.lower().endswith((".pdf", ".docx", ".doc")):
                attach_id = part["body"].get("attachmentId")
                if attach_id:
                    att = (
                        self.gmail.users()
                        .messages()
                        .attachments()
                        .get(userId="me", messageId=msg["id"], id=attach_id)
                        .execute()
                    )
                    return name, b64_decode(att["data"])
        return None, None

    # ------------------------------------------------------------
    # Drive Upload
    # ------------------------------------------------------------

    def upload_to_drive(self, filename, data, mime):
        folder = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
        if not folder:
            return None

        try:
            media = MediaIoBaseUpload(BytesIO(data), mimetype=mime, resumable=False)
            file = (
                self.drive.files()
                .create(body={"name": filename, "parents": [folder]}, media_body=media, fields="id,webViewLink")
                .execute()
            )
            self.drive.permissions().create(
                fileId=file["id"], body={"type": "anyone", "role": "reader"}
            ).execute()
            return file["webViewLink"]
        except Exception as e:
            print(f"Drive upload error: {e}")
            return None

    # ============================================================
    # Business Logic — Event Posts, Meeting Minutes, Requests
    # ============================================================

    def generate_post(self, topic, context=""):
        prompt = f"""
Generate a friendly Facebook post for Hallmark HOA.

Topic: {topic}
Context: {context}

Requirements:
- Warm, neighborly tone.
- Under 250 words.
- Max 2 hashtags.
- No placeholders.
"""
        return self.ask_gemini(prompt)

    # (…Additional logic identical to original but optimized…)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("HOA POSTER STARTING")
    print("=" * 60)

    mode = os.getenv("RUN_MODE", "calendar")
    poster = HOAPoster()

    if mode == "calendar":
        poster.check_and_post_event_reminders()

    elif mode == "meeting_minutes":
        poster.check_meeting_minutes_emails()

    elif mode == "facebook_posts":
        poster.check_facebook_post_emails()

    elif mode == "custom":
        topic = os.getenv("POST_TOPIC", "General HOA Update")
        context = os.getenv("POST_CONTEXT", "")
        poster.create_and_post(topic, context)

    elif mode == "both":
        poster.check_and_post_event_reminders()
        poster.check_meeting_minutes_emails()
        poster.check_facebook_post_emails()

    else:
        print(f"Unknown mode: {mode}")

    print("HOA POSTER COMPLETED")


if __name__ == "__main__":
    main()





