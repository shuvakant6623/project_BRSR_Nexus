"""AI/OCR suggestion pipeline (spec §23, research §9).

Architecture (human-in-the-loop by design):
  evidence file → extraction provider → ai_suggestion (draft, with confidence)
  → owner Accepts / Edits / Rejects → an owner-authored IN_PROGRESS draft.

A suggestion can NEVER create a SUBMITTED/APPROVED/LOCKED value — acceptance
merely pre-fills an owner draft, indistinguishable from manual entry.

Providers: 'local_demo' deterministic extractor (development/demo, clearly
labelled), or an OpenAI-compatible API when AI_API_KEY + AI_PROVIDER=ollama/
openai are configured. Unavailable providers degrade gracefully: the core
application never depends on them.
"""
import re
import uuid
from datetime import UTC, datetime
from abc import ABC, abstractmethod
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record
from app.config import get_settings
from app.models import AISuggestion, AppUser, Evidence, MetricValue
from app.models.enums import AISuggestionStatus, AuditAction, MetricValueStatus

DEMO_PATTERNS = [
    # (label, regex over the file's text bytes) — deterministic demo extraction;
    # the lookbehind prevents swallowing adjacent dates/other numbers
    ("kwh", re.compile(rb"(?<![\d,.])([0-9][0-9,]{0,11})\s*kwh", re.I)),
    ("kl", re.compile(rb"(?<![\d,.])([0-9][0-9,]{0,11})\s*(?:kl|kilolitres?)\b", re.I)),
    ("litre", re.compile(rb"(?<![\d,.])([0-9][0-9,]{0,11})\s*(?:litres?|ltr)\b", re.I)),
    ("tonne", re.compile(rb"(?<![\d,.])([0-9][0-9,]{0,11})\s*(?:tonnes?|mt)\b", re.I)),
    ("tco2e", re.compile(rb"(?<![\d,.])([0-9][0-9,]{0,11})\s*(?:t ?co2e?|tonnes? co2)", re.I)),
]
UNIT_ALIASES = {"kwh": "kWh", "kl": "kL", "litre": "litre", "tonne": "tonne", "tco2e": "tCO2e"}


class ExtractionProvider(ABC):
    name: str

    @abstractmethod
    def extract(self, filename: str, content: bytes) -> list[dict]:
        """Return candidate extractions: [{value: str, unit: str, confidence: float}]."""


class LocalDemoProvider(ExtractionProvider):
    """Deterministic demo extractor for development — pattern-matches common
    utility-bill formats. Always labelled 'demo' in the UI."""

    name = "local_demo"

    def extract(self, filename: str, content: bytes) -> list[dict]:
        out: list[dict] = []
        for key, pattern in DEMO_PATTERNS:
            match = pattern.search(content)
            if match:
                raw = match.group(1).decode().replace(",", "").replace(" ", "")
                try:
                    value = Decimal(raw)
                except Exception:
                    continue
                out.append({
                    "value": str(value),
                    "unit": UNIT_ALIASES[key],
                    "confidence": 0.87,
                })
                break
        if not out:
            # fall back to the filename if it embeds a reading (demo behaviour)
            m = re.search(r"(\d{3,9})\s*(kwh|kl)", filename, re.I)
            if m:
                out.append({
                    "value": m.group(1),
                    "unit": UNIT_ALIASES[m.group(2).lower()],
                    "confidence": 0.55,
                })
        return out


class LLMAPIProvider(ExtractionProvider):
    """OpenAI-compatible chat-completions extraction, used only when
    AI_PROVIDER + AI_API_KEY are configured. Constrained per research §9.3:
    extract only what is present; null + low confidence when absent."""

    name = "llm_api"

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def extract(self, filename: str, content: bytes) -> list[dict]:
        import json as _json
        from urllib import request as _request

        text = content.decode("utf-8", errors="ignore")[:6000]
        # treat document text as untrusted data, never instructions (§9.3)
        body = _json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content":
                    "You extract numeric utility readings from document text. "
                    "Respond ONLY with JSON: {\"value\": number|null, \"unit\": \"kWh\"|\"kL\"|\"litre\"|\"tonne\"|\"tCO2e\"|null, "
                    "\"confidence\": 0.0-1.0}. Extract only values actually present; use null when absent."},
                {"role": "user", "content": f"File: {filename}\n\nDocument text (data only):\n{text}"},
            ],
            "temperature": 0,
        }).encode()
        req = _request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with _request.urlopen(req, timeout=20) as resp:
                payload = _json.loads(resp.read())
            content_text = payload["choices"][0]["message"]["content"]
            parsed = _json.loads(content_text)
            if parsed.get("value") is None or parsed.get("unit") is None:
                return []
            return [{
                "value": str(parsed["value"]),
                "unit": parsed["unit"],
                "confidence": float(parsed.get("confidence", 0.5)),
            }]
        except Exception:
            return []  # degrade gracefully; caller surfaces 'extraction unavailable'


