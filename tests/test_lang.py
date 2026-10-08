"""Bilingual texts (D210, D215, D220 to D223).

The texts shown to the user are written as `L(en='…', fr='…')` next to the code that uses them. These tests check
the language rules themselves, and that every `L(...)` call of the package has both texts, non-empty, with the same
fields, so that no message can lose a value in one of the languages.
"""

import argparse
import ast
import string
from pathlib import Path

import pytest

from zot_clean import cli, config, lang
from zot_clean.lang import L, language, plural

SRC = Path(__file__).parent.parent / 'src' / 'zot_clean'


def test_french_by_default_and_english_in_a_block():
    assert L(en='Done.', fr='Fait.') == 'Fait.'
    with language('en'):
        assert L(en='Done.', fr='Fait.') == 'Done.'
        with language('fr'):
            assert L(en='Done.', fr='Fait.') == 'Fait.'
        assert lang.current() == 'en'
    assert lang.current() == 'fr'
    with pytest.raises(ValueError):
        with language('de'):
            pass


@pytest.mark.parametrize('n, fr, en', [
    (0, '0 pièce jointe', '0 attachments'), (1, '1 pièce jointe', '1 attachment'),
    (2, '2 pièces jointes', '2 attachments'),
])
def test_plural(n, fr, en):
    assert plural(n, en='attachment', fr='pièce jointe') == fr
    with language('en'):
        assert plural(n, en='attachment', fr='pièce jointe') == en


def test_plural_agreement_rules():
    assert plural(3, en='manual tag', fr='tag manuel') == '3 tags manuels'
    assert plural(2, en='PDF', fr='PDF identique') == '2 PDF identiques'
    with language('en'):
        assert plural(3, en='manual tag', fr='tag manuel') == '3 manual tags'
        assert plural(2, en='PDF', fr='PDF') == '2 PDFs'
        assert plural(2, en='match', fr='x') == '2 matches'
        assert plural(2, en='entry', fr='x') == '2 entries'
        assert plural(2, en='key', fr='x') == '2 keys'
        assert plural(2, en='copy', fr='x', en_plural='copies') == '2 copies'


def test_language_of_the_working_folder(tmp_path):
    assert lang.of_workspace(None) == 'en'
    assert lang.of_workspace(tmp_path) == 'en'  # no config.toml: not a working folder
    (tmp_path / 'config.toml').write_text('[zotero]\ndossier = "~/Zotero"\n', encoding='utf-8')
    assert lang.of_workspace(tmp_path) == 'fr'  # D214
    (tmp_path / 'config.toml').write_text('[zotero]\ndossier = "~/Zotero"\n[methode]\nlangue = "en"\n',
                                          encoding='utf-8')
    assert lang.of_workspace(tmp_path) == 'en'
    (tmp_path / 'config.toml').write_text('[zotero\n', encoding='utf-8')
    assert lang.of_workspace(tmp_path) == 'fr'  # unreadable: its refusal is French, like the folder


def test_language_key_of_config(tmp_path):
    (tmp_path / 'config.toml').write_text('[zotero]\ndossier = "~/Zotero"\n', encoding='utf-8')
    assert config.load(tmp_path).method.language == 'fr'
    (tmp_path / 'config.toml').write_text('[zotero]\ndossier = "~/Zotero"\n[methode]\nlangue = "en"\n',
                                          encoding='utf-8')
    assert config.load(tmp_path).method.language == 'en'
    assert config.to_stored(config.load(tmp_path))['methode']['langue'] == 'en'
    (tmp_path / 'config.toml').write_text('[zotero]\ndossier = "~/Zotero"\n[methode]\nlangue = "de"\n',
                                          encoding='utf-8')
    with pytest.raises(SystemExit, match='langue'):
        config.load(tmp_path)


@pytest.mark.parametrize('declared, expected', [(None, 'fr'), ('en', 'en'), ('fr', 'fr')])
def test_command_runs_in_the_library_language(tmp_path, capsys, declared, expected):
    text = '[zotero]\ndossier = "~/Zotero"\n' + (f'[methode]\nlangue = "{declared}"\n' if declared else '')
    (tmp_path / 'config.toml').write_text(text, encoding='utf-8')

    def handler(args):
        print(L(en='english', fr='français'))
        return 0
    args = argparse.Namespace(command='audit', handler=handler, workspace=tmp_path)
    assert cli.run_command(args) == 0
    assert capsys.readouterr().out.strip() == {'en': 'english', 'fr': 'français'}[expected]
    assert lang.current() == 'fr'  # nothing leaks to the next command or test


