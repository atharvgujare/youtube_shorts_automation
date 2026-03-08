import argparse
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-secrets", required=True, help="Path to OAuth desktop client JSON")
    parser.add_argument(
        "--scopes",
        default="https://www.googleapis.com/auth/youtube.upload",
        help="Comma-separated scopes",
    )
    args = parser.parse_args()

    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    flow = InstalledAppFlow.from_client_secrets_file(args.client_secrets, scopes=scopes)
    creds = flow.run_local_server(port=0)

    payload = json.loads(creds.to_json())
    print("YT_CLIENT_ID=" + payload.get("client_id", ""))
    print("YT_CLIENT_SECRET=" + payload.get("client_secret", ""))
    print("YT_REFRESH_TOKEN=" + payload.get("refresh_token", ""))


if __name__ == "__main__":
    main()
