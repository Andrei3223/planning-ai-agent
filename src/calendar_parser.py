from __future__ import annotations
from datetime import datetime, timedelta, timezone
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import os.path

# Read-only scope
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

def get_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)

def list_upcoming_primary(n=10):
    service = get_service()
    now = datetime.now(timezone.utc).isoformat()
    events_result = service.events().list(
        calendarId="primary",
        timeMin=now,
        maxResults=n,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    for e in events_result.get("items", []):
        start = e["start"].get("dateTime") or e["start"].get("date")
        print(start, "-", e.get("summary", "(no title)"))

if __name__ == "__main__":
    list_upcoming_primary()
