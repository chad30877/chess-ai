"""Versioned, serializable settings for handcrafted evaluation."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from numbers import Real
from types import MappingProxyType


EVALUATION_CONFIG_VERSION = 1
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

    def __post_init__(self) -> None:
        if isinstance(self.version, bool) or self.version != EVALUATION_CONFIG_VERSION:
            raise ValueError(f"Unsupported evaluation config version: {self.version}")
        object.__setattr__(self, "piece_values", MappingProxyType(
            _normalize_piece_values(self.piece_values),
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
            "perspective": "white",
            "score_unit": "pawn",
            "terms": {
                "material": {
                    "enabled": self.material_enabled,
                    "weight": 1.0,
                    "piece_values": dict(self.piece_values),
                },
                "piece_square": {
                    "enabled": self.pst_enabled,
                    "weight": self.pst_weight,
                    "table_version": PST_TABLE_VERSION,
                },
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "EvaluationConfig":
        if not isinstance(payload, Mapping):
            raise ValueError("Evaluation config must be an object")
        expected = {"version", "perspective", "score_unit", "terms"}
        if set(payload) != expected:
            raise ValueError("Evaluation config fields do not match version 1")
        if payload["perspective"] != "white":
            raise ValueError("Evaluation perspective must be white")
        if payload["score_unit"] != "pawn":
            raise ValueError("Evaluation score_unit must be pawn")
        terms = payload["terms"]
        if not isinstance(terms, Mapping) or set(terms) != {"material", "piece_square"}:
            raise ValueError("Evaluation terms must contain material and piece_square")
        material = terms["material"]
        piece_square = terms["piece_square"]
        if not isinstance(material, Mapping) or set(material) != {"enabled", "weight", "piece_values"}:
            raise ValueError("Material term fields do not match version 1")
        if _finite_number(material["weight"], "material.weight") != 1.0:
            raise ValueError("Material term weight is fixed at 1")
        if not isinstance(piece_square, Mapping) or set(piece_square) != {
            "enabled", "weight", "table_version",
        }:
            raise ValueError("Piece-square term fields do not match version 1")
        table_version = piece_square["table_version"]
        if isinstance(table_version, bool) or table_version != PST_TABLE_VERSION:
            raise ValueError(f"Unsupported PST table version: {table_version}")
        piece_values = material["piece_values"]
        if not isinstance(piece_values, Mapping) or set(piece_values) != set(PIECE_SYMBOLS):
            raise ValueError("Material piece_values must contain P, N, B, R, and Q")
        return cls(
            version=payload["version"],
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
    perspective: str = "white"
    score_unit: str = "pawn"

    def to_dict(self) -> dict:
        return {
            "perspective": self.perspective,
            "score_unit": self.score_unit,
            "terms": {name: term.to_dict() for name, term in self.terms.items()},
            "total_score": self.total_score,
        }
