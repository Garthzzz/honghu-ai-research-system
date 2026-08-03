from __future__ import annotations


def coverage_multiplier(coverage: float) -> float:
    if coverage >= 0.80:
        return 1.0
    if coverage >= 0.65:
        return 0.85
    if coverage >= 0.50:
        return 0.60
    return 0.0


def confidence_multiplier(confidence: float) -> float:
    if confidence >= 0.85:
        return 1.0
    if confidence >= 0.75:
        return 0.90
    if confidence >= 0.60:
        return 0.75
    if confidence >= 0.45:
        return 0.50
    return 0.0


def audit_multiplier(open_p0: int, open_p1: int, calculation_fail: bool = False) -> float:
    if calculation_fail:
        return 0.0
    if open_p0:
        return 0.0
    if open_p1:
        return 0.85
    return 1.0


def adjusted_score(raw: float, multiplier: float) -> float:
    return 50.0 + (raw - 50.0) * multiplier


def score_grade(score: float | None, blocked: bool = False) -> str:
    if score is None:
        return "unrated"
    if blocked:
        return "F"
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    if score >= 50:
        return "D"
    return "F"


def score_quality_label(coverage: float, confidence: float, review_required: bool = False) -> str:
    if review_required:
        return "review_required"
    if coverage < 0.5 or confidence < 0.45:
        return "unrated_insufficient_evidence"
    if coverage >= 0.80 and confidence >= 0.85:
        return "high_confidence"
    if coverage >= 0.65 and confidence >= 0.75:
        return "medium_confidence"
    return "provisional"


def score_band_width(coverage: float, confidence: float, open_p1: int) -> float:
    width = 6.0
    if coverage < 0.8:
        width += 4.0
    if confidence < 0.75:
        width += 4.0
    if open_p1:
        width += 3.0
    return width
