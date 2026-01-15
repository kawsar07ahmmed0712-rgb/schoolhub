from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "ML-Dataset"
EXTRACT_DIR = DATA_DIR / "extracted"
ARTIFACT_DIR = Path(__file__).resolve().parent / "ml_artifacts"

DROP_ZIP = DATA_DIR / "archive (6).zip"
DROP_FILE = EXTRACT_DIR / "archive6" / "data.csv"
PERF_ZIP = DATA_DIR / "archive (7).zip"
PERF_FILE = EXTRACT_DIR / "archive7" / "StudentsPerformance.csv"

DROPOUT_FORM_FIELDS: List[Dict[str, Any]] = [
    {"name": "admission_grade", "label": "Admission grade", "hint": "0-200", "type": "number", "step": "0.1"},
    {"name": "age_at_enrollment", "label": "Age at enrollment", "hint": "18-65", "type": "number", "step": "1"},
    {"name": "first_sem_enrolled", "label": "1st sem units (enrolled)", "hint": "0-10", "type": "number", "step": "1"},
    {"name": "first_sem_approved", "label": "1st sem units (approved)", "hint": "0-10", "type": "number", "step": "1"},
    {"name": "first_sem_grade", "label": "1st sem average grade", "hint": "0-20", "type": "number", "step": "0.1"},
    {"name": "second_sem_enrolled", "label": "2nd sem units (enrolled)", "hint": "0-10", "type": "number", "step": "1"},
    {"name": "second_sem_approved", "label": "2nd sem units (approved)", "hint": "0-10", "type": "number", "step": "1"},
    {"name": "second_sem_grade", "label": "2nd sem average grade", "hint": "0-20", "type": "number", "step": "0.1"},
    {"name": "tuition_paid", "label": "Tuition fees up to date", "hint": "1=yes, 0=no", "type": "number", "step": "1"},
    {"name": "scholarship_holder", "label": "Scholarship holder", "hint": "1=yes, 0=no", "type": "number", "step": "1"},
    {"name": "debtor", "label": "Debtor flag", "hint": "1=yes, 0=no", "type": "number", "step": "1"},
    {"name": "international", "label": "International student", "hint": "1=yes, 0=no", "type": "number", "step": "1"},
    {"name": "gender", "label": "Gender", "hint": "1=male, 0=female", "type": "number", "step": "1"},
]

EXAM_FORM_FIELDS: List[Dict[str, Any]] = [
    {"name": "gender", "label": "Gender"},
    {"name": "race_ethnicity", "label": "Race/ethnicity"},
    {"name": "parent_education", "label": "Parental education"},
    {"name": "lunch", "label": "Lunch"},
    {"name": "test_prep", "label": "Test prep course"},
]

DROPOUT_SOURCE_COLUMNS = {
    "admission_grade": "Admission grade",
    "age_at_enrollment": "Age at enrollment",
    "first_sem_enrolled": "Curricular units 1st sem (enrolled)",
    "first_sem_approved": "Curricular units 1st sem (approved)",
    "first_sem_grade": "Curricular units 1st sem (grade)",
    "second_sem_enrolled": "Curricular units 2nd sem (enrolled)",
    "second_sem_approved": "Curricular units 2nd sem (approved)",
    "second_sem_grade": "Curricular units 2nd sem (grade)",
    "tuition_paid": "Tuition fees up to date",
    "scholarship_holder": "Scholarship holder",
    "debtor": "Debtor",
    "international": "International",
    "gender": "Gender",
}

EXAM_SOURCE_COLUMNS = {
    "gender": "gender",
    "race_ethnicity": "race/ethnicity",
    "parent_education": "parental level of education",
    "lunch": "lunch",
    "test_prep": "test preparation course",
}

_dropout_model = None
_dropout_meta: Dict[str, Any] | None = None
_performance_model = None
_performance_meta: Dict[str, Any] | None = None
_summary_cache: Dict[str, Any] | None = None


@dataclass
class TrainSummary:
    name: str
    rows: int
    metrics: Dict[str, float]
    trained_at: str
    features: List[str]
    defaults: Dict[str, Any]
    extra: Dict[str, Any] | None = None


def _ensure_dirs() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)


def _extract_if_needed(zip_path: Path, dest: Path) -> None:
    if dest.exists():
        return
    if zip_path.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest.parent)