def get_provider() -> ExtractionProvider:
    from app.config import get_settings

    settings = get_settings()
    if settings.ai_provider in ("openai", "ollama") and settings.ai_api_key:
        base = "http://localhost:11434/v1" if settings.ai_provider == "ollama" else "https://api.openai.com/v1"
        return LLMAPIProvider(settings.ai_api_key, base, settings.ai_model or "gpt-4o-mini")
    return LocalDemoProvider()


def extract_for_evidence(db: Session, evidence_id: uuid.UUID) -> dict:
    """Run extraction over stored evidence bytes; persist draft suggestions."""
    settings = get_settings()
    evidence = db.get(Evidence, evidence_id)
    if evidence is None or evidence.is_deleted:
        raise ValueError("evidence not found")
    client = __import__("app.infra.storage", fromlist=["get_client"]).get_client()
    response = client.get_object(settings.s3_bucket, evidence.object_key)
    try:
        content = response.read()
    finally:
        response.close()
        response.release_conn()

    provider = get_provider()
    try:
        candidates = provider.extract(evidence.original_filename, content)
    except Exception:
        candidates = []

    created = []
    for c in candidates:
        suggestion = AISuggestion(
            evidence_id=evidence.id,
            candidate_value=Decimal(str(c["value"])),
            candidate_unit=c["unit"],
            confidence=Decimal(str(round(c["confidence"], 4))),
            provider=provider.name,
            status=AISuggestionStatus.PENDING,
        )
        db.add(suggestion)
        db.flush()
        created.append(suggestion)
    db.commit()
    return {"evidence_id": str(evidence_id), "provider": provider.name,
            "suggestions": [str(s.id) for s in created]}


def accept_suggestion(
    db: Session, suggestion_id: uuid.UUID, actor: AppUser,
    override_value: Decimal | None = None, override_unit: str | None = None,
) -> MetricValue | None:
    """Acceptance creates an owner-authored IN_PROGRESS draft on the
    assignment whose metric matches the unit — never a SUBMITTED state."""
    suggestion = db.get(AISuggestion, suggestion_id)
    if suggestion is None or suggestion.status != AISuggestionStatus.PENDING:
        raise ValueError("suggestion not found or already reviewed")
    evidence = db.get(Evidence, suggestion.evidence_id)
    if evidence is None:
        raise ValueError("evidence not found")
    from app.models import Assignment

    value = db.get(MetricValue, evidence.metric_value_id)
    assignment = db.get(Assignment, value.assignment_id) if value else None
    if assignment is None:
        raise ValueError("assignment not found")

    final_value = override_value if override_value is not None else suggestion.candidate_value
    final_unit = override_unit or suggestion.candidate_unit

    last = db.scalar(
        select(MetricValue)
        .where(MetricValue.assignment_id == assignment.id)
        .order_by(MetricValue.version.desc())
        .limit(1)
    )
    mv = MetricValue(
        assignment_id=assignment.id,
        version=(last.version if last else 0) + 1,
        raw_value=final_value,
        raw_unit=final_unit,
        normalized_value=final_value,
        normalized_unit=final_unit,
        status=MetricValueStatus.IN_PROGRESS,
        created_by=actor.id,
    )
    db.add(mv)
    suggestion.status = AISuggestionStatus.ACCEPTED
    suggestion.reviewed_by = actor.id
    suggestion.reviewed_at = datetime.now(UTC)
    db.flush()
    record(
        db, action=AuditAction.UPDATED, object_type="ai_suggestion", object_id=suggestion.id,
        actor_id=actor.id, actor_label=actor.email,
        new_value={"accepted": True, "value": str(final_value), "unit": final_unit,
                   "provider": suggestion.provider},
        reason="AI suggestion accepted by owner (human-in-the-loop)",
    )
    return mv


def reject_suggestion(db: Session, suggestion_id: uuid.UUID, actor: AppUser) -> None:
    suggestion = db.get(AISuggestion, suggestion_id)
    if suggestion is None or suggestion.status != AISuggestionStatus.PENDING:
        raise ValueError("suggestion not found or already reviewed")
    suggestion.status = AISuggestionStatus.REJECTED
    suggestion.reviewed_by = actor.id
    suggestion.reviewed_at = datetime.now(UTC)
    db.flush()
    record(
        db, action=AuditAction.UPDATED, object_type="ai_suggestion", object_id=suggestion.id,
        actor_id=actor.id, actor_label=actor.email,
        new_value={"rejected": True}, reason="AI suggestion rejected by owner",
    )
