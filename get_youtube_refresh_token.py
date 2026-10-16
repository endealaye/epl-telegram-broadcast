"""
One-time helper: get a YouTube refresh token for the upload scope.

Run on your own computer (it opens a browser), signed in as the channel owner:

    pip install google-auth-oauthlib
    python get_youtube_refresh_token.py client_secret.json

client_secret.json is the OAuth client ("Desktop app") downloaded from Google
Cloud Console. Then store the printed values as GitHub Actions secrets:
YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN.
"""
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python get_youtube_refresh_token.py client_secret.json")
    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
    # offline + consent forces Google to return a refresh token every time
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    print("\nAdd these as GitHub Actions secrets:")
    print(f"YOUTUBE_CLIENT_ID={creds.client_id}")
    print(f"YOUTUBE_CLIENT_SECRET={creds.client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")


if __name__ == "__main__":
    main()
