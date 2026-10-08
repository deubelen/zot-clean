"""Golden fixtures of version 0.3.2 (D209, phase 0 of the move to English).

`tests/donnees/v032/` keeps what 0.3.2 wrote on disk, produced by
`generer.py` on the synthetic library: a complete working folder
(plans of each step, journals, `suivi/` files, subject-plan validation,
audit snapshot, `config.toml`), the same plans in format 1, three
configurations and a backup description. `attendu.json` gives what
0.3.2 derived from them. Today's code must read these files with exactly
the same results, and a plan read then rewritten must give back its file.

The fixtures are never regenerated: they freeze a format that existing working
folders keep (D209). Results are expressed in the vocabulary of the files
(stored keys and values), never in that of the Python code, so that
renaming the code leaves `attendu.json` untouched.
"""

import json
import shutil
import tomllib
from dataclasses import fields
from datetime import date
from pathlib import Path

import pytest

from zot_clean import (citation_keys, config, checkup, duplicates, subjects, journal as jl, metadata, attachments, plans,
                       filing, backup, sources, tags)
from zot_clean.reader import Library, Collection, Item

V032 = Path(__file__).parent / 'donnees' / 'v032'
FAR_FUTURE = date(2100, 1, 1)  # day of an audit later than all those of the fixtures


# --- What is derived from the files, in the vocabulary of the files ------------------

def plan_summary(plan: plans.Plan) -> dict:
    return {'format': plan.format, 'empreinte': plan.fingerprint, 'etape': plan.step,
            'bibliotheque': plan.library, 'partiel': plan.partial, 'annule': plan.undoes,
            'groupes': [g.id for g in plan.groups], 'operations': plan.n_operations}


def journal_summary(r: jl.Summary) -> dict:
    return {'en_tete': {k: v for k, v in r.header.items() if k not in ('debut', 'zc')},
            'groupes': r.groups, 'elements': r.all_items, 'termine': r.finished}


def plans_state(folder: Path) -> dict:
    """For each plan of the folder, what the journals say about it: groups done, trial, pending intents."""
    res = {}
    for path in sorted((folder / 'plans').glob('*.json')):
        e = plans.load(path).fingerprint
        res[path.name] = {
            'groupes_faits': sorted(jl.done_groups(folder / 'journal', e)),
            'essai_fait': jl.trial_done(folder / 'journal', e),
            'en_suspens': sorted(list(k) for k in jl.pending([r.path for r in jl.for_plan(folder / 'journal', e)])),
        }
    return res


def duplicates_tracking(cfg) -> list:
    return [{'cles': e.keys, 'classe': e.grade, 'decision': e.decision, 'conserver': e.keep,
             'raison': e.reason, 'forcer': e.force} for e in duplicates.load_tracking(cfg)]


def attachments_tracking(cfg) -> list:
    return [{'copies': e.copies, 'decision': e.decision, 'corbeille': e.trash, 'rattacher': e.move,
             'raison': e.reason} for e in attachments.load(cfg)]


def metadata_tracking(cfg) -> list:
    return [{'cle': c.key, 'sous_etape': c.substep, 'probleme': c.problem, 'decision': c.decision,
             'choix': c.selection, 'forcer': c.force, 'classe': c.grade,
             'propositions': [{'champs': p.fields, 'source': p.source, 'note': p.note, 'avis': p.verdict}
                              for p in c.proposals]} for c in metadata.load_tracking(cfg)]


def subjects_tracking(cfg) -> dict:
    s = subjects.load_tracking(cfg)
    return {'collection': [{'cle': c.key, 'chemin': c.path, 'effectif': c.count, 'sort': c.action,
                            'cible': c.target, 'candidats': c.candidates, 'note': c.note} for c in s.collections],
            'racines': s.roots, 'tags': s.tags}


def filing_tracking(cfg) -> list:
    return [{'cle': e.key, 'action': e.action, 'cible': e.target, 'depuis': e.origin, 'source': e.source,
             'decision': e.decision, 'note': e.note} for e in filing.load(cfg)]


