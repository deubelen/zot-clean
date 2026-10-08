"""Words read back from the workspace files (D209, phase 0 of the move to English).

These words are both displayed and read back: a « thème » fate is written in
`suivi/fonds.toml` and decides the filing, a « fait » status in a journal
makes a group be skipped on resume. Each test starts from the word as it is written
in a version 0.3.2 file and checks what `zc` does with it, so that the
translation of a displayed text cannot change a behavior.
"""

import json

import pytest

from fake_server import FakeServer
from test_apply import write, titles_plan
from zot_clean import (apply as a, audit, citation_keys, config, checkup, duplicates as d, api, subjects as f, init,
                       inbox, journal as jl, reader, metadata as m, filenames, attachments as p, plans, filing as r,
                       tags as t)
from zot_clean.config import Config
from zot_clean.plans import Group, Operation, Plan


@pytest.fixture
def cfg(tmp_path, zotero):
    c = Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)
    c.tracking.mkdir(parents=True)
    return c


def tracking(cfg, file: str, text: str) -> None:
    (cfg.tracking / file).write_text(text, encoding='utf-8')


# --- plan.md ----------------------------------------------------------------------------

@pytest.mark.parametrize('line, attribute', [
    ('Inclut. Psychophysique.', 'includes'), ('Inclut : Psychophysique.', 'includes'),
    ('**Inclut.** Psychophysique.', 'includes'), ('inclut. Psychophysique.', 'includes'),
    ('Exclut. Psychophysique.', 'excludes'), ('_Exclut :_ Psychophysique.', 'excludes'),
    ('Includes. Psychophysique.', 'includes'), ('**Excludes:** Psychophysique.', 'excludes'),
])
def test_includes_and_excludes_of_outline(cfg, line, attribute):
    text = f'# Fonds\n\n## Psychologie\n\nEsprit.\n{line}\n'
    node = f.read_outline(text, cfg).nodes['Psychologie']
    assert getattr(node, attribute) == 'Psychophysique.' and node.definition == 'Esprit.'


# --- suivi/fonds.toml: fates of the old collections -----------------------------------

@pytest.mark.parametrize('word, action', [('thème', 'thème'), ('theme', 'thème'), ('répartir', 'répartir'),
                                       ('repartir', 'répartir'), ('projet', 'projet'), ('archives', 'archives'),
                                       ('dissoudre', 'dissoudre'), ('hors plan', 'hors plan')])
def test_subjects_action(cfg, word, action):
    tracking(cfg, f.FILE, f'[[collection]]\ncle = "AAAA2222"\nsort = "{word}"\n')
    assert f.load_tracking(cfg).collections[0].action == action


def test_unknown_subjects_action(cfg):
    tracking(cfg, f.FILE, '[[collection]]\ncle = "AAAA2222"\nsort = "theme du plan"\n')
    with pytest.raises(SystemExit, match='sort inconnu'):
        f.load_tracking(cfg)


# --- suivi/rangement.toml -----------------------------------------------------------------

def filing(cfg, **fields) -> r.Entry:
    lines = ''.join(f'{k} = {d._toml(v)}\n' for k, v in fields.items())
    tracking(cfg, r.FILE, '[[fiche]]\ncle = "AAAA2222"\n' + lines)
    return r.load(cfg)[0]


@pytest.mark.parametrize('word, action', [('déplacer', 'déplacer'), ('deplacer', 'déplacer'), ('ajouter', 'ajouter'),
                                         ('corbeille', 'corbeille')])
def test_filing_action(cfg, word, action):
    assert filing(cfg, action=word, cible='Arts').action == action


@pytest.mark.parametrize('word', ['', 'accepter', 'refuser'])
def test_filing_decision(cfg, word):
    assert filing(cfg, action='ajouter', cible='Arts', decision=word).decision == word


@pytest.mark.parametrize('word', ['agent', 'tag', 'consigne'])
def test_filing_source(cfg, word):
    assert filing(cfg, action='ajouter', cible='Arts', source=word).source == word


def test_tag_cited_by_filing_proposal(cfg, zotero):
    """The note « tag « … » » of a pending « tag » source proposal protects this tag at step 6 (D156)."""
    zotero.item('Une fiche', tags=('perception visuelle', 'autre'))
    filing(cfg, action='déplacer', cible='Arts', source='tag', note='tag « perception visuelle »')
    analysis = t._Analysis(reader.read(zotero.save()), cfg)
    assert analysis.waiting == {'perception visuelle'}


