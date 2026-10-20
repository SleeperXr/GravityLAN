"""Hourly and daily rollups of the raw measurement tables (telemetry database).

Raw DeviceHealthSample / DeviceMetrics rows are kept only for a short time
(``telemetry.raw_retention_hours``). Every complete hour is folded into one row
per device here, and every complete day into one more, so long time windows stay
cheap to store and to query (app.services.telemetry_rollups builds them,
app.services.telemetry_query reads them).

``resolution`` is the bucket length in seconds (3600 or 86400), ``bucket_start``
the naive-UTC start of the bucket. Averages are stored together with the number of
values behind them so buckets can be combined into larger ones without bias.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import TELEMETRY_SCHEMA, Base

HOUR = 3600
DAY = 86400


class DeviceHealthRollup(Base):
    """Health probes of one device aggregated over an hour or a day.

    Attributes:
        samples / online: Probe count and how many of them saw the device online
            (uptime = online / samples).
        latency_count: Probes with a latency value; latency_avg is their mean.
        jitter_sum / jitter_count: Sum and count of absolute differences between
            consecutive latencies, so jitter = jitter_sum / jitter_count.
        ports_up_avg / ports_total: Mean of reachable configured services, and the
            largest number of configured services seen in the bucket.
    """

    __tablename__ = "device_health_rollups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution: Mapped[int] = mapped_column(Integer, nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    online: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    jitter_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    jitter_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ports_up_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ports_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("device_id", "resolution", "bucket_start", name="uq_health_rollup_bucket"),
        Index("ix_health_rollups_res_bucket", "resolution", "bucket_start"),
        {"schema": TELEMETRY_SCHEMA},
    )


class DeviceMetricsRollup(Base):
    """Agent metrics of one device aggregated over an hour or a day.

    Attributes:
        samples: Number of agent reports in the bucket (weight of the averages).
        temp_count: Reports that carried a temperature (weight of temp_avg).
        disk_percent_max: Fullest monitored mount in the bucket.
        net_rx_* / net_tx_*: Throughput in bytes/s, summed over all interfaces.
        disk_json / net_json: Last non-empty snapshot of the bucket, as the raw
            history returns it for the detail view.
    """

    __tablename__ = "device_metrics_rollups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[int] = mapped_column(Integer, nullable=False)
    resolution: Mapped[int] = mapped_column(Integer, nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cpu_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cpu_max: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ram_percent_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ram_percent_max: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ram_used_mb_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ram_total_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    temp_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    temp_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    temp_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_percent_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_rx_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    net_rx_max: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    net_tx_avg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    net_tx_max: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    disk_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    net_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("device_id", "resolution", "bucket_start", name="uq_metrics_rollup_bucket"),
        Index("ix_metrics_rollups_res_bucket", "resolution", "bucket_start"),
        {"schema": TELEMETRY_SCHEMA},
    )
