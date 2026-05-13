"""データモデル定義。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Language:
    code: str
    label: str
    aliases: list[str] = field(default_factory=list)
    user_level: str = ""
    teaching_guide: str = ""


@dataclass(frozen=True)
class UserConfig:
    native_language: str
    memory_test_period_hours: int = 24


@dataclass(frozen=True)
class AppConfig:
    vocab_get_limit: int = 5
    quiz_server_port: int = 8765
    quiz_server_port_pool_size: int = 3


@dataclass(frozen=True)
class Instruction:
    name: str
    description: str
    template: str
    requires_language: bool = False
    variables: dict[str, list[str]] = field(default_factory=dict)
