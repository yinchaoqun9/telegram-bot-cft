"""
Default days an opened item stays usable, by category.
Used for dashboard “opened” urgency (not a hard medical claim).
"""

from __future__ import annotations

from typing import Optional

# Days after opened_at before we treat the open lot as urgent/expired.
OPEN_SHELF_DAYS = {
    "罐头": 2,
    "汤包": 2,
    "猫条": 3,
    "冻干": 30,
    "零食": 14,
    "猫砂": 60,
    "药品": 90,
    "其他": 7,
}


def open_shelf_days(category: Optional[str]) -> int:
    cat = (category or "").strip() or "其他"
    return int(OPEN_SHELF_DAYS.get(cat, OPEN_SHELF_DAYS["其他"]))
