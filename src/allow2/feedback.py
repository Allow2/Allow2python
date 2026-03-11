from __future__ import annotations

from allow2.models import FeedbackCategory

VALID_CATEGORIES: list[FeedbackCategory] = list(FeedbackCategory)

CATEGORY_LABELS: dict[FeedbackCategory, str] = {
    FeedbackCategory.BYPASS: "Bypass / Circumvention report",
    FeedbackCategory.MISSING_FEATURE: "Missing Feature report",
    FeedbackCategory.NOT_WORKING: "Not Working report",
    FeedbackCategory.QUESTION: "Question",
    FeedbackCategory.OTHER: "General feedback",
}


def feedback_category_to_text(category: FeedbackCategory) -> str:
    return CATEGORY_LABELS.get(category, "Feedback")
