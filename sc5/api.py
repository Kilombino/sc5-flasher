"""Read-only client for the Goldshell SC5 Pro II.

Phase 1 of this project must never change anything on the miner. This module
enforces that by construction:

* cgminer API (TCP 4028): only commands in READ_COMMANDS are sent.
* Web API (HTTP 80): only GET requests, only paths in READ_PATHS.

There is no code path here that issues PUT/POST, logs in, restarts, uploads
firmware or toggles SSH. Adding one belongs to a later, reviewed phase.
"""

import json
import re
import socket
import urllib.request

READ_COMMANDS = frozenset({"version", "summary", "devs", "pools", "stats"})
READ_PATHS = frozenset({
    "/mcb/status",
    "/mcb/setting",
    "/mcb/pools",
    "/mcb/algosetting",
    "/mcb/ip",
})

CGMINER_PORT = 4028
TIMEOUT = 8


class ReadOnlyViolation(ValueError):
    """Raised when a caller asks for something outside the read-only allowlist."""


def parse_cgminer(raw):
    """Parses a cgminer reply. Strips NULs and fixes the missing comma that
    intminer 5.4.2 emits between objects in `stats` ("...}{...")."""
    text = raw.replace("\x00", "").strip()
    text = re.sub(r"\}\s*\{", "},{", text)
    return json.loads(text)


def cgminer(host, command, port=CGMINER_PORT, timeout=TIMEOUT):
    if command not in READ_COMMANDS:
        raise ReadOnlyViolation(f"cgminer command not allowed in read-only mode: {command!r}")
    payload = json.dumps({"command": command}).encode()
    chunks = []
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(payload)
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
            if data.endswith(b"\x00"):
                break
    return parse_cgminer(b"".join(chunks).decode("utf-8", errors="replace"))


def web_get(host, path, timeout=TIMEOUT):
    if path not in READ_PATHS:
        raise ReadOnlyViolation(f"web path not allowed in read-only mode: {path!r}")
    req = urllib.request.Request(f"http://{host}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    return json.loads(body) if body.strip() else None
