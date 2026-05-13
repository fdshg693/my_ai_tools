"""YAML 設定の読み込みと ConfigStore。

dataclass は frozen=True のまま維持し、ConfigStore が mutable wrapper として
設定インスタンスの差し替え・ホットリロードを担う。

設定の取得元は `config_source.ConfigSource` で抽象化されており、ローカル
ファイル / GCS バケットの両方に対応する。`PROMPTS_URI` 環境変数で切り替える。
TTL ベースのキャッシュ (`CONFIG_TTL_SECONDS`、既定 60 秒) により、外部
ストレージへの問い合わせ回数を抑える。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from dynamic_prompt.config_source import (
    DEFAULT_LOCAL_PROMPTS_DIR,
    ConfigSource,
    LocalConfigSource,
    make_config_source,
)
from dynamic_prompt.models import AppConfig, Instruction, Language, UserConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 後方互換: validate.py 等が import している定数
# ---------------------------------------------------------------------------

PROMPTS_DIR: Path = DEFAULT_LOCAL_PROMPTS_DIR
LANGUAGES_DIR: Path = PROMPTS_DIR / "languages"
USER_CONFIG_PATH: Path = PROMPTS_DIR / "user_config.yaml"
APP_CONFIG_PATH: Path = PROMPTS_DIR / "app_config.yaml"
INSTRUCTIONS_PATH: Path = PROMPTS_DIR / "instructions.yaml"


# ---------------------------------------------------------------------------
# YAML loaders（ConfigSource からテキストを取り、dataclass に変換）
# ---------------------------------------------------------------------------


def _load_languages(source: ConfigSource) -> dict[str, Language]:
    languages: dict[str, Language] = {}
    for path in source.list_yaml("languages"):
        data = yaml.safe_load(source.read_text(path))
        lang = Language(
            code=data["code"],
            label=data["label"],
            aliases=data.get("aliases", []),
            user_level=data.get("user_level", "").strip(),
            teaching_guide=data.get("teaching_guide", "").strip(),
        )
        languages[lang.code] = lang
    return languages


def _load_user_config(source: ConfigSource) -> UserConfig:
    data = yaml.safe_load(source.read_text("user_config.yaml"))
    return UserConfig(**data)


def _load_app_config(source: ConfigSource) -> AppConfig:
    data = yaml.safe_load(source.read_text("app_config.yaml"))
    return AppConfig(**data)


def _load_instructions(source: ConfigSource) -> dict[str, Instruction]:
    data = yaml.safe_load(source.read_text("instructions.yaml"))
    instructions: dict[str, Instruction] = {}
    for name, entry in data.items():
        instructions[name] = Instruction(
            name=name,
            description=entry["description"],
            template=entry["template"].strip(),
            requires_language=entry.get("requires_language", False),
            variables=entry.get("variables", {}),
        )
    return instructions


# ---------------------------------------------------------------------------
# ConfigStore — TTL キャッシュ付き mutable wrapper
# ---------------------------------------------------------------------------


def _default_ttl_seconds() -> float:
    """環境変数 `CONFIG_TTL_SECONDS` から TTL を取る。

    既定: 60 秒。0 以下なら自動 refresh を無効化（明示 reload() のみ）。
    """
    raw = os.environ.get("CONFIG_TTL_SECONDS")
    if raw is None or raw.strip() == "":
        return 60.0
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid CONFIG_TTL_SECONDS=%r, fallback to 60s", raw)
        return 60.0


class ConfigStore:
    """設定の動的変更とキャッシュを管理する mutable wrapper。

    - 値オブジェクト (UserConfig / AppConfig / Language / Instruction) は
      frozen dataclass のまま保つ
    - 属性アクセスごとに TTL を確認し、期限切れなら裏で再読み込みする
    - 再読み込み中の例外は古いキャッシュにフォールバック（GCS 一時障害でも
      サーバを停止させない）
    - `update_user_config` / `update_app_config` による上書き値は、次回の
      自動 refresh または `reload()` で破棄される
    """

    def __init__(
        self,
        source: ConfigSource | None = None,
        ttl_seconds: float | None = None,
    ) -> None:
        self._source: ConfigSource = source or make_config_source()
        self._ttl: float = (
            ttl_seconds if ttl_seconds is not None else _default_ttl_seconds()
        )
        self._lock = threading.RLock()
        self._cache: dict[str, Any] = {}
        self._last_loaded: float = 0.0
        self._load_now()

    # --- internal loaders ----------------------------------------------

    def _load_now(self) -> None:
        with self._lock:
            self._cache = {
                "user_config": _load_user_config(self._source),
                "app_config": _load_app_config(self._source),
                "languages": _load_languages(self._source),
                "instructions": _load_instructions(self._source),
            }
            self._last_loaded = time.monotonic()

    def _refresh_if_stale(self) -> None:
        if self._ttl <= 0:
            return
        if time.monotonic() - self._last_loaded <= self._ttl:
            return
        # TTL 切れ。失敗時は古いキャッシュを維持して次の TTL までバックオフ
        try:
            self._load_now()
        except Exception:  # noqa: BLE001
            logger.exception("Config refresh failed; keeping stale cache")
            self._last_loaded = time.monotonic()

    # --- public reload --------------------------------------------------

    def reload(self) -> None:
        """設定ソースから全設定を即時再読み込みする (TTL を無視)。"""
        self._load_now()

    @property
    def source(self) -> ConfigSource:
        return self._source

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    @property
    def last_loaded_at(self) -> float:
        return self._last_loaded

    # --- accessors (TTL チェック付き) -----------------------------------

    @property
    def user_config(self) -> UserConfig:
        self._refresh_if_stale()
        return self._cache["user_config"]

    @user_config.setter
    def user_config(self, value: UserConfig) -> None:
        with self._lock:
            self._cache["user_config"] = value

    @property
    def app_config(self) -> AppConfig:
        self._refresh_if_stale()
        return self._cache["app_config"]

    @app_config.setter
    def app_config(self, value: AppConfig) -> None:
        with self._lock:
            self._cache["app_config"] = value

    @property
    def languages(self) -> dict[str, Language]:
        self._refresh_if_stale()
        return self._cache["languages"]

    @languages.setter
    def languages(self, value: dict[str, Language]) -> None:
        with self._lock:
            self._cache["languages"] = value

    @property
    def instructions(self) -> dict[str, Instruction]:
        self._refresh_if_stale()
        return self._cache["instructions"]

    @instructions.setter
    def instructions(self, value: dict[str, Instruction]) -> None:
        with self._lock:
            self._cache["instructions"] = value

    # --- update helpers -------------------------------------------------

    def update_user_config(self, **kwargs: object) -> UserConfig:
        with self._lock:
            current = asdict(self.user_config)
            current.update(kwargs)
            self._cache["user_config"] = UserConfig(**current)
            return self._cache["user_config"]

    def update_app_config(self, **kwargs: object) -> AppConfig:
        with self._lock:
            current = asdict(self.app_config)
            current.update(kwargs)
            self._cache["app_config"] = AppConfig(**current)
            return self._cache["app_config"]

    # --- utilities ------------------------------------------------------

    def format_language_codes(self) -> str:
        return ", ".join(k for k in self.languages if k != "_default")


config_store = ConfigStore()


__all__ = [
    "PROMPTS_DIR",
    "LANGUAGES_DIR",
    "USER_CONFIG_PATH",
    "APP_CONFIG_PATH",
    "INSTRUCTIONS_PATH",
    "ConfigSource",
    "LocalConfigSource",
    "ConfigStore",
    "config_store",
]
