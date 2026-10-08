import json

import pytest

from zot_clean import bbt, config, init, reader
from zot_clean.lang import language


@pytest.fixture
def valid_key(monkeypatch):
    calls = []

    def check(key):
        calls.append(key)
        if key != 'BONNE':
            raise init.KeyRejected('Clé refusée par Zotero (invalide ou révoquée).')
        return init.KeyInfo(4242, 'durand', True, True, True)  # account synchronised by the test database

    monkeypatch.setattr(init, 'check_key', check)
    return calls


def run(folder, zotero, answers=(), secrets=(), update=False):
    answers, secrets, output = list(answers), list(secrets), []
    code = init.initialize(folder, zotero.folder, update, lambda _: answers.pop(0) if answers else '',
                            lambda _: secrets.pop(0) if secrets else '',
                            output.append)
    return code, '\n'.join(output)


def test_creates_workspace(tmp_path, zotero, valid_key):
    zotero.save()
    (zotero.folder / 'better-bibtex').mkdir()
    workspace = tmp_path / 'travail'
    code, output = run(workspace, zotero, secrets=['MAUVAISE', 'BONNE'])
    assert code == 0 and valid_key == ['MAUVAISE', 'BONNE']
    assert 'Réessayer' in output and 'BONNE' not in output
    assert init.read_env(workspace) == {'ZOTERO_API_KEY': 'BONNE', 'ZOTERO_USER_ID': '4242'}
    assert {p.name for p in workspace.iterdir()} == {'config.toml', '.env', '.gitignore', 'AGENTS.md', 'guide.md', 'methode.md', '.agents', '.claude', 'rapports', 'journal', 'plans', 'suivi'}
    for root in ('.agents', '.claude'):
        for skill in ('duplicates', 'metadata', 'subjects', 'tags', 'citation-keys', 'filenames', 'checkup', 'inbox'):
            assert (workspace / root / 'skills' / skill / 'SKILL.md').is_file()
    cfg = config.load(workspace)
    assert cfg.zotero_dir == zotero.folder and cfg.method.use_citation_keys
    assert '.env' in (workspace / '.gitignore').read_text(encoding='utf-8')


def test_without_better_bibtex_keys_are_disabled(tmp_path, zotero, valid_key):
    zotero.save()
    run(tmp_path, zotero, secrets=['BONNE'])
    assert config.load(tmp_path).method.use_citation_keys is False


def zotero_profile(tmp_path, monkeypatch, zotero, active: bool, version: str = '9.1.0'):
    """Zotero profile serving the test data folder, with Better BibTeX enabled or disabled."""
    root = tmp_path / 'profils'
    profile = root / 'Profiles' / 'x.default'
    profile.mkdir(parents=True)
    (root / 'profiles.ini').write_text('[Profile0]\nName=default\nIsRelative=1\nPath=Profiles/x.default\nDefault=1\n',
                                         encoding='utf-8')
    (profile / 'prefs.js').write_text(f'user_pref("extensions.zotero.dataDir", {json.dumps(str(zotero.folder))});\n'
                                     'user_pref("extensions.zotero.useDataDir", true);\n', encoding='utf-8')
    (profile / 'extensions.json').write_text(json.dumps({'addons': [
        {'id': 'better-bibtex@iris-advies.com', 'version': version, 'active': active}]}), encoding='utf-8')
    monkeypatch.setattr(bbt, 'profile_folders', lambda: [root])


def test_better_bibtex_read_from_profile(tmp_path, zotero, valid_key, monkeypatch):
    zotero.save()
    zotero_profile(tmp_path, monkeypatch, zotero, active=True)
    workspace = tmp_path / 'actif'
    _, output = run(workspace, zotero, secrets=['BONNE'])
    assert 'Better BibTeX 9.1.0 actif' in output and config.load(workspace).method.use_citation_keys


def test_better_bibtex_disabled_counts_as_missing(tmp_path, zotero, valid_key, monkeypatch):
    zotero.save()
    (zotero.folder / 'better-bibtex').mkdir()  # old caches, ignored since the profile answers
    zotero_profile(tmp_path, monkeypatch, zotero, active=False)
    workspace = tmp_path / 'inactif'
    _, output = run(workspace, zotero, secrets=['BONNE'])
    assert 'désactivé dans Zotero' in output and config.load(workspace).method.use_citation_keys is False


