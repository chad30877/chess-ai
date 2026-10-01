"""Versioned, serializable settings for handcrafted evaluation."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from numbers import Real
from types import MappingProxyType


EVALUATION_CONFIG_VERSION = 2
ENDGAME_PST_TABLE_VERSION = 1
PHASE_MODEL_VERSION = 1
PST_TABLE_VERSION = 1
PIECE_SYMBOLS = ("P", "N", "B", "R", "Q")
DEFAULT_PIECE_VALUES = {
    "P": 1.0,
    "N": 3.0,
    "B": 3.0,
    "R": 5.0,
    "Q": 9.0,
}


def _finite_number(value: object, field_name: str, *, non_negative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be a finite number")
    if non_negative and number < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return number


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _normalize_piece_values(values: Mapping[str, object] | None) -> dict[str, float]:
    normalized = DEFAULT_PIECE_VALUES.copy()
    if values is None:
        return normalized

    for key, value in values.items():
        if not isinstance(key, str) or key.upper() not in PIECE_SYMBOLS:
            raise ValueError(f"Unsupported piece key: {key}")
        normalized[key.upper()] = _finite_number(
            value, f"piece_values.{key.upper()}", non_negative=True,
        )
    if normalized["P"] <= 0:
        raise ValueError("piece_values.P must be greater than 0")
    return normalized


@dataclass(frozen=True)
class EvaluationConfig:
    """The complete settings needed to reproduce a handcrafted evaluation."""

    piece_values: Mapping[str, float] = field(default_factory=lambda: DEFAULT_PIECE_VALUES.copy())
    material_enabled: bool = True
    pst_enabled: bool = True
    pst_weight: float = 1.0
    version: int = EVALUATION_CONFIG_VERSION
    phase_enabled: bool = False
    endgame_piece_values: Mapping[str, float] | None = None
    endgame_pst_weight: float = 1.0

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or self.version != EVALUATION_CONFIG_VERSION:
            raise ValueError(f"Unsupported evaluation config version: {self.version}")
        object.__setattr__(self, "piece_values", MappingProxyType(
            _normalize_piece_values(self.piece_values),
        ))
        object.__setattr__(self, "endgame_piece_values", MappingProxyType(
            _normalize_piece_values(self.piece_values if self.endgame_piece_values is None
                                    else self.endgame_piece_values),
        ))
        object.__setattr__(self, "phase_enabled", _boolean(self.phase_enabled, "phase_enabled"))
        object.__setattr__(self, "endgame_pst_weight", _finite_number(
            self.endgame_pst_weight, "endgame_pst_weight", non_negative=True,
        ))
        object.__setattr__(self, "material_enabled", _boolean(
            self.material_enabled, "material_enabled",
        ))
        object.__setattr__(self, "pst_enabled", _boolean(self.pst_enabled, "pst_enabled"))
        object.__setattr__(self, "pst_weight", _finite_number(
            self.pst_weight, "pst_weight", non_negative=True,
        ))

    @classmethod
    def material_only(
        cls, piece_values: Mapping[str, float] | None = None,
    ) -> "EvaluationConfig":
        return cls(piece_values=piece_values or DEFAULT_PIECE_VALUES, pst_enabled=False)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "phase": {"enabled": self.phase_enabled, "model_version": PHASE_MODEL_VERSION},
            "perspective": "white",
            "score_unit": "pawn",
            "terms": {
                "material": {
                    "enabled": self.material_enabled,
                    "weight": 1.0,
                    "piece_values": dict(self.piece_values),
                    "endgame_piece_values": dict(self.endgame_piece_values),
                },
                "piece_square": {
                    "enabled": self.pst_enabled,
                    "weight": self.pst_weight,
                    "table_version": PST_TABLE_VERSION,
                    "endgame_weight": self.endgame_pst_weight,
                    "endgame_table_version": ENDGAME_PST_TABLE_VERSION,
                },
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "EvaluationConfig":
        if not isinstance(payload, Mapping):
            raise ValueError("Evaluation config must be an object")
        version = payload.get("version")
        if isinstance(version, bool) or version not in (1, 2):
            raise ValueError(f"Unsupported evaluation config version: {version}")
        expected = {"version", "perspective", "score_unit", "terms"}
        if version == 2:
            expected.add("phase")
        if set(payload) != expected:
            raise ValueError("Evaluation config fields do not match declared version")
        if payload["perspective"] != "white":
            raise ValueError("Evaluation perspective must be white")
        if payload["score_unit"] != "pawn":
            raise ValueError("Evaluation score_unit must be pawn")
        terms = payload["terms"]
        if not isinstance(terms, Mapping) or set(terms) != {"material", "piece_square"}:
            raise ValueError("Evaluation terms must contain material and piece_square")
        material = terms["material"]
        piece_square = terms["piece_square"]
        material_fields = {"enabled", "weight", "piece_values"}
        pst_fields = {"enabled", "weight", "table_version"}
        if version == 2:
            material_fields.add("endgame_piece_values")
            pst_fields.update({"endgame_weight", "endgame_table_version"})
        if not isinstance(material, Mapping) or set(material) != material_fields:
            raise ValueError("Material term fields do not match declared version")
        if _finite_number(material["weight"], "material.weight") != 1.0:
            raise ValueError("Material term weight is fixed at 1")
        if not isinstance(piece_square, Mapping) or set(piece_square) != pst_fields:
            raise ValueError("Piece-square term fields do not match declared version")
        table_version = piece_square["table_version"]
        if isinstance(table_version, bool) or table_version != PST_TABLE_VERSION:
            raise ValueError(f"Unsupported PST table version: {table_version}")
        piece_values = material["piece_values"]
        if not isinstance(piece_values, Mapping) or set(piece_values) != set(PIECE_SYMBOLS):
            raise ValueError("Material piece_values must contain P, N, B, R, and Q")
        phase_enabled = False
        endgame_values = piece_values
        endgame_weight = piece_square["weight"]
        if version == 2:
            phase = payload["phase"]
            if not isinstance(phase, Mapping) or set(phase) != {"enabled", "model_version"}:
                raise ValueError("Invalid phase model fields")
            if isinstance(phase["model_version"], bool) or phase["model_version"] != PHASE_MODEL_VERSION:
                raise ValueError("Unsupported phase model version")
            phase_enabled = _boolean(phase["enabled"], "phase.enabled")
            endgame_values = material["endgame_piece_values"]
            if not isinstance(endgame_values, Mapping) or set(endgame_values) != set(PIECE_SYMBOLS):
                raise ValueError("Endgame piece_values must contain P, N, B, R, and Q")
            endgame_weight = piece_square["endgame_weight"]
            eg_version = piece_square["endgame_table_version"]
            if isinstance(eg_version, bool) or eg_version != ENDGAME_PST_TABLE_VERSION:
                raise ValueError("Unsupported endgame PST table version")
        return cls(
            phase_enabled=phase_enabled,
            endgame_piece_values=endgame_values,
            endgame_pst_weight=endgame_weight,
            piece_values=piece_values,
            material_enabled=_boolean(material["enabled"], "material.enabled"),
            pst_enabled=_boolean(piece_square["enabled"], "piece_square.enabled"),
            pst_weight=piece_square["weight"],
        )


@dataclass(frozen=True)
class EvaluationTerm:
    """One raw feature and its weighted contribution to the final score."""

    raw_value: float
    weight: float
    contribution: float
    enabled: bool
    unit: str
    direction: str
    stage: str
    overlap_risk: str

    def to_dict(self) -> dict:
        return {
            "raw_value": self.raw_value,
            "weight": self.weight,
            "contribution": self.contribution,
            "enabled": self.enabled,
            "unit": self.unit,
            "direction": self.direction,
            "stage": self.stage,
            "overlap_risk": self.overlap_risk,
        }


@dataclass(frozen=True)
class EvaluationBreakdown:
    """White-perspective score terms whose contributions sum to total_score."""

    terms: Mapping[str, EvaluationTerm]
    total_score: float
    phase: Mapping[str, object] | None = None
    stage_terms: Mapping[str, Mapping[str, EvaluationTerm]] | None = None
    perspective: str = "white"
    score_unit: str = "pawn"

    def to_dict(self) -> dict:
        return {
            "phase": dict(self.phase) if self.phase is not None else None,
            "stage_terms": {
                stage: {name: term.to_dict() for name, term in terms.items()}
                for stage, terms in (self.stage_terms or {}).items()
            },
            "perspective": self.perspective,
            "score_unit": self.score_unit,
            "terms": {name: term.to_dict() for name, term in self.terms.items()},
            "total_score": self.total_score,
        }
