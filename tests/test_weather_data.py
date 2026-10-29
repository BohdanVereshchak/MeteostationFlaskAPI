from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock

from weather_data import (
    finite_number,
    history_report,
    latest_reading,
    parse_timestamp,
    rainfall_buckets,
    rainfall_report,
    validate_configuration,
)


class WeatherDataTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 10, 29, 10, tzinfo=timezone.utc)

    def samples(self, reset=False):
        return [
            {
                "timestamp": (self.start + timedelta(minutes=minute)).isoformat(),
                "rainfall": {"tips": minute if not reset or minute < 30 else minute - 30},
            }
            for minute in range(61)
        ]

    def test_timestamp_formats_are_equivalent(self):
        for value in ["2026-10-29 10:00:00", "2026-10-29T10:00:00Z", "2026-10-29T12:00:00+02:00"]:
            self.assertEqual(parse_timestamp(value), self.start)
        self.assertIsNone(parse_timestamp("broken"))

    def test_zero_is_valid_but_non_finite_values_are_not(self):
        self.assertEqual(finite_number(0), 0)
        for value in [None, "", "NaN", float("inf"), True]:
            self.assertIsNone(finite_number(value))

    def test_complete_hour_accumulates_tip_differences(self):
        bucket = rainfall_buckets(self.samples(), self.start, 1)[0]
        self.assertTrue(bucket["complete"])
        self.assertEqual(bucket["rainfall_mm"], 59.22)

    def test_dry_hour_is_zero(self):
        samples = self.samples()
        for record in samples:
            record["rainfall"]["tips"] = 0
        self.assertEqual(rainfall_buckets(samples, self.start, 1)[0]["rainfall_mm"], 0)

    def test_reset_missing_baseline_and_long_gap_are_unknown(self):
        cases = [
            self.samples(reset=True),
            self.samples()[1:],
            [self.samples()[0], self.samples()[-1]],
            [],
        ]
        for samples in cases:
            bucket = rainfall_buckets(samples, self.start, 1)[0]
            self.assertFalse(bucket["complete"])
            self.assertIsNone(bucket["rainfall_mm"])

    def test_configuration_preserves_zero_and_rejects_invalid_ranges(self):
        configuration = validate_configuration(
            {"location": {"latitude": 0, "longitude": 0}, "temperature": {"min": 0, "max": None}}
        )
        self.assertEqual(configuration["temperature"]["min"], 0)
        self.assertIsNone(configuration["temperature"]["max"])
        for payload in [
            [],
            {},
            {"humidity": {"min": 70, "max": 20}},
            {"system": {"update_interval_ms": 0}},
            {"location": {"latitude": 91}},
            {"humidity": {"max": float("nan")}},
            {"unexpected": {"value": 1}},
        ]:
            with self.assertRaises(ValueError):
                validate_configuration(payload)

    def test_latest_query_orders_converted_timestamps_and_normalizes_output(self):
        collection = Mock()
        collection.aggregate.return_value = [{"timestamp": "2026-10-29 10:00:00"}]
        record = latest_reading(collection, self.start)
        self.assertEqual(record["timestamp"], self.start.isoformat())
        pipeline = collection.aggregate.call_args.args[0]
        self.assertIn("$convert", pipeline[0]["$set"]["observed_at"])
        self.assertEqual(pipeline[2], {"$sort": {"observed_at": -1}})

    def test_empty_history_is_stable_and_query_bounds_raw_readings(self):
        collection = Mock()
        collection.aggregate.return_value = [{"series": [], "readings": [], "summary": []}]
        report = history_report(collection, 24, self.start)
        self.assertEqual(report["summary"], {"count": 0})
        self.assertEqual(report["series"], [])
        pipeline = collection.aggregate.call_args.args[0]
        self.assertIn({"$limit": 100}, pipeline[-1]["$facet"]["readings"])

    def test_station_filter_is_applied_before_every_time_series_query(self):
        scope = {"device_id": "only-this-device"}
        history = Mock()
        history.aggregate.return_value = [{"series": [], "readings": [], "summary": []}]
        history_report(history, 24, self.start, device_filter=scope)
        self.assertEqual(history.aggregate.call_args.args[0][0], {"$match": scope})
        recent = Mock()
        recent.aggregate.return_value = []
        latest_reading(recent, device_filter=scope)
        self.assertEqual(recent.aggregate.call_args.args[0][0], {"$match": scope})
        rainfall_report(recent, 1, now=self.start, device_filter=scope)
        for call in recent.aggregate.call_args_list:
            self.assertEqual(call.args[0][0], {"$match": scope})


if __name__ == "__main__":
    unittest.main()
