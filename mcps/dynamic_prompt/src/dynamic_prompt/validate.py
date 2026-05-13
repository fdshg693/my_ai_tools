"""
instructions.yaml の variables 宣言と、user_config.yaml / languages/*.yaml の
キーの整合性をチェックするバリデーションスクリプト。

Usage:
    uv run mcps/dynamic_prompt/src/dynamic_prompt/validate.py
"""

import re
import sys
from dataclasses import fields as dc_fields

import yaml

from dynamic_prompt.config import INSTRUCTIONS_PATH, LANGUAGES_DIR
from dynamic_prompt.models import Language, UserConfig

# コード内で動的に生成される変数（user_config.yaml にも languages/*.yaml にもないもの）
COMPUTED_USER_CONFIG_VARS = {"available_learning_languages"}


def _extract_template_vars(template: str) -> set[str]:
    """テンプレート文字列から {var_name} 形式の変数名を抽出する。"""
    return set(re.findall(r"\{(\w+)\}", template))


def validate() -> list[str]:
    errors: list[str] = []

    # --- ソースから利用可能なキーを収集 ---
    user_config_keys = {f.name for f in dc_fields(UserConfig)} | COMPUTED_USER_CONFIG_VARS

    language_keys = {f.name for f in dc_fields(Language)} - {"code", "aliases"}

    # --- instructions.yaml を読み込み ---
    instructions = yaml.safe_load(INSTRUCTIONS_PATH.read_text(encoding="utf-8"))

    # --- 各言語 YAML のキーもチェック ---
    for f in sorted(LANGUAGES_DIR.glob("*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        file_keys = set(data.keys()) - {"code", "aliases"}
        missing = language_keys - file_keys
        if missing:
            errors.append(f"languages/{f.name}: Language フィールド不足: {missing}")

    # --- テンプレートごとのチェック ---
    for name, entry in instructions.items():
        variables: dict[str, list[str]] = entry.get("variables", {})
        template: str = entry.get("template", "")

        declared_user_config = set(variables.get("user_config", []))
        declared_language = set(variables.get("language", []))
        declared_all = declared_user_config | declared_language

        used = _extract_template_vars(template)

        # 1. 宣言された user_config 変数が user_config.yaml + computed に存在するか
        unknown_user_config = declared_user_config - user_config_keys
        if unknown_user_config:
            errors.append(
                f"[{name}] variables.user_config に未知の変数: {unknown_user_config} "
                f"(利用可能: {user_config_keys})"
            )

        # 2. 宣言された language 変数が Language フィールドに存在するか
        unknown_lang = declared_language - language_keys
        if unknown_lang:
            errors.append(
                f"[{name}] variables.language に未知の変数: {unknown_lang} "
                f"(利用可能: {language_keys})"
            )

        # 3. テンプレートで使われているのに宣言されていない変数
        undeclared = used - declared_all
        if undeclared:
            errors.append(
                f"[{name}] テンプレートで使用されているが variables に未宣言: {undeclared}"
            )

        # 4. 宣言されているのにテンプレートで使われていない変数
        unused = declared_all - used
        if unused:
            errors.append(
                f"[{name}] variables に宣言されているがテンプレートで未使用: {unused}"
            )

    return errors


def main() -> None:
    errors = validate()
    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("OK: すべてのチェックに合格しました。")


if __name__ == "__main__":
    main()
