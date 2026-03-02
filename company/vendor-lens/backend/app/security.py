"""Security utilities: URL validation, input sanitization, prompt injection hardening."""
import re
from urllib.parse import urlparse
from fastapi import HTTPException

# Blocked networks (private, loopback, metadata)
_BLOCKED_HOSTS = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|::1"
    r"|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+"
    r"|169\.254\.\d+\.\d+"
    r"|metadata\.google\.internal"
    r"|100\.64\.\d+\.\d+"
    r")$",
    re.IGNORECASE,
)

_ALLOWED_SCHEMES = {"http", "https"}
MAX_URL_LENGTH = 2048

_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(previous|prior|all)\s+instructions?", re.IGNORECASE),
    re.compile(r"(system\s*prompt|system\s*message)", re.IGNORECASE),
    re.compile(r"<\s*(system|assistant|user)\s*>", re.IGNORECASE),
    re.compile(r"```\s*(system|prompt)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"act\s+as\s+(a\s+)?different", re.IGNORECASE),
    re.compile(r"forget\s+(your|all)\s+(previous|prior|instructions?)", re.IGNORECASE),
    re.compile(r"\[INST\]|\[\/INST\]", re.IGNORECASE),
    re.compile(r"<\|im_start\|>|<\|im_end\|>"),
]


def validate_url(url: str) -> str:
    """Validate URL is safe to fetch. Raises HTTPException on violation."""
    if len(url) > MAX_URL_LENGTH:
        raise HTTPException(status_code=400, detail="URL too long (max 2048 chars)")

    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL")

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=400,
            detail=f"URL scheme '{parsed.scheme}' not allowed. Use http or https.",
        )

    host = parsed.hostname or ""
    if not host:
        raise HTTPException(status_code=400, detail="URL has no host")

    if _BLOCKED_HOSTS.match(host):
        raise HTTPException(
            status_code=400,
            detail="URL points to a private or reserved address",
        )

    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
        raise HTTPException(
            status_code=400,
            detail="Direct IP addresses are not allowed. Use a domain name.",
        )

    return url


def sanitize_content(content: str, max_chars: int = 15000) -> str:
    """Strip prompt injection attempts from scraped content before passing to LLM."""
    content = content[:max_chars]
    for pattern in _INJECTION_PATTERNS:
        content = pattern.sub("[REMOVED]", content)
    return content
