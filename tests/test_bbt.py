"""Detection of Better BibTeX in a fake Zotero profile (D145)."""

import json
from pathlib import Path

from zot_clean import bbt

PREFIX = 'extensions.zotero.translators.better-bibtex.'


def write_profile(root: Path, name: str, data: Path | None, extension: dict | None, prefs: dict = (),
                  default: bool = False) -> Path:
    """Profile `root/Profiles/<name>` serving the data folder `data` (None, default folder)."""
    profile = root / 'Profiles' / name
    profile.mkdir(parents=True)
    lines = ['// Mozilla User Preferences', '']
    values = dict(prefs)
    if data is not None:
        values |= {'extensions.zotero.dataDir': str(data), 'extensions.zotero.useDataDir': True}
    for k, v in values.items():
        lines.append(f'user_pref({json.dumps(k)}, {json.dumps(v)});')
    (profile / 'prefs.js').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    if extension is not None:
        addons = [{'id': 'autre@exemple.org', 'version': '1.0', 'active': True}]
        if extension:
            addons.append(dict({'id': bbt.BBT_ID}, **extension))
        (profile / 'extensions.json').write_text(json.dumps({'schemaVersion': 36, 'addons': addons}), encoding='utf-8')
    ini = root / 'profiles.ini'
    text = ini.read_text(encoding='utf-8') if ini.exists() else '[General]\nStartWithLastProfile=1\nVersion=2\n'
    n = text.count('[Profile')
    text += f'\n[Profile{n}]\nName={name}\nIsRelative=1\nPath=Profiles/{name}\n' + ('Default=1\n' if default else '')
    ini.write_text(text, encoding='utf-8')
    return profile


def two_profiles(tmp_path, extension_test: dict | None = None, test_prefs: dict = ()) -> tuple[Path, Path, Path]:
    root = tmp_path / 'Zotero-profils'
    main, test = tmp_path / 'Zotero', tmp_path / 'Zotero Test'
    write_profile(root, 'a1.default', main, {'version': '9.1.0', 'active': True}, default=True)
    test_profile = write_profile(root, 'b2.Test', test, extension_test, test_prefs)
    return root, test, test_profile


def detect(folder, root, personal):
    return bbt.detect(folder, [root], personal)


def test_automatic_tags_setting(tmp_path):
    """D155: the setting is written to prefs.js only if it differs from the default (true)."""
    root, test, _ = two_profiles(tmp_path, test_prefs={'extensions.zotero.automaticTags': False})
    assert bbt.automatic_tags(test, [root], tmp_path) is False
    assert bbt.automatic_tags(tmp_path / 'Zotero', [root], tmp_path) is True
    assert bbt.automatic_tags(tmp_path / 'Ailleurs', [root], tmp_path) is None


def test_picks_profile_of_data_folder(tmp_path):
    prefs = {PREFIX + 'citekeyFormat': 'auth.lower + year', PREFIX + 'fillKeyAfter': 0,
             PREFIX + 'resetKeyOnChange': True, PREFIX + 'citekeyCaseInsensitive': False}
    root, test, profile = two_profiles(tmp_path, {'version': '9.0.40', 'active': True}, prefs)
    state = detect(test, root, tmp_path)
    assert state.profile == profile and state.source == bbt.PROFILE
    assert state.present and state.version == '9.0.40' and state.major == 9 and not state.too_old
    assert state.formula == 'auth.lower + year' and not state.method_formula
    assert state.fill_after == 0 and state.regenerates and state.casing
    main = detect(tmp_path / 'Zotero', root, tmp_path)
    assert main.version == '9.1.0' and main.profile.name == 'a1.default'


def test_missing_preferences_bbt_defaults(tmp_path):
    root, test, _ = two_profiles(tmp_path, {'version': '9.1.0', 'active': True})
    state = detect(test, root, tmp_path)
    assert state.formula == bbt.BBT_FORMULA and state.method_formula
    assert state.fill_after == 2 and not state.regenerates and not state.casing


