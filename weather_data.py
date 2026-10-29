"""Time-series queries shared by the dashboard and rainfall endpoints."""

from datetime import datetime, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo

RAIN_MM_PER_TIP = 0.987
KYIV = ZoneInfo("Europe/Kyiv")


def parse_timestamp(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    # The station's legacy timestamps have no offset, but were recorded in UTC.
    return (
        parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )


def finite_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def timestamp_stage():
    return {
        "$set": {
            "observed_at": {
                "$convert": {
                    "input": "$timestamp",
                    "to": "date",
                    "onError": None,
                    "onNull": None,
                }
            }
        }
    }


def time_window_stages(start, end):
    # This coarse string range can use an existing timestamp index. The date
    # conversion below makes the final comparison independent of stored offsets.
    return [
        {
            "$match": {
                "timestamp": {
                    "$gte": (start - timedelta(days=1)).strftime("%Y-%m-%d"),
                    "$lt": (end + timedelta(days=2)).strftime("%Y-%m-%d"),
                }
            }
        },
        timestamp_stage(),
        {"$match": {"observed_at": {"$gte": start, "$lte": end}}},
    ]


def latest_reading(collection, before=None, device_filter=None):
    condition = {"$ne": None}
    if before is not None:
        condition["$lte"] = before
    records = list(
        collection.aggregate(
            [
                *([{"$match": device_filter}] if device_filter else []),
                timestamp_stage(),
                {"$match": {"observed_at": condition}},
                {"$sort": {"observed_at": -1}},
                {"$limit": 1},
                {"$project": {"_id": 0, "observed_at": 0}},
            ]
        )
    )
    if not records:
        return None
    record = records[0]
    record["timestamp"] = parse_timestamp(record["timestamp"]).isoformat()
    return record


def history_report(collection, hours, now=None, device_filter=None):
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    bucket_ms = max(60, hours * 3600 // 240) * 1000
    metrics = {
        "temperature": "$environment.temperature",
        "humidity": "$environment.humidity",
        "pressure": "$environment.pressure",
        "eco2": "$air_quality.eco2",
        "tvoc": "$air_quality.tvoc",
        "aqi": "$air_quality.aqi",
    }
    group = {"_id": {"$floor": {"$divide": [{"$toLong": "$observed_at"}, bucket_ms]}}}
    for name, path in metrics.items():
        group[name] = {
            "$avg": {
                "$convert": {
                    "input": path,
                    "to": "double",
                    "onError": None,
                    "onNull": None,
                }
            }
        }
    result = list(
        collection.aggregate(
            [
                *([{"$match": device_filter}] if device_filter else []),
                *time_window_stages(start, end),
                {
                    "$facet": {
                        "series": [
                            {"$group": group},
                            {"$sort": {"_id": 1}},
                        ],
                        "readings": [
                            {"$sort": {"observed_at": -1}},
                            {"$limit": 100},
                            {"$project": {"_id": 0, "observed_at": 0}},
                        ],
                        "summary": [
                            {
                                "$group": {
                                    "_id": None,
                                    "count": {"$sum": 1},
                                    "minimum": {
                                        "$min": {
                                            "$convert": {
                                                "input": "$environment.temperature",
                                                "to": "double",
                                                "onError": None,
                                                "onNull": None,
                                            }
                                        }
                                    },
                                    "maximum": {
                                        "$max": {
                                            "$convert": {
                                                "input": "$environment.temperature",
                                                "to": "double",
                                                "onError": None,
                                                "onNull": None,
                                            }
                                        }
                                    },
                                    "average": {
                                        "$avg": {
                                            "$convert": {
                                                "input": "$environment.temperature",
                                                "to": "double",
                                                "onError": None,
                                                "onNull": None,
                                            }
                                        }
                                    },
                                }
                            }
                        ],
                    }
                },
            ]
        )
    )[0]
    series = []
    for bucket in result["series"]:
        timestamp = datetime.fromtimestamp(bucket["_id"] * bucket_ms / 1000, timezone.utc)
        series.append(
            {
                "timestamp": timestamp.isoformat(),
                **{name: finite_number(bucket.get(name)) for name in metrics},
            }
        )
    summary = result["summary"][0] if result["summary"] else {"count": 0}
    summary.pop("_id", None)
    for reading in result["readings"]:
        reading["timestamp"] = parse_timestamp(reading["timestamp"]).isoformat()
    return {
        "hours": hours,
        "bucket_seconds": bucket_ms // 1000,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "series": series,
        "readings": result["readings"],
        "summary": summary,
    }


def rainfall_buckets(readings, start, hours, max_gap_seconds=600):
    samples = []
    for record in readings:
        timestamp = parse_timestamp(record.get("timestamp"))
        tips = finite_number((record.get("rainfall") or {}).get("tips"))
        if timestamp is not None and tips is not None and tips >= 0:
            samples.append((timestamp, tips))
    samples.sort(key=lambda sample: sample[0])
    buckets = []
    for index in range(hours):
        lower = start + timedelta(hours=index)
        upper = lower + timedelta(hours=1)
        previous = next((sample for sample in reversed(samples) if sample[0] <= lower), None)
        current = [sample for sample in samples if lower < sample[0] <= upper]
        complete = previous is not None and (lower - previous[0]).total_seconds() <= max_gap_seconds
        total = 0
        for sample in current:
            if previous is None:
                complete = False
            else:
                gap = (sample[0] - previous[0]).total_seconds()
                delta = sample[1] - previous[1]
                if gap > max_gap_seconds or delta < 0:
                    complete = False
                else:
                    total += delta * RAIN_MM_PER_TIP
            previous = sample
        if previous is None or (upper - previous[0]).total_seconds() > max_gap_seconds:
            complete = False
        local_end = upper.astimezone(KYIV)
        buckets.append(
            {
                "hour": local_end.hour,
                "time_label": local_end.strftime("%H:%M"),
                "start_ts": lower.isoformat(),
                "end_ts": upper.isoformat(),
                "rainfall_mm": round(total, 2) if complete else None,
                "complete": complete,
            }
        )
    return buckets


def rainfall_report(
    collection, hours, update_interval_ms=60000, now=None, round_hour=True, device_filter=None
):
    end = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    if round_hour and (end.minute or end.second):
        end = (end + timedelta(hours=1)).replace(minute=0, second=0)
    start = end - timedelta(hours=hours)
    baseline = latest_reading(collection, start, device_filter)
    readings = list(
        collection.aggregate(
            [
                *([{"$match": device_filter}] if device_filter else []),
                *time_window_stages(start, end),
                {"$project": {"_id": 0, "timestamp": 1, "rainfall": 1}},
            ]
        )
    )
    if baseline:
        readings.insert(0, baseline)
    max_gap = max(600, (finite_number(update_interval_ms) or 60000) / 1000 * 3)
    buckets = rainfall_buckets(readings, start, hours, max_gap)
    actual_end = now or datetime.now(timezone.utc)
    if end > actual_end:
        buckets[-1]["complete"] = False
        buckets[-1]["rainfall_mm"] = None
    return {"hours": hours, "data": buckets}


def validate_configuration(payload):
    if not isinstance(payload, dict) or not payload:
        raise ValueError("Надішліть об’єкт налаштувань.")
    allowed = {"system", "location", "temperature", "humidity"}
    if set(payload) - allowed:
        raise ValueError("Невідомий розділ налаштувань.")
    cleaned = {}
    for section, values in payload.items():
        cleaned[section] = {}
        if not isinstance(values, dict):
            raise ValueError("Кожний розділ має бути об’єктом.")
        rules = {
            "system": {"update_interval_ms": (1000, 86400000)},
            "location": {"latitude": (-90, 90), "longitude": (-180, 180)},
            "temperature": {"min": (-100, 100), "max": (-100, 100)},
            "humidity": {"min": (0, 100), "max": (0, 100)},
        }[section]
        if set(values) - set(rules):
            raise ValueError("Невідоме поле налаштувань.")
        for field, value in values.items():
            if value is None and section in {"temperature", "humidity"}:
                cleaned[section][field] = None
                continue
            number = finite_number(value)
            lower, upper = rules[field]
            if number is None or not lower <= number <= upper:
                raise ValueError("Перевірте числові значення та допустимі межі.")
            if section == "system" and not number.is_integer():
                raise ValueError("Інтервал має бути цілим числом мілісекунд.")
            cleaned[section][field] = int(number) if section == "system" else number
        minimum, maximum = values.get("min"), values.get("max")
        if minimum is not None and maximum is not None and float(minimum) > float(maximum):
            raise ValueError("Мінімум не може перевищувати максимум.")
    return cleaned
