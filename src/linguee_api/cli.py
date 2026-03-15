import asyncio
import sys

import httpx

from linguee_api.client import CaptchaError, LingueeError, fetch_search
from linguee_api.models import Correction, NotFound, ParseError
from linguee_api.parser import parse_search_result

from linguee_api.logging import setup_logging

SRC = "de"
DST = "en"

DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RESET = "\033[0m"


async def lookup(client: httpx.AsyncClient, word: str) -> None:
    try:
        html = await fetch_search(client, SRC, DST, word)
    except CaptchaError:
        print(f"  {DIM}blocked by Linguee (CAPTCHA){RESET}")
        return
    except LingueeError as e:
        print(f"  {DIM}error: {e.detail}{RESET}")
        return

    result = parse_search_result(html)

    if isinstance(result, NotFound):
        print(f"  {DIM}no results{RESET}")
        return
    if isinstance(result, Correction):
        print(f"  {DIM}did you mean:{RESET} {BOLD}{result.text}{RESET}")
        return
    if isinstance(result, ParseError):
        print(f"  {DIM}parse error: {result.message}{RESET}")
        return

    if not result.lemmas and not result.examples:
        print(f"  {DIM}no results{RESET}")
        return

    for i, lemma in enumerate(result.lemmas):
        if i > 0:
            print(f"  {DIM}{'─' * 40}{RESET}")

        pos = f" {DIM}{lemma.pos}{RESET}" if lemma.pos else ""
        forms = f" {DIM}({', '.join(lemma.forms)}){RESET}" if lemma.forms else ""
        print(f"\n  {BOLD}{lemma.text}{RESET}{pos}{forms}")

        for t in lemma.translations:
            freq = ""
            if t.usage_frequency:
                freq = f" {GREEN}●{RESET}" if t.usage_frequency.value == "almost_always" else f" {GREEN}○{RESET}"
            t_pos = f" {DIM}{t.pos}{RESET}" if t.pos else ""
            print(f"    {CYAN}→{RESET} {t.text}{t_pos}{freq}")

            for ex in t.examples:
                print(f"      {ex.src}")
                print(f"      {GREEN}{ex.dst}{RESET}")

    if result.examples:
        print(f"\n  {DIM}{'─' * 40}{RESET}")
        print(f"  {BOLD}Examples{RESET}\n")
        for ex in result.examples:
            pos = f" {DIM}{ex.pos}{RESET}" if ex.pos else ""
            translations = ", ".join(t.text for t in ex.translations)
            print(f"    {ex.text}{pos}  {CYAN}→{RESET}  {translations}")


async def repl() -> None:
    import os

    os.environ.setdefault("LINGUEE_LOG_LEVEL", "WARNING")
    setup_logging()
    print(f"\n  {BOLD}linguee{RESET} {DIM}de → en{RESET}  {DIM}(ctrl-c to quit){RESET}\n")
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                word = input(f"{BOLD}>{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not word:
                continue
            await lookup(client, word)
            print()


def main() -> None:
    try:
        asyncio.run(repl())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
