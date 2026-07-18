from enum import StrEnum


class FvgSide(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class FvgStatus(StrEnum):
    ACTIVE = "active"
    PARTIALLY_FILLED = "partially_filled"
    FULLY_FILLED = "fully_filled"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


class Direction(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class SwingSide(StrEnum):
    HIGH = "high"
    LOW = "low"


class SwingStatus(StrEnum):
    CONFIRMED = "confirmed"
    INVALIDATED = "invalidated"


class StructureLevelType(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"


class StructureBreakKind(StrEnum):
    BOS = "bos"
    CHOCH = "choch"
    MSS = "mss"


class LiquidityContextType(StrEnum):
    LIQUIDITY_SWEEP = "liquidity_sweep"
    UNSWEPT_EXTERNAL_LIQUIDITY = "unswept_external_liquidity"
    FAILED_CONTINUATION_HIGH = "failed_continuation_high"
    FAILED_CONTINUATION_LOW = "failed_continuation_low"
    SWEEP_AND_FAILED_CONTINUATION = "sweep_and_failed_continuation"
    ACCEPTED_BREAKOUT = "accepted_breakout"
    NO_CLEAR_CONTEXT = "no_clear_context"


class LiquidityInteractionType(StrEnum):
    TOUCHED = "touched"
    SWEPT = "swept"
    REJECTED = "rejected"
    ACCEPTED_BEYOND = "accepted_beyond"
    RECLAIMED = "reclaimed"
    INVALIDATED = "invalidated"


class SetupSide(StrEnum):
    LONG = "long"
    SHORT = "short"


class SetupStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    H4_TOUCHED = "h4_touched"
    H4_REACTING = "h4_reacting"
    CONFIRMED = "confirmed"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


class ScannerRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class H4ReactionStatus(StrEnum):
    WAITING_FOR_TOUCH = "waiting_for_touch"
    ZONE_TOUCHED = "zone_touched"
    EARLY_REACTION = "early_reaction"
    REACTION_CONFIRMED = "reaction_confirmed"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    TOUCHED = "touched"  # Legacy persistence value.


class H4TouchType(StrEnum):
    WICK_TOUCH = "wick_touch"
    BODY_ENTRY = "body_entry"
    CLOSE_INSIDE = "close_inside"
    MIDPOINT_REACHED = "midpoint_reached"
    FULL_FILL = "full_fill"
    CLOSE_THROUGH = "close_through"
    GAP_OVER_ZONE = "gap_over_zone"


class ReactionOutcomeLabel(StrEnum):
    REACTION_CONTINUED = "reaction_continued"
    REACTION_FAILED = "reaction_failed"
    ZONE_RETESTED = "zone_retested"
    D1_TARGET_REACHED = "d1_target_reached"
    OPPOSITE_LIQUIDITY_REACHED = "opposite_liquidity_reached"
    INVALIDATION_REACHED = "invalidation_reached"
    NO_RESOLUTION_WITHIN_HORIZON = "no_resolution_within_horizon"


class BatchRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
