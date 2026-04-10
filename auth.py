import os
import httpx
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
ALLOWED_EMAIL = os.getenv("ALLOWED_EMAIL", "")


async def verify_google_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    """
    Validates the Bearer token against Google's tokeninfo endpoint.
    Returns token info dict if valid.
    """
    token = credentials.credentials

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            GOOGLE_TOKENINFO_URL,
            params={"access_token": token}
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired Google token. Re-authenticate via OAuth."
        )

    info = resp.json()

    # Check for token expiry explicitly
    if "error" in info:
        raise HTTPException(
            status_code=401,
            detail=f"Token error: {info.get('error_description', info['error'])}"
        )

    # Optional: restrict to specific email
    if ALLOWED_EMAIL and info.get("email") != ALLOWED_EMAIL:
        raise HTTPException(
            status_code=403,
            detail=f"Unauthorized account: {info.get('email')}. Only {ALLOWED_EMAIL} is allowed."
        )

    return info
