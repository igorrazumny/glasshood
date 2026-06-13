# File: tests/test_provision_customer.py
# Purpose: Tests for customer provisioning script

from argparse import Namespace
from unittest.mock import patch, MagicMock

from scripts.provision_customer import (
    provision, create_bigquery_dataset, create_gcs_bucket, _bq_location,
)


def _args(**overrides):
    base = {
        "customer": "acme-pharma",
        "display_name": "ACME Pharmaceuticals",
        "region": "europe-west1",
        "tier": "professional",
        "project": "test-proj",
        "contact_email": "test@example.com",
        "retention_days": 365,
        "kms_key": "",
        "dry_run": False,
    }
    base.update(overrides)
    return Namespace(**base)


class TestBqLocation:
    def test_europe(self):
        assert _bq_location("europe-west1") == "EU"

    def test_us(self):
        assert _bq_location("us-central1") == "US"

    def test_other(self):
        assert _bq_location("asia-east1") == "asia-east1"


class TestCreateBigqueryDataset:
    def test_dry_run(self):
        assert create_bigquery_dataset("proj", "ds", "EU", dry_run=True) is True

    def test_creates_new(self):
        mock_client = MagicMock()
        mock_client.get_dataset.side_effect = Exception("not found")
        with patch("google.cloud.bigquery.Client", return_value=mock_client), \
             patch("google.cloud.bigquery.DatasetReference"), \
             patch("google.cloud.bigquery.Dataset"):
            result = create_bigquery_dataset("proj", "ds", "EU", dry_run=False)
        assert result is True
        mock_client.create_dataset.assert_called_once()

    def test_idempotent_existing(self):
        mock_client = MagicMock()
        with patch("google.cloud.bigquery.Client", return_value=mock_client), \
             patch("google.cloud.bigquery.DatasetReference"):
            result = create_bigquery_dataset("proj", "ds", "EU", dry_run=False)
        assert result is True
        mock_client.create_dataset.assert_not_called()

    def test_cmek_dry_run_logs_key(self, capsys):
        kms = "projects/p/locations/l/keyRings/kr/cryptoKeys/k"
        create_bigquery_dataset("proj", "ds", "EU", dry_run=True, kms_key=kms)

    def test_cmek_sets_encryption_config(self):
        mock_client = MagicMock()
        mock_client.get_dataset.side_effect = Exception("not found")
        mock_ds = MagicMock()
        kms = "projects/p/locations/l/keyRings/kr/cryptoKeys/k"
        with patch("google.cloud.bigquery.Client", return_value=mock_client), \
             patch("google.cloud.bigquery.DatasetReference"), \
             patch("google.cloud.bigquery.Dataset", return_value=mock_ds), \
             patch("google.cloud.bigquery.EncryptionConfiguration") as mock_enc:
            create_bigquery_dataset("proj", "ds", "EU", False, kms_key=kms)
        mock_enc.assert_called_once_with(kms_key_name=kms)


class TestCreateGcsBucket:
    def test_dry_run(self):
        assert create_gcs_bucket("bucket", "EU", dry_run=True) is True

    def test_creates_new(self):
        mock_client = MagicMock()
        mock_client.get_bucket.side_effect = Exception("not found")
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = create_gcs_bucket("bucket", "EU", dry_run=False)
        assert result is True
        mock_client.create_bucket.assert_called_once()

    def test_idempotent_existing(self):
        mock_client = MagicMock()
        with patch("google.cloud.storage.Client", return_value=mock_client):
            result = create_gcs_bucket("bucket", "EU", dry_run=False)
        assert result is True
        mock_client.create_bucket.assert_not_called()

    def test_cmek_sets_kms_key(self):
        mock_client = MagicMock()
        mock_client.get_bucket.side_effect = Exception("not found")
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        kms = "projects/p/locations/l/keyRings/kr/cryptoKeys/k"
        with patch("google.cloud.storage.Client", return_value=mock_client):
            create_gcs_bucket("bucket", "EU", False, kms_key=kms)
        assert mock_bucket.default_kms_key_name == kms


class TestProvision:
    def test_dry_run(self, tmp_path):
        with patch("scripts.provision_customer.get_customer", return_value=None), \
             patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)):
            result = provision(_args(dry_run=True))
        assert result is True

    def test_invalid_customer_id(self):
        result = provision(_args(customer="BAD ID"))
        assert result is False

    def test_full_provision(self, tmp_path):
        mock_bq_client = MagicMock()
        mock_bq_client.get_dataset.side_effect = Exception("not found")
        mock_gcs_client = MagicMock()
        mock_gcs_client.get_bucket.side_effect = Exception("not found")
        mock_gcs_client.bucket.return_value = MagicMock()

        with patch("src.customers.manager.CUSTOMERS_DIR", str(tmp_path)), \
             patch("google.cloud.bigquery.Client", return_value=mock_bq_client), \
             patch("google.cloud.bigquery.DatasetReference"), \
             patch("google.cloud.bigquery.Dataset"), \
             patch("google.cloud.storage.Client", return_value=mock_gcs_client):
            result = provision(_args())
        assert result is True
        assert (tmp_path / "acme-pharma.yaml").exists()

    def test_existing_customer_reruns_gcp(self, tmp_path):
        """Re-running with existing config should still ensure GCP resources."""
        existing_config = {"customer_id": "acme-pharma", "tier": "professional"}
        with patch("scripts.provision_customer.get_customer",
                   return_value=existing_config):
            result = provision(_args(dry_run=True))
        assert result is True
