from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ARTIFACT_DIR = Path(__file__).resolve().parent / "ml_artifacts"
AUTO_FILE = ARTIFACT_DIR / "auto_insights.json"


@dataclass
class AutoInsight:
    student_name: str
    label: str
    confidence: float
    submitted_by: str
    submitted_role: str
    submitted_at: str
    features: Dict[str, Any]


def _ensure_dir() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def load_auto_insights() -> List[AutoInsight]:
    if not AUTO_FILE.exists():
        return []
    with AUTO_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f) or []
    out: List[AutoInsight] = []
    for row in data:
        try:
            out.append(
                AutoInsight(
                    student_name=row.get("student_name", "Unknown"),
                    label=row.get("label", "Unknown"),
                    confidence=float(row.get("confidence", 0.0)),
                    submitted_by=row.get("submitted_by", "unknown"),
                    submitted_role=row.get("submitted_role", "unknown"),
                    submitted_at=row.get("submitted_at", ""),
                    features=row.get("features", {}),
                )
            )
        except Exception:
            continue
    return out


def save_auto_insight(entry: AutoInsight) -> None:
    _ensure_dir()
    rows = load_auto_insights()
    rows.append(entry)
    with AUTO_FILE.open("w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in rows], f, indent=2)


def clear_auto_insights() -> None:
    _ensure_dir()
    AUTO_FILE.write_text("[]", encoding="utf-8")


def build_risk_buckets(rows: List[AutoInsight]) -> Dict[str, List[AutoInsight]]:
    """
    Groups into high / medium / good buckets based on label and confidence.
    """
    buckets = {"high": [], "medium": [], "good": []}
    for r in rows:
        label = (r.label or "").lower()
        if "dropout" in label:
            buckets["high"].append(r)
        elif "enrolled" in label or "risk" in label:
            buckets["medium"].append(r)
        else:
            buckets["good"].append(r)
    # Secondary sort: highest confidence first
    for key in buckets:
        buckets[key] = sorted(buckets[key], key=lambda x: x.confidence, reverse=True)
    return buckets


def new_entry(student_name: str, label: str, confidence: float, submitted_by: str, role: str, features: Dict[str, Any]) -> AutoInsight:
    return AutoInsight(
        student_name=student_name.strip() or "Unnamed student",
        label=label,
        confidence=confidence,
        submitted_by=submitted_by,
        submitted_role=role,
        submitted_at=datetime.utcnow().isoformat() + "Z",
        features=features,
    )