def _load_dropout_df() -> pd.DataFrame:
    _ensure_dirs()
    _extract_if_needed(DROP_ZIP, DROP_FILE)
    df = pd.read_csv(DROP_FILE, sep=";")
    df.columns = [c.strip() for c in df.columns]
    df = df.dropna(subset=["Target"])
    df["Target"] = df["Target"].str.strip()
    return df


def _load_exam_df() -> pd.DataFrame:
    _ensure_dirs()
    _extract_if_needed(PERF_ZIP, PERF_FILE)
    df = pd.read_csv(PERF_FILE)
    return df


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _load_json(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _train_dropout(force: bool = False) -> TrainSummary:
    global _dropout_model, _dropout_meta
    model_path = ARTIFACT_DIR / "dropout_model.joblib"
    meta_path = ARTIFACT_DIR / "dropout_meta.json"

    if not force and model_path.exists() and meta_path.exists():
        _dropout_model = joblib.load(model_path)
        _dropout_meta = _load_json(meta_path)
        assert _dropout_meta is not None
        return TrainSummary(
            name="dropout",
            rows=_dropout_meta.get("dataset_rows", 0),
            metrics=_dropout_meta.get("metrics", {}),
            trained_at=_dropout_meta.get("trained_at", ""),
            features=list(DROPOUT_SOURCE_COLUMNS.keys()),
            defaults=_dropout_meta.get("defaults", {}),
            extra={"classes": _dropout_meta.get("classes", [])},
        )

    df = _load_dropout_df()
    feature_cols = [DROPOUT_SOURCE_COLUMNS[k] for k in DROPOUT_SOURCE_COLUMNS]
    X = df[feature_cols]
    y = df["Target"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    pipeline = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(max_iter=1200)),
        ]
    )

    pipeline.fit(X_train, y_train)
    preds = pipeline.predict(X_test)

    metrics = {
        "accuracy": float(accuracy_score(y_test, preds)),
        "f1_weighted": float(f1_score(y_test, preds, average="weighted")),
    }

    defaults = X.median(numeric_only=True).to_dict()
    trained_at = datetime.utcnow().isoformat() + "Z"

    meta = {
        "trained_at": trained_at,
        "metrics": metrics,
        "features": list(DROPOUT_SOURCE_COLUMNS.keys()),
        "source_columns": DROPOUT_SOURCE_COLUMNS,
        "defaults": defaults,
        "classes": list(pipeline.classes_),
        "dataset_rows": int(len(df)),
        "dataset_path": str(DROP_FILE),
    }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, model_path)
    _save_json(meta_path, meta)

    _dropout_model = pipeline
    _dropout_meta = meta

    return TrainSummary(
        name="dropout",
        rows=len(df),
        metrics=metrics,
        trained_at=trained_at,
        features=list(DROPOUT_SOURCE_COLUMNS.keys()),
        defaults=defaults,
        extra={"classes": meta["classes"]},
    )


