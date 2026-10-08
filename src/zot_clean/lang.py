"""Language of the displayed texts (D210, D215, phase 2 of the move to English).

Every text shown to the user (messages, refusals, reports, headers of the
tracking files) is written next to the code that uses it, in both languages:
`L(en='…', fr='…')` returns the text in the current language. The current
language is that of the library, `[methode] langue` in `config.toml` (`fr`
when the key is absent, D214). `cli.run_command` sets it as soon as it knows
the working folder; before that, and outside any working folder, texts are in
English, like the help and the argparse errors (D215, D222). Code called
directly, as in the tests, gets French unless a `language('en')` block says
otherwise.

Stored keys and values never go through `L`: they stay those of version 0.3.2
in both languages (D209).
"""

import contextlib
import tomllib
from contextvars import ContextVar
from pathlib import Path

LANGUAGES = ('fr', 'en')
DEFAULT = 'fr'  # a library without a declared language is French (D214)
OUTSIDE = 'en'  # no working folder known yet (D222)

_current: ContextVar[str] = ContextVar('language', default=DEFAULT)


def current() -> str:
    return _current.get()


def set_language(code: str) -> None:
    if code not in LANGUAGES:
        raise ValueError(code)
    _current.set(code)


@contextlib.contextmanager
def language(code: str):
    """Texts in `code` inside the block, the previous language afterwards."""
    if code not in LANGUAGES:
        raise ValueError(code)
    token = _current.set(code)
    try:
        yield
    finally:
        _current.reset(token)


def L(*, en: str, fr: str) -> str:
    """The text in the current language. Both texts are given in full, with the same `{…}` fields when the text
    is formatted afterwards (checked by `tests/test_lang.py`)."""
    return en if _current.get() == 'en' else fr


def plural(n: int, *, en: str, fr: str, en_plural: str = '') -> str:
    """Count followed by the agreed noun phrase: « 2 pièces jointes », « 0 tag manuel » (every French word agrees
    above 1, except acronyms), "2 attachments", "0 manual tags" (the last English word agrees, except for 1).
    `en_plural` gives an irregular English plural in full ("entries", "copies")."""
    if _current.get() == 'en':
        if n == 1:
            return f'{n} {en}'
        if en_plural:
            return f'{n} {en_plural}'
        head, _, last = en.rpartition(' ')
        return f'{n} {head + " " if head else ""}{_english_plural(last)}'
    if n <= 1:
        return f'{n} {fr}'
    return f"{n} " + ' '.join(m if m.isupper() or m[-1] in 'sx' else m + 's' for m in fr.split())


def _english_plural(word: str) -> str:
    if word.isupper():
        return word + 's'  # PDFs, DOIs
    if word.endswith(('s', 'x', 'ch', 'sh')):
        return word + 'es'
    if word.endswith('y') and len(word) > 1 and word[-2] not in 'aeiou':
        return word[:-1] + 'ies'
    return word + 's'


def of_workspace(folder: Path | None) -> str:
    """Language declared in the `config.toml` of `folder`, read without the rest of the configuration so that it
    applies even to the message refusing an invalid configuration. `fr` when the key is absent or the file
    unreadable (D214), English when there is no working folder (D222)."""
    if folder is None:
        return OUTSIDE
    try:
        raw = tomllib.loads((folder / 'config.toml').read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return OUTSIDE if not (folder / 'config.toml').is_file() else DEFAULT
    code = raw.get('methode', {}).get('langue', DEFAULT) if isinstance(raw.get('methode', {}), dict) else DEFAULT
    return code if code in LANGUAGES else DEFAULT
