from datetime import UTC, datetime

from sqlalchemy import Engine, Select, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from htf_scanner.domain.candle import Candle
from htf_scanner.storage.models import CandleRow


class CandleRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert_many(self, candles: list[Candle]) -> int:
        if not candles:
            return 0
        records = [candle.model_dump() for candle in candles]
        statement = insert(CandleRow).values(records)
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "open_time"],
            set_={
                "close_time": excluded.close_time,
                "open": excluded.open,
                "high": excluded.high,
                "low": excluded.low,
                "close": excluded.close,
                "volume": excluded.volume,
                "quote_volume": excluded.quote_volume,
                "trades": excluded.trades,
                "is_closed": excluded.is_closed,
            },
        )
        with Session(self._engine) as session, session.begin():
            session.execute(statement)
        return len(candles)

    def list_range(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        query: Select[tuple[CandleRow]] = (
            select(CandleRow)
            .where(
                CandleRow.symbol == symbol.upper(),
                CandleRow.timeframe == timeframe,
                CandleRow.open_time >= start,
                CandleRow.open_time < end,
                CandleRow.is_closed.is_(True),
            )
            .order_by(CandleRow.open_time)
        )
        with Session(self._engine) as session:
            rows = session.scalars(query).all()
        return [self._to_domain(row) for row in rows]

    @staticmethod
    def _to_domain(row: CandleRow) -> Candle:
        open_time = (
            row.open_time.replace(tzinfo=UTC) if row.open_time.tzinfo is None else row.open_time
        )
        close_time = (
            row.close_time.replace(tzinfo=UTC) if row.close_time.tzinfo is None else row.close_time
        )
        return Candle(
            symbol=row.symbol,
            timeframe=row.timeframe,
            open_time=open_time,
            close_time=close_time,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            quote_volume=row.quote_volume,
            trades=row.trades,
            is_closed=row.is_closed,
        )
