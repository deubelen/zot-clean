"""Command registry (D213): complete compared with the 0.3.2 parser, and translation of lines."""

import argparse
import re

import pytest

from zot_clean import citation_keys, registry, tags
from zot_clean.cli import build_parser


def _subparsers(p: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    actions = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
    return dict(actions[0].choices) if actions else {}


def _options(p: argparse.ArgumentParser) -> set[str]:
    return {o for a in p._actions for o in a.option_strings if o.startswith('--') and o != '--help'}


def test_all_commands_and_options_of_parser():
    """The parser has exactly the English names of the registry (D219), plus those that appeared with 0.4.0."""
    p = build_parser()
    commands = _subparsers(p)
    new_ones = {new: set(under.values()) for new, under in registry.COMMANDS.values()}
    new_options = set(registry.OPTIONS.values())
    for line in registry.NEW_COMMANDS:
        command, word = line.split()
        if word.startswith('--'):
            new_options.add(word)
        else:
            new_ones.setdefault(command, set()).add(word)
    assert set(commands) == set(new_ones)
    options = _options(p)
    for name, sp in commands.items():
        assert set(_subparsers(sp)) == new_ones[name], name
        options |= _options(sp)
        for sp2 in _subparsers(sp).values():
            options |= _options(sp2)
    assert options == new_options


def test_former_names_no_longer_accepted():
    """No old command, subcommand or option is still accepted by the parser: each is refused with its equivalent
    (D213)."""
    from zot_clean.cli import former_names
    p = build_parser()
    commands = _subparsers(p)
    for old, (new, under) in registry.COMMANDS.items():
        assert (old in commands) == (old == new)
        for old_sub, new_sub in under.items():
            assert (old_sub in _subparsers(commands[new])) == (old_sub == new_sub)
            if old_sub != new_sub:
                assert former_names([new, old_sub]) == ([new, new_sub], [(old_sub, new_sub)])
    for old, new in registry.OPTIONS.items():
        if old != new:
            assert former_names(['audit', old]) == (['audit', new], [(old, new)])
    assert former_names(['duplicates', 'accept', '--certain', '--workspace', '~/zc']) is None


def test_accepted_values():
    """The registry values are those accepted by `zc tags … --sort` and `zc cles decider`."""
    assert set(registry.TAG_ACTIONS) == set(tags.ACTIONS.values())
    assert set(registry.VALUES['cles decider', 'decisions']) == set(citation_keys.DECISIONS.values())


def test_english_names_well_formed_and_distinct():
    new_ones = [n for n, _ in registry.COMMANDS.values()]
    assert len(set(new_ones)) == len(new_ones)
    for n, under in registry.COMMANDS.values():
        assert re.fullmatch(r'[a-z]+(-[a-z]+)*', n)
        assert len(set(under.values())) == len(under) and all(re.fullmatch(r'[a-z]+(-[a-z]+)*', x) for x in under.values())
    assert len(set(registry.OPTIONS.values())) == len(registry.OPTIONS)
    assert all(re.fullmatch(r'--[a-z]+(-[a-z]+)*', o) for o in registry.OPTIONS.values())
    for table in registry.VALUES.values():
        assert len(set(table.values())) == len(table) and all(re.fullmatch(r'[a-z]+', v) for v in table.values())


@pytest.mark.parametrize('former, new', [
    ('doublons accepter --surs --sauf ABCD2345', 'duplicates accept --certain --except ABCD2345'),
    ('appliquer plans/x.json --tout --dossier ~/zc', 'apply plans/x.json --all --workspace ~/zc'),
    ('annuler journal/x.jsonl', 'undo journal/x.jsonl'),
    ('fonds a-ranger --laisser ABCD2345', 'subjects pending --leave-out ABCD2345'),
    ('tags ajouter perception --sort état --cible #perception', 'tags add perception --action status --target #perception'),
    ('tags accepter --sort=etat mémoire', 'tags accept --action=status mémoire'),
    ('cles decider ABCD2345=écarter EFGH6789=Natif', 'citation-keys decide ABCD2345=skip EFGH6789=native'),
    ('init --maj', 'init --update'),
    ('voir --tag état', 'show --tag état'),
])
def test_translate(former, new):
    assert registry.translate(former.split()) == new.split()
