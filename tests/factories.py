from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from htf_scanner.domain.candle import Candle
from htf_scanner.domain.displacement import Displacement
from htf_scanner.domain.enums import (
    Direction,
    FvgSide,
    LiquidityContextType,
    SwingSide,
)
from htf_scanner.domain.fvg import FairValueGap
from htf_scanner.domain.liquidity import LiquidityContext
from htf_scanner.domain.swing import SwingPoint


def make_swing(
    candles: list[Candle],
    side: SwingSide,
    price: str,
    bar_index: int,
    confirmation_bar_index: int,
) -> SwingPoint:
    identity = f"swing:{side}:{bar_index}:{confirmation_bar_index}:{price}"
    return SwingPoint(
        id=uuid5(NAMESPACE_URL, identity),
        symbol=candles[0].symbol,
        timeframe=candles[0].timeframe,
        side=side,
        formed_at=candles[bar_index].open_time,
        known_at=candles[confirmation_bar_index].close_time,
        price=Decimal(price),
        atr_at_formation=Decimal("2"),
        confirmation_move_atr=1.0,
        bar_index=bar_index,
        confirmation_bar_index=confirmation_bar_index,
    )


def make_fvg(candle: Candle, side: FvgSide) -> FairValueGap:
    lower = Decimal("8")
    upper = Decimal("9")
    identity = f"fvg:{side}:{candle.open_time.isoformat()}"
    return FairValueGap(
        id=uuid5(NAMESPACE_URL, identity),
        symbol=candle.symbol,
        timeframe=candle.timeframe,
        side=side,
        formed_at=candle.open_time,
        known_at=candle.close_time,
        lower=lower,
        upper=upper,
        midpoint=Decimal("8.5"),
        size=Decimal("1"),
        size_atr=1.0,
        source_candle_time=candle.open_time,
    )


def make_displacement(
    candle: Candle,
    direction: Direction,
    fvg: FairValueGap | None = None,
    *,
    structure_break: bool = True,
    structure_break_id: UUID | None = None,
    score: float = 6.0,
) -> Displacement:
    identity = f"displacement:{direction}:{candle.open_time.isoformat()}"
    displacement_id = uuid5(NAMESPACE_URL, identity)
    break_id = (
        structure_break_id or uuid5(NAMESPACE_URL, identity + ":break") if structure_break else None
    )
    return Displacement(
        id=displacement_id,
        symbol=candle.symbol,
        timeframe=candle.timeframe,
        direction=direction,
        start_time=candle.open_time,
        end_time=candle.open_time,
        known_at=candle.close_time,
        sequence_bars=1,
        score=score,
        body_atr=1.0,
        range_atr=1.2,
        net_move_atr=1.0,
        body_efficiency=1.0,
        directional_efficiency=1.0,
        close_location=0.9 if direction == Direction.BULLISH else 0.1,
        structure_break=structure_break,
        structure_break_id=break_id,
        created_fvg=fvg is not None,
        fvg_id=fvg.id if fvg else None,
        component_scores={"test": score},
    )


def make_context(
    displacement: Displacement,
    classification: LiquidityContextType,
    score: float,
    *,
    external_reference_swing_id: UUID | None = None,
    attempt_swing_id: UUID | None = None,
    retracement_swing_id: UUID | None = None,
    structure_break_id: UUID | None = None,
) -> LiquidityContext:
    identity = f"context:{displacement.id}:{classification}"
    return LiquidityContext(
        id=uuid5(NAMESPACE_URL, identity),
        displacement_id=displacement.id,
        symbol=displacement.symbol,
        timeframe=displacement.timeframe,
        reversal_direction=displacement.direction,
        classification=classification,
        formed_at=displacement.start_time,
        known_at=displacement.known_at,
        external_reference_swing_id=external_reference_swing_id,
        attempt_swing_id=attempt_swing_id,
        retracement_swing_id=retracement_swing_id,
        structure_break_id=structure_break_id,
        sweep=classification
        in {
            LiquidityContextType.LIQUIDITY_SWEEP,
            LiquidityContextType.SWEEP_AND_FAILED_CONTINUATION,
        },
        accepted_breakout=classification == LiquidityContextType.ACCEPTED_BREAKOUT,
        external_liquidity_remained=(
            classification
            in {
                LiquidityContextType.FAILED_CONTINUATION_HIGH,
                LiquidityContextType.FAILED_CONTINUATION_LOW,
                LiquidityContextType.UNSWEPT_EXTERNAL_LIQUIDITY,
            }
        ),
        score=score,
        component_scores={
            "sweep_history": 1.5
            if classification
            in {
                LiquidityContextType.LIQUIDITY_SWEEP,
                LiquidityContextType.SWEEP_AND_FAILED_CONTINUATION,
            }
            else 0.0,
            "failed_continuation": 1.5
            if classification
            in {
                LiquidityContextType.FAILED_CONTINUATION_HIGH,
                LiquidityContextType.FAILED_CONTINUATION_LOW,
                LiquidityContextType.SWEEP_AND_FAILED_CONTINUATION,
            }
            else 0.0,
        },
        features={"bars_attempt_to_displacement": 1},
    )
