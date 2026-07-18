from itertools import pairwise
from math import isfinite
from uuid import NAMESPACE_URL, uuid5

from htf_scanner.config import DisplacementConfig
from htf_scanner.domain.candle import Candle
from htf_scanner.domain.displacement import Displacement
from htf_scanner.domain.enums import Direction, FvgSide
from htf_scanner.domain.fvg import FairValueGap
from htf_scanner.domain.structure import StructureBreak
from htf_scanner.indicators.candle_features import calculate_candle_features


class DisplacementDetector:
    def __init__(self, config: DisplacementConfig, atr_period: int) -> None:
        self._config = config
        self._atr_period = atr_period

    def detect(
        self,
        candles: list[Candle],
        structure_breaks: list[StructureBreak],
        fvgs: list[FairValueGap],
    ) -> list[Displacement]:
        ordered = sorted(candles, key=lambda item: item.open_time)
        features = calculate_candle_features(ordered, self._atr_period)
        detected: list[Displacement] = []
        for end_index in range(len(ordered)):
            atr = float(features.iloc[end_index]["atr"])
            if not isfinite(atr) or atr <= 0:
                continue
            candidates = [
                self._measure(ordered, start_index, end_index, atr, structure_breaks, fvgs)
                for start_index in range(
                    max(0, end_index - self._config.maximum_sequence_bars + 1),
                    end_index + 1,
                )
            ]
            qualified = [item for item in candidates if item is not None]
            detected.extend(qualified)
        return detected

    def detect_ending_at(
        self,
        candles: list[Candle],
        end_index: int,
        atr: float,
        structure_breaks: list[StructureBreak],
        fvgs: list[FairValueGap],
    ) -> list[Displacement]:
        """Measure only sequences ending at the newly closed candle."""
        if not isfinite(atr) or atr <= 0:
            return []
        return [
            measured
            for start_index in range(
                max(0, end_index - self._config.maximum_sequence_bars + 1),
                end_index + 1,
            )
            if (
                measured := self._measure(
                    candles,
                    start_index,
                    end_index,
                    atr,
                    structure_breaks,
                    fvgs,
                )
            )
            is not None
        ]

    def _measure(
        self,
        candles: list[Candle],
        start_index: int,
        end_index: int,
        atr: float,
        structure_breaks: list[StructureBreak],
        fvgs: list[FairValueGap],
    ) -> Displacement | None:
        window = candles[start_index : end_index + 1]
        first, final = window[0], window[-1]
        net_signed = float(final.close - first.open)
        if net_signed == 0:
            return None
        direction = Direction.BULLISH if net_signed > 0 else Direction.BEARISH
        bodies = [abs(float(candle.close - candle.open)) for candle in window]
        directional_bodies = [
            max(0.0, float(candle.close - candle.open))
            if direction == Direction.BULLISH
            else max(0.0, float(candle.open - candle.close))
            for candle in window
        ]
        body_atr = sum(directional_bodies) / atr
        range_atr = (
            max(float(candle.high) for candle in window)
            - min(float(candle.low) for candle in window)
        ) / atr
        net_move_atr = abs(net_signed) / atr
        body_efficiency = sum(directional_bodies) / sum(bodies) if sum(bodies) else 0.0
        path = [float(first.open), *[float(candle.close) for candle in window]]
        path_distance = sum(abs(right - left) for left, right in pairwise(path))
        directional_efficiency = min(1.0, abs(net_signed) / path_distance) if path_distance else 0.0
        candle_range = float(final.high - final.low)
        close_location = float(final.close - final.low) / candle_range if candle_range else 0.5
        matching_breaks = [
            item
            for item in structure_breaks
            if item.direction == direction
            and first.open_time <= item.formed_at <= final.open_time
            and item.known_at <= final.close_time
        ]
        structure_break = matching_breaks[-1] if matching_breaks else None
        expected_fvg_side = FvgSide.BULLISH if direction == Direction.BULLISH else FvgSide.BEARISH
        matching_fvgs = [
            item
            for item in fvgs
            if item.side == expected_fvg_side
            and item.formed_at == final.open_time
            and item.known_at <= final.close_time
        ]
        fvg = matching_fvgs[-1] if matching_fvgs else None
        close_strength = (
            close_location >= self._config.bullish_min_close_location
            if direction == Direction.BULLISH
            else close_location <= self._config.bearish_max_close_location
        )
        components = {
            "body_atr": 1.0 if body_atr >= self._config.minimum_body_atr else 0.0,
            "range_atr": 1.0 if range_atr >= self._config.minimum_range_atr else 0.0,
            "net_move_atr": (1.0 if net_move_atr >= self._config.minimum_net_move_atr else 0.0),
            "body_efficiency": (
                1.0 if body_efficiency >= self._config.minimum_body_efficiency else 0.0
            ),
            "close_location": 1.0 if close_strength else 0.0,
            "structure_break": 1.5 if structure_break is not None else 0.0,
            "created_fvg": 1.0 if fvg is not None else 0.0,
        }
        score = sum(components.values())
        if score < self._config.minimum_score:
            return None
        identity = ":".join(
            [
                final.symbol,
                final.timeframe,
                direction.value,
                first.open_time.isoformat(),
                final.close_time.isoformat(),
            ]
        )
        return Displacement(
            id=uuid5(NAMESPACE_URL, identity),
            symbol=final.symbol,
            timeframe=final.timeframe,
            direction=direction,
            start_time=first.open_time,
            end_time=final.open_time,
            known_at=final.close_time,
            sequence_bars=len(window),
            score=score,
            body_atr=body_atr,
            range_atr=range_atr,
            net_move_atr=net_move_atr,
            body_efficiency=body_efficiency,
            directional_efficiency=directional_efficiency,
            close_location=close_location,
            structure_break=structure_break is not None,
            structure_break_id=structure_break.id if structure_break else None,
            created_fvg=fvg is not None,
            fvg_id=fvg.id if fvg else None,
            component_scores=components,
        )
