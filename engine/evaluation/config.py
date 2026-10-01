"""Versioned, serializable settings for handcrafted evaluation."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from numbers import Real
from types import MappingProxyType


EVALUATION_CONFIG_VERSION = 6
COORDINATION_FEATURE_VERSION = 1
COORDINATION_TERM_NAMES = ("bishop_pair", "rook_open_file", "rook_half_open_file")
KING_SAFETY_FEATURE_VERSION = 1
KING_SAFETY_TERM_NAMES = ("king_pawn_shield", "king_zone_attacks", "king_file_exposure")
MOBILITY_FEATURE_VERSION = 1
MOBILITY_TERM_NAMES = ("pawn_mobility", "knight_mobility", "bishop_mobility",
                       "rook_mobility", "queen_mobility", "king_mobility")
PAWN_FEATURE_VERSION = 1
PAWN_TERM_NAMES = ("isolated_pawns", "doubled_pawns", "passed_pawns")
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
class PawnTermConfig:
    """Non-negative pawn-unit prices; feature signs are defined by the model."""

    enabled: bool = False
    weight: float = 0.0
    endgame_weight: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled", _boolean(self.enabled, "pawn term enabled"))
        for name in ("weight", "endgame_weight"):
            object.__setattr__(self, name, _finite_number(
                getattr(self, name), f"pawn term {name}", non_negative=True,
            ))

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "weight": self.weight,
                "endgame_weight": self.endgame_weight, "feature_version": PAWN_FEATURE_VERSION}


def _default_pawn_terms() -> dict[str, PawnTermConfig]:
    # Experimental starting prices, disabled until explicitly selected.
    return {
        "isolated_pawns": PawnTermConfig(weight=0.15, endgame_weight=0.20),
        "doubled_pawns": PawnTermConfig(weight=0.10, endgame_weight=0.15),
        "passed_pawns": PawnTermConfig(weight=0.05, endgame_weight=0.10),
    }


@dataclass(frozen=True)
class MobilityTermConfig:
    """Pawn-unit price per geometric attack destination, with independent stages."""

    enabled: bool = False
    weight: float = 0.0
    endgame_weight: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled", _boolean(self.enabled, "mobility term enabled"))
        for name in ("weight", "endgame_weight"):
            object.__setattr__(self, name, _finite_number(
                getattr(self, name), f"mobility term {name}", non_negative=True,
            ))

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "weight": self.weight,
                "endgame_weight": self.endgame_weight, "feature_version": MOBILITY_FEATURE_VERSION}


def _default_mobility_terms() -> dict[str, MobilityTermConfig]:
    prices = ((.01, .01), (.03, .03), (.03, .03), (.02, .03), (.01, .02), (.01, .02))
    return {name: MobilityTermConfig(weight=mg, endgame_weight=eg)
            for name, (mg, eg) in zip(MOBILITY_TERM_NAMES, prices)}


@dataclass(frozen=True)
class KingSafetyTermConfig:
    """Independent non-negative prices; default endgame contribution is zero."""

    enabled: bool = False
    weight: float = 0.0
    endgame_weight: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled", _boolean(self.enabled, "king safety term enabled"))
        for name in ("weight", "endgame_weight"):
            object.__setattr__(self, name, _finite_number(
                getattr(self, name), f"king safety term {name}", non_negative=True,
            ))

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "weight": self.weight,
                "endgame_weight": self.endgame_weight, "feature_version": KING_SAFETY_FEATURE_VERSION}


def _default_king_safety_terms() -> dict[str, KingSafetyTermConfig]:
    return {name: KingSafetyTermConfig(weight=weight)
            for name, weight in zip(KING_SAFETY_TERM_NAMES, (.10, .05, .08))}


@dataclass(frozen=True)
class CoordinationTermConfig:
    """Independent pawn-unit prices for bishop coverage and rook-file features."""

    enabled: bool = False
    weight: float = 0.0
    endgame_weight: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "enabled", _boolean(self.enabled, "coordination term enabled"))
        for name in ("weight", "endgame_weight"):
            object.__setattr__(self, name, _finite_number(
                getattr(self, name), f"coordination term {name}", non_negative=True,
            ))

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "weight": self.weight,
                "endgame_weight": self.endgame_weight, "feature_version": COORDINATION_FEATURE_VERSION}


def _default_coordination_terms() -> dict[str, CoordinationTermConfig]:
    prices = ((.30, .40), (.15, .20), (.10, .15))
    return {name: CoordinationTermConfig(weight=mg, endgame_weight=eg)
            for name, (mg, eg) in zip(COORDINATION_TERM_NAMES, prices)}


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
    pawn_terms: Mapping[str, PawnTermConfig] = field(default_factory=_default_pawn_terms)
    mobility_terms: Mapping[str, MobilityTermConfig] = field(default_factory=_default_mobility_terms)
    king_safety_terms: Mapping[str, KingSafetyTermConfig] = field(default_factory=_default_king_safety_terms)

    coordination_terms: Mapping[str, CoordinationTermConfig] = field(default_factory=_default_coordination_terms)

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
        if not isinstance(self.pawn_terms, Mapping):
            raise ValueError("pawn_terms must be a mapping")
        normalized = _default_pawn_terms()
        for name, settings in self.pawn_terms.items():
            if name not in PAWN_TERM_NAMES or not isinstance(settings, PawnTermConfig):
                raise ValueError(f"Unsupported pawn term or settings: {name}")
            normalized[name] = settings
        object.__setattr__(self, "pawn_terms", MappingProxyType(normalized))
        if not isinstance(self.mobility_terms, Mapping):
            raise ValueError("mobility_terms must be a mapping")
        normalized_mobility = _default_mobility_terms()
        for name, settings in self.mobility_terms.items():
            if name not in MOBILITY_TERM_NAMES or not isinstance(settings, MobilityTermConfig):
                raise ValueError(f"Unsupported mobility term or settings: {name}")
            normalized_mobility[name] = settings
        object.__setattr__(self, "mobility_terms", MappingProxyType(normalized_mobility))
        if not isinstance(self.king_safety_terms, Mapping):
            raise ValueError("king_safety_terms must be a mapping")
        normalized_safety = _default_king_safety_terms()
        for name, settings in self.king_safety_terms.items():
            if name not in KING_SAFETY_TERM_NAMES or not isinstance(settings, KingSafetyTermConfig):
                raise ValueError(f"Unsupported king safety term or settings: {name}")
            normalized_safety[name] = settings
        object.__setattr__(self, "king_safety_terms", MappingProxyType(normalized_safety))
        if not isinstance(self.coordination_terms, Mapping):
            raise ValueError("coordination_terms must be a mapping")
        normalized_coordination = _default_coordination_terms()
        for name, settings in self.coordination_terms.items():
            if name not in COORDINATION_TERM_NAMES or not isinstance(settings, CoordinationTermConfig):
                raise ValueError(f"Unsupported coordination term or settings: {name}")
            normalized_coordination[name] = settings
        object.__setattr__(self, "coordination_terms", MappingProxyType(normalized_coordination))

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
                **{name: settings.to_dict() for name, settings in self.pawn_terms.items()},
                **{name: settings.to_dict() for name, settings in self.mobility_terms.items()},
                **{name: settings.to_dict() for name, settings in self.king_safety_terms.items()},
                **{name: settings.to_dict() for name, settings in self.coordination_terms.items()},
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "EvaluationConfig":
        if not isinstance(payload, Mapping):
            raise ValueError("Evaluation config must be an object")
        version = payload.get("version")
        if isinstance(version, bool) or version not in (1, 2, 3, 4, 5, 6):
            raise ValueError(f"Unsupported evaluation config version: {version}")
        expected = {"version", "perspective", "score_unit", "terms"}
        if version >= 2:
            expected.add("phase")
        if set(payload) != expected:
            raise ValueError("Evaluation config fields do not match declared version")
        if payload["perspective"] != "white":
            raise ValueError("Evaluation perspective must be white")
        if payload["score_unit"] != "pawn":
            raise ValueError("Evaluation score_unit must be pawn")
        terms = payload["terms"]
        term_names = {"material", "piece_square"}
        if version >= 3:
            term_names.update(PAWN_TERM_NAMES)
        if version >= 4:
            term_names.update(MOBILITY_TERM_NAMES)
        if version >= 5:
            term_names.update(KING_SAFETY_TERM_NAMES)
        if version == 6:
            term_names.update(COORDINATION_TERM_NAMES)
        if not isinstance(terms, Mapping) or set(terms) != term_names:
            raise ValueError("Evaluation terms do not match declared version")
        material = terms["material"]
        piece_square = terms["piece_square"]
        material_fields = {"enabled", "weight", "piece_values"}
        pst_fields = {"enabled", "weight", "table_version"}
        if version >= 2:
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
        if version >= 2:
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
        pawn_terms = _default_pawn_terms()
        if version >= 3:
            for name in PAWN_TERM_NAMES:
                settings = terms[name]
                if not isinstance(settings, Mapping) or set(settings) != {
                    "enabled", "weight", "endgame_weight", "feature_version",
                }:
                    raise ValueError(f"Invalid pawn term fields: {name}")
                feature_version = settings["feature_version"]
                if isinstance(feature_version, bool) or feature_version != PAWN_FEATURE_VERSION:
                    raise ValueError(f"Unsupported pawn feature version: {feature_version}")
                pawn_terms[name] = PawnTermConfig(
                    enabled=settings["enabled"], weight=settings["weight"],
                    endgame_weight=settings["endgame_weight"],
                )
        mobility_terms = _default_mobility_terms()
        if version >= 4:
            for name in MOBILITY_TERM_NAMES:
                settings = terms[name]
                if not isinstance(settings, Mapping) or set(settings) != {
                    "enabled", "weight", "endgame_weight", "feature_version",
                }:
                    raise ValueError(f"Invalid mobility term fields: {name}")
                feature_version = settings["feature_version"]
                if isinstance(feature_version, bool) or feature_version != MOBILITY_FEATURE_VERSION:
                    raise ValueError(f"Unsupported mobility feature version: {feature_version}")
                mobility_terms[name] = MobilityTermConfig(
                    enabled=settings["enabled"], weight=settings["weight"],
                    endgame_weight=settings["endgame_weight"],
                )
        king_safety_terms = _default_king_safety_terms()
        if version >= 5:
            for name in KING_SAFETY_TERM_NAMES:
                settings = terms[name]
                if not isinstance(settings, Mapping) or set(settings) != {
                    "enabled", "weight", "endgame_weight", "feature_version",
                }:
                    raise ValueError(f"Invalid king safety term fields: {name}")
                feature_version = settings["feature_version"]
                if isinstance(feature_version, bool) or feature_version != KING_SAFETY_FEATURE_VERSION:
                    raise ValueError(f"Unsupported king safety feature version: {feature_version}")
                king_safety_terms[name] = KingSafetyTermConfig(
                    enabled=settings["enabled"], weight=settings["weight"],
                    endgame_weight=settings["endgame_weight"],
                )
        coordination_terms = _default_coordination_terms()
        if version == 6:
            for name in COORDINATION_TERM_NAMES:
                settings = terms[name]
                if not isinstance(settings, Mapping) or set(settings) != {
                    "enabled", "weight", "endgame_weight", "feature_version",
                }:
                    raise ValueError(f"Invalid coordination term fields: {name}")
                feature_version = settings["feature_version"]
                if isinstance(feature_version, bool) or feature_version != COORDINATION_FEATURE_VERSION:
                    raise ValueError(f"Unsupported coordination feature version: {feature_version}")
                coordination_terms[name] = CoordinationTermConfig(
                    enabled=settings["enabled"], weight=settings["weight"],
                    endgame_weight=settings["endgame_weight"],
                )
        return cls(
            coordination_terms=coordination_terms,
            king_safety_terms=king_safety_terms,
            mobility_terms=mobility_terms,
            pawn_terms=pawn_terms,
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
