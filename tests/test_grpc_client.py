# File: tests/test_grpc_client.py
# Purpose: Tests for gRPC transport client (agent/grpc_transport.py)

import json
import unittest
from unittest.mock import patch, MagicMock

import grpc

from agent.grpc_transport import GrpcTransport, _serialize_request, _deserialize_response


class TestSerialization(unittest.TestCase):
    """JSON serialization for gRPC payloads."""

    def test_serialize_request(self):
        data = {"agent_id": "a1", "events": [{"msg": "hi"}]}
        raw = _serialize_request(data)
        self.assertIsInstance(raw, bytes)
        self.assertEqual(json.loads(raw), data)

    def test_deserialize_response(self):
        raw = b'{"accepted": 5}'
        result = _deserialize_response(raw)
        self.assertEqual(result["accepted"], 5)


class TestGrpcTransport(unittest.TestCase):
    """GrpcTransport client behavior."""

    def test_creates_insecure_channel(self):
        t = GrpcTransport("localhost:50051", api_key="key", use_tls=False)
        ch = t._get_channel()
        self.assertIsNotNone(ch)
        t.close()

    def test_metadata_includes_api_key(self):
        t = GrpcTransport("localhost:50051", api_key="test-key", use_tls=False)
        meta = t._metadata()
        self.assertIn(("x-api-key", "test-key"), meta)

    def test_metadata_empty_without_key(self):
        t = GrpcTransport("localhost:50051", api_key="", use_tls=False)
        self.assertEqual(t._metadata(), [])

    @patch.object(GrpcTransport, "_get_channel")
    def test_push_success(self, mock_channel):
        mock_method = MagicMock(return_value={"accepted": 3})
        mock_channel.return_value.unary_unary.return_value = mock_method
        t = GrpcTransport("localhost:50051", api_key="k", use_tls=False)
        ok, msg = t.push_events("agent-1", [{"msg": "e1"}])
        self.assertTrue(ok)
        self.assertIn("Accepted", msg)

    @patch.object(GrpcTransport, "_get_channel")
    def test_push_rpc_error(self, mock_channel):
        error = grpc.RpcError()
        error.code = lambda: grpc.StatusCode.UNAVAILABLE
        error.details = lambda: "server down"
        mock_method = MagicMock(side_effect=error)
        mock_channel.return_value.unary_unary.return_value = mock_method
        t = GrpcTransport("localhost:50051", api_key="k", use_tls=False)
        ok, msg = t.push_events("agent-1", [])
        self.assertFalse(ok)

    def test_close_without_channel(self):
        t = GrpcTransport("localhost:50051", api_key="k", use_tls=False)
        t.close()  # should not raise

    def test_close_with_channel(self):
        t = GrpcTransport("localhost:50051", api_key="k", use_tls=False)
        t._get_channel()
        t.close()
        self.assertIsNone(t._channel)
