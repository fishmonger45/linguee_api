from enum import StrEnum

from pydantic import BaseModel


class UsageFrequency(StrEnum):
    often = "often"
    almost_always = "almost_always"


class FollowCorrections(StrEnum):
    always = "always"
    never = "never"
    on_empty_translations = "on_empty_translations"


class AudioLink(BaseModel):
    url: str
    lang: str


class TranslationExample(BaseModel):
    src: str
    dst: str


class Translation(BaseModel):
    text: str
    pos: str | None = None
    featured: bool = False
    audio_links: list[AudioLink] = []
    usage_frequency: UsageFrequency | None = None
    examples: list[TranslationExample] = []


class Lemma(BaseModel):
    text: str
    pos: str | None = None
    featured: bool = False
    forms: list[str] = []
    grammar_info: str | None = None
    audio_links: list[AudioLink] = []
    translations: list[Translation] = []


class ExampleTranslation(BaseModel):
    text: str
    pos: str | None = None


class Example(BaseModel):
    text: str
    pos: str | None = None
    audio_links: list[AudioLink] = []
    translations: list[ExampleTranslation] = []


class ExternalSource(BaseModel):
    src: str
    dst: str
    src_url: str | None = None
    dst_url: str | None = None


class AutocompletionItem(BaseModel):
    text: str
    pos: str | None = None
    translations: list[str] = []


class SearchResult(BaseModel):
    src_lang: str
    dst_lang: str
    query: str
    correct_query: str | None = None
    lemmas: list[Lemma] = []
    examples: list[Example] = []
    external_sources: list[ExternalSource] = []


class Correction(BaseModel):
    text: str


class NotFound(BaseModel):
    pass


class ParseError(BaseModel):
    message: str
