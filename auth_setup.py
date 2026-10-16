"""Create a Google OAuth refresh token on a device with a browser."""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
SCOPES = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/youtube.upload"]
def main():
    path = Path("credentials.json")
    if not path.exists(): raise SystemExit("Place your Google OAuth Desktop client JSON here as credentials.json")
    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
    # Termux can host this temporary loopback callback on the same Android device.
    creds = flow.run_local_server(host="127.0.0.1", port=0, open_browser=False, authorization_prompt_message="Open this Google authorization URL in your phone browser: {url}", success_message="Authorization complete. You can return to Termux.", access_type="offline", prompt="consent")
    Path("token.json").write_text(creds.to_json(), encoding="utf-8")
    print("Created token.json. Never share credentials.json or token.json.")
if __name__ == "__main__": main()