# --- suivi/tags.toml -----------------------------------------------------------------------

def tag(cfg, **fields) -> t.Entry:
    lines = ''.join(f'{k} = {d._toml(v)}\n' for k, v in fields.items())
    tracking(cfg, t.FILE, '[[tag]]\nnom = "mémoire"\n' + lines)
    return t.load(cfg).tags[0]


@pytest.mark.parametrize('word, action', [('supprimer', 'supprimer'), ('garder', 'garder'), ('concept', 'concept'),
                                       ('état', 'état'), ('etat', 'état'), ('fusionner', 'fusionner')])
def test_action_of_tag(cfg, word, action):
    assert tag(cfg, sort=word).action == action


@pytest.mark.parametrize('word', ['zc', 'agent', 'utilisateur'])
def test_source_of_tag(cfg, word):
    assert tag(cfg, source=word).source == word


@pytest.mark.parametrize('word', ['', 'accepter', 'refuser'])
def test_decision_of_tag(cfg, word):
    assert tag(cfg, sort='supprimer', decision=word).decision == word


@pytest.mark.parametrize('word, accepted', [('évident', True), ('douteux', False)])
def test_grade_of_tag(cfg, word, accepted):
    tag(cfg, sort='supprimer', classe=word)
    s = t.load(cfg)
    assert t.decide(s, cfg, t.ACCEPT, obvious=True) == int(accepted)
    assert s.tags[0].decision == ('accepter' if accepted else '')


@pytest.mark.parametrize('section', ['automatiques', 'importes'])
def test_global_tag_rules(cfg, section):
    tracking(cfg, t.FILE, f'[{section}]\nsort = "supprimer"\ndecision = "accepter"\n')
    assert getattr(t.load(cfg), t.SECTIONS[section]) == 'accepter'
    tracking(cfg, t.FILE, f'[{section}]\nsort = "garder"\ndecision = "accepter"\n')
    with pytest.raises(SystemExit):
        t.load(cfg)


# --- suivi/doublons.toml, pieces.toml, metadonnees.toml, cles.toml ----------------------------

@pytest.mark.parametrize('word', ['', 'fusionner', 'distinct'])
def test_decision_of_duplicate_group(cfg, word):
    tracking(cfg, d.FILE, f'[[groupe]]\ncles = ["AAAA2222", "BBBB2222"]\ndecision = "{word}"\n')
    assert d.load_tracking(cfg)[0].decision == word


@pytest.mark.parametrize('word, is_merged', [('sûr', True), ('à juger', False)])
def test_grade_of_duplicate_group(cfg, word, is_merged):
    tracking(cfg, d.FILE, f'[[groupe]]\ncles = ["AAAA2222", "BBBB2222"]\nclasse = "{word}"\n')
    entries = d.load_tracking(cfg)
    d.decide(entries, certain=True)
    assert entries[0].decision == ('fusionner' if is_merged else '')


@pytest.mark.parametrize('word', ['', 'appliquer', 'garder'])
def test_decision_of_pdf_group(cfg, word):
    tracking(cfg, p.FILE, f'[[pdf]]\ncopies = ["AAAA2222", "BBBB2222"]\ndecision = "{word}"\n')
    assert p.load(cfg)[0].decision == word


def cases(cfg, **fields) -> m.Case:
    default = {'cle': 'AAAA2222', 'sous_etape': 'identifiants', 'probleme': 'doi_inconnu'}
    lines = ''.join(f'{k} = {d._toml(v)}\n' for k, v in (default | fields).items())
    tracking(cfg, m.FILE, '[[cas]]\n' + lines + '[[cas.propositions]]\nchamps = { DOI = "" }\n')
    return m.load_tracking(cfg)[0]


@pytest.mark.parametrize('word', ['', 'accepter', 'refuser'])
def test_decision_of_metadata_case(cfg, word):
    assert cases(cfg, decision=word).decision == word


@pytest.mark.parametrize('word, accepted', [('évident', True), ('douteux', False)])
def test_grade_of_metadata_case(cfg, word, accepted):
    x = cases(cfg, classe=word)
    m.decide([x], obvious=True)
    assert x.decision == ('accepter' if accepted else '')


