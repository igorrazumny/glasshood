# File: tests/test_customer_routing.py
# Purpose: Tests for per-customer BQ dataset and GCS bucket routing

import unittest
from unittest.mock import patch

from src.storage.customer_routing import (
    _sanitize_customer_id, get_dataset_for_customer,
    get_table_ref_for_customer, get_bucket_for_customer,
    group_events_by_customer,
)


class TestSanitizeCustomerId(unittest.TestCase):

    def test_hyphens_replaced_with_underscores(self):
        self.assertEqual(_sanitize_customer_id("acme-pharma"), "acme_pharma")

    def test_no_hyphens_unchanged(self):
        self.assertEqual(_sanitize_customer_id("acme"), "acme")

    def test_multiple_hyphens(self):
        self.assertEqual(_sanitize_customer_id("a-b-c"), "a_b_c")


class TestGetDatasetForCustomer(unittest.TestCase):

    @patch("src.storage.customer_routing.STORAGE_BQ_DATASET", "glasshood_shared")
    def test_empty_customer_returns_shared(self):
        self.assertEqual(get_dataset_for_customer(""), "glasshood_shared")

    def test_customer_id_returns_prefixed(self):
        self.assertEqual(get_dataset_for_customer("acme-pharma"), "glasshood_acme_pharma")

    def test_customer_id_no_hyphens(self):
        self.assertEqual(get_dataset_for_customer("roche"), "glasshood_roche")


class TestGetTableRefForCustomer(unittest.TestCase):

    @patch("src.storage.customer_routing.STORAGE_BQ_TABLE", "events")
    @patch("src.storage.customer_routing.STORAGE_BQ_PROJECT", "my-project")
    def test_customer_table_ref(self):
        ref = get_table_ref_for_customer("acme-pharma")
        self.assertEqual(ref, "my-project.glasshood_acme_pharma.events")

    @patch("src.storage.customer_routing.STORAGE_BQ_TABLE", "events")
    @patch("src.storage.customer_routing.STORAGE_BQ_PROJECT", "my-project")
    @patch("src.storage.customer_routing.STORAGE_BQ_DATASET", "glasshood_shared")
    def test_empty_customer_uses_shared(self):
        ref = get_table_ref_for_customer("")
        self.assertEqual(ref, "my-project.glasshood_shared.events")


class TestGetBucketForCustomer(unittest.TestCase):

    @patch("src.storage.customer_routing.RETENTION_ARCHIVE_BUCKET", "glasshood-archive-shared")
    def test_empty_customer_returns_shared(self):
        self.assertEqual(get_bucket_for_customer(""), "glasshood-archive-shared")

    def test_customer_bucket(self):
        self.assertEqual(get_bucket_for_customer("acme-pharma"), "glasshood-archive-acme-pharma")


class TestGroupEventsByCustomer(unittest.TestCase):

    def test_groups_by_customer_id(self):
        rows = [
            {"event_id": "1", "customer_id": "acme"},
            {"event_id": "2", "customer_id": "roche"},
            {"event_id": "3", "customer_id": "acme"},
        ]
        groups = group_events_by_customer(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups["acme"]), 2)
        self.assertEqual(len(groups["roche"]), 1)

    def test_empty_customer_id_grouped_under_empty_string(self):
        rows = [
            {"event_id": "1", "customer_id": ""},
            {"event_id": "2"},
        ]
        groups = group_events_by_customer(rows)
        self.assertEqual(len(groups), 1)
        self.assertIn("", groups)
        self.assertEqual(len(groups[""]), 2)

    def test_empty_rows(self):
        groups = group_events_by_customer([])
        self.assertEqual(groups, {})

    def test_mixed_with_and_without_customer(self):
        rows = [
            {"event_id": "1", "customer_id": "acme"},
            {"event_id": "2"},
            {"event_id": "3", "customer_id": "acme"},
        ]
        groups = group_events_by_customer(rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups["acme"]), 2)
        self.assertEqual(len(groups[""]), 1)
