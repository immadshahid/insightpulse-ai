"""Read a Google Sheet that is shared by link, as CSV.

Only sheet links on docs.google.com are accepted, and the download URL is rebuilt from the
sheet id, so a user cannot make the server fetch an arbitrary address. Redirects are
followed by hand and must stay on Google hosts.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

import httpx

_SHEET = re.compile(r"^https://docs\.google\.com/spreadsheets/d/([\w-]{20,})(?:[/?#].*)?$")
_GID = re.compile(r"[?#&]gid=(\d+)")
_ALLOWED_HOSTS = (".google.com", ".googleusercontent.com")
_MAX_REDIRECTS = 5
_NOT_SHARED = (
    "That sheet isn't shared. In Google Sheets choose Share, set General access to "
    "'Anyone with the link', then try again."
)


class SheetError(ValueError):
    """The link is not usable; the message is safe to show to the user."""


def export_url(link: str) -> str:
    """The CSV download address for a Google Sheets link."""
    found = _SHEET.match(link.strip())
    if not found:
        raise SheetError("Paste a Google Sheets link (docs.google.com/spreadsheets/...).")
    gid = _GID.search(link)
    suffix = f"&gid={gid.group(1)}" if gid else ""
    return f"https://docs.google.com/spreadsheets/d/{found.group(1)}/export?format=csv{suffix}"


def _allowed(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and (parts.hostname or "").endswith(_ALLOWED_HOSTS)


def _read(response: httpx.Response, max_bytes: int) -> bytes:
    if "text/html" in response.headers.get("content-type", ""):
        raise SheetError(_NOT_SHARED)
    data = bytearray()
    for chunk in response.iter_bytes():
        data.extend(chunk)
        if len(data) > max_bytes:
            raise SheetError(f"That sheet is larger than {max_bytes // (1024 * 1024)} MB.")
    return bytes(data)


def fetch_sheet(link: str, max_bytes: int, client: httpx.Client | None = None) -> bytes:
    """Download the sheet as CSV bytes; raises SheetError with a user-facing message."""
    url = export_url(link)
    http = client or httpx.Client(timeout=30.0)
    try:
        for _ in range(_MAX_REDIRECTS + 1):
            with http.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    if not _allowed(url):
                        raise SheetError("That sheet could not be read safely.")
                    if urlsplit(url).hostname == "accounts.google.com":
                        raise SheetError(_NOT_SHARED)
                    continue
                if response.status_code in (401, 403, 404):
                    raise SheetError(_NOT_SHARED)
                if response.status_code != 200:
                    raise SheetError("Google Sheets didn't respond. Please try again.")
                return _read(response, max_bytes)
    except httpx.HTTPError as exc:
        raise SheetError("Couldn't reach Google Sheets. Please try again.") from exc
    finally:
        if client is None:
            http.close()
    raise SheetError("That sheet could not be read safely.")
