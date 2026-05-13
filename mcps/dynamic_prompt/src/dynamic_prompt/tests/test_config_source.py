"""ConfigSource と TTL キャッシュの単体テスト。"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dynamic_prompt.config import ConfigStore
from dynamic_prompt.config_source import (
    GCSConfigSource,
    LocalConfigSource,
    make_config_source,
)


# ---------------------------------------------------------------------------
# Helpers — minimal valid YAML tree
# ---------------------------------------------------------------------------


def _write_prompts_tree(root: Path, *, native_language: str = "ja", vocab_limit: int = 5) -> None:
    (root / "languages").mkdir(parents=True, exist_ok=True)
    (root / "user_config.yaml").write_text(
        textwrap.dedent(
            f"""
            native_language: {native_language}
            memory_test_period_hours: 24
            """
        ).strip(),
        encoding="utf-8",
    )
    (root / "app_config.yaml").write_text(
        textwrap.dedent(
            f"""
            vocab_get_limit: {vocab_limit}
            quiz_server_port: 8765
            quiz_server_port_pool_size: 3
            """
        ).strip(),
        encoding="utf-8",
    )
    (root / "instructions.yaml").write_text(
        textwrap.dedent(
            """
            greet:
              description: greeting
              requires_language: false
              variables: {}
              template: |
                hello
            """
        ).strip(),
        encoding="utf-8",
    )
    (root / "languages" / "_default.yaml").write_text(
        textwrap.dedent(
            """
            code: _default
            label: Default
            user_level: ""
            teaching_guide: ""
            """
        ).strip(),
        encoding="utf-8",
    )
    (root / "languages" / "en.yaml").write_text(
        textwrap.dedent(
            """
            code: en
            label: English
            aliases: [English, 英語]
            user_level: intermediate
            teaching_guide: speak clearly
            """
        ).strip(),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


class TestMakeConfigSource:
    def test_empty_returns_default_local(self):
        src = make_config_source("")
        assert isinstance(src, LocalConfigSource)

    def test_none_uses_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("PROMPTS_URI", str(tmp_path))
        src = make_config_source()
        assert isinstance(src, LocalConfigSource)
        assert src.base_dir == tmp_path

    def test_gcs_uri(self):
        src = make_config_source("gs://my-bucket/prompts/")
        assert isinstance(src, GCSConfigSource)
        assert src.bucket_name == "my-bucket"
        assert src.prefix == "prompts"

    def test_gcs_uri_no_prefix(self):
        src = make_config_source("gs://my-bucket")
        assert isinstance(src, GCSConfigSource)
        assert src.bucket_name == "my-bucket"
        assert src.prefix == ""

    def test_gcs_uri_missing_bucket_raises(self):
        with pytest.raises(ValueError):
            make_config_source("gs:///no-bucket")


# ---------------------------------------------------------------------------
# LocalConfigSource
# ---------------------------------------------------------------------------


class TestLocalConfigSource:
    def test_read_text(self, tmp_path: Path):
        _write_prompts_tree(tmp_path)
        src = LocalConfigSource(tmp_path)
        text = src.read_text("user_config.yaml")
        assert "native_language: ja" in text

    def test_list_yaml(self, tmp_path: Path):
        _write_prompts_tree(tmp_path)
        src = LocalConfigSource(tmp_path)
        files = src.list_yaml("languages")
        assert files == ["languages/_default.yaml", "languages/en.yaml"]


# ---------------------------------------------------------------------------
# GCSConfigSource (mocked)
# ---------------------------------------------------------------------------


class TestGCSConfigSource:
    def test_read_text_invokes_blob_download(self):
        src = GCSConfigSource(bucket="my-bucket", prefix="prompts")
        mock_blob = MagicMock()
        mock_blob.download_as_text.return_value = "native_language: ja"
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        src._bucket = mock_bucket  # bypass auth

        result = src.read_text("user_config.yaml")
        assert result == "native_language: ja"
        mock_bucket.blob.assert_called_once_with("prompts/user_config.yaml")

    def test_list_yaml_filters_and_strips_prefix(self):
        src = GCSConfigSource(bucket="my-bucket", prefix="prompts")
        b1 = MagicMock(name="prompts/languages/en.yaml")
        b1.name = "prompts/languages/en.yaml"
        b2 = MagicMock(name="prompts/languages/_default.yaml")
        b2.name = "prompts/languages/_default.yaml"
        b3 = MagicMock(name="prompts/languages/README.md")
        b3.name = "prompts/languages/README.md"
        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = [b1, b2, b3]
        src._bucket = mock_bucket

        result = src.list_yaml("languages")
        assert result == ["languages/_default.yaml", "languages/en.yaml"]
        mock_bucket.list_blobs.assert_called_once_with(prefix="prompts/languages/")

    def test_key_without_prefix(self):
        src = GCSConfigSource(bucket="my-bucket", prefix="")
        assert src._key("user_config.yaml") == "user_config.yaml"


# ---------------------------------------------------------------------------
# ConfigStore + TTL
# ---------------------------------------------------------------------------


class TestConfigStoreFromLocalSource:
    def test_loads_from_temp_local_source(self, tmp_path: Path):
        _write_prompts_tree(tmp_path, native_language="ko", vocab_limit=7)
        store = ConfigStore(source=LocalConfigSource(tmp_path), ttl_seconds=0)
        assert store.user_config.native_language == "ko"
        assert store.app_config.vocab_get_limit == 7
        assert "en" in store.languages

    def test_reload_picks_up_yaml_changes(self, tmp_path: Path):
        _write_prompts_tree(tmp_path, native_language="ja")
        store = ConfigStore(source=LocalConfigSource(tmp_path), ttl_seconds=0)
        assert store.user_config.native_language == "ja"

        _write_prompts_tree(tmp_path, native_language="ko")
        # TTL=0 → 自動 refresh しないので、明示 reload するまで変わらない
        assert store.user_config.native_language == "ja"

        store.reload()
        assert store.user_config.native_language == "ko"


class TestConfigStoreTTL:
    def test_ttl_zero_disables_auto_refresh(self, tmp_path: Path):
        _write_prompts_tree(tmp_path, native_language="ja")
        store = ConfigStore(source=LocalConfigSource(tmp_path), ttl_seconds=0)

        _write_prompts_tree(tmp_path, native_language="ko")
        # どれだけアクセスしても自動再読み込みされない
        for _ in range(3):
            assert store.user_config.native_language == "ja"

    def test_ttl_expiry_triggers_refresh(self, tmp_path: Path):
        _write_prompts_tree(tmp_path, native_language="ja")
        store = ConfigStore(source=LocalConfigSource(tmp_path), ttl_seconds=10)
        assert store.user_config.native_language == "ja"

        _write_prompts_tree(tmp_path, native_language="ko")
        # TTL を擬似的に切らす
        store._last_loaded -= 100
        assert store.user_config.native_language == "ko"

    def test_refresh_failure_keeps_stale_cache(self, tmp_path: Path):
        _write_prompts_tree(tmp_path, native_language="ja")
        store = ConfigStore(source=LocalConfigSource(tmp_path), ttl_seconds=10)

        # ソースを壊す: read_text を raise させる
        broken = MagicMock(wraps=store._source)
        broken.read_text.side_effect = RuntimeError("boom")
        store._source = broken
        store._last_loaded -= 100  # TTL 切れにする

        # 古いキャッシュにフォールバックするはず
        assert store.user_config.native_language == "ja"
        # バックオフ: すぐ再 load しない (last_loaded が現在時刻にリセットされる)
        broken.read_text.reset_mock()
        _ = store.user_config
        broken.read_text.assert_not_called()


class TestConfigStoreUpdateAndRefresh:
    def test_update_value_is_overwritten_by_refresh(self, tmp_path: Path):
        _write_prompts_tree(tmp_path, vocab_limit=5)
        store = ConfigStore(source=LocalConfigSource(tmp_path), ttl_seconds=10)
        store.update_app_config(vocab_get_limit=999)
        assert store.app_config.vocab_get_limit == 999

        # TTL 切れ → ファイルの値で上書き
        store._last_loaded -= 100
        assert store.app_config.vocab_get_limit == 5