def test_key_without_write_access(tmp_path, zotero, monkeypatch):
    zotero.save()
    monkeypatch.setattr(init, 'check_key', lambda key: init.KeyInfo(1, 'x', True, False, True))
    _, output = run(tmp_path, zotero, secrets=['LECTURE', ''])
    assert "sans droit d'écriture" in output and 'Étape passée' in output
    assert not (tmp_path / '.env').exists()


def test_rerun_without_overwriting_and_asks_missing_key_again(tmp_path, zotero, valid_key):
    zotero.save()
    run(tmp_path, zotero, secrets=[''])
    (tmp_path / 'config.toml').write_text('[methode]\ninbox = "Boîte"\n', encoding='utf-8')
    (tmp_path / 'AGENTS.md').write_text('mes consignes', encoding='utf-8')
    _, output = run(tmp_path, zotero, secrets=['BONNE'])
    assert 'conservé' in output and init.read_env(tmp_path)['ZOTERO_API_KEY'] == 'BONNE'
    assert config.load(tmp_path).method.inbox == 'Boîte'
    assert (tmp_path / 'AGENTS.md').read_text(encoding='utf-8') == 'mes consignes'
    _, output = run(tmp_path, zotero)
    assert 'déjà enregistrée' in output


def test_update_replaces_agents_md_and_skills(tmp_path, zotero):
    (tmp_path / 'config.toml').write_text('', encoding='utf-8')
    (tmp_path / 'AGENTS.md').write_text('ancien', encoding='utf-8')
    skill = tmp_path / '.agents' / 'skills' / 'tags' / 'SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('ancien', encoding='utf-8')
    run(tmp_path, zotero, update=True)
    assert 'zot-clean' in (tmp_path / 'AGENTS.md').read_text(encoding='utf-8')
    assert skill.read_text(encoding='utf-8').startswith('---\nname: tags')


def test_update_removes_the_skills_of_032(tmp_path, zotero):
    """D230: the skills shipped under an old name are removed, so that the agent does not follow two sets. A skill
    of the user, or a file the user added to an old one, stays."""
    (tmp_path / 'config.toml').write_text('', encoding='utf-8')
    for root in ('.agents', '.claude'):
        for name in ('doublons', 'fonds', 'mon-skill'):
            (tmp_path / root / 'skills' / name).mkdir(parents=True)
            (tmp_path / root / 'skills' / name / 'SKILL.md').write_text('ancien', encoding='utf-8')
    (tmp_path / '.claude' / 'skills' / 'fonds' / 'notes.md').write_text('à moi', encoding='utf-8')
    code, output = run(tmp_path, zotero, update=True)
    assert code == 0 and 'Retirés' in output and '.claude/skills/doublons/' in output
    for root in ('.agents', '.claude'):
        assert not (tmp_path / root / 'skills' / 'doublons').exists()
        assert not (tmp_path / root / 'skills' / 'fonds' / 'SKILL.md').exists()
        assert (tmp_path / root / 'skills' / 'mon-skill' / 'SKILL.md').read_text(encoding='utf-8') == 'ancien'
        assert (tmp_path / root / 'skills' / 'duplicates' / 'SKILL.md').is_file()
    assert (tmp_path / '.claude' / 'skills' / 'fonds' / 'notes.md').is_file()
    assert 'Retirés' not in run(tmp_path, zotero, update=True)[1]


def test_zotero_dir_not_found(tmp_path):
    questions = []
    code = init.initialize(tmp_path, tmp_path / 'nulle-part', False, lambda q: questions.append(q) or '',
                            lambda _: '', lambda _: None)
    assert code == 1 and 'introuvable' in questions[0]
    assert not (tmp_path / 'config.toml').exists()


def test_warns_if_a_claude_md_hides_agents_md(tmp_path, zotero, monkeypatch):
    monkeypatch.setattr(init.Path, 'home', lambda: tmp_path / 'maison')
    zotero.save()
    workspace = tmp_path / 'projets' / 'biblio'
    workspace.mkdir(parents=True)
    (workspace / 'config.toml').write_text('', encoding='utf-8')
    _, output = run(workspace, zotero, update=True)
    assert 'Attention' not in output
    (tmp_path / 'projets' / 'CLAUDE.md').write_text('consignes du dossier parent', encoding='utf-8')
    _, output = run(workspace, zotero, update=True)
    assert 'Attention' in output and '@AGENTS.md' in output
    (workspace / 'CLAUDE.md').write_text('@AGENTS.md\n', encoding='utf-8')
    _, output = run(workspace, zotero, update=True)
    assert 'Attention' not in output


