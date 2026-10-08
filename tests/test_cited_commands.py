"""Commands cited in the documents and the texts of zc (phase 3 of the move to English, D213, D219).

Every `` `zc …` `` written between backquotes in the shipped skills, the shipped AGENTS.md, the guide, the method,
the README and the strings of the package must be accepted by the real argument parser of zc, and must not use a name
of version 0.3.2, which zc now refuses. A user or an agent who copies a cited command must not hit a refusal.

The values to fill in are replaced before parsing: `<plan>` by a dummy value, `keep|skip` by its first choice, and
`…` dropped. A command or an option cited without its required values (`zc apply`, `--leave-out`, to name them)
is accepted, an unknown command, subcommand, option or choice is not.
"""

import ast
import contextlib
import io
import re
from pathlib import Path

import pytest

from zot_clean import cli

ROOT = Path(__file__).parent.parent
SRC = ROOT / 'src' / 'zot_clean'
CITED = re.compile(r'`(zc(?: [^`\n]*)?)`')

DOCUMENTS = sorted([*(SRC / 'templates').rglob('*.md'), ROOT / 'README.md', ROOT / 'tests' / 'manual' / 'LISEZMOI.md',
                    ROOT / 'outils' / 'pilote' / 'LISEZMOI.md'])


def _words(command: str) -> list[str]:
    res = []
    for w in command.split()[1:]:
        if w in ('…', '...'):
            continue
        if '<' in w or '>' in w:
            w = re.sub(r'<[^>]*>', 'x', w)
        if '|' in w:
            w = w.split('|')[0]
        res.append(w)
    return res


def problem(command: str) -> str | None:
    """Why `command` would not run as cited, or None."""
    argv = _words(command)
    if cli.former_names(argv):
        return 'name of version 0.3.2, refused by zc'
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            cli.build_parser().parse_args(argv)
    except SystemExit as e:
        if e.code and not re.search(r'the following arguments are required|expected (at least )?one argument',
                                    err.getvalue()):
            return err.getvalue().strip().splitlines()[-1]
    return None


def _strings(path: Path):
    for n in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.lineno, n.value


def _report(cited) -> list[str]:
    return [f'{where}: `{c}`: {why}' for where, c in cited if (why := problem(c))]


def test_commands_cited_in_the_code():
    cited = [(f'{p.name}:{line}', c) for p in sorted(SRC.glob('*.py')) for line, s in _strings(p)
             for c in CITED.findall(s)]
    assert len(cited) > 100
    problems = _report(cited)
    assert not problems, '\n'.join(problems)


@pytest.mark.parametrize('path', DOCUMENTS, ids=lambda p: str(p.relative_to(ROOT)))
def test_commands_cited_in_the_documents(path):
    text = path.read_text(encoding='utf-8')
    cited = [(f'{path.name}:{text[:m.start()].count(chr(10)) + 1}', m.group(1)) for m in CITED.finditer(text)]
    problems = _report(cited)
    assert not problems, '\n'.join(problems)


@pytest.mark.parametrize('command, expected', [
    ('zc duplicates find', None), ('zc apply <plan> --trial', None), ('zc apply', None),
    ('zc citation-keys decide ITEM=keep|skip …', None), ('zc tags accept --help', None),
    ('zc doublons chercher', 'name of version 0.3.2'), ('zc apply x --essai', 'name of version 0.3.2'),
    ('zc duplicates search', 'invalid choice'), ('zc audit --everything', 'unrecognized arguments'),
])
def test_the_check_itself(command, expected):
    why = problem(command)
    assert (why is None) if expected is None else (expected in why)
