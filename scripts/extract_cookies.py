"""Extract Beike cookies from CDP browser session and save as JSON."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BROWSER_COOKIES_JS = (
    Path.home() / ".claude" / "skills" / "browser-tools" / "browser-cookies.js"
)
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "beike_cookies.json"


def extract_beike_cookies() -> dict[str, str]:
    """Connect to Chrome CDP, extract .ke.com cookies, return name→value dict."""
    proc = subprocess.run(
        [str(BROWSER_COOKIES_JS)], capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"browser-cookies.js failed: {proc.stderr}")

    cookies: dict[str, str] = {}
    cookie_name = ""
    cookie_value = ""
    cookie_domain = ""

    for line in proc.stdout.splitlines():
        stripped = line.strip()

        # Blank line = end of current cookie
        if not stripped:
            if cookie_name and cookie_value and ".ke.com" in cookie_domain:
                cookies[cookie_name] = cookie_value
            cookie_name = ""
            cookie_value = ""
            cookie_domain = ""
            continue

        # Indented = property line
        if line.startswith(" "):
            if stripped.startswith("domain:"):
                cookie_domain = stripped.split(":", 1)[1].strip()
            continue

        # Non-indented, non-empty = "name: value" line
        if ": " in stripped:
            cookie_name, cookie_value = stripped.split(": ", 1)

    # Don't forget last cookie if no trailing blank line
    if cookie_name and cookie_value and ".ke.com" in cookie_domain:
        cookies[cookie_name] = cookie_value

    return cookies


def main() -> int:
    try:
        cookies = extract_beike_cookies()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("Make sure Chrome is running with remote debugging on :9222", file=sys.stderr)
        return 1

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(cookies, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(f"Extracted {len(cookies)} .ke.com cookies → {OUTPUT_PATH}")
    for name in sorted(cookies.keys()):
        val = cookies[name]
        print(f"  {name}={val[:50]}{'...' if len(val) > 50 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
