"""YAML 設定の読み込みと ConfigStore。

dataclass は frozen=True のまま維持し、ConfigStore が mutable wrapper として
設定インスタンスの差し替え・リロードを担う。
"""

from dataclasses import asdict
from pathlib import Path

import yaml

from dynamic_prompt.models import AppConfig, Instruction, Language, UserConfig

PROMPTS_DIR = Path(__file__).parent / "prompts"
LANGUAGES_DIR = PROMPTS_DIR / "languages"
USER_CONFIG_PATH = PROMPTS_DIR / "user_config.yaml"
APP_CONFIG_PATH = PROMPTS_DIR / "app_config.yaml"
INSTRUCTIONS_PATH = PROMPTS_DIR / "instructions.yaml"


# ---------------------------------------------------------------------------
# YAML loaders
# ---------------------------------------------------------------------------


def _load_languages() -> dict[str, Language]:
    languages: dict[str, Language] = {}
    for f in sorted(LANGUAGES_DIR.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        lang = Language(
            code=data["code"],
            label=data["label"],
            aliases=data.get("aliases", []),
            user_level=data.get("user_level", "").strip(),
            teaching_guide=data.get("teaching_guide", "").strip(),
        )
        languages[lang.code] = lang
    return languages


def _load_user_config() -> UserConfig:
    data = yaml.safe_load(USER_CONFIG_PATH.read_text(encoding="utf-8"))
    return UserConfig(**data)


def _load_instructions() -> dict[str, Instruction]:
    data = yaml.safe_load(INSTRUCTIONS_PATH.read_text(encoding="utf-8"))
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


def _load_app_config() -> AppConfig:
    data = yaml.safe_load(APP_CONFIG_PATH.read_text(encoding="utf-8"))
    return AppConfig(**data)


# ---------------------------------------------------------------------------
# ConfigStore — mutable wrapper over frozen dataclasses
# ---------------------------------------------------------------------------


class ConfigStore:
    """設定の動的変更を可能にする mutable wrapper。

    各設定値は frozen dataclass のままだが、ConfigStore の属性を差し替えることで
    実行時の設定変更・ホットリロードに対応する。
    """

    def __init__(self) -> None:
        self.user_config: UserConfig = _load_user_config()
        self.app_config: AppConfig = _load_app_config()
        self.languages: dict[str, Language] = _load_languages()
        self.instructions: dict[str, Instruction] = _load_instructions()

    # --- reload ---------------------------------------------------------

    def reload(self) -> None:
        """YAML ファイルからすべての設定を再読み込みする。"""
        self.user_config = _load_user_config()
        self.app_config = _load_app_config()
        self.languages = _load_languages()
        self.instructions = _load_instructions()

    # --- update helpers -------------------------------------------------

    def update_user_config(self, **kwargs: object) -> UserConfig:
        """指定フィールドだけ変更した新しい UserConfig に差し替える。"""
        current = asdict(self.user_config)
        current.update(kwargs)
        self.user_config = UserConfig(**current)
        return self.user_config

    def update_app_config(self, **kwargs: object) -> AppConfig:
        """指定フィールドだけ変更した新しい AppConfig に差し替える。"""
        current = asdict(self.app_config)
        current.update(kwargs)
        self.app_config = AppConfig(**current)
        return self.app_config

    # --- utilities ------------------------------------------------------

    def format_language_codes(self) -> str:
        return ", ".join(k for k in self.languages if k != "_default")


config_store = ConfigStore()
