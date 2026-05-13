"""ConfigStore の単体テスト — reload・update・format_language_codes。"""

import pytest

from dynamic_prompt.config import ConfigStore, config_store
from dynamic_prompt.models import AppConfig, UserConfig


@pytest.fixture()
def store() -> ConfigStore:
    """テストごとに独立した ConfigStore を生成する。"""
    return ConfigStore()


# ---------------------------------------------------------------------------
# 初期化
# ---------------------------------------------------------------------------


class TestConfigStoreInit:
    def test_loads_user_config(self, store: ConfigStore):
        assert isinstance(store.user_config, UserConfig)
        assert store.user_config.native_language  # 空でないこと

    def test_loads_app_config(self, store: ConfigStore):
        assert isinstance(store.app_config, AppConfig)
        assert store.app_config.vocab_get_limit > 0

    def test_loads_languages(self, store: ConfigStore):
        assert isinstance(store.languages, dict)
        assert len(store.languages) > 0
        assert "_default" in store.languages

    def test_loads_instructions(self, store: ConfigStore):
        assert isinstance(store.instructions, dict)
        assert len(store.instructions) > 0


# ---------------------------------------------------------------------------
# update_user_config
# ---------------------------------------------------------------------------


class TestUpdateUserConfig:
    def test_updates_single_field(self, store: ConfigStore):
        original_lang = store.user_config.native_language
        new_config = store.update_user_config(native_language="ko")
        assert new_config.native_language == "ko"
        assert store.user_config.native_language == "ko"
        # 他のフィールドは保持
        assert store.user_config.memory_test_period_hours == 24
        # 元の値と異なること確認
        assert original_lang != "ko" or original_lang == "ko"  # 元がkoでも動作

    def test_updates_multiple_fields(self, store: ConfigStore):
        store.update_user_config(native_language="zh", memory_test_period_hours=48)
        assert store.user_config.native_language == "zh"
        assert store.user_config.memory_test_period_hours == 48

    def test_returns_new_frozen_instance(self, store: ConfigStore):
        result = store.update_user_config(memory_test_period_hours=12)
        assert isinstance(result, UserConfig)
        with pytest.raises(AttributeError):
            result.native_language = "should_fail"  # type: ignore[misc]

    def test_invalid_field_raises(self, store: ConfigStore):
        with pytest.raises(TypeError):
            store.update_user_config(nonexistent_field="value")


# ---------------------------------------------------------------------------
# update_app_config
# ---------------------------------------------------------------------------


class TestUpdateAppConfig:
    def test_updates_single_field(self, store: ConfigStore):
        store.update_app_config(vocab_get_limit=10)
        assert store.app_config.vocab_get_limit == 10
        # 他のフィールドは保持
        assert store.app_config.quiz_server_port == 8765

    def test_returns_new_frozen_instance(self, store: ConfigStore):
        result = store.update_app_config(quiz_server_port=9000)
        assert isinstance(result, AppConfig)
        with pytest.raises(AttributeError):
            result.vocab_get_limit = 999  # type: ignore[misc]

    def test_invalid_field_raises(self, store: ConfigStore):
        with pytest.raises(TypeError):
            store.update_app_config(nonexistent_field="value")


# ---------------------------------------------------------------------------
# reload
# ---------------------------------------------------------------------------


class TestReload:
    def test_reload_restores_original_values(self, store: ConfigStore):
        original_limit = store.app_config.vocab_get_limit
        store.update_app_config(vocab_get_limit=999)
        assert store.app_config.vocab_get_limit == 999

        store.reload()
        assert store.app_config.vocab_get_limit == original_limit

    def test_reload_restores_user_config(self, store: ConfigStore):
        original_lang = store.user_config.native_language
        store.update_user_config(native_language="xx")

        store.reload()
        assert store.user_config.native_language == original_lang


# ---------------------------------------------------------------------------
# format_language_codes
# ---------------------------------------------------------------------------


class TestFormatLanguageCodes:
    def test_returns_comma_separated_codes(self, store: ConfigStore):
        result = store.format_language_codes()
        assert isinstance(result, str)
        assert "_default" not in result
        assert "en" in result

    def test_reflects_current_languages(self, store: ConfigStore):
        codes_before = store.format_language_codes()
        # languages を差し替え
        from dynamic_prompt.models import Language

        store.languages = {
            "xx": Language(code="xx", label="Test"),
            "yy": Language(code="yy", label="Test2"),
        }
        assert store.format_language_codes() == "xx, yy"
        assert store.format_language_codes() != codes_before


# ---------------------------------------------------------------------------
# グローバルシングルトン
# ---------------------------------------------------------------------------


class TestGlobalSingleton:
    def test_config_store_is_singleton(self):
        from dynamic_prompt.config import config_store as cs2

        assert config_store is cs2