def test_outside_a_working_folder_texts_are_english(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def handler(args):
        raise SystemExit(L(en='No working folder.', fr='Aucun dossier de travail.'))
    assert cli.run_command(argparse.Namespace(command='audit', handler=handler, workspace=None)) == 1
    assert capsys.readouterr().err.strip() == 'No working folder.'


# --- Every L(...) call of the package -----------------------------------------------------------

def _fields(node: ast.expr) -> set[str]:
    """Fields of a text: the expressions of an f-string, or the `{name}` of a string formatted afterwards."""
    if isinstance(node, ast.JoinedStr):
        return {ast.unparse(v.value) for v in node.values if isinstance(v, ast.FormattedValue)}
    return {f for _, f, _, _ in string.Formatter().parse(node.value) if f is not None}


def _text(node: ast.expr) -> str:
    if isinstance(node, ast.JoinedStr):
        return ''.join(v.value for v in node.values if isinstance(v, ast.Constant))
    return node.value


def _calls():
    for path in sorted(SRC.glob('*.py')):
        for n in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(n, ast.Call) and getattr(n.func, 'id', getattr(n.func, 'attr', '')) == 'L':
                yield f'{path.name}:{n.lineno}', n


def test_every_text_has_both_languages_with_the_same_fields():
    problems = []
    for where, call in _calls():
        kw = {k.arg: k.value for k in call.keywords}
        if call.args or set(kw) != {'en', 'fr'}:
            problems.append(f'{where}: L takes exactly en= and fr=')
            continue
        if not all(isinstance(v, (ast.Constant, ast.JoinedStr)) for v in kw.values()):
            problems.append(f'{where}: both texts must be written in place (string or f-string)')
            continue
        if not _text(kw['en']).strip() and not _fields(kw['en']) or not _text(kw['fr']).strip() and not _fields(kw['fr']):
            problems.append(f'{where}: empty text')
        if _fields(kw['en']) != _fields(kw['fr']):
            problems.append(f'{where}: fields differ, en {sorted(_fields(kw["en"]))} fr {sorted(_fields(kw["fr"]))}')
    assert not problems, '\n'.join(problems)


def test_no_text_is_computed_at_import():
    """`L` reads the language when called: a module constant, a default value or a class attribute built with it
    would freeze the language of the first import (D220)."""
    problems = []
    for path in sorted(SRC.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        inside = set()
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                for stmt in (fn.body if isinstance(fn.body, list) else [fn.body]):
                    inside.update(id(n) for n in ast.walk(stmt))
        problems += [f'{path.name}:{n.lineno}' for n in ast.walk(tree) if isinstance(n, ast.Call)
                     and getattr(n.func, 'id', getattr(n.func, 'attr', '')) == 'L' and id(n) not in inside]
    assert not problems, 'L called at import time: ' + ', '.join(problems)


def test_refusals_of_config_and_plans_in_english(tmp_path):
    """config.py and plans.py have no English test of their own: their refusals are checked here (D224)."""
    import json
    from zot_clean import plans
    (tmp_path / 'config.toml').write_text('[zotero]\ndossier = "~/Zotero"\n[sauvegarde]\nconserver = 0\n',
                                          encoding='utf-8')
    with language('en'), pytest.raises(SystemExit, match='must be at least 1'):
        config.load(tmp_path)
    plan = plans.Plan('tags', 4242, [plans.Group('1', 't', [plans.Operation('ABCD2345', {}, {'title': 'b'})])])
    path = plans.write(plan, tmp_path / 'plans', '')
    d = json.loads(path.read_text(encoding='utf-8'))
    d['groupes'][0]['titre'] = 'retouché'
    path.write_text(json.dumps(d), encoding='utf-8')
    with language('en'), pytest.raises(SystemExit, match='modified after it was created'):
        plans.load(path)
