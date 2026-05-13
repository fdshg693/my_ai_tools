"""テンプレート解決の単体テスト — 変数解決・レンダリング。"""

import pytest

from dynamic_prompt.config import config_store
from dynamic_prompt.models import Instruction, Language
from dynamic_prompt.session import session
from dynamic_prompt.tools import (
    _render_instruction,
    _resolve_language_vars,
    _resolve_user_config_vars,
)


@pytest.fixture(autouse=True)
def reset_session():
    """各テストの前後にセッションをリセットする。"""
    session._lang = None
    yield
    session._lang = None


@pytest.fixture(autouse=True)
def save_instructions():
    """各テストの前後に instructions を復元する。"""
    original = config_store.instructions
    yield
    config_store.instructions = original


# ---------------------------------------------------------------------------
# _resolve_user_config_vars
# ---------------------------------------------------------------------------


class TestResolveUserConfigVars:
    def test_contains_native_language(self):
        result = _resolve_user_config_vars()
        assert "native_language" in result
        assert isinstance(result["native_language"], str)

    def test_contains_memory_test_period(self):
        result = _resolve_user_config_vars()
        assert "memory_test_period_hours" in result

    def test_contains_available_languages(self):
        result = _resolve_user_config_vars()
        assert "available_learning_languages" in result
        assert isinstance(result["available_learning_languages"], str)


# ---------------------------------------------------------------------------
# _resolve_language_vars
# ---------------------------------------------------------------------------


class TestResolveLanguageVars:
    def test_returns_language_fields(self):
        session.lang = Language(
            code="en",
            label="English",
            user_level="Beginner",
            teaching_guide="Teach in English",
        )
        result = _resolve_language_vars()
        assert result == {
            "label": "English",
            "user_level": "Beginner",
            "teaching_guide": "Teach in English",
        }

    def test_raises_without_language(self):
        with pytest.raises(ValueError, match="not determined yet"):
            _resolve_language_vars()


# ---------------------------------------------------------------------------
# _render_instruction
# ---------------------------------------------------------------------------


class TestRenderInstruction:
    def test_template_without_variables(self):
        instr = Instruction(
            name="plain",
            description="No variables",
            template="This is a static instruction",
            requires_language=False,
            variables={},
        )
        config_store.instructions = {"plain": instr}
        assert _render_instruction("plain") == "This is a static instruction"

    def test_instruction_with_user_config_vars(self):
        instr = Instruction(
            name="test_uc",
            description="User config test",
            template="Native: {native_language}",
            requires_language=False,
            variables={"user_config": ["native_language"]},
        )
        config_store.instructions = {"test_uc": instr}
        result = _render_instruction("test_uc")
        assert "Native:" in result
        assert result != "Native: {native_language}"

    def test_instruction_with_language_vars(self):
        session.lang = Language(
            code="fr",
            label="French",
            user_level="Intermediate",
            teaching_guide="Teach basics",
        )
        instr = Instruction(
            name="test_lang",
            description="Language test",
            template="Learn {label} at {user_level} level",
            requires_language=True,
            variables={"language": ["label", "user_level"]},
        )
        config_store.instructions = {"test_lang": instr}
        assert _render_instruction("test_lang") == "Learn French at Intermediate level"

    def test_instruction_with_multiple_variable_groups(self):
        session.lang = Language(
            code="en",
            label="English",
            user_level="Advanced",
            teaching_guide="Advanced guide",
        )
        instr = Instruction(
            name="multi",
            description="Multi-group",
            template="Native: {native_language}, Learning: {label}, Level: {user_level}",
            requires_language=True,
            variables={
                "user_config": ["native_language"],
                "language": ["label", "user_level"],
            },
        )
        config_store.instructions = {"multi": instr}
        result = _render_instruction("multi")
        assert "English" in result
        assert "Advanced" in result

    def test_requires_language_but_not_set(self):
        instr = Instruction(
            name="needs_lang",
            description="Needs language",
            template="Learn {label}",
            requires_language=True,
            variables={"language": ["label"]},
        )
        config_store.instructions = {"needs_lang": instr}
        with pytest.raises(ValueError, match="requires a language"):
            _render_instruction("needs_lang")

    def test_unknown_instruction_raises_key_error(self):
        with pytest.raises(KeyError):
            _render_instruction("nonexistent")