def test_substeps_and_metadata_problems():
    """Sub-steps and problems read back from `metadonnees.toml`: they are also the steps of the step 3 plans."""
    assert (m.IDENTIFIERS, m.TYPES, m.FILL_IN) == ('identifiants', 'types', 'completer')
    import inspect
    source = inspect.getsource(m)
    for problem in ('doi_inconnu', 'doi_discordant', 'doi_malforme', 'doi_manquant', 'isbn_discordant',
                     'type_doublon', 'forcer'):
        assert f"'{problem}'" in source, problem


def test_case_forced_by_hand(cfg):
    """The « forcer » case that the header teaches to add by hand is carried over as is by the next plan."""
    x = cases(cfg, sous_etape='completer', probleme='forcer', decision='accepter', forcer={'volume': '12'})
    assert (x.substep, x.problem, x.retained()) == ('completer', 'forcer', {'DOI': '', 'volume': '12'})


@pytest.mark.parametrize('section, word', [('double', ''), ('double', 'écarter'), ('extra', ''), ('extra', 'natif'),
                                          ('extra', 'extra'), ('extra', 'écarter')])
def test_decision_of_citation_keys_case(cfg, section, word):
    entry = 'fiches = ["AAAA2222", "BBBB2222"]' if section == 'double' else 'fiche = "AAAA2222"'
    tracking(cfg, citation_keys.FILE, f'[[{section}]]\n{entry}\ndecision = "{word}"\n')
    s = citation_keys.load(cfg)
    assert (s.doubles if section == 'double' else s.extra)[0].decision == word


@pytest.mark.parametrize('word, decision', [('garder', 'garder'), ('garde', 'garder'), ('écarter', 'écarter'),
                                           ('ecarter', 'écarter'), ('natif', 'natif'), ('extra', 'extra')])
def test_decision_of_zc_citation_keys_decide(word, decision):
    assert citation_keys.DECISIONS[word] == decision


# --- Journals ------------------------------------------------------------------------------

def journal(folder, name, header: dict, *lines: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    everything = [{'type': 'en-tete', 'empreinte': 'e1', 'mode': 'essai', 'annule': [], **header}, *lines]
    (folder / name).write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in everything), encoding='utf-8')


@pytest.mark.parametrize('status, is_done', [('fait', True), ('partiel', True), ('conflit', False), ('erreur', False)])
def test_status_of_group(tmp_path, status, is_done):
    """A « fait » or « partiel » group is not redone on resume (D37)."""
    journal(tmp_path, '2026-01-01_000000_tags.jsonl', {}, {'type': 'groupe', 'id': 'g1', 'statut': status})
    assert jl.done_groups(tmp_path, 'e1') == ({'g1'} if is_done else set())


@pytest.mark.parametrize('mode, trial', [('essai', True), ('tout', False)])
def test_mode_of_journal(tmp_path, mode, trial):
    journal(tmp_path, '2026-01-01_000000_tags.jsonl', {'mode': mode}, {'type': 'groupe', 'id': 'g1', 'statut': 'fait'})
    assert jl.trial_done(tmp_path, 'e1') == trial


def test_line_types_and_undo(tmp_path):
    """« intention » without « element »: pending write (D178). « fin »: finished journal. `annule` of a header:
    the groups done by the undone journal are reversed (D180)."""
    journal(tmp_path, '2026-01-01_000000_tags.jsonl', {},
            {'type': 'intention', 'groupe': 'g1', 'cle': 'AAAA2222'},
            {'type': 'intention', 'groupe': 'g2', 'cle': 'BBBB2222'},
            {'type': 'element', 'groupe': 'g1', 'cle': 'AAAA2222'},
            {'type': 'groupe', 'id': 'g1', 'statut': 'fait'}, {'type': 'fin'})
    path = tmp_path / '2026-01-01_000000_tags.jsonl'
    assert list(jl.pending([path])) == [('g2', 'BBBB2222')]
    assert jl.summarize(path).finished and jl.summarize(path).all_items == 1
    assert jl.done_groups(tmp_path, 'e1') == {'g1'}
    journal(tmp_path, '2026-01-01_000001_annulation.jsonl', {'empreinte': 'e2', 'annule': [path.name]},
            {'type': 'groupe', 'id': 'g1', 'statut': 'fait'})
    assert jl.done_groups(tmp_path, 'e1') == set()