def test_formula_with_parentheses_and_quotes(tmp_path):
    root, test, _ = two_profiles(tmp_path, {'version': '9.1.0', 'active': True},
                                   {PREFIX + 'citekeyFormat': 'auth.lower + "-" + shorttitle(3, 3) + year'})
    assert detect(test, root, tmp_path).formula == 'auth.lower + "-" + shorttitle(3, 3) + year'


def test_bbt_disabled_counts_as_missing(tmp_path):
    root, test, _ = two_profiles(tmp_path, {'version': '9.1.0', 'active': False})
    state = detect(test, root, tmp_path)
    assert state.installed and not state.active and not state.present
    assert 'désactivé' in bbt.describe(state)


def test_bbt_missing_from_profile(tmp_path):
    for extension in ({}, None):  # entry missing from extensions.json, or no extensions.json
        root, test, _ = two_profiles(tmp_path / str(extension is None), extension)
        state = detect(test, root, tmp_path / str(extension is None))
        assert not state.present and not state.installed and state.source == bbt.PROFILE
    # BBT's old cache folder no longer counts when the profile says BBT is absent.
    (test / 'better-bibtex').mkdir(parents=True)
    assert not detect(test, root, tmp_path / 'True').present


def test_bbt_7_too_old(tmp_path):
    root, test, _ = two_profiles(tmp_path, {'version': '7.0.5', 'active': True})
    state = detect(test, root, tmp_path)
    assert state.present and state.major == 7 and state.too_old
    assert 'trop ancienne' in bbt.describe(state)


def test_profile_without_data_folder_uses_zotero_of_home_folder(tmp_path):
    root = tmp_path / 'profils'
    write_profile(root, 'c3.default', None, {'version': '9.1.0', 'active': True}, default=True)
    assert detect(tmp_path / 'Zotero', root, tmp_path).present
    # useDataDir false: dataDir is not followed.
    write_profile(root, 'd4.autre', None, {'version': '8.0.1', 'active': True},
                  {'extensions.zotero.dataDir': str(tmp_path / 'Ailleurs'), 'extensions.zotero.useDataDir': False})
    assert detect(tmp_path / 'Ailleurs', root, tmp_path).source == bbt.DATA_FOLDER


def test_fallback_to_data_folder(tmp_path):
    root, _, _ = two_profiles(tmp_path, {'version': '9.1.0', 'active': True})
    other = tmp_path / 'Autre'
    other.mkdir()
    state = detect(other, root, tmp_path)
    assert state.source == bbt.DATA_FOLDER and not state.present
    assert 'profil de Zotero introuvable' in bbt.describe(state)
    (other / 'better-bibtex.sqlite').write_bytes(b'')
    state = detect(other, root, tmp_path)
    assert state.present and state.version == '' and state.major is None and not state.too_old
    # Without any profiles folder either.
    assert bbt.detect(other, [], tmp_path).present


def test_profile_paths_per_system(tmp_path):
    assert bbt.profile_paths('darwin', tmp_path) == [tmp_path / 'Library' / 'Application Support' / 'Zotero']
    assert bbt.profile_paths('win32', tmp_path) == [tmp_path / 'AppData' / 'Roaming' / 'Zotero' / 'Zotero']
    assert bbt.profile_paths('win32', tmp_path, str(tmp_path / 'Roaming')) == [
        tmp_path / 'Roaming' / 'Zotero' / 'Zotero']
    assert bbt.profile_paths('linux', tmp_path)[0] == tmp_path / '.zotero' / 'zotero'