def tags_tracking(cfg) -> dict:
    s = tags.load(cfg)
    return {'automatiques': s.automatic, 'importes': s.imported,
            'resume_automatiques': s.automatic_summary, 'resume_importes': s.imported_summary,
            'tag': [{'nom': e.name, 'type': e.type, 'effectif': e.count, 'dispersion': e.dispersion,
                     'themes': e.themes, 'theme': e.theme, 'recherches': e.searches, 'sort': e.action,
                     'cible': e.target, 'source': e.source, 'classe': e.grade, 'decision': e.decision,
                     'note': e.note, 'variantes': e.variants} for e in s.tags],
            'variantes': [{'noms': g.names, 'cible': g.target, 'classe': g.grade, 'source': g.source,
                           'decision': g.decision, 'note': g.note} for g in s.variants]}


def citation_keys_tracking(cfg) -> dict:
    s = citation_keys.load(cfg)
    return {'double': [{'fiches': d.items, 'garde': d.keeper, 'decision': d.decision, 'raison': d.reason}
                       for d in s.doubles],
            'extra': [{'fiche': e.item, 'decision': e.decision, 'raison': e.reason} for e in s.extra]}


def library_of_left_out(cfg) -> Library:
    """Library where each remaining item is still in the recorded collections, as at the time of the decision."""
    raw = json.loads((cfg.tracking / filing.LEFT_OUT).read_text(encoding='utf-8'))
    cols = {k: Collection(i, k, k, None, True)
            for i, k in enumerate(sorted({c for d in raw.values() for c in d['collections']}), 1000)}
    all_items = {i: Item(i, k, 'journalArticle', '', True, collections={cols[c].id for c in d['collections']})
                for i, (k, d) in enumerate(raw.items(), 1)}
    return Library(0, all_items, {c.id: c for c in cols.values()}, {}, {}, [])


def tracking(cfg) -> dict:
    k = subjects.check(cfg)
    previous = checkup.previous(cfg, FAR_FUTURE)
    return {
        'doublons.toml': duplicates_tracking(cfg),
        'pieces.toml': attachments_tracking(cfg),
        'metadonnees.toml': metadata_tracking(cfg),
        'fonds.toml': subjects_tracking(cfg),
        'rangement.toml': filing_tracking(cfg),
        'tags.toml': tags_tracking(cfg),
        'cles.toml': citation_keys_tracking(cfg),
        'rangement-examinees.json': {c: sorted(v) for c, v in filing.load_reviewed(cfg).items()},
        'rangement-laissees.json': sorted(filing.load_left_out(library_of_left_out(cfg), cfg)),
        'fonds-validation.json': {'empreinte': k.fingerprint, 'deja_valide': k.already_validated, 'erreurs': k.errors,
                                  'changements': k.changes, 'a_jour': list(subjects.validation_up_to_date(cfg))},
        'fonds-collections.json': checkup.read_memory(cfg),
        'audits': {'jour': previous[0].isoformat(), 'instantane': previous[1]} if previous else None,
    }


def backups(folder: Path) -> list:
    cfg = config.Config(workspace=folder, zotero_dir=Path('/zotero-factice/Zotero'))
    cfg.backup.folder = folder / 'sauvegardes'
    return [{'dossier': i.folder.name, 'date': i.date.isoformat(), 'methode': i.method,
             'version_bibliotheque': i.library_version, 'taille': i.size,
             'dossier_zotero': i.zotero_dir.as_posix() if i.zotero_dir else None}
            for i in backup.list_backups(cfg)]


def cache(folder: Path) -> dict:
    """Source responses reread as works, then put back into their stored form."""
    def reloaded(v):
        if isinstance(v, dict):
            return sources.work_to_stored(sources.read_work(v))
        return [reloaded(x) for x in v] if isinstance(v, list) else v
    return {p.name: {k: reloaded(v) for k, v in json.loads(p.read_text(encoding='utf-8')).items()}
            for p in sorted((folder / 'cache').glob('*.json'))}


