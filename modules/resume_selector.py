from __future__ import annotations

from modules.matcher import MatchResult

# If top-1 minus top-2 hybrid is below this, treat suggestion as low-confidence.
MARGIN_THRESHOLD = 5.0


def suggest_resume(results: list[MatchResult]) -> tuple[str | None, bool, list[MatchResult]]:
    """
    Returns (suggested_resume_id, low_confidence, sorted_results).
    low_confidence True means UI should nudge manual review.
    """
    if not results:
        return None, True, []
    if len(results) == 1:
        return results[0].resume_id, False, results
    top, second = results[0], results[1]
    margin = top.hybrid - second.hybrid
    low = margin < MARGIN_THRESHOLD
    return top.resume_id, low, results
