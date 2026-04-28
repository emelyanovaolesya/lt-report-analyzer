from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path


OUTPUT_DIR = Path("mock_metrics/output")
OUTPUT_FILE = OUTPUT_DIR / "prometheus_good_test.prom"

INSTANCE = "app-lt1:9100"
JOB = "node-exporter"
DEVICE = "C:"
FILESYSTEM = "NTFS"
MOUNTPOINT = "C:\\"
TOTAL_MEMORY = 16 * 1024**3
TOTAL_DISK = 200 * 1024**3
CPU_COUNT = 4
STEP_SECONDS = 60
DURATION_MINUTES = 60


def fmt(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def add_sample(lines: list[str], metric: str, labels: dict[str, str], value: float, timestamp_ms: int) -> None:
    rendered_labels = ",".join(f'{key}="{escape_label_value(val)}"' for key, val in labels.items())
    lines.append(f"{metric}{{{rendered_labels}}} {fmt(value)} {timestamp_ms}")


def build_openmetrics() -> str:
    start_time = datetime.now(UTC) - timedelta(hours=1)
    lines = [
        "# HELP node_cpu_seconds_total Seconds the CPUs spent in each mode.",
        "# TYPE node_cpu_seconds_total counter",
        "# HELP node_memory_MemTotal_bytes Memory information field MemTotal_bytes.",
        "# TYPE node_memory_MemTotal_bytes gauge",
        "# HELP node_memory_MemAvailable_bytes Memory information field MemAvailable_bytes.",
        "# TYPE node_memory_MemAvailable_bytes gauge",
        "# HELP node_filesystem_size_bytes Filesystem size in bytes.",
        "# TYPE node_filesystem_size_bytes gauge",
        "# HELP node_filesystem_avail_bytes Filesystem space available to non-root users in bytes.",
        "# TYPE node_filesystem_avail_bytes gauge",
        "# HELP node_load1 1m load average.",
        "# TYPE node_load1 gauge",
    ]

    cpu_totals = {
        cpu: {"idle": 0.0, "user": 0.0, "system": 0.0, "iowait": 0.0}
        for cpu in range(CPU_COUNT)
    }

    for minute in range(DURATION_MINUTES + 1):
        timestamp = start_time + timedelta(minutes=minute)
        timestamp_seconds = int(timestamp.timestamp())

        cpu_util = 42 + 8 * math.sin(minute / 9) + 4 * math.cos(minute / 5)
        cpu_util = max(28.0, min(cpu_util, 58.0))
        system_share = 0.24 + 0.03 * math.sin(minute / 7)
        iowait_share = 0.04 + 0.01 * math.cos(minute / 6)
        user_share = max(cpu_util / 100 - system_share - iowait_share, 0.12)
        idle_share = 1 - (user_share + system_share + iowait_share)

        for cpu in range(CPU_COUNT):
            jitter = (cpu - 1.5) * 0.007
            cpu_user = max(user_share + jitter, 0.08)
            cpu_system = max(system_share - jitter / 2, 0.08)
            cpu_iowait = max(iowait_share + jitter / 3, 0.01)
            cpu_idle = max(1 - (cpu_user + cpu_system + cpu_iowait), 0.20)

            increments = {
                "user": STEP_SECONDS * cpu_user,
                "system": STEP_SECONDS * cpu_system,
                "iowait": STEP_SECONDS * cpu_iowait,
                "idle": STEP_SECONDS * cpu_idle,
            }
            for mode, increment in increments.items():
                cpu_totals[cpu][mode] += increment
                add_sample(
                    lines,
                    "node_cpu_seconds_total",
                    {"instance": INSTANCE, "job": JOB, "cpu": str(cpu), "mode": mode},
                    cpu_totals[cpu][mode],
                    timestamp_seconds,
                )

        memory_used_ratio = 0.55 + 0.06 * math.sin(minute / 8) + 0.03 * math.cos(minute / 3.5)
        memory_used_ratio = max(0.46, min(memory_used_ratio, 0.68))
        mem_available = TOTAL_MEMORY * (1 - memory_used_ratio)
        add_sample(
            lines,
            "node_memory_MemTotal_bytes",
            {"instance": INSTANCE, "job": JOB},
            TOTAL_MEMORY,
            timestamp_seconds,
        )
        add_sample(
            lines,
            "node_memory_MemAvailable_bytes",
            {"instance": INSTANCE, "job": JOB},
            mem_available,
            timestamp_seconds,
        )

        disk_used_ratio = 0.58 + 0.02 * math.sin(minute / 10) + 0.01 * math.cos(minute / 4)
        disk_used_ratio = max(0.54, min(disk_used_ratio, 0.64))
        disk_avail = TOTAL_DISK * (1 - disk_used_ratio)
        add_sample(
            lines,
            "node_filesystem_size_bytes",
            {
                "instance": INSTANCE,
                "job": JOB,
                "device": DEVICE,
                "fstype": FILESYSTEM,
                "mountpoint": MOUNTPOINT,
            },
            TOTAL_DISK,
            timestamp_seconds,
        )
        add_sample(
            lines,
            "node_filesystem_avail_bytes",
            {
                "instance": INSTANCE,
                "job": JOB,
                "device": DEVICE,
                "fstype": FILESYSTEM,
                "mountpoint": MOUNTPOINT,
            },
            disk_avail,
            timestamp_seconds,
        )

        load1 = 1.2 + 0.25 * math.sin(minute / 12) + 0.1 * math.cos(minute / 5)
        add_sample(
            lines,
            "node_load1",
            {"instance": INSTANCE, "job": JOB},
            max(load1, 0.5),
            timestamp_seconds,
        )

    lines.append("# EOF")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(build_openmetrics(), encoding="utf-8", newline="\n")
    print(f"Generated {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
