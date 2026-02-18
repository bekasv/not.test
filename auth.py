from passlib.context import CryptContext
from itsdangerous import URLSafeSerializer
from fastapi import Request
from typing import Optional

# bcrypt убираем: он сейчас ломается в твоей среде
pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd.verify(password, password_hash)

def make_serializer(secret: str) -> URLSafeSerializer:
    return URLSafeSerializer(secret, salt="session")

def set_session(response, serializer: URLSafeSerializer, user_id: int):
    token = serializer.dumps({"user_id": user_id})
    response.set_cookie("session", token, httponly=True, samesite="lax")

def clear_session(response):
    response.delete_cookie("session")

def get_session_user_id(request: Request, serializer: URLSafeSerializer) -> Optional[int]:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        data = serializer.loads(token)
        return int(data.get("user_id"))
    except Exception:
        return None
