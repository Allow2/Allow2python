from __future__ import annotations

from typing import Any, Callable

from allow2.models import WarningLevel, WarningThreshold

DEFAULT_THRESHOLDS: list[WarningThreshold] = [
    WarningThreshold(remaining=15 * 60, level=WarningLevel.INFO),
    WarningThreshold(remaining=5 * 60, level=WarningLevel.URGENT),
    WarningThreshold(remaining=60, level=WarningLevel.FINAL),
    WarningThreshold(remaining=30, level=WarningLevel.COUNTDOWN),
]


class WarningScheduler:
    """Tracks remaining time per activity and emits 'warning' events
    when configurable thresholds are crossed. Fire-once per level per activity."""

    def __init__(
        self,
        *,
        emit: Callable[..., Any],
        thresholds: list[WarningThreshold] | None = None,
    ) -> None:
        self._emit = emit
        self._thresholds = sorted(
            (thresholds or DEFAULT_THRESHOLDS)[:],
            key=lambda t: t.remaining,
            reverse=True,
        )
        self._fired: dict[str, set[WarningLevel]] = {}

    def update(self, activities: dict[str, dict[str, Any]]) -> None:
        for activity_id, data in activities.items():
            remaining = data.get("remaining")
            if remaining is None or remaining < 0:
                continue

            fired_set = self._fired.get(activity_id)
            if fired_set is None:
                fired_set = set()
                self._fired[activity_id] = fired_set

            for threshold in self._thresholds:
                if remaining <= threshold.remaining and threshold.level not in fired_set:
                    fired_set.add(threshold.level)
                    self._emit("warning", {
                        "level": threshold.level.value,
                        "activityId": activity_id,
                        "remaining": remaining,
                    })

    def reset_activity(self, activity_id: str) -> None:
        self._fired.pop(activity_id, None)

    def reset_all(self) -> None:
        self._fired.clear()
