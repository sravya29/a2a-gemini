import os
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from google_auth_oauthlib.flow import InstalledAppFlow
import requests, json

# This opens a browser → shows Google consent screen → gets token
flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json",
    scopes=["openid", "email", "profile", "https://www.googleapis.com/auth/cloud-platform"]
)
creds = flow.run_local_server(port=9999, host="127.0.0.1")
token = creds.token

print(f"Got token: {token[:20]}...")

# Now call your agent
response = requests.post(
    "http://localhost:8080/",
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    },
    json={
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"text": "Hello, what can you do?"}],
                "messageId": "msg-1"
            }
        }
    }
)
print(json.dumps(response.json(), indent=2))
