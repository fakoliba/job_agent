"""Map internal hybrid scores (0–100) to user-facing 0–10 scale."""


def hybrid_to_score_10(hybrid: float) -> int:
    return max(0, min(10, int(round(hybrid / 10))))