def _train_exam(force: bool = False) -> TrainSummary:
    global _performance_model, _performance_meta
    model_path = ARTIFACT_DIR / "exam_performance_model.joblib"
    meta_path = ARTIFACT_DIR / "exam_performance_meta.json"

    if not force and model_path.exists() and meta_path.exists():
        _performance_model = joblib.load(model_path)
        _performance_meta = _load_json(meta_path)
        assert _performance_meta is not None
        return TrainSummary(
            name="exam_performance",
            rows=_performance_meta.get("dataset_rows", 0),
            metrics=_performance_meta.get("metrics", {}),
            trained_at=_performance_meta.get("trained_at", ""),
            features=list(EXAM_SOURCE_COLUMNS.keys()),
            defaults=_performance_meta.get("defaults", {}),
            extra={"choices": _performance_meta.get("choices", {})},
        )

    df = _load_exam_df()
    df["avg_score"] = df[["math score", "reading score", "writing score"]].mean(axis=1)

    feature_cols = [EXAM_SOURCE_COLUMNS[k] for k in EXAM_SOURCE_COLUMNS]
    X = df[feature_cols]
    y = df["avg_score"]

    cat_features = feature_cols
    pre = ColumnTransformer(
        transformers=[
            (
                "cat",
                Pipeline(
                    steps=[
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                cat_features,
            )
        ]
    )

    model = RandomForestRegressor(
        n_estimators=400,
        random_state=42,
        min_samples_leaf=1,
    )

    pipeline = Pipeline(steps=[("pre", pre), ("model", model)])

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    pipeline.fit(X_train, y_train)
    preds = pipeline.predict(X_test)

    metrics = {
        "mae": float(mean_absolute_error(y_test, preds)),
        "r2": float(r2_score(y_test, preds)),
    }

    defaults = {}
    choices = {}
    for key, col in EXAM_SOURCE_COLUMNS.items():
        defaults[key] = df[col].mode(dropna=True).iloc[0]
        choices[key] = sorted(str(v) for v in df[col].dropna().unique())

    trained_at = datetime.utcnow().isoformat() + "Z"

    meta = {
        "trained_at": trained_at,
        "metrics": metrics,
        "features": list(EXAM_SOURCE_COLUMNS.keys()),
        "source_columns": EXAM_SOURCE_COLUMNS,
        "defaults": defaults,
        "choices": choices,
        "dataset_rows": int(len(df)),
        "dataset_path": str(PERF_FILE),
    }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, model_path)
    _save_json(meta_path, meta)

    _performance_model = pipeline
    _performance_meta = meta

    return TrainSummary(
        name="exam_performance",
        rows=len(df),
        metrics=metrics,
        trained_at=trained_at,
        features=list(EXAM_SOURCE_COLUMNS.keys()),
        defaults=defaults,
        extra={"choices": choices},
    )


def train_all(force: bool = False) -> Tuple[TrainSummary, TrainSummary]:
    """
    Train both models. If artifacts already exist and force=False, they are reused.
    """
    return _train_dropout(force=force), _train_exam(force=force)


def _ensure_models() -> None:
    if _dropout_model is None or _dropout_meta is None:
        _train_dropout(force=False)
    if _performance_model is None or _performance_meta is None:
        _train_exam(force=False)


def predict_dropout(features: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_models()
    assert _dropout_model is not None
    assert _dropout_meta is not None

    row: Dict[str, Any] = {}
    for key, col in DROPOUT_SOURCE_COLUMNS.items():
        raw = features.get(key)
        try:
            val = float(raw)
        except Exception:
            val = float(_dropout_meta["defaults"].get(key, 0))
        row[col] = val

    df = pd.DataFrame([row])
    proba = _dropout_model.predict_proba(df)[0]
    classes = list(_dropout_model.classes_)
    confidence = max(proba)
    label = classes[int(proba.argmax())]

    return {
        "label": label,
        "confidence": float(confidence),
        "probabilities": {cls: float(p) for cls, p in zip(classes, proba)},
        "used_features": row,
        "trained_at": _dropout_meta.get("trained_at"),
        "metrics": _dropout_meta.get("metrics", {}),
    }


def predict_exam_performance(features: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_models()
    assert _performance_model is not None
    assert _performance_meta is not None

    row: Dict[str, Any] = {}
    for key, col in EXAM_SOURCE_COLUMNS.items():
        val = features.get(key) or _performance_meta["defaults"].get(key)
        row[col] = str(val)

    df = pd.DataFrame([row])
    pred = _performance_model.predict(df)[0]

    def grade_band(score: float) -> str:
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "Needs support"

    return {
        "predicted_score": float(pred),
        "grade_band": grade_band(float(pred)),
        "used_features": row,
        "trained_at": _performance_meta.get("trained_at"),
        "metrics": _performance_meta.get("metrics", {}),
    }


def get_ml_summary() -> Dict[str, Any]:
    global _summary_cache
    if _summary_cache:
        return _summary_cache

    dropout_train, exam_train = train_all(force=False)
    dropout_df = _load_dropout_df()
    exam_df = _load_exam_df()

    _summary_cache = {
        "dropout": {
            "rows": dropout_train.rows,
            "metrics": dropout_train.metrics,
            "trained_at": dropout_train.trained_at,
            "features": DROPOUT_FORM_FIELDS,
            "classes": dropout_train.extra.get("classes") if dropout_train.extra else [],
            "defaults": dropout_train.defaults,
            "sample": dropout_df[[c for c in DROPOUT_SOURCE_COLUMNS.values()]].head(3).to_dict(orient="records"),
        },
        "exam": {
            "rows": exam_train.rows,
            "metrics": exam_train.metrics,
            "trained_at": exam_train.trained_at,
            "features": EXAM_FORM_FIELDS,
            "choices": exam_train.extra.get("choices") if exam_train.extra else {},
            "defaults": exam_train.defaults,
            "sample": exam_df[list(EXAM_SOURCE_COLUMNS.values()) + ["math score", "reading score", "writing score"]]
            .head(3)
            .to_dict(orient="records"),
        },
    }
    return _summary_cache
