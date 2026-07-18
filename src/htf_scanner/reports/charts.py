# mypy: disable-error-code="no-untyped-call"

from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.patches import Rectangle

from htf_scanner.domain.candle import Candle
from htf_scanner.domain.displacement import Displacement
from htf_scanner.domain.enums import FvgSide, LiquidityContextType
from htf_scanner.domain.fvg import FairValueGap
from htf_scanner.domain.liquidity import (
    LiquidityContext,
    LiquidityInteraction,
    LiquiditySequence,
)
from htf_scanner.domain.outcome import ReactionTargetOutcome
from htf_scanner.domain.reaction import H4Reaction, H4TouchPhase
from htf_scanner.domain.setup import HTFSetup
from htf_scanner.domain.structure import (
    MarketStructureSnapshot,
    StructureBreak,
    StructurePromotion,
)
from htf_scanner.domain.swing import SwingPoint


def plot_d1_fvgs(candles: list[Candle], fvgs: list[FairValueGap], path: Path) -> Path:
    if not candles:
        raise ValueError("cannot plot an empty candle series")
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(18, 9), constrained_layout=True)
    candle_width = 0.62
    for candle in candles:
        timestamp = mdates.date2num(candle.open_time)
        color = "#16855b" if candle.close >= candle.open else "#c54444"
        axis.vlines(timestamp, float(candle.low), float(candle.high), color=color, linewidth=0.65)
        body_low = float(min(candle.open, candle.close))
        body_height = max(float(abs(candle.close - candle.open)), 1e-12)
        axis.add_patch(
            Rectangle(
                (timestamp - candle_width / 2, body_low),
                candle_width,
                body_height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.5,
            )
        )
    last_time = candles[-1].close_time
    for fvg in fvgs:
        terminal = _terminal_time(fvg) or last_time
        start_number = mdates.date2num(fvg.formed_at)
        end_number = mdates.date2num(terminal)
        color = "#16855b" if fvg.side == FvgSide.BULLISH else "#c54444"
        axis.add_patch(
            Rectangle(
                (start_number, float(fvg.lower)),
                max(end_number - start_number, 0.5),
                float(fvg.size),
                facecolor=color,
                edgecolor=color,
                alpha=0.12,
                linewidth=0.8,
            )
        )
    axis.set_title(f"{candles[0].symbol} D1 Fair Value Gaps")
    axis.set_ylabel("Price (USDT)")
    axis.set_xlabel("UTC")
    axis.grid(color="#d7dce2", linewidth=0.5, alpha=0.7)
    axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=6, maxticks=14))
    axis.xaxis.set_major_formatter(mdates.ConciseDateFormatter(axis.xaxis.get_major_locator()))
    axis.set_xlim(mdates.date2num(candles[0].open_time) - 1, mdates.date2num(last_time) + 1)
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path


def _terminal_time(fvg: FairValueGap) -> datetime | None:
    return fvg.invalidated_at or fvg.expired_at or fvg.full_fill_at


