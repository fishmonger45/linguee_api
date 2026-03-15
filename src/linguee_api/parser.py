import re

import structlog
from selectolax.lexbor import LexborHTMLParser, LexborNode

from linguee_api.models import (
    AudioLink,
    Correction,
    Example,
    ExampleTranslation,
    ExternalSource,
    Lemma,
    NotFound,
    ParseError,
    SearchResult,
    Translation,
    TranslationExample,
    UsageFrequency,
)

log = structlog.get_logger()


def _text(node: LexborNode | None) -> str:
    if node is None:
        return ""
    return (node.text(strip=True) or "").strip()


def _parse_audio_links(parent: LexborNode) -> list[AudioLink]:
    links: list[AudioLink] = []
    for a in parent.css("a.audio"):
        onclick = a.attributes.get("onclick", "")
        match = re.search(r"playSound\(this,\"([^\"]+)\",\"([^\"]+)\"", onclick)
        if match:
            links.append(AudioLink(url=match.group(1), lang=match.group(2)))
    return links


def _parse_pos(node: LexborNode) -> str | None:
    for selector in ("span.tag_wordtype", "span.tag_type"):
        el = node.css_first(selector)
        if el is not None:
            title = el.attributes.get("title", "")
            if title:
                return title.strip()
            text = _text(el)
            if text:
                return text
    return None


def _parse_usage_frequency(node: LexborNode) -> UsageFrequency | None:
    tag_c = node.css_first("span.tag_c")
    if tag_c is None:
        return None
    classes = tag_c.attributes.get("class", "")
    if "almost_always" in classes:
        return UsageFrequency.almost_always
    if "often" in classes:
        return UsageFrequency.often
    return None


def _parse_translation_examples(node: LexborNode) -> list[TranslationExample]:
    examples: list[TranslationExample] = []
    for ex in node.css(".example_lines > .example"):
        src_el = ex.css_first(".tag_s")
        dst_el = ex.css_first(".tag_t")
        if src_el and dst_el:
            examples.append(TranslationExample(src=_text(src_el), dst=_text(dst_el)))
    return examples


def _parse_translations(parent: LexborNode) -> list[Translation]:
    translations: list[Translation] = []
    for t_node in parent.css("div.translation_lines div.translation"):
        link = t_node.css_first("a.dictLink")
        if link is None:
            continue
        text = _text(link)
        if not text:
            continue

        featured = "featured" in (t_node.attributes.get("class", ""))
        pos = _parse_pos(t_node)
        audio_links = _parse_audio_links(t_node)
        usage_frequency = _parse_usage_frequency(t_node)
        examples = _parse_translation_examples(t_node)

        translations.append(
            Translation(
                text=text,
                pos=pos,
                featured=featured,
                audio_links=audio_links,
                usage_frequency=usage_frequency,
                examples=examples,
            )
        )
    return translations


def _parse_lemmas(tree: LexborHTMLParser) -> list[Lemma]:
    lemmas: list[Lemma] = []
    for lemma_node in tree.css("div.exact > div.lemma"):
        link = lemma_node.css_first("span.tag_lemma a.dictLink")
        if link is None:
            continue
        text = _text(link)
        if not text:
            continue

        featured = "featured" in (lemma_node.attributes.get("class", ""))
        pos = _parse_pos(lemma_node)
        audio_links = _parse_audio_links(lemma_node)

        forms: list[str] = []
        forms_el = lemma_node.css_first("span.tag_forms")
        if forms_el:
            forms_text = _text(forms_el)
            if forms_text:
                forms = [f.strip() for f in forms_text.split(",") if f.strip()]

        grammar_info: str | None = None
        gi_el = lemma_node.css_first("span.grammar_info")
        if gi_el:
            grammar_info = _text(gi_el) or None

        translations = _parse_translations(lemma_node)

        lemmas.append(
            Lemma(
                text=text,
                pos=pos,
                featured=featured,
                forms=forms,
                grammar_info=grammar_info,
                audio_links=audio_links,
                translations=translations,
            )
        )
    return lemmas


def _parse_examples(tree: LexborHTMLParser) -> list[Example]:
    examples: list[Example] = []
    for ex_node in tree.css("div.example_lines div.lemma"):
        link = ex_node.css_first("a.dictLink")
        if link is None:
            continue
        text = _text(link)
        if not text:
            continue

        pos = _parse_pos(ex_node)
        audio_links = _parse_audio_links(ex_node)

        translations: list[ExampleTranslation] = []
        for t_node in ex_node.css("div.translation_lines div.translation"):
            t_link = t_node.css_first("a.dictLink")
            if t_link is None:
                continue
            t_text = _text(t_link)
            if t_text:
                translations.append(ExampleTranslation(text=t_text, pos=_parse_pos(t_node)))

        examples.append(
            Example(text=text, pos=pos, audio_links=audio_links, translations=translations)
        )
    return examples


def _parse_external_sources(tree: LexborHTMLParser) -> list[ExternalSource]:
    sources: list[ExternalSource] = []
    for row in tree.css("table.result_table > tbody > tr"):
        left = row.css_first("td.left div.wrap")
        right = row.css_first("td.right2 div.wrap")
        if left is None or right is None:
            continue

        src_text = _text(left)
        dst_text = _text(right)
        if not src_text or not dst_text:
            continue

        src_link = left.css_first("a")
        dst_link = right.css_first("a")
        src_url = src_link.attributes.get("href") if src_link else None
        dst_url = dst_link.attributes.get("href") if dst_link else None

        sources.append(ExternalSource(src=src_text, dst=dst_text, src_url=src_url, dst_url=dst_url))
    return sources


def _parse_correction(tree: LexborHTMLParser) -> str | None:
    corrected = tree.css_first("span.corrected")
    if corrected:
        return _text(corrected) or None
    return None


def parse_search_result(html: str) -> SearchResult | Correction | NotFound | ParseError:
    try:
        tree = LexborHTMLParser(html)
    except Exception as e:
        log.error("html_parse_failed", error=str(e))
        return ParseError(message=str(e))

    noresults = tree.css_first("h1.noresults")
    if noresults is not None:
        return NotFound()

    correction = _parse_correction(tree)
    if correction:
        return Correction(text=correction)

    data_div = tree.css_first("div#data")
    src_lang = ""
    dst_lang = ""
    query = ""
    correct_query: str | None = None

    if data_div:
        src_lang = data_div.attributes.get("data-lang1", "")
        dst_lang = data_div.attributes.get("data-lang2", "")
        query = data_div.attributes.get("data-query", "")
        correct_query = data_div.attributes.get("data-correctspellingofquery") or None

    lemmas = _parse_lemmas(tree)
    examples = _parse_examples(tree)
    external_sources = _parse_external_sources(tree)

    return SearchResult(
        src_lang=src_lang,
        dst_lang=dst_lang,
        query=query,
        correct_query=correct_query,
        lemmas=lemmas,
        examples=examples,
        external_sources=external_sources,
    )


def parse_autocompletions(html: str) -> list[dict[str, str]]:
    import json

    try:
        return json.loads(html)
    except (json.JSONDecodeError, TypeError):
        return []
