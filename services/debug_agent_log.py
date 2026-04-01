"""Append NDJSON lines for Cursor debug mode (local path; fails silently on server)."""

import json
import os
import time
from typing import Any, Dict

_SESSION_ID = "0a386a"
# Primary: Cursor session path. Secondary: repo root (always writable when running from checkout).
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_DEBUG_LOG = os.path.normpath(os.path.join(_HERE, "..", "debug-0a386a.log"))
_DEBUG_LOG_PATHS = (
    "/Users/olcoz/Documents/My Cursor/.cursor/debug-0a386a.log",
    _REPO_DEBUG_LOG,
)


def debug_agent_log(
    hypothesis_id: str, location: str, message: str, data: Dict[str, Any]
) -> None:
    # #region agent log
    payload: Dict[str, Any] = {
        "sessionId": _SESSION_ID,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    for path in _DEBUG_LOG_PATHS:
        try:
            log_dir = os.path.dirname(path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass
    # #endregion