def plot_d1_setup_debug(
    candles: list[Candle],
    fvgs: list[FairValueGap],
    swings: list[SwingPoint],
    structure_breaks: list[StructureBreak],
    structure_promotions: list[StructurePromotion],
    structure_snapshots: list[MarketStructureSnapshot],
    liquidity_interactions: list[LiquidityInteraction],
    liquidity_sequences: list[LiquiditySequence],
    displacements: list[Displacement],
    contexts: list[LiquidityContext],
    setups: list[HTFSetup],
    path: Path,
) -> Path:
    if not candles:
        raise ValueError("cannot plot an empty candle series")
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, (axis, context_axis) = plt.subplots(
        2,
        1,
        figsize=(20, 11),
        constrained_layout=True,
        gridspec_kw={"height_ratios": [4, 1]},
        sharex=True,
    )
    _draw_candles(axis, candles)
    candle_by_time = {candle.open_time: candle for candle in candles}
    swing_by_id = {swing.id: swing for swing in swings}
    for interaction in liquidity_interactions:
        if interaction.event_type.value != "swept":
            continue
        price = (
            interaction.level_price + interaction.excursion_price
            if interaction.direction.value == "bearish"
            else interaction.level_price - interaction.excursion_price
        )
        axis.scatter(
            mdates.date2num(interaction.candle_time),
            float(price),
            marker="D",
            facecolors="none",
            edgecolors="#7c3aed",
            s=30,
            linewidth=0.8,
            zorder=7,
        )
    for sequence in liquidity_sequences:
        if sequence.attempt_swing_id is None:
            continue
        attempt = swing_by_id[sequence.attempt_swing_id]
        axis.annotate(
            "A",
            (mdates.date2num(attempt.formed_at), float(attempt.price)),
            fontsize=5,
            color="#111827",
            xytext=(2, 4),
            textcoords="offset points",
            zorder=7,
        )
    for displacement in displacements:
        color = "#d7a21b" if displacement.direction.value == "bullish" else "#8d63b8"
        end_candle = candle_by_time[displacement.end_time]
        axis.scatter(
            mdates.date2num(displacement.end_time),
            float(end_candle.close),
            color=color,
            marker=".",
            s=7,
            alpha=0.35,
            zorder=3,
        )
    displacement_by_id = {item.id: item for item in displacements}
    for setup in setups:
        displacement = displacement_by_id[setup.displacement_id]
        start_candle = candle_by_time[displacement.start_time]
        end_candle = candle_by_time[displacement.end_time]
        color = "#16855b" if setup.side.value == "long" else "#c54444"
        axis.annotate(
            "",
            xy=(mdates.date2num(displacement.end_time), float(end_candle.close)),
            xytext=(mdates.date2num(displacement.start_time), float(start_candle.open)),
            arrowprops={"arrowstyle": "->", "color": color, "lw": 0.8, "alpha": 0.7},
        )
    for swing in swings:
        marker = "v" if swing.side.value == "high" else "^"
        color = "#b33333" if swing.side.value == "high" else "#126b4f"
        axis.scatter(
            mdates.date2num(swing.formed_at),
            float(swing.price),
            marker=marker,
            color=color,
            s=18,
            zorder=4,
        )
        axis.hlines(
            float(swing.price),
            mdates.date2num(swing.formed_at),
            mdates.date2num(swing.known_at),
            color=color,
            linewidth=0.5,
            alpha=0.45,
        )
    for structure_break in structure_breaks:
        color = "#1769aa" if structure_break.direction.value == "bullish" else "#7b2f86"
        axis.scatter(
            mdates.date2num(structure_break.known_at),
            float(structure_break.break_price),
            marker="x",
            color=color,
            s=24,
            linewidth=0.8,
            zorder=5,
        )
    for promotion in structure_promotions:
        promoted = swing_by_id[promotion.promoted_swing_id]
        axis.scatter(
            mdates.date2num(promotion.promoted_at),
            float(promoted.price),
            marker="*",
            color="#111827",
            s=38,
            linewidth=0.5,
            zorder=6,
        )
    snapshot_times = [mdates.date2num(snapshot.known_at) for snapshot in structure_snapshots]
    for attribute, color, label in (
        ("internal_high", "#d97706", "internal high"),
        ("internal_low", "#2563eb", "internal low"),
        ("external_high", "#8b1e1e", "external high"),
        ("external_low", "#075f47", "external low"),
        ("protected_high", "#db6b5f", "protected high"),
        ("protected_low", "#2f9f75", "protected low"),
    ):
        values = [
            float(value) if (value := getattr(snapshot, attribute)) is not None else float("nan")
            for snapshot in structure_snapshots
        ]
        axis.step(
            snapshot_times, values, where="post", color=color, lw=0.65, alpha=0.55, label=label
        )
    fvg_by_id = {fvg.id: fvg for fvg in fvgs}
    context_by_id = {context.id: context for context in contexts}
    last_time = candles[-1].close_time
    visible_contexts = [
        context
        for context in contexts
        if context.classification != LiquidityContextType.NO_CLEAR_CONTEXT
    ]
    context_names = sorted({context.classification.value for context in visible_contexts})
    context_rows = {name: index for index, name in enumerate(context_names)}
    for context in visible_contexts:
        context_axis.scatter(
            mdates.date2num(context.known_at),
            context_rows[context.classification.value],
            marker="x",
            color="#6b7280",
            s=14,
            linewidth=0.7,
            alpha=0.55,
            zorder=2,
        )
    for setup_index, setup in enumerate(setups, start=1):
        fvg = fvg_by_id[setup.fvg_id]
        context = context_by_id[setup.liquidity_context_id]
        color = "#16855b" if setup.side.value == "long" else "#c54444"
        start_number = mdates.date2num(fvg.formed_at)
        zone_end = min(
            _terminal_time(fvg) or last_time,
            candles[min(setup.expires_after_bar_index, len(candles) - 1)].close_time,
            last_time,
        )
        end_number = mdates.date2num(zone_end)
        axis.add_patch(
            Rectangle(
                (start_number, float(fvg.lower)),
                max(0.5, end_number - start_number),
                float(fvg.size),
                facecolor=color,
                edgecolor=color,
                alpha=0.17,
                linewidth=1.0,
            )
        )
        marker = "^" if setup.side.value == "long" else "v"
        row = context_rows[context.classification.value]
        context_axis.scatter(
            mdates.date2num(setup.known_at),
            row,
            marker=marker,
            color=color,
            s=26,
            zorder=3,
        )
        context_axis.annotate(
            f"S{setup_index}",
            (mdates.date2num(setup.known_at), row),
            fontsize=5,
            color=color,
            xytext=(2, 3 if setup_index % 2 else -7),
            textcoords="offset points",
        )
    axis.set_title(f"{candles[0].symbol} D1 Causal Structure and HTF Setups")
    axis.set_ylabel("Price (USDT)")
    axis.grid(color="#d7dce2", linewidth=0.5, alpha=0.7)
    axis.legend(loc="upper left", fontsize=6, ncols=2)
    context_axis.set_yticks(list(context_rows.values()), labels=context_names, fontsize=7)
    context_axis.set_ylabel("Liquidity context")
    context_axis.set_xlabel("UTC")
    context_axis.grid(color="#d7dce2", linewidth=0.5, alpha=0.7)
    context_axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=6, maxticks=14))
    context_axis.xaxis.set_major_formatter(
        mdates.ConciseDateFormatter(context_axis.xaxis.get_major_locator())
    )
    axis.set_xlim(mdates.date2num(candles[0].open_time) - 1, mdates.date2num(last_time) + 1)
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path