def test_personal_claude_md_ignored(tmp_path, monkeypatch):
    home_dir = tmp_path / 'maison'
    monkeypatch.setattr(init.Path, 'home', lambda: home_dir)
    (home_dir / '.claude').mkdir(parents=True)
    (home_dir / '.claude' / 'CLAUDE.md').write_text('préférences', encoding='utf-8')
    assert init.competing_claude_md(home_dir / 'biblio') == []
    (home_dir / 'biblio').mkdir()
    (home_dir / 'biblio' / 'CLAUDE.local.md').write_text('x', encoding='utf-8')
    assert init.competing_claude_md(home_dir / 'biblio') == [home_dir / 'biblio' / 'CLAUDE.local.md']


def test_openalex_key_optional(tmp_path, zotero, valid_key):
    zotero.save()
    code, output = run(tmp_path, zotero, secrets=['BONNE', 'CLE-OA'])
    assert code == 0 and 'CLE-OA' not in output
    assert init.read_env(tmp_path) == {'ZOTERO_API_KEY': 'BONNE', 'ZOTERO_USER_ID': '4242',
                                       'OPENALEX_API_KEY': 'CLE-OA'}


def test_update_rejected_outside_workspace(tmp_path, zotero):
    """Safeguard: --maj in a folder without config.toml (a code repository, for example) writes nothing."""
    (tmp_path / 'AGENTS.md').write_text('consignes du projet', encoding='utf-8')
    code, output = run(tmp_path, zotero, update=True)
    assert code == 1 and "n'est pas un dossier de travail" in output
    assert (tmp_path / 'AGENTS.md').read_text(encoding='utf-8') == 'consignes du projet'
    assert not (tmp_path / '.agents').exists() and not (tmp_path / '.claude').exists()


def test_saved_key_revoked_asked_again(tmp_path, zotero, valid_key):
    zotero.save()
    init.write_env(tmp_path, ZOTERO_API_KEY='REVOQUEE', ZOTERO_USER_ID='1', OPENALEX_API_KEY='OA')
    _, output = run(tmp_path, zotero, secrets=['BONNE'])
    assert 'à remplacer' in output and valid_key == ['REVOQUEE', 'BONNE']
    assert init.read_env(tmp_path) == {'ZOTERO_API_KEY': 'BONNE', 'ZOTERO_USER_ID': '4242', 'OPENALEX_API_KEY': 'OA'}


def test_saved_key_without_write_access_asked_again(tmp_path, zotero, monkeypatch):
    zotero.save()
    init.write_env(tmp_path, ZOTERO_API_KEY='LECTURE')
    monkeypatch.setattr(init, 'check_key', lambda key: init.KeyInfo(4242, 'x', True, key != 'LECTURE', True))
    _, output = run(tmp_path, zotero, secrets=['COMPLETE'])
    assert "n'a plus droit d'écriture" in output and init.read_env(tmp_path)['ZOTERO_API_KEY'] == 'COMPLETE'


def test_saved_key_kept_if_zotero_unreachable(tmp_path, zotero, monkeypatch):
    zotero.save()
    init.write_env(tmp_path, ZOTERO_API_KEY='GARDEE')

    def unreachable(key):
        raise init.urllib.error.URLError('pas de réseau')

    monkeypatch.setattr(init, 'check_key', unreachable)
    _, output = run(tmp_path, zotero)
    assert 'non vérifiée' in output and init.read_env(tmp_path)['ZOTERO_API_KEY'] == 'GARDEE'


def test_guide_and_method_copied(tmp_path, zotero):
    """The repository stays private: the guide and the method travel with the package, into the working folder."""
    run(tmp_path, zotero)
    assert '# ' in (tmp_path / 'guide.md').read_text(encoding='utf-8')
    assert (tmp_path / 'methode.md').is_file()
    assert 'methode.md' in (tmp_path / 'config.toml').read_text(encoding='utf-8')


