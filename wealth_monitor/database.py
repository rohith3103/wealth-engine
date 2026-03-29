from __future__ import annotations

from datetime import datetime
from pathlib import Path


def initialize_database(database_path: Path | str) -> None:
    import duckdb

    database_path = Path(database_path)
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cycle_history (
                timestamp TIMESTAMP,
                fear_score INTEGER,
                dominant_theme VARCHAR,
                india_vix DOUBLE,
                recommended_asset VARCHAR,
                action_taken VARCHAR,
                position_size INTEGER
            )
            """
        )
    finally:
        connection.close()


def log_cycle(
    database_path: Path | str,
    timestamp: datetime,
    fear_score: int,
    dominant_theme: str,
    india_vix: float | None,
    recommended_asset: str | None,
    action_taken: str,
    position_size: int,
) -> None:
    import duckdb

    initialize_database(database_path)
    connection = duckdb.connect(str(Path(database_path)))
    try:
        connection.execute(
            """
            INSERT INTO cycle_history (
                timestamp,
                fear_score,
                dominant_theme,
                india_vix,
                recommended_asset,
                action_taken,
                position_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                timestamp.replace(tzinfo=None),
                fear_score,
                dominant_theme,
                india_vix,
                recommended_asset,
                action_taken,
                position_size,
            ],
        )
    finally:
        connection.close()