def _draw_candles(axis: Axes, candles: list[Candle]) -> None:
    for candle in candles:
        timestamp = mdates.date2num(candle.open_time)
        color = "#16855b" if candle.close >= candle.open else "#c54444"
        axis.vlines(timestamp, float(candle.low), float(candle.high), color=color, linewidth=0.6)
        axis.add_patch(
            Rectangle(
                (timestamp - 0.31, float(min(candle.open, candle.close))),
                0.62,
                max(float(abs(candle.close - candle.open)), 1e-12),
                facecolor=color,
                edgecolor=color,
                linewidth=0.45,
            )
        )


def plot_h4_reaction_debug(
    candles: list[Candle],
    d1_fvgs: list[FairValueGap],
    reactions: list[H4Reaction],
    touch_phases: list[H4TouchPhase],
    structure_breaks: list[StructureBreak],
    displacements: list[Displacement],
    target_outcomes: list[ReactionTargetOutcome],
    path: Path,
) -> Path:
    if not candles:
        raise ValueError("cannot plot an empty candle series")
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(20, 10), constrained_layout=True)
    _draw_candles(axis, candles)
    zone_by_id = {item.id: item for item in d1_fvgs}
    phase_by_id = {item.id: item for item in touch_phases}
    displacement_by_id = {item.id: item for item in displacements}
    break_by_id = {item.id: item for item in structure_breaks}
    last_time = candles[-1].close_time
    for reaction in reactions:
        if reaction.zone_id is None or reaction.zone_id not in zone_by_id:
            continue
        zone = zone_by_id[reaction.zone_id]
        color = "#16855b" if reaction.side.value == "long" else "#c54444"
        axis.add_patch(
            Rectangle(
                (mdates.date2num(reaction.created_at), float(zone.lower)),
                max(0.2, mdates.date2num(last_time) - mdates.date2num(reaction.created_at)),
                float(zone.size),
                facecolor=color,
                edgecolor=color,
                alpha=0.12,
                linewidth=0.8,
            )
        )
        axis.axvline(mdates.date2num(reaction.created_at), color=color, lw=0.55, alpha=0.55)
        if reaction.touch_phase_id is not None and reaction.touch_phase_id in phase_by_id:
            phase = phase_by_id[reaction.touch_phase_id]
            axis.scatter(
                mdates.date2num(phase.first_touch_close_time),
                float(phase.deepest_penetration_price),
                marker="o",
                facecolors="none",
                edgecolors="#d97706",
                s=42,
                zorder=8,
            )
        if reaction.first_reaction_at is not None:
            axis.axvline(
                mdates.date2num(reaction.first_reaction_at), color="#7c3aed", lw=0.7, alpha=0.7
            )
        if reaction.confirmed_at is not None:
            axis.axvline(mdates.date2num(reaction.confirmed_at), color="#111827", lw=1.0, alpha=0.8)
        if reaction.invalidated_at is not None:
            axis.axvline(
                mdates.date2num(reaction.invalidated_at), color="#b91c1c", lw=0.9, linestyle="--"
            )
        if reaction.expired_at is not None:
            axis.axvline(
                mdates.date2num(reaction.expired_at), color="#6b7280", lw=0.8, linestyle=":"
            )
        displacement = (
            displacement_by_id.get(reaction.displacement_id)
            if reaction.displacement_id is not None
            else None
        )
        if displacement is not None:
            axis.axvspan(
                mdates.date2num(displacement.start_time),
                mdates.date2num(displacement.known_at),
                color="#2563eb",
                alpha=0.08,
            )
        structure_break = (
            break_by_id.get(reaction.structure_break_id)
            if reaction.structure_break_id is not None
            else None
        )
        if structure_break is not None:
            axis.scatter(
                mdates.date2num(structure_break.known_at),
                float(structure_break.break_price),
                marker="x",
                color="#111827",
                s=35,
                zorder=8,
            )
    targets_by_key = {
        (item.reaction_id, item.target_type, item.target_price): item for item in target_outcomes
    }
    for target in targets_by_key.values():
        terminal = target.reached_at or last_time
        axis.hlines(
            float(target.target_price),
            mdates.date2num(target.known_at),
            mdates.date2num(terminal),
            color="#0f766e",
            linewidth=0.55,
            alpha=0.65,
        )
    axis.set_title(f"{candles[0].symbol} H4 Causal Reactions and Outcomes")
    axis.set_ylabel("Price (USDT)")
    axis.set_xlabel("UTC")
    axis.grid(color="#d7dce2", linewidth=0.5, alpha=0.7)
    axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=6, maxticks=16))
    axis.xaxis.set_major_formatter(mdates.ConciseDateFormatter(axis.xaxis.get_major_locator()))
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path
