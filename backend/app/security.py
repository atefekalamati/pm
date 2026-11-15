import hashlib
import hmac
import secrets


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt, digest = stored.split(":")
    return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)).split(":")[1], digest)


def hash_token(token: str) -> str:
    """Only this hash is stored; a copy of the database cannot be used to sign in."""
    return hashlib.sha256(token.encode()).hexdigest()
