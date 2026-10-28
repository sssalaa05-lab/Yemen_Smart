from __future__ import annotations

import unittest

from services.nexus_ml.training_data import (
    LABEL_DEFINITION,
    TRAINING_SCHEMA_VERSION,
    build_pending_sample,
    finalize_next_bar_sample,
    is_eligible_training_record,
    purge_boundary_sample,
    purge_overlapping_targets,
    sanitize_training_features,
    training_schema_is_safe,
)


class LeakageSafeTrainingDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.features = {
            "rsi": 51.5,
            "ema_9": 2020.25,
            "close": 2021.0,
            "open": 2020.0,
            "volume": 100,
            "next_return": 0.02,
            "target_label": 1,
            "bar_timestamp": "2026-10-28T10:00:00+00:00",
            "trend_direction": "UP",
            "nan_feature": float("nan"),
        }

    def test_raw_prices_targets_and_nonfinite_values_are_excluded(self) -> None:
        safe = sanitize_training_features(self.features)
        self.assertEqual(safe, {"rsi": 51.5, "ema_9": 2020.25})

    def test_target_uses_next_adjacent_bar_and_never_keeps_close_in_x(self) -> None:
        pending = build_pending_sample(
            self.features,
            "2026-10-28T10:00:00+00:00",
            2021.0,
        )
        self.assertIsNotNone(pending)
        record = finalize_next_bar_sample(
            pending,
            "2026-10-28T10:05:00+00:00",
            2022.0,
            "M5",
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["label"], 1)
        self.assertEqual(record["label_definition"], LABEL_DEFINITION)
        self.assertEqual(record["schema_version"], TRAINING_SCHEMA_VERSION)
        self.assertEqual(record["features"], {"rsi": 51.5, "ema_9": 2020.25})
        self.assertLess(record["timestamp"], record["target_timestamp"])

    def test_down_label_is_created_from_future_close(self) -> None:
        pending = build_pending_sample(self.features, "2026-10-28T10:00:00+00:00", 2021.0)
        record = finalize_next_bar_sample(
            pending, "2026-10-28T10:05:00+00:00", 2020.0, "M5",
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["label"], 0)

    def test_non_adjacent_or_flat_next_observation_is_not_labeled(self) -> None:
        pending = build_pending_sample(self.features, "2026-10-28T10:00:00+00:00", 2021.0)
        self.assertIsNone(finalize_next_bar_sample(
            pending, "2026-10-28T10:10:00+00:00", 2022.0, "M5",
        ))
        self.assertIsNone(finalize_next_bar_sample(
            pending, "2026-10-28T10:05:00+00:00", 2021.0, "M5",
        ))

    def test_legacy_same_bar_record_is_ineligible(self) -> None:
        legacy = {
            "features": {"close": 2021.0, "rsi": 50.0},
            "label": 0,
            "timestamp": "2026-10-28T10:00:00+00:00",
        }
        self.assertFalse(is_eligible_training_record(legacy))

    def test_only_versioned_forward_target_record_is_eligible(self) -> None:
        pending = build_pending_sample(self.features, "2026-10-28T10:00:00+00:00", 2021.0)
        record = finalize_next_bar_sample(
            pending, "2026-10-28T10:05:00+00:00", 2022.0, "M5",
        )
        self.assertTrue(is_eligible_training_record(record))
        tampered = dict(record or {})
        tampered["features"] = {"rsi": 50.0, "future_return": 0.1}
        self.assertFalse(is_eligible_training_record(tampered))

    def test_schema_receipt_requires_v2_and_safe_feature_names(self) -> None:
        safe_schema = {
            "schema_version": TRAINING_SCHEMA_VERSION,
            "label_definition": LABEL_DEFINITION,
            "feature_names": ["rsi", "ema_9"],
            "trained_models": ["xgboost"],
        }
        self.assertTrue(training_schema_is_safe(safe_schema))
        unsafe_schema = dict(safe_schema, feature_names=["close"])
        self.assertFalse(training_schema_is_safe(unsafe_schema))
        self.assertFalse(training_schema_is_safe(None))

    def test_calendar_training_rows_require_point_in_time_revision_receipt(self) -> None:
        ts = "2026-10-28T10:00:00+00:00"
        features = {"rsi": 50.0, "cal_high_last90": 1.0}
        pending = build_pending_sample(features, ts, 100.0)
        record = finalize_next_bar_sample(pending, "2026-10-28T10:05:00+00:00", 101.0, "M5")
        self.assertFalse(is_eligible_training_record(record))

        features["_calendar_provenance"] = {
            "decision_time": ts,
            "availability_policy": "available_at<=decision_time; latest_revision_per_event",
            "event_revisions": [{
                "event_id": "evt", "revision_id": "rev1", "available_at": ts,
            }],
        }
        pending = build_pending_sample(features, ts, 100.0)
        record = finalize_next_bar_sample(pending, "2026-10-28T10:05:00+00:00", 101.0, "M5")
        self.assertTrue(is_eligible_training_record(record))

        assert record is not None
        record["feature_provenance"]["event_revisions"][0]["available_at"] = "2026-10-28T10:01:00+00:00"
        self.assertFalse(is_eligible_training_record(record))

    def test_external_news_macro_and_cross_asset_features_require_point_in_time_vintages(self) -> None:
        ts = "2026-10-28T10:00:00+00:00"
        next_ts = "2026-10-28T10:05:00+00:00"
        cases = [
            ("news_sentiment", "news"),
            ("economic_surprise", "macro"),
            ("dxy_change_5d", "cross_asset"),
            ("social_sentiment", "sentiment"),
        ]
        for feature_name, source in cases:
            with self.subTest(feature=feature_name):
                features = {"rsi": 50.0, feature_name: 0.25}
                pending = build_pending_sample(features, ts, 100.0)
                record = finalize_next_bar_sample(pending, next_ts, 101.0, "M5")
                self.assertFalse(is_eligible_training_record(record))

                receipt = {
                    "decision_time": ts,
                    "availability_policy": "available_at<=decision_time; latest_revision_per_event",
                    "revisions": [{
                        "source_id": "provider:event-1",
                        "revision_id": "revision-1",
                        "available_at": ts,
                    }],
                }
                pending = build_pending_sample(features, ts, 100.0, provenance={source: receipt})
                record = finalize_next_bar_sample(pending, next_ts, 101.0, "M5")
                self.assertTrue(is_eligible_training_record(record))

                receipt["revisions"][0]["available_at"] = "2026-10-28T10:01:00+00:00"
                pending = build_pending_sample(features, ts, 100.0, provenance={source: receipt})
                record = finalize_next_bar_sample(pending, next_ts, 101.0, "M5")
                self.assertFalse(is_eligible_training_record(record))

    def test_external_feature_receipt_rejects_missing_revision_identity(self) -> None:
        ts = "2026-10-28T10:00:00+00:00"
        receipt = {
            "news": {
                "decision_time": ts,
                "availability_policy": "available_at<=decision_time; latest_revision_per_event",
                "revisions": [{"available_at": ts, "revision_id": "rev1"}],
            },
        }
        pending = build_pending_sample(
            {"news_impact_score": 0.8}, ts, 100.0, provenance=receipt,
        )
        record = finalize_next_bar_sample(pending, "2026-10-28T10:05:00+00:00", 101.0, "M5")
        self.assertFalse(is_eligible_training_record(record))

    def test_purge_removes_only_last_training_sample(self) -> None:
        import numpy as np

        mask = np.array([True, True, True, False, False])
        self.assertEqual(
            purge_boundary_sample(mask).tolist(),
            [True, True, False, False, False],
        )
        self.assertEqual(
            purge_boundary_sample(np.array([2, 3, 4])).tolist(),
            [2, 3],
        )

    def test_purge_uses_target_horizon_not_assumed_one_bar(self) -> None:
        import numpy as np

        samples = np.array([0, 5, 10, 15, 20, 25], dtype="datetime64[m]")
        targets = np.array([20, 20, 20, 20, 25, 30], dtype="datetime64[m]")
        train = np.array([True, True, True, True, False, False])
        val = np.array([False, False, False, False, True, True])
        kept = purge_overlapping_targets(train, val, samples, targets)
        # Validation begins at minute 20; any training label resolving at or
        # after that time overlaps the evaluation information set.
        self.assertEqual(kept.tolist(), [False, False, False, False, False, False])

    def test_purge_supports_an_explicit_embargo_gap(self) -> None:
        import numpy as np

        samples = np.array([0, 5, 10, 15, 20], dtype="datetime64[m]")
        targets = np.array([5, 10, 15, 20, 25], dtype="datetime64[m]")
        train = np.array([True, True, True, False, False])
        val = np.array([False, False, False, True, True])
        kept = purge_overlapping_targets(
            train, val, samples, targets, gap=np.timedelta64(5, "m"),
        )
        self.assertEqual(kept.tolist(), [True, False, False, False, False])


if __name__ == "__main__":
    unittest.main()
