"""セッション状態管理。"""

from dynamic_prompt.models import Language


class _Session:
    _lang: Language | None = None

    @property
    def lang(self) -> Language:
        if self._lang is None:
            raise ValueError(
                "Language is not determined yet. Call 'determine_language' tool first."
            )
        return self._lang

    @lang.setter
    def lang(self, value: Language) -> None:
        self._lang = value

    @property
    def lang_is_set(self) -> bool:
        return self._lang is not None


session = _Session()
