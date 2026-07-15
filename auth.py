import os
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")


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