def test_timeout_while_reading_response(tmp_path, zotero, monkeypatch):
    """A timeout while reading the response (outside `URLError`) gives a message, not a Python traceback."""
    zotero.save()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, *_):
            raise TimeoutError('The read operation timed out')

    monkeypatch.setattr(init.urllib.request, 'urlopen', lambda *a, **k: FakeResponse())
    with pytest.raises(init.urllib.error.URLError, match='Zotero injoignable'):
        init.check_key('CLE')
    _, output = run(tmp_path, zotero, secrets=['CLE'])
    assert 'Zotero injoignable (délai de 20 secondes dépassé). Réessayer.' in output
    init.write_env(tmp_path, ZOTERO_API_KEY='GARDEE')
    _, output = run(tmp_path, zotero)
    assert 'non vérifiée' in output


def test_key_of_another_account_asked_again(tmp_path, zotero, valid_key):
    """The key must be that of the account Zotero synchronises on this computer (two accounts, personal and
    institutional). A key of the other account is not saved."""
    zotero.account(777, 'institution')
    zotero.save()
    code, output = run(tmp_path, zotero, secrets=['BONNE'])
    assert code == 0 and valid_key == ['BONNE']
    assert 'avec le compte que Zotero synchronise sur cet ordinateur, « institution » (n° 777)' in output
    assert 'La clé API est celle du compte zotero.org n° 4242' in output and 'Entrée pour passer' in output
    assert 'ZOTERO_API_KEY' not in init.read_env(tmp_path)


def test_saved_key_of_another_account_to_replace(tmp_path, zotero, monkeypatch):
    zotero.account(777)
    zotero.save()
    init.write_env(tmp_path, ZOTERO_API_KEY='AUTRE', ZOTERO_USER_ID='4242')
    monkeypatch.setattr(init, 'check_key', lambda key: init.KeyInfo(777 if key == 'BONNE' else 4242, 'x', True,
                                                                       True, True))
    _, output = run(tmp_path, zotero, secrets=['BONNE'])
    assert 'Elle est à remplacer par une clé créée' in output
    assert init.read_env(tmp_path) == {'ZOTERO_API_KEY': 'BONNE', 'ZOTERO_USER_ID': '777'}
    # Zotero unreachable: the account noted with the key is compared with that of the database.
    init.write_env(tmp_path, ZOTERO_API_KEY='AUTRE', ZOTERO_USER_ID='4242')

    def unreachable(key):
        raise init.urllib.error.URLError('pas de réseau')

    monkeypatch.setattr(init, 'check_key', unreachable)
    assert not init.saved_key_valid(tmp_path, lambda m: None, reader.Account(777))
    assert init.saved_key_valid(tmp_path, lambda m: None, reader.Account(4242))


def test_database_never_synced_no_key_asked(tmp_path, zotero, valid_key):
    """Without synchronisation, no key can fit: `zc init` says so first, without asking for one, and prepares the
    folder for the audit."""
    zotero.account(None)
    zotero.save()
    code, output = run(tmp_path, zotero)
    assert code == 0 and valid_key == [] and "jamais synchronisé" in output and '`zc init`' in output
    assert 'ZOTERO_API_KEY' not in init.read_env(tmp_path) and (tmp_path / 'config.toml').is_file()


def test_language_written_in_new_config(tmp_path, zotero):
    """D221: a new folder writes `[methode] langue`, with the comments of config.toml in that language. Keys and
    values stay French (D209)."""
    zotero.save()
    run(tmp_path / 'fr', zotero)
    text = (tmp_path / 'fr' / 'config.toml').read_text(encoding='utf-8')
    assert 'langue = "fr"' in text and '# Collections racines.' in text
    with language('en'):
        code = init.initialize(tmp_path / 'en', zotero.folder, False, lambda _: '', lambda _: '', lambda _: None, 'en')
    text = (tmp_path / 'en' / 'config.toml').read_text(encoding='utf-8')
    assert code == 0 and 'langue = "en"' in text and '# Root collections.' in text and 'Collections racines' not in text
    assert 'fonds = "Subjects"' in text and '[confidentialite]' in text and 'Better BibTeX not detected' in text
    assert 'method.md' in text and (tmp_path / 'en' / 'method.md').is_file() and not (tmp_path / 'en' / 'methode.md').exists()
    cfg = config.load(tmp_path / 'en')
    assert cfg.method.language == 'en' and cfg.zotero_dir == zotero.folder
    french = config.to_stored(config.load(tmp_path / 'fr'))
    english = config.to_stored(cfg)
    # D227: only the names of the profile differ, written in full in both new files.
    assert english == french | {'methode': french['methode'] | config.PROFILES['en']['methode'] | {'langue': 'en'},
                                'confidentialite': french['confidentialite'] | {'tags_exclus': ['_private']}}
    assert 'fonds = "Fonds"' in (tmp_path / 'fr' / 'config.toml').read_text(encoding='utf-8')
    assert 'etats = ["1 to read", "2 reading", "3 read"]' in text and 'tags_exclus = ["_private"]' in text


