import os
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
DEVICE_INGEST_TOKEN = os.environ.get("DEVICE_INGEST_TOKEN")


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    if not ADMIN_PASSWORD:
        raise HTTPException(status_code=500, detail="ADMIN_PASSWORD is not configured on the server")

    valid_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    valid_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (valid_username and valid_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


def require_device_token(token: str) -> None:
    if not DEVICE_INGEST_TOKEN:
        raise HTTPException(status_code=500, detail="DEVICE_INGEST_TOKEN is not configured on the server")

    # 404 rather than 401/403: a wrong token should look like a nonexistent
    # path, not confirm that a protected ingest endpoint lives here.
    if not secrets.compare_digest(token, DEVICE_INGEST_TOKEN):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
