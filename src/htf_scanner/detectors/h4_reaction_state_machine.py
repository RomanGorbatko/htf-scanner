from datetime import datetime
from typing import ClassVar
from uuid import NAMESPACE_URL, UUID, uuid5

from htf_scanner.domain.enums import H4ReactionStatus
from htf_scanner.domain.reaction import H4ReactionTransition


class H4ReactionStateMachine:
    _allowed: ClassVar[dict[H4ReactionStatus, set[H4ReactionStatus]]] = {
        H4ReactionStatus.WAITING_FOR_TOUCH: {
            H4ReactionStatus.ZONE_TOUCHED,
            H4ReactionStatus.INVALIDATED,
            H4ReactionStatus.EXPIRED,
        },
        H4ReactionStatus.ZONE_TOUCHED: {
            H4ReactionStatus.EARLY_REACTION,
            H4ReactionStatus.REACTION_CONFIRMED,
            H4ReactionStatus.INVALIDATED,
            H4ReactionStatus.EXPIRED,
        },
        H4ReactionStatus.EARLY_REACTION: {
            H4ReactionStatus.REACTION_CONFIRMED,
            H4ReactionStatus.INVALIDATED,
            H4ReactionStatus.EXPIRED,
        },
        H4ReactionStatus.REACTION_CONFIRMED: {H4ReactionStatus.INVALIDATED},
        H4ReactionStatus.INVALIDATED: set(),
        H4ReactionStatus.EXPIRED: set(),
        H4ReactionStatus.TOUCHED: set(),
    }

    @classmethod
    def transition(
        cls,
        reaction_id: UUID,
        setup_id: UUID,
        current: H4ReactionStatus,
        target: H4ReactionStatus,
        formed_at: datetime,
        known_at: datetime,
        bar_index: int,
        reason: str,
    ) -> H4ReactionTransition:
        if target not in cls._allowed[current]:
            raise ValueError(f"invalid H4 reaction transition: {current.value} -> {target.value}")
        identity = ":".join(
            [str(reaction_id), current.value, target.value, known_at.isoformat(), reason]
        )
        return H4ReactionTransition(
            id=uuid5(NAMESPACE_URL, identity),
            reaction_id=reaction_id,
            setup_id=setup_id,
            from_status=current,
            to_status=target,
            formed_at=formed_at,
            known_at=known_at,
            bar_index=bar_index,
            reason=reason,
        )