# Keys added to config.toml after version 0.3.2, with the value a 0.3.2 folder gets (D221: French).
ADDED_KEYS = {('methode', 'langue'): 'fr'}


def stored_032(cfg) -> dict:
    """Effective configuration under the keys of version 0.3.2. The keys added since must take their default."""
    stored = config.to_stored(cfg)
    for (section, key), value in ADDED_KEYS.items():
        assert stored[section].pop(key) == value, (section, key)
    return stored


def results(root: Path) -> dict:
    """Everything the code derives from the fixtures of `root` (a copy of `tests/donnees/v032/`)."""
    folder = root / 'dossier'
    cfg = config.load(folder)
    return {
        'plans': {f'{p.parent.name}/{p.name}': plan_summary(plans.load(p))
                  for d in ('dossier/plans', 'format1') for p in sorted((root / d).glob('*.json'))},
        'journaux': {r.path.name: journal_summary(r) for r in jl.all_entries(folder / 'journal')},
        'etat_des_plans': plans_state(folder),
        'suivi': tracking(cfg),
        'configs': {d.name: stored_032(config.load(d)) for d in sorted((root / 'configs').iterdir())}
                   | {'dossier': stored_032(cfg)},
        'sauvegardes': backups(root),
        'cache': cache(folder),
    }


# --- Tests --------------------------------------------------------------------------

@pytest.fixture(scope='module')
def copy(tmp_path_factory) -> Path:
    """Copy of the fixtures, so that no read can modify them."""
    target = tmp_path_factory.mktemp('v032') / 'v032'
    shutil.copytree(V032, target, ignore=shutil.ignore_patterns('generer.py', '__pycache__'))
    return target