def test_profile_completes_missing_names(tmp_path):
    """D227: a key absent from config.toml takes the name of the library's language, a key present is kept."""
    (tmp_path / 'config.toml').write_text('[zotero]\ndossier = "~/Zotero"\n[methode]\nlangue = "en"\n'
                                          'archives = "Old"\n', encoding='utf-8')
    cfg = config.load(tmp_path)
    assert (cfg.method.subjects, cfg.method.projects, cfg.method.archives) == ('Subjects', ['Projects'], 'Old')
    assert cfg.method.statuses == ['1 to read', '2 reading', '3 read'] and cfg.privacy.excluded_tags == ['_private']
    cfg.method.projects.append('Courses')
    assert config.load(tmp_path).method.projects == ['Projects']
    (tmp_path / 'config.toml').write_text('[zotero]\ndossier = "~/Zotero"\n', encoding='utf-8')
    cfg = config.load(tmp_path)
    assert (cfg.method.subjects, cfg.privacy.excluded_tags) == ('Fonds', ['_privé'])


def test_choose_language(tmp_path):
    shown = []
    new = tmp_path / 'nouveau'
    assert init.choose_language(new, 'en', False, None, shown.append) == 'en'
    assert init.choose_language(new, None, False, None, shown.append) is None  # no terminal: the option is required
    assert '--library-language fr' in shown[-1] and 'Pas de terminal interactif' in shown[-1]
    answers = ['de', 'EN']
    assert init.choose_language(new, None, False, lambda _: answers.pop(0), shown.append) == 'en'
    assert init.choose_language(new, None, False, lambda _: '', shown.append) is None
    # An existing folder keeps its language, a different one is refused (no conversion, D214).
    new.mkdir()
    (new / 'config.toml').write_text('[zotero]\ndossier = "x"\n', encoding='utf-8')
    assert init.choose_language(new, None, False, None, shown.append) == 'fr'
    assert init.choose_language(new, 'fr', True, None, shown.append) == 'fr'
    assert init.choose_language(new, 'en', False, None, shown.append) is None
    assert 'aucune conversion' in shown[-1] and 'en français' in shown[-1]


def test_init_command_with_library_language(tmp_path, zotero, monkeypatch, capsys):
    """`zc init --library-language` through the command line, without a terminal (an agent): English before the
    choice (D222), then the language chosen."""
    import io
    from zot_clean.cli import main
    zotero.save()
    monkeypatch.setattr('sys.stdin', io.StringIO(''))
    workspace = tmp_path / 'work'
    assert main(['init', str(workspace), '--zotero-dir', str(zotero.folder)]) == 1
    assert 'zc init --library-language en' in capsys.readouterr().out and not workspace.exists()
    assert main(['init', str(workspace), '--zotero-dir', str(zotero.folder), '--library-language', 'en']) == 0
    output = capsys.readouterr().out
    assert 'Step skipped' in output and 'Working folder ready' in output and 'Dossier' not in output
    assert config.load(workspace).method.language == 'en'
    assert main(['init', str(workspace), '--zotero-dir', str(zotero.folder), '--library-language', 'fr']) == 1
    assert 'no conversion' in capsys.readouterr().out
    assert main(['init', str(workspace), '--update']) == 0
    assert 'Updated: AGENTS.md' in capsys.readouterr().out


def test_messages_in_english(tmp_path, zotero, valid_key):
    zotero.account(777, 'institution')
    zotero.save()
    with language('en'):
        code, output = run(tmp_path, zotero, secrets=['MAUVAISE', 'BONNE'])
    assert code == 0 and 'Zotero database found in' in output and ' Try again.' in output
    assert 'with the account that Zotero syncs on this computer, “institution” (no. 777)' in output
    assert 'config.toml written' in output and 'Next step, `zc audit` in this folder.' in output
