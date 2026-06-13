# File: tests/test_agent_file_tail.py
# Purpose: Tests for file tail collector

import queue

from agent.collectors.file_tail import FileTailCollector


class TestFileTailCollector:
    def test_tails_new_lines(self, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("line one\nline two\n")

        q = queue.Queue()
        ft = FileTailCollector([str(log_file)], q, buffer_dir=str(tmp_path))
        events = ft._tail_file(str(log_file))
        assert len(events) == 2
        assert events[0]["message"] == "line one"
        assert events[1]["message"] == "line two"
        assert events[0]["source_type"] == "file"
        assert events[0]["source_id"] == "test.log"

    def test_tracks_offset(self, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("first\n")

        q = queue.Queue()
        ft = FileTailCollector([str(log_file)], q, buffer_dir=str(tmp_path))

        # First read
        events1 = ft._tail_file(str(log_file))
        assert len(events1) == 1

        # No new data
        events2 = ft._tail_file(str(log_file))
        assert len(events2) == 0

        # Append new line
        with open(log_file, "a") as f:
            f.write("second\n")
        events3 = ft._tail_file(str(log_file))
        assert len(events3) == 1
        assert events3[0]["message"] == "second"

    def test_handles_file_rotation(self, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("old line 1\nold line 2\nold line 3\n")

        q = queue.Queue()
        ft = FileTailCollector([str(log_file)], q, buffer_dir=str(tmp_path))
        ft._tail_file(str(log_file))  # read all 3 lines

        # Simulate rotation: file is truncated and new content written
        log_file.write_text("new line 1\n")
        events = ft._tail_file(str(log_file))
        assert len(events) == 1
        assert events[0]["message"] == "new line 1"

    def test_skips_missing_file(self, tmp_path):
        q = queue.Queue()
        ft = FileTailCollector(["/nonexistent/file.log"], q, buffer_dir=str(tmp_path))
        events = ft._tail_file("/nonexistent/file.log")
        assert events == []

    def test_skips_blank_lines(self, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("content\n\n  \nanother\n")

        q = queue.Queue()
        ft = FileTailCollector([str(log_file)], q, buffer_dir=str(tmp_path))
        events = ft._tail_file(str(log_file))
        assert len(events) == 2

    def test_tags_include_path(self, tmp_path):
        log_file = tmp_path / "app.log"
        log_file.write_text("hello\n")

        q = queue.Queue()
        ft = FileTailCollector([str(log_file)], q, buffer_dir=str(tmp_path))
        events = ft._tail_file(str(log_file))
        assert events[0]["tags"]["path"] == str(log_file)

    def test_offset_persists_to_disk(self, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("data\n")

        q = queue.Queue()
        ft = FileTailCollector([str(log_file)], q, buffer_dir=str(tmp_path))
        ft._tail_file(str(log_file))

        # Check offset file exists
        offset_files = list(tmp_path.glob("*.offset"))
        assert len(offset_files) == 1
        assert int(offset_files[0].read_text()) > 0


class TestFileTailConfig:
    def test_loads_yaml_config(self, tmp_path):
        from agent.config import load_config
        config_file = tmp_path / "agent.yaml"
        config_file.write_text("""
agent_id: test-agent
backend_url: http://localhost:9090
collectors:
  - type: file_tail
    paths:
      - /var/log/test.log
""")
        config = load_config(str(config_file))
        assert config.agent_id == "test-agent"
        assert config.backend_url == "http://localhost:9090"
        assert len(config.collectors) == 1
        assert config.collectors[0]["type"] == "file_tail"

    def test_missing_config_uses_defaults(self, tmp_path):
        from agent.config import load_config
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        assert config.agent_id == "agent-default"
        assert config.collectors == []
