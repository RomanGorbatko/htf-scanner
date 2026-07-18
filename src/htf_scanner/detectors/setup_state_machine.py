from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from htf_scanner.domain.enums import SetupStatus
from htf_scanner.domain.setup import HTFSetup, HTFSetupTransition

ALLOWED_TRANSITIONS: dict[SetupStatus, frozenset[SetupStatus]] = {
    SetupStatus.CANDIDATE: frozenset(
        {SetupStatus.CONFIRMED, SetupStatus.INVALIDATED, SetupStatus.EXPIRED}
    ),
    SetupStatus.CONFIRMED: frozenset(
        {SetupStatus.ACTIVE, SetupStatus.INVALIDATED, SetupStatus.EXPIRED}
    ),
    SetupStatus.ACTIVE: frozenset({SetupStatus.INVALIDATED, SetupStatus.EXPIRED}),
    SetupStatus.INVALIDATED: frozenset(),
    SetupStatus.EXPIRED: frozenset(),
    SetupStatus.H4_TOUCHED: frozenset(),
    SetupStatus.H4_REACTING: frozenset(),
}


class HTFSetupStateMachine:
    def transition(
        self,
        setup: HTFSetup,
        to_status: SetupStatus,
        known_at: datetime,
        bar_index: int,
        reason: str,
    ) -> tuple[HTFSetup, HTFSetupTransition]:
        if to_status not in ALLOWED_TRANSITIONS[setup.status]:
            raise ValueError(f"invalid setup transition: {setup.status} -> {to_status}")
        if known_at < setup.known_at:
            raise ValueError("transition cannot be known before the setup")
        identity = f"{setup.id}:{setup.status}:{to_status}:{known_at.isoformat()}:{reason}"
        transition = HTFSetupTransition(
            id=uuid5(NAMESPACE_URL, identity),
            setup_id=setup.id,
            from_status=setup.status,
            to_status=to_status,
            known_at=known_at,
            bar_index=bar_index,
            reason=reason,
        )
        return setup.model_copy(update={"status": to_status}), transition

    def expire_if_due(
        self, setup: HTFSetup, known_at: datetime, bar_index: int
    ) -> tuple[HTFSetup, HTFSetupTransition | None]:
        if setup.status != SetupStatus.ACTIVE or bar_index < setup.expires_after_bar_index:
            return setup, None
        return self.transition(
            setup,
            SetupStatus.EXPIRED,
            known_at,
            bar_index,
            "max_setup_age_bars_reached",
        )