@pytest.fixture(scope='module')
def expected() -> dict:
    return json.loads((V032 / 'attendu.json').read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def actual(copy) -> dict:
    return json.loads(json.dumps(results(copy), ensure_ascii=False))  # tuples and keys as in attendu.json


@pytest.mark.parametrize('part', ['plans', 'journaux', 'etat_des_plans', 'configs', 'sauvegardes', 'cache'])
def test_read_like_032(actual, expected, part):
    assert actual[part] == expected[part]


@pytest.mark.parametrize('file', ['doublons.toml', 'pieces.toml', 'metadonnees.toml', 'fonds.toml',
                                     'rangement.toml', 'tags.toml', 'cles.toml', 'rangement-examinees.json',
                                     'rangement-laissees.json', 'fonds-validation.json', 'fonds-collections.json',
                                     'audits'])
def test_tracking_read_like_032(actual, expected, file):
    assert actual['suivi'][file] == expected['suivi'][file]


def test_complete_fixtures(expected):
    """One plan of each step in both formats, and the journals that phase 0 asks for (D209)."""
    steps = {p['etape'] for p in expected['plans'].values()}
    assert steps == {'doublons', 'pieces', 'identifiants', 'types', 'completer', 'fonds', 'tags', 'cles', 'noms',
                      'inbox', 'annulation'}
    for f in (1, 2):
        assert {p['etape'] for p in expected['plans'].values() if p['format'] == f} == steps
    journals = expected['journaux'].values()
    assert any(j['en_tete']['mode'] == 'essai' and j['termine'] for j in journals)
    assert any('partiel' in j['groupes'].values() for j in journals)
    assert any('conflit' in j['groupes'].values() for j in journals)
    assert any(not j['termine'] for j in journals)
    assert any(e['en_suspens'] for e in expected['etat_des_plans'].values())
    assert any(e['essai_fait'] and e['groupes_faits'] for e in expected['etat_des_plans'].values())
    assert any(j['en_tete'].get('annule') for j in journals)


@pytest.mark.parametrize('name', sorted(p.name for p in (V032 / 'dossier' / 'plans').glob('*.json')))
def test_plan_read_then_rewritten_identically(copy, name):
    """A format 2 plan read then rewritten gives back its file. A format 1 plan is never rewritten, its
    fingerprint is checked on reading (`plans.load`)."""
    file = copy / 'dossier' / 'plans' / name
    assert plans.to_stored(plans.load(file)) == json.loads(file.read_text(encoding='utf-8'))


EMPTY = Library(0, {}, {}, {}, {}, [])


@pytest.mark.parametrize('file, reread, rewrite', [
    ('doublons.toml', duplicates.load_tracking, lambda cfg, x: duplicates.write_tracking(cfg, x, EMPTY)),
    ('pieces.toml', attachments.load, lambda cfg, x: attachments.write(cfg, x, EMPTY)),
    ('metadonnees.toml', metadata.load_tracking, lambda cfg, x: metadata.write_tracking(cfg, x, EMPTY)),
    ('fonds.toml', subjects.load_tracking, subjects.write_tracking),
    ('rangement.toml', filing.load, lambda cfg, x: filing.write(cfg, x, EMPTY, set())),
    ('tags.toml', tags.load, lambda cfg, x: tags.write(cfg, x, EMPTY)),
])
def test_tracking_read_then_rewritten_with_same_keys(copy, tmp_path, file, reread, rewrite):
    """The file rewritten by zc holds the same keys and values (the comments describe the library)."""
    folder = tmp_path / 'travail'
    shutil.copytree(copy / 'dossier', folder)
    cfg = config.load(folder)
    before = tomllib.loads((cfg.tracking / file).read_text(encoding='utf-8'))
    rewrite(cfg, reread(cfg))
    assert tomllib.loads((cfg.tracking / file).read_text(encoding='utf-8')) == before


def test_stored_fields_tables_complete():
    """Each attribute of a plan, a cached work or the configuration has its key in the file (D209): an attribute added
    without a key would be neither written nor read, an attribute renamed without updating the table would be
    refused here."""
    for table, cls in ((plans.PLAN_FIELDS, plans.Plan), (plans.GROUP_FIELDS, plans.Group),
                          (plans.OPERATION_FIELDS, plans.Operation)):
        assert set(table.values()) == {f.name for f in fields(cls)} - {'format'}
    assert set(sources.WORK_FIELDS.values()) == {f.name for f in fields(sources.Work)}
    assert {a for a, _, _ in config.KEYS.values()} == {f.name for f in fields(config.Config)} - {
        'workspace', 'zotero_dir'}
    for attribute, cls, keys_ in config.KEYS.values():
        assert type(getattr(config.Config(Path('.')), attribute)) is cls
        assert set(keys_.values()) == {f.name for f in fields(cls)}


def test_journal_written_with_032_keys(zotero, tmp_path):
    """The lines the core writes today have, type by type, the keys of those of 0.3.2."""
    from fake_server import FakeServer
    from test_apply import write, titles_plan
    from zot_clean.apply import TRIAL, apply_plan
    forms = {}
    for path in (V032 / 'dossier' / 'journal').glob('*.jsonl'):
        for line in jl.read(path):
            forms.setdefault(line['type'], set()).add(frozenset(line))
    server = FakeServer()
    cfg = config.Config(workspace=tmp_path / 'travail', zotero_dir=zotero.save().parent)
    plan = titles_plan(server, 2)
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    lines = jl.read(outcome.journal)
    assert {l['type'] for l in lines} == {'en-tete', 'intention', 'element', 'groupe', 'fin'} == set(forms)
    for line in lines:
        assert frozenset(line) in forms[line['type']], line


def test_sources_cache_served_offline(copy):
    """A response cached by 0.3.2 is still served, without a new request."""
    import httpx2

    def reject(request):
        raise AssertionError(f'requête inattendue : {request.url}')
    crossref = sources.Crossref(copy / 'dossier' / 'cache', client_http=httpx2.Client(
        transport=httpx2.MockTransport(reject)))
    o = crossref.work('10.1111/color')
    assert (o.title, o.year, o.authors) == ('Acquisition of categorical color perception', '2002', [['Özgen', 'Emre']])
    assert crossref.work('10.1111/inexistant') is None
