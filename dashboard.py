from __future__ import annotations

from pathlib import Path

import duckdb
import streamlit as st

from wealth_monitor.database import initialize_database

DATABASE_PATH = Path(__file__).resolve().parent / "wealth_logs.duckdb"


def load_cycle_history(database_path: Path) -> object:
    initialize_database(database_path)
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        return connection.execute(
            """
            SELECT
                timestamp,
                fear_score,
                dominant_theme,
                india_vix,
                recommended_asset,
                action_taken,
                position_size
            FROM cycle_history
            ORDER BY timestamp DESC
            """
        ).df()
    finally:
        connection.close()


st.set_page_config(page_title="Wealth Loop Dashboard", layout="wide")
st.title("Wealth Loop Analytics")
st.caption(f"DuckDB source: {DATABASE_PATH}")

history_df = load_cycle_history(DATABASE_PATH)

if history_df.empty:
    st.info("No cycle history has been logged yet. Run `python run_cycle.py` to populate the dashboard.")
else:
    latest_row = history_df.iloc[0]
    metric_columns = st.columns(3)
    metric_columns[0].metric("Latest Fear Score", int(latest_row["fear_score"]))
    metric_columns[1].metric("Latest Asset", latest_row["recommended_asset"] or "None")
    metric_columns[2].metric("Latest Action", latest_row["action_taken"])

    st.subheader("Fear Score Over Time")
    chart_df = history_df.sort_values("timestamp")[["timestamp", "fear_score"]].set_index("timestamp")
    st.line_chart(chart_df)

    st.subheader("Recent Trading Actions")
    st.dataframe(
        history_df[
            [
                "timestamp",
                "dominant_theme",
                "india_vix",
                "recommended_asset",
                "action_taken",
                "position_size",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )
