from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


OUTPUT_DIR = Path("mock_metrics/output")
LINE_PROTOCOL_FILE = OUTPUT_DIR / "influx_bad_test.lp"
SUMMARY_FILE = OUTPUT_DIR / "influx_bad_test_summary.json"

APPLICATION = "lt-report-demo"
TEST_NAME = "bad_test_2026_04_26"
BUCKET = "lt-metrics"
TEST_START_UTC = datetime(2026, 4, 26, 16, 0, 0, tzinfo=UTC)
TEST_END_UTC = datetime(2026, 4, 26, 17, 0, 0, tzinfo=UTC)
TEST_DURATION_SECONDS = int((TEST_END_UTC - TEST_START_UTC).total_seconds())


@dataclass(frozen=True)
class TransactionSpec:
    name: str
    uc: str
    operation: str
    target_count: int
    sla_ms: int
    mean_ms: int
    p95_ms: int
    threads: int
    requests: tuple[str, ...]
    failure_rate: float = 0.0
    failure_request: str | None = None
    failure_response_ms: int | None = None


TRANSACTIONS: tuple[TransactionSpec, ...] = (
    TransactionSpec(
        name="UC_01_TR_01_Авторизация",
        uc="UC_01",
        operation="Авторизация",
        target_count=150,
        sla_ms=2000,
        mean_ms=1380,
        p95_ms=2550,
        threads=8,
        requests=("GET /login", "POST /api/auth/login", "GET /api/profile"),
    ),
    TransactionSpec(
        name="UC_02_TR_01_Авторизация",
        uc="UC_02",
        operation="Авторизация",
        target_count=140,
        sla_ms=2000,
        mean_ms=1460,
        p95_ms=2680,
        threads=10,
        requests=("GET /login", "POST /api/auth/login", "GET /api/dashboard"),
    ),
    TransactionSpec(
        name="UC_02_TR_02_Открытие меню",
        uc="UC_02",
        operation="Открытие меню",
        target_count=250,
        sla_ms=1000,
        mean_ms=340,
        p95_ms=680,
        threads=10,
        requests=("GET /api/menu", "GET /api/notifications"),
    ),
    TransactionSpec(
        name="UC_02_TR_03_Открытие страницы продуктов - Кредиты",
        uc="UC_02",
        operation="Открытие страниц продуктов",
        target_count=430,
        sla_ms=1000,
        mean_ms=540,
        p95_ms=920,
        threads=10,
        requests=("GET /api/products/credits", "GET /api/products/credits/rates", "GET /api/products/credits/offers"),
    ),
    TransactionSpec(
        name="UC_02_TR_04_Оформление кредита",
        uc="UC_02",
        operation="Оформление кредита",
        target_count=360,
        sla_ms=5000,
        mean_ms=4050,
        p95_ms=6280,
        threads=10,
        requests=("GET /api/credits/form", "POST /api/credits/validate", "POST /api/credits/submit", "GET /api/credits/status"),
        failure_rate=0.06,
        failure_request="POST /api/credits/submit",
        failure_response_ms=7400,
    ),
    TransactionSpec(
        name="UC_03_TR_01_Авторизация",
        uc="UC_03",
        operation="Авторизация",
        target_count=135,
        sla_ms=2000,
        mean_ms=1420,
        p95_ms=2620,
        threads=11,
        requests=("GET /login", "POST /api/auth/login", "GET /api/dashboard"),
    ),
    TransactionSpec(
        name="UC_03_TR_02_Открытие меню",
        uc="UC_03",
        operation="Открытие меню",
        target_count=230,
        sla_ms=1000,
        mean_ms=330,
        p95_ms=650,
        threads=11,
        requests=("GET /api/menu", "GET /api/notifications"),
    ),
    TransactionSpec(
        name="UC_03_TR_03_Открытие страницы продуктов - Карты",
        uc="UC_03",
        operation="Открытие страниц продуктов",
        target_count=390,
        sla_ms=1000,
        mean_ms=560,
        p95_ms=980,
        threads=11,
        requests=("GET /api/products/cards", "GET /api/products/cards/tariffs", "GET /api/products/cards/offers"),
    ),
    TransactionSpec(
        name="UC_03_TR_04_Оформление карты",
        uc="UC_03",
        operation="Оформление карты",
        target_count=720,
        sla_ms=5000,
        mean_ms=2280,
        p95_ms=4120,
        threads=11,
        requests=("GET /api/cards/form", "POST /api/cards/validate", "POST /api/cards/submit", "GET /api/cards/status"),
    ),
    TransactionSpec(
        name="UC_04_TR_01_Авторизация",
        uc="UC_04",
        operation="Авторизация",
        target_count=120,
        sla_ms=2000,
        mean_ms=1340,
        p95_ms=2460,
        threads=7,
        requests=("GET /login", "POST /api/auth/login", "GET /api/support/profile"),
    ),
    TransactionSpec(
        name="UC_04_TR_02_Открытие чата поддержки",
        uc="UC_04",
        operation="Открытие чата поддержки",
        target_count=430,
        sla_ms=1000,
        mean_ms=380,
        p95_ms=780,
        threads=7,
        requests=("GET /api/support/chat", "GET /api/support/chat/history", "POST /api/support/chat/session"),
    ),
)


def escape_tag(value: str) -> str:
    return value.replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def escape_field_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_point(
    lines: list[str],
    measurement: str,
    tags: dict[str, str],
    fields: dict[str, str | int | float | bool],
    timestamp_ns: int,
) -> None:
    tag_part = ",".join(f"{key}={escape_tag(val)}" for key, val in tags.items())
    field_parts: list[str] = []
    for key, value in fields.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, int):
            rendered = f"{value}i"
        elif isinstance(value, float):
            rendered = f"{value:.3f}".rstrip("0").rstrip(".")
        else:
            rendered = f'"{escape_field_string(value)}"'
        field_parts.append(f"{key}={rendered}")
    lines.append(f"{measurement},{tag_part} {','.join(field_parts)} {timestamp_ns}")


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def load_factor(second: int) -> float:
    if second < 900:
        return 0.24 + 0.76 * smoothstep(second / 900)
    if second < 3000:
        hold_progress = (second - 900) / 2100
        return 1.02 + 0.16 * math.sin(hold_progress * math.pi)
    if second <= TEST_DURATION_SECONDS:
        down_progress = (second - 3000) / max(TEST_DURATION_SECONDS - 3000, 1)
        return 1.10 - 0.70 * smoothstep(down_progress)
    return 0.24


def scheduled_offsets(target_count: int, rng: random.Random) -> list[float]:
    if target_count <= 0:
        return []
    spacing = TEST_DURATION_SECONDS / target_count
    offsets: list[float] = []
    for index in range(target_count):
        base = (index + 0.5) * spacing
        jitter = rng.uniform(-0.32, 0.32) * spacing
        offset = min(max(base + jitter, 1.0), TEST_DURATION_SECONDS - 1.0)
        offsets.append(offset)
    offsets.sort()
    return offsets


def sample_duration_ms(spec: TransactionSpec, rng: random.Random) -> int:
    sigma = 0.33 if spec.sla_ms <= 2000 else 0.38
    mu = math.log(spec.mean_ms) - (sigma**2) / 2
    value = int(rng.lognormvariate(mu, sigma))
    cap = int(spec.p95_ms * rng.uniform(1.04, 1.16))
    floor = max(160, int(spec.mean_ms * 0.58))
    return max(floor, min(value, cap))


def request_duration_split(total_ms: int, request_count: int, rng: random.Random) -> list[int]:
    weights = [max(rng.uniform(0.6, 1.8), 0.1) for _ in range(request_count)]
    weight_sum = sum(weights)
    durations = [max(40, int(total_ms * weight / weight_sum)) for weight in weights]
    durations[-1] += total_ms - sum(durations)
    return durations


def all_threads_at(second: int, uc_threads: dict[str, int]) -> dict[str, int]:
    threads: dict[str, int] = {}
    for uc, max_threads in uc_threads.items():
        factor = load_factor(second)
        value = max(1, min(int(round(max_threads * 1.25)), int(round(max_threads * factor))))
        threads[uc] = value
    return threads


def generate() -> tuple[list[str], dict[str, object]]:
    rng = random.Random(20260426)
    lines: list[str] = []
    summary: dict[str, object] = {
        "application": APPLICATION,
        "test_name": TEST_NAME,
        "bucket": BUCKET,
        "start_utc": TEST_START_UTC.isoformat(),
        "end_utc": TEST_END_UTC.isoformat(),
        "transactions": {},
        "operations": {},
        "failed_request_examples": [],
    }

    uc_threads = {
        "UC_01": 8,
        "UC_02": 10,
        "UC_03": 11,
        "UC_04": 7,
    }

    operation_rollup: dict[str, dict[str, float]] = {}

    for spec in TRANSACTIONS:
        txn_stats = {
            "count": 0,
            "errors": 0,
            "max_elapsed_ms": 0,
            "sum_elapsed_ms": 0,
            "sla_ms": spec.sla_ms,
            "target_count": spec.target_count,
            "operation": spec.operation,
        }
        offsets = scheduled_offsets(spec.target_count, rng)

        for offset in offsets:
            second = int(offset)
            current_threads = all_threads_at(second, uc_threads)
            all_threads = sum(current_threads.values())
            grp_threads = current_threads[spec.uc]
            timestamp = TEST_START_UTC + timedelta(seconds=offset)
            ts_ns = int(timestamp.timestamp() * 1_000_000_000)

            txn_failed = spec.failure_rate > 0.0 and rng.random() < spec.failure_rate
            elapsed_ms = sample_duration_ms(spec, rng)
            if txn_failed and spec.failure_response_ms is not None:
                elapsed_ms = max(elapsed_ms, spec.failure_response_ms)
            latency_ms = max(20, int(elapsed_ms * rng.uniform(0.66, 0.84)))
            connect_ms = max(5, int(elapsed_ms * rng.uniform(0.05, 0.12)))
            recv_bytes = rng.randint(18_000, 140_000)
            sent_bytes = rng.randint(600, 8_000)
            thread_num = 1 + (txn_stats["count"] % max(spec.threads, 1))
            thread_name = f"{spec.uc} {thread_num}-1"

            response_code = "500" if txn_failed else "200"
            status_tag = "ko" if txn_failed else "ok"

            write_point(
                lines,
                "jmeter_samples",
                {
                    "application": APPLICATION,
                    "test_name": TEST_NAME,
                    "sampler_type": "transaction",
                    "transaction": spec.name,
                    "operation": spec.operation,
                    "uc": spec.uc,
                    "status": status_tag,
                    "response_code": response_code,
                },
                {
                    "elapsed_ms": elapsed_ms,
                    "latency_ms": latency_ms,
                    "connect_ms": connect_ms,
                    "success": not txn_failed,
                    "all_threads": all_threads,
                    "grp_threads": grp_threads,
                    "bytes": recv_bytes,
                    "sent_bytes": sent_bytes,
                    "thread_name": thread_name,
                },
                ts_ns,
            )

            request_names = spec.requests
            request_durations = request_duration_split(elapsed_ms, len(request_names), rng)
            request_ts = timestamp
            for request_name, request_elapsed in zip(request_names, request_durations):
                request_ts += timedelta(milliseconds=rng.randint(8, 35))
                request_ts_ns = int(request_ts.timestamp() * 1_000_000_000)
                request_latency = max(15, int(request_elapsed * rng.uniform(0.55, 0.78)))
                request_connect = max(4, int(request_elapsed * rng.uniform(0.04, 0.10)))
                request_bytes = max(4_000, int(recv_bytes / len(request_names) * rng.uniform(0.75, 1.20)))
                request_sent = max(200, int(sent_bytes / len(request_names) * rng.uniform(0.70, 1.25)))

                request_failed = txn_failed and request_name == spec.failure_request
                request_code = "500" if request_failed else ("302" if request_name == "GET /login" else "200")
                request_status = "ko" if request_failed else "ok"
                if request_failed and spec.failure_response_ms is not None:
                    request_elapsed = max(request_elapsed, spec.failure_response_ms)

                write_point(
                    lines,
                    "jmeter_samples",
                    {
                        "application": APPLICATION,
                        "test_name": TEST_NAME,
                        "sampler_type": "request",
                        "transaction": spec.name,
                        "request": request_name,
                        "operation": spec.operation,
                        "uc": spec.uc,
                        "status": request_status,
                        "response_code": request_code,
                    },
                    {
                        "elapsed_ms": request_elapsed,
                        "latency_ms": request_latency,
                        "connect_ms": request_connect,
                        "success": not request_failed,
                        "all_threads": all_threads,
                        "grp_threads": grp_threads,
                        "bytes": request_bytes,
                        "sent_bytes": request_sent,
                        "thread_name": thread_name,
                    },
                    request_ts_ns,
                )
                if request_failed:
                    failed_examples = summary["failed_request_examples"]
                    if isinstance(failed_examples, list) and len(failed_examples) < 8:
                        failed_examples.append(
                            {
                                "operation": spec.operation,
                                "transaction": spec.name,
                                "request": request_name,
                                "timestamp": request_ts.isoformat(),
                                "response_code": request_code,
                            }
                        )
                request_ts += timedelta(milliseconds=request_elapsed)

            txn_stats["count"] += 1
            txn_stats["sum_elapsed_ms"] += elapsed_ms
            txn_stats["max_elapsed_ms"] = max(txn_stats["max_elapsed_ms"], elapsed_ms)
            if txn_failed:
                txn_stats["errors"] += 1

            operation_stats = operation_rollup.setdefault(
                spec.operation,
                {"count": 0, "sum_elapsed_ms": 0.0, "max_elapsed_ms": 0.0, "errors": 0},
            )
            operation_stats["count"] += 1
            operation_stats["sum_elapsed_ms"] += elapsed_ms
            operation_stats["max_elapsed_ms"] = max(operation_stats["max_elapsed_ms"], elapsed_ms)
            if txn_failed:
                operation_stats["errors"] += 1

        summary["transactions"][spec.name] = {
            "count": txn_stats["count"],
            "errors": txn_stats["errors"],
            "target_count": spec.target_count,
            "deviation_percent": round((txn_stats["count"] - spec.target_count) / spec.target_count * 100, 2),
            "avg_elapsed_ms": round(txn_stats["sum_elapsed_ms"] / max(txn_stats["count"], 1), 2),
            "max_elapsed_ms": txn_stats["max_elapsed_ms"],
            "sla_ms": spec.sla_ms,
            "operation": spec.operation,
            "uc": spec.uc,
        }

    profile_targets = {
        "Авторизация": 300,
        "Открытие страниц продуктов": 700,
        "Оформление кредита": 400,
        "Оформление карты": 650,
        "Открытие чата поддержки": 500,
    }

    for operation, stats in operation_rollup.items():
        count = int(stats["count"])
        target = profile_targets.get(operation)
        summary["operations"][operation] = {
            "count": count,
            "errors": int(stats["errors"]),
            "target_count": target,
            "deviation_percent": round(((count - target) / target) * 100, 2) if target else None,
            "avg_elapsed_ms": round(stats["sum_elapsed_ms"] / max(count, 1), 2),
            "max_elapsed_ms": round(stats["max_elapsed_ms"], 2),
        }

    return lines, summary


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lines, summary = generate()
    LINE_PROTOCOL_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"Generated {LINE_PROTOCOL_FILE}")
    print(f"Generated {SUMMARY_FILE}")


if __name__ == "__main__":
    main()