def test_statuses_written_by_core(zotero, tmp_path):
    """The core writes « fait », « conflit » and « partiel » (undo plan, D39), and the header the « essai »
    mode."""
    server = FakeServer()
    cfg = Config(workspace=tmp_path / 'travail', zotero_dir=zotero.save().parent)
    plan = titles_plan(server, 2)
    server.modify(plan.groups[1].operations[0].key, title='Changé ailleurs')
    outcome = a.apply_plan(plan, write(plan, cfg), server.client(), cfg, a.TRIAL)
    lines = jl.read(outcome.journal)
    assert lines[0]['mode'] == 'essai' and a.TRIAL == 'essai' and a.ALL == 'tout'
    assert [(l['id'], l['statut']) for l in lines if l['type'] == 'groupe'] == [('0', 'fait'), ('1', 'conflit')]
    key = plan.groups[0].operations[0].key
    partial = Plan('annulation', server.user, [Group('a', 'annulation', [
        Operation(key, {'title': 'Titre 0 corrigé', 'date': 'x'}, {'title': 'Titre 0', 'date': 'y'})])], partial=True)
    outcome = a.apply_plan(partial, write(partial, cfg), server.client(), cfg, a.TRIAL)
    assert [l['statut'] for l in jl.read(outcome.journal) if l['type'] == 'groupe'] == ['partiel']


# --- Steps and kinds of plans --------------------------------------------------------------

def test_step_names():
    """Step names written in the plans and in the file names of the plans and journals."""
    assert (citation_keys.STEP, t.STEP, filenames.STEP, inbox.STEP) == ('cles', 'tags', 'noms', 'inbox')
    assert a.MANAGEMENT_STEPS == {'inbox'}


@pytest.mark.parametrize('step, no_trial', [('inbox', True), ('tags', False)])
def test_small_management_plan(cfg, step, no_trial):
    """Only a plan of the « inbox » step touching few items applies without a trial or a backup (D136, D138)."""
    plan = Plan(step, 4242, [Group(str(i), 'g', [Operation(f'AAAA222{i}', {}, {})]) for i in range(8)])
    if no_trial:
        assert len(a.to_process(plan, cfg, a.ALL)) == 8
    else:
        with pytest.raises(api.Refusal, match='essai'):
            a.to_process(plan, cfg, a.ALL)


def test_undo_plan_never_compared_to_newer(cfg):
    plan = Plan('annulation', 4242, [])
    first = plans.write(plan, cfg.plans, '')
    assert plans.newer_plans(first, plans.load(first)) == []


# --- Audit snapshot -------------------------------------------------------------------

def test_audit_snapshot_comparable_to_032(cfg, zotero):
    """An audit compares its points with those of the last snapshot by the title of each check, and its figures by
    their name (D139). A changed title would lose the comparison with the audits already done."""
    from test_v032 import V032
    old = json.loads(next((V032 / 'dossier' / 'suivi' / 'audits').glob('*.json')).read_text(encoding='utf-8'))
    b = reader.read(zotero.save())
    sections = audit.run_audit(b, cfg, fingerprints=False)
    sections.append(checkup.outline_check(b, cfg)[0])
    snap = checkup.snapshot(sections, b)
    assert list(snap['chiffres']) == list(old['chiffres']) == ['référence', 'pièce jointe', 'note', 'collection']
    assert list(snap['points']) == list(old['points'])


# --- .env ---------------------------------------------------------------------------------------

def test_keys_of_env_file(tmp_path):
    init.write_env(tmp_path, ZOTERO_API_KEY='CLE', ZOTERO_USER_ID='4242')
    assert (tmp_path / '.env').read_text(encoding='utf-8') == 'ZOTERO_API_KEY=CLE\nZOTERO_USER_ID=4242\n'
    client = api.from_config(Config(workspace=tmp_path))
    assert client.user == 4242


def test_config_of_032_still_accepted():
    """The 0.3.2 configurations (fixtures) are read without an unknown key."""
    from test_v032 import V032
    for folder in (V032 / 'configs').iterdir():
        config.load(folder)