def test_profile_found_under_home_folder(tmp_path, monkeypatch):
    """Real path of the current system, with a replaced home folder."""
    import os
    import sys
    root = bbt.profile_paths(sys.platform, tmp_path, str(tmp_path / 'AppData' / 'Roaming'))[0]
    write_profile(root, 'e5.default', tmp_path / 'Données', {'version': '9.1.0', 'active': True}, default=True)
    monkeypatch.undo()  # removes the conftest guard, which prevents reading the profiles
    monkeypatch.setattr(bbt.Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setitem(os.environ, 'APPDATA', str(tmp_path / 'AppData' / 'Roaming'))
    assert bbt.profile_folders()[0] == root
    state = bbt.detect(tmp_path / 'Données')
    assert state.source == bbt.PROFILE and state.version == '9.1.0'


def test_profile_at_absolute_path(tmp_path):
    root = tmp_path / 'profils'
    root.mkdir()
    elsewhere = tmp_path / 'ailleurs'
    write_profile(elsewhere, 'f6', tmp_path / 'Z', {'version': '9.0.0', 'active': True})
    (root / 'profiles.ini').write_text(f'[Profile0]\nName=x\nIsRelative=0\nPath={elsewhere / "Profiles" / "f6"}\n',
                                         encoding='utf-8')
    assert detect(tmp_path / 'Z', root, tmp_path).version == '9.0.0'


def test_file_storage_read_in_profile(tmp_path):
    # D157: zotero.org by default, WebDAV, file synchronisation disabled, profile not found.
    root = tmp_path / 'Zotero-profils'
    cases = {'Defaut': ({}, bbt.ZOTERO_ORG),
           'Webdav': ({'extensions.zotero.sync.storage.protocol': 'webdav'}, bbt.WEBDAV),
           'Aucune': ({'extensions.zotero.sync.storage.enabled': False,
                       'extensions.zotero.sync.storage.protocol': 'webdav'}, bbt.NONE)}
    for name, (prefs, expected) in cases.items():
        write_profile(root, name, tmp_path / name, None, prefs)
        assert bbt.file_storage(tmp_path / name, [root], tmp_path) == expected
    assert bbt.file_storage(tmp_path / 'Ailleurs', [root], tmp_path) == bbt.UNKNOWN


def test_zotero_language(tmp_path):
    root = tmp_path / 'Zotero-profils'
    cases = {'Choisie': ({'intl.locale.requested': 'de', 'intl.accept_languages': 'fr, en'}, 'de'),
           'Systeme': ({'intl.accept_languages': 'fr-BE, fr, en-us'}, 'fr'), 'Rien': ({}, '')}
    for name, (prefs, expected) in cases.items():
        write_profile(root, name, tmp_path / name, None, prefs)
        assert bbt.zotero_language(tmp_path / name, [root], tmp_path) == expected
    assert bbt.zotero_language(tmp_path / 'Ailleurs', [root], tmp_path) == ''


def test_describe_in_english(tmp_path):
    from zot_clean.lang import language
    root, test, _ = two_profiles(tmp_path, {"version": "9.1.0", "active": False})
    state = detect(test, root, tmp_path)
    with language("en"):
        assert "installed but disabled in Zotero" in bbt.describe(state)


def test_download_mode_read_in_profile(tmp_path):
    """D242, pilot bench: once Zotero downloads at sync time, the advice to set it is not repeated."""
    from zot_clean.audit import download_advice
    root = tmp_path / 'Zotero-profils'
    write_profile(root, 'Sync', tmp_path / 'Sync', None, {'extensions.zotero.sync.storage.downloadMode.personal': 'on-sync'})
    write_profile(root, 'Demande', tmp_path / 'Demande', None, {})
    assert bbt.downloads_at_sync(tmp_path / 'Sync', [root], tmp_path)
    assert not bbt.downloads_at_sync(tmp_path / 'Demande', [root], tmp_path)
    assert not bbt.downloads_at_sync(tmp_path / 'Ailleurs', [root], tmp_path)
    assert 'au moment de la synchronisation », puis' in download_advice(bbt.ZOTERO_ORG)
    assert 'point 5 de l\'audit' in download_advice(bbt.ZOTERO_ORG, at_sync=True)
