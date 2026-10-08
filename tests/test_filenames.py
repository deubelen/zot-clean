"""File names computed as Zotero does (step 8, D148, D150).

The expected values follow the code of Zotero 10.0.5 (`getFileBaseNameFromItem`, `templates.mjs`,
`firstCreator` de `items.js`, `getValidFileName`, `getBestAttachments`)."""

import itertools
import json
from pathlib import Path

import pytest

from fake_server import FakeServer
from test_undo import undo_plan
from test_apply import write, fake_backup
from zot_clean import bbt, config, privacy, reader, filenames, plans
from zot_clean.apply import TRIAL, ALL, apply_plan
from zot_clean.config import Config
from zot_clean.api import Refusal

DEFAULT = filenames.DEFAULT_TEMPLATE


def compute(zotero, item: int, template: str = DEFAULT, conjunction: str | None = ' et ', name: str = 'x.pdf',
             **options) -> str:
    attachment = zotero.pdf(item, name, **options)
    b = reader.read(zotero.save())
    return filenames.expected_name(b.all_items[item], b.attachments[attachment], b, filenames.Template.analyze(template),
                            filenames.Rules.of(b, conjunction))


@pytest.mark.parametrize('authors, expected', [
    (('Durand',), 'Durand - 2020 - Titre.pdf'),
    (('Durand', 'Martin'), 'Durand et Martin - 2020 - Titre.pdf'),
    (('Durand', 'Martin', 'Petit'), 'Durand et al. - 2020 - Titre.pdf'),
    ((), '2020 - Titre.pdf'),
])
def test_default_template_by_number_of_authors(zotero, authors, expected):
    assert compute(zotero, zotero.item('Titre', authors=authors)) == expected


def test_english_conjunction(zotero):
    f = zotero.item('Titre', authors=('Durand', 'Martin'))
    assert compute(zotero, f, conjunction=' and ') == 'Durand and Martin - 2020 - Titre.pdf'


def test_without_year_suffix_disappears(zotero):
    # A suffix is only added to a non-empty value: « Auteur - Titre » (D150).
    assert compute(zotero, zotero.item('Titre', date='')) == 'Durand - Titre.pdf'
    assert compute(zotero, zotero.item('Titre', date='0000-00-00 s. d.')) == 'Durand - Titre.pdf'
    # Date that Zotero could not read, kept without its SQL part: empty year.
    assert compute(zotero, zotero.item('Titre', date='printemps')) == 'Durand - Titre.pdf'
    assert compute(zotero, zotero.item('Titre', date='2019-03-00 mars 2019')) == 'Durand - 2019 - Titre.pdf'


def test_editors_then_contributors_when_main_role_missing(zotero):
    only_editors = zotero.item('Ouvrage', type_='book', authors=(), editors=('Dupont', 'Leroy'))
    assert compute(zotero, only_editors) == 'Dupont et Leroy - 2020 - Ouvrage.pdf'
    # Chapter: the author comes before the editors entered first.
    chapter = zotero.item('Chapitre', type_='bookSection', authors=('Durand',), editors=('Dupont',))
    assert compute(zotero, chapter) == 'Durand - 2020 - Chapitre.pdf'
    contributor = zotero.item('Note', authors=(), creators=(('Roux', 'B.', 'contributor'),))
    assert compute(zotero, contributor) == 'Roux - 2020 - Note.pdf'
    translator = zotero.item('Traduction', authors=(), creators=(('Roux', 'B.', 'translator'),))
    assert compute(zotero, translator) == '2020 - Traduction.pdf'


def test_base_fields_specific_to_type(zotero):
    # For a case, title is caseName and the date is dateDecided, like getField(…, true) in Zotero.
    legal_case = zotero.item('', type_='case', authors=('Cour',), date='', caseName='Arrêt Dupont',
                           dateDecided='2001-05-12 12 mai 2001')
    assert compute(zotero, legal_case) == 'Cour - 2001 - Arrêt Dupont.pdf'


def test_long_title_truncated_to_100_units_then_without_trailing_space(zotero):
    title = 'Mot ' * 30
    assert compute(zotero, zotero.item(title)) == f"Durand - 2020 - {('Mot ' * 25).strip()}.pdf"


def test_chars_outside_basic_plane_counted_double_and_removed(zotero):
    # JavaScript counts an emoji as two units, and getValidFileName removes both halves.
    assert compute(zotero, zotero.item('A' * 99 + '😀b')) == 'Durand - 2020 - ' + 'A' * 99 + '.pdf'
    assert compute(zotero, zotero.item('Un 😀 deux')) == 'Durand - 2020 - Un  deux.pdf'


def test_forbidden_chars_markup_and_leading_dot(zotero):
    f = zotero.item('Pourquoi? Le "vrai" : a/b <i>c</i>|d*', authors=('Durand',))
    assert compute(zotero, f) == 'Durand - 2020 - Pourquoi Le vrai  ab cd.pdf'
    bare = zotero.item('.cache', authors=(), date='')
    assert compute(zotero, bare) == 'cache.pdf'
    empty = zotero.item('', authors=(), date='')
    assert compute(zotero, empty) == '_.pdf'


def test_extension_of_file_or_type(zotero):
    f = zotero.item('Titre')
    assert compute(zotero, f, name='sans-extension') == 'Durand - 2020 - Titre.pdf'
    assert compute(zotero, f, name='ABSENT.PDF', content=None) == 'Durand - 2020 - Titre.PDF'
    assert compute(zotero, f, name='livre.epub', content_type='application/epub+zip') == 'Durand - 2020 - Titre.epub'


def test_suffix_that_would_repeat_written_once(zotero):
    f = zotero.item('Titre')
    assert compute(zotero, f, '{{ firstCreator suffix="-" }}-{{ year }}') == 'Durand-2020.pdf'
    # A suffix already present at the end of the value is not added.
    g = zotero.item('Titre -', authors=())
    assert compute(zotero, g, '{{ title suffix=" -" }}{{ year }}') == 'Titre -2020.pdf'


def test_common_variables_and_parameters(zotero):
    f = zotero.item('Titre long', authors=(), creators=(('Durand', 'Anne', 'author'), ('Martin', 'Paul', 'author'),
                                                          ('Petit', 'Léa', 'author'), ('Roux', 'Ève', 'editor')),
                     publicationTitle='Revue', date='2020-02-03 3 février 2020')
    cases = {
        '{{ authors max="2" join=" & " suffix="_" }}{{ year }}': 'Durand & Martin_2020',
        '{{ authors name="given-family" initialize="given" max="1" }}': 'A. Durand',
        '{{ authors max="-1" }}': 'Petit',
        '{{ editors }}{{ creatorsCount prefix=" (" suffix=")" }}': 'Roux (4)',
        '{{ title case="upper" truncate="5" }}': 'TITRE',
        '{{ title case="hyphen" }}': 'titre-long',
        '{{ title case="camel" }}': 'titreLong',
        '{{ title start="6" }}': 'long',
        '{{ publicationTitle prefix="[" suffix="]" }}{{ date }}': '[Revue]3 février 2020',
        '{{ itemType }}{{ inconnu suffix="x" }}': 'journalArticle',
        '{{ "litteral" }} {{ year }}': 'litteral 2020',
    }
    b_before = None
    for template, expected in cases.items():
        attachment = zotero.pdf(f, 'x.pdf', None)
        b_before = reader.read(zotero.save())
        rules = filenames.Rules.of(b_before, ' et ')
        database = filenames.base_name(b_before.all_items[f], filenames.Template.analyze(template), rules)
        assert database == expected, template
    assert attachment in b_before.attachments


def test_attachment_title(zotero):
    f = zotero.item('Titre')
    assert compute(zotero, f, '{{ year suffix=" " }}{{ attachmentTitle }}', title='Version auteur') == \
        '2020 Version auteur.pdf'


@pytest.mark.parametrize('template, cause', [
    ('{{ if year }}{{ year }}{{ endif }}', 'condition'),
    ('{{ title match="\\d+" }}', 'match'),
    ('{{ title replaceFrom="a" replaceTo="b" }}', 'replaceFrom'),
    ('{{ title case="title" }}', 'title'),
    ('{{ itemType localize="true" }}', 'localize'),
])
def test_template_outside_subset(template, cause):
    with pytest.raises(filenames.UnsupportedTemplate, match=cause):
        filenames.Template.analyze(template)


def test_template_read_in_zotero(zotero):
    b = reader.read(zotero.save())
    assert filenames.template_of(b) == DEFAULT
    zotero.setting('attachmentRenameTemplate', '{{ year }} {{ title }}')
    assert filenames.template_of(reader.read(zotero.save())) == '{{ year }} {{ title }}'
    # A malformed template is replaced by the default template, as in Zotero.
    zotero.setting('attachmentRenameTemplate', '{{ year }')
    assert filenames.template_of(reader.read(zotero.save())) == DEFAULT
    zotero.setting('attachmentRenameTemplate', '{{ if year }}x')
    assert filenames.template_of(reader.read(zotero.save())) == DEFAULT


def test_conjunction_inferred_from_existing_names(zotero, tmp_path):
    for i, name in enumerate(('Durand and Martin - 2020 - Un.pdf', 'Durand and Martin - 2020 - Deux.pdf',
                             'Durand et Martin - 2020 - Trois.pdf', 'Durand et Martin - 1999 - Quatre.pdf')):
        f = zotero.item(['Un', 'Deux', 'Trois', 'Quatre'][i], authors=('Durand', 'Martin'))
        zotero.pdf(f, name)
    b = reader.read(zotero.save())
    template = filenames.Template.analyze(DEFAULT)
    # The fourth name dates from old metadata: it does not count.
    assert filenames.infer_conjunction(b, template) == (' and ', 2)
    cfg = config.Config(workspace=tmp_path)
    assert filenames.conjunction(b, cfg, template) == ' and '
    cfg.method.conjunction = 'et'
    assert filenames.conjunction(b, cfg, template) == ' et '


def test_unknown_conjunction(zotero, tmp_path):
    f = zotero.item('Titre', authors=('Durand', 'Martin'))
    zotero.pdf(f, 'scan.pdf')
    b = reader.read(zotero.save())
    template = filenames.Template.analyze(DEFAULT)
    assert filenames.conjunction(b, config.Config(workspace=tmp_path), template) is None
    with pytest.raises(filenames.UnknownConjunction):
        filenames.base_name(b.all_items[f], template, filenames.Rules.of(b))


def test_main_attachment_like_zotero(zotero):
    f = zotero.item('Titre', url='https://editeur.org/article')
    recent = zotero.pdf(f, 'recent.pdf', date_added='2026-03-01')
    old = zotero.pdf(f, 'ancien.pdf', date_added='2026-02-01')
    html = zotero.pdf(f, 'page.html', date_added='2025-01-01', content_type='text/html', mode=1)
    b = reader.read(zotero.save())
    assert filenames.main_attachment(b, b.all_items[f]).id == old
    # The PDF whose URL is the item's URL comes before an older PDF.
    incoming = zotero.pdf(f, 'venu.pdf', date_added='2026-04-01', mode=1, url='https://editeur.org/article')
    b = reader.read(zotero.save())
    assert [p.id for p in filenames.attachments_of(b, b.all_items[f])] == [incoming, old, recent, html]
    # A snapshot alone is the main attachment, but Zotero does not rename it.
    g = zotero.item('Page')
    zotero.pdf(g, 'page.html', content_type='text/html', mode=1)
    link = zotero.item('Lien')
    zotero.pdf(link, 'https://exemple.org', mode=3, content_type='')
    linked_item = zotero.item('Lié')
    zotero.pdf(linked_item, 'lie.pdf', mode=2)
    b = reader.read(zotero.save())
    assert not filenames.renamable(filenames.main_attachment(b, b.all_items[g]))
    assert filenames.main_attachment(b, b.all_items[link]) is None
    assert not filenames.renamable(filenames.main_attachment(b, b.all_items[linked_item]))
    assert filenames.renamable(filenames.main_attachment(b, b.all_items[linked_item]), linked=True)
    assert [e.id for e, _ in filenames.main_attachments(b)] == [f]


def test_skipped_cases(zotero):
    f = zotero.item('Titre')
    p = zotero.pdf(f, 'scan.pdf', others=('durand - 2020 - titre.pdf',))
    b = reader.read(zotero.save())
    attachment = b.attachments[p]
    assert 'déjà pris' in filenames.skip_cause(attachment, 'Durand - 2020 - Titre.pdf')
    # Changing only the case of the file itself is not a collision.
    assert filenames.skip_cause(attachment, 'SCAN.pdf') is None
    assert 'Windows' in filenames.skip_cause(attachment, 'Titre.')
    assert 'réservé' in filenames.skip_cause(attachment, 'CON.pdf')
    assert 'réservé' in filenames.skip_cause(attachment, 'nul .pdf')
    assert filenames.skip_cause(attachment, 'Console.pdf') is None
    assert 'octets' in filenames.skip_cause(attachment, 'é' * 130 + '.pdf')
    assert 'chemin' in filenames.skip_cause(attachment, 'a' * 240 + '.pdf')


def test_local_renaming_failed(zotero):
    f = zotero.item('Titre')
    failed = zotero.pdf(f, 'Durand - 2020 - Titre.pdf', None, others=('ancien.pdf',))
    absent = zotero.pdf(zotero.item('Autre'), 'perdu.pdf', None)
    b = reader.read(zotero.save())
    assert filenames.other_file(b.attachments[failed]) == 'ancien.pdf'
    assert filenames.other_file(b.attachments[absent]) is None


def test_old_config_with_file_template(tmp_path):
    (tmp_path / 'config.toml').write_text("[methode]\nmodele_fichier = '^.+$'\nconjonction = \"and\"\n",
                                          encoding='utf-8')
    cfg = config.load(Path(tmp_path))
    assert cfg.method.conjunction == 'and' and not hasattr(cfg.method, 'modele_fichier')


# Plan of step 8 (D147, D149, D150, D158)

API_MODES = {0: 'imported_file', 1: 'imported_url', 2: 'linked_file'}


class World:
    """Items and attachments created both in the synthetic database and on the fake server, with the same
    keys. `sync` does what Zotero does after a write through the API: file renamed on disk,
    attachment path and title taken from the server (D161)."""

    def __init__(self, zotero, server):
        self.zotero, self.server = zotero, server
        server._n = itertools.count(10 ** 6)
        self.ids: dict[str, int] = {}

    def item(self, title, authors=('Durand',), date='2020', **fields):
        key = self.server._key()
        self.ids[key] = self.zotero.item(title, authors=authors, date=date, key=key, **fields)
        self.server.add(key=key, title=title, date=date,
                             creators=[{'creatorType': 'author', 'lastName': a, 'firstName': 'A.'} for a in authors],
                             **{k: v for k, v in fields.items() if k != 'tags'})
        return key

    def pdf(self, parent, name, title=None, content=b'%PDF-1.4 factice', mode=0, content_type='application/pdf',
            **options):
        key = self.server._key()
        title = name if title is None else title
        self.ids[key] = self.zotero.pdf(self.ids[parent], name, content, key=key, title=title, mode=mode,
                                        content_type=content_type, **options)
        self.server.add('attachment', key=key, parentItem=parent, linkMode=API_MODES[mode], title=title,
                             contentType=content_type, **({'path': f'/Documents/{name}'} if mode == 2
                                                          else {'filename': name, 'md5': 'abc'}))
        return key

    def sync(self):
        db = self.zotero.db
        title = db.execute("select fieldID from fields where fieldName = 'title'").fetchone()[0]
        for key, iid in self.ids.items():
            d = self.server.all_items[key]
            if d.get('itemType') != 'attachment' or 'filename' not in d:
                continue
            old = db.execute('select path from itemAttachments where itemID = ?', (iid,)).fetchone()[0]
            old = old.removeprefix('storage:')
            folder = self.zotero.folder / 'storage' / key
            if old != d['filename'] and (folder / old).is_file():
                (folder / old).rename(folder / d['filename'])
            db.execute('update itemAttachments set path = ? where itemID = ?', (f"storage:{d['filename']}", iid))
            db.execute('delete from itemData where itemID = ? and fieldID = ?', (iid, title))
            self.zotero._fields(iid, {'title': d.get('title', '')})

    def read(self):
        self.zotero.sync(self.server.version)
        return reader.read(self.zotero.save())


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def cfg(tmp_path, zotero):
    return Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)


@pytest.fixture
def world(zotero, server):
    m = World(zotero, server)
    f = {'juste': m.item('Déjà bien nommé'), 'titre': m.item('Titre court'), 'deux': m.item('Deux PDF'),
         'casse': m.item('casse'), 'autre': m.item('Autre retard'), 'lie': m.item('Fichier lié')}
    x = {'juste': m.pdf(f['juste'], 'Durand - 2020 - Déjà bien nommé.pdf'),
         # Title equal to the old name, the item's only PDF: it becomes « PDF ».
         'titre': m.pdf(f['titre'], 'scan.pdf'),
         # Two PDFs: the main attachment's title, equal to the old name without extension (case ignored), becomes the
         # new name without extension. The second PDF is not renamed.
         'deux': m.pdf(f['deux'], 'article.pdf', title='ARTICLE', date_added='2026-01-01'),
         'second': m.pdf(f['deux'], 'annexe.pdf', date_added='2026-02-01'),
         'casse': m.pdf(f['casse'], 'Durand - 2020 - Casse.pdf', title='Texte intégral'),
         'autre': m.pdf(f['autre'], 'x.pdf', title='PDF'),
         'lie': m.pdf(f['lie'], 'lie.pdf', mode=2)}
    return m, f, x


def ops_by_key(plan):
    return {op.key: op for g in plan.groups for op in g.operations}


def test_plan_trial_apply_rerun_and_undo(world, cfg, server):
    m, f, x = world
    plan, report = filenames.make_plan(m.read(), cfg, server.client(), {}, bbt.ZOTERO_ORG)
    ops = ops_by_key(plan)
    assert plan.step == 'noms' and set(ops) == {x['titre'], x['deux'], x['casse'], x['autre']}
    assert ops[x['titre']].before == {'filename': 'scan.pdf', 'title': 'scan.pdf'}
    assert ops[x['titre']].after == {'filename': 'Durand - 2020 - Titre court.pdf', 'title': 'PDF'}
    assert ops[x['deux']].after == {'filename': 'Durand - 2020 - Deux PDF.pdf', 'title': 'Durand - 2020 - Deux PDF'}
    assert ops[x['casse']].after == {'filename': 'Durand - 2020 - casse.pdf'}  # only the case changes
    assert ops[x['autre']].after == {'filename': 'Durand - 2020 - Autre retard.pdf'}
    assert [g.id for g in plan.groups] == [f['autre'], f['casse'], f['deux'], f['titre']]
    assert 'synchronisation de Zotero' in report and '`zc show`' in report
    assert '1 fichier lié principal en retard' in report

    cfg.writing.trial = 2
    path = write(plan, cfg)
    outcome = apply_plan(plan, path, server.client(), cfg, TRIAL)
    assert outcome.done == [f['autre'], f['casse']] and outcome.remaining == 2
    assert server.all_items[x['casse']]['filename'] == 'Durand - 2020 - casse.pdf'
    assert server.all_items[x['casse']]['md5'] == 'abc'
    with pytest.raises(Refusal, match='sauvegarde'):
        apply_plan(plan, path, server.client(), cfg, ALL)

    # After the trial, Zotero renames the files: a rerun only plans the rest.
    m.sync()
    rest, _ = filenames.make_plan(m.read(), cfg, server.client(), {}, bbt.ZOTERO_ORG)
    assert {g.id for g in rest.groups} == {f['deux'], f['titre']}
    fake_backup(cfg)
    outcome = apply_plan(plan, path, server.client(), cfg, ALL)
    assert sorted(outcome.done) == sorted([f['deux'], f['titre']]) and not outcome.conflicts
    assert server.all_items[x['titre']]['title'] == 'PDF'
    assert server.all_items[x['second']]['filename'] == 'annexe.pdf'
    m.sync()
    b = m.read()
    assert (m.zotero.folder / 'storage' / x['titre'] / 'Durand - 2020 - Titre court.pdf').is_file()
    end, _ = filenames.make_plan(b, cfg, server.client(), {}, bbt.ZOTERO_ORG)
    assert end.groups == []

    # Undo restores the old names and titles.
    p_undo, _, c_undo = undo_plan(path, server, cfg)
    apply_plan(p_undo, c_undo, server.client(), cfg, TRIAL)
    apply_plan(p_undo, c_undo, server.client(), cfg, ALL)
    assert server.all_items[x['titre']]['filename'] == 'scan.pdf'
    assert server.all_items[x['titre']]['title'] == 'scan.pdf'
    assert server.all_items[x['casse']]['filename'] == 'Durand - 2020 - Casse.pdf'
    assert server.all_items[x['deux']]['title'] == 'ARTICLE'


def test_conflict_if_name_changes_meanwhile(world, cfg, server):
    m, f, x = world
    plan, _ = filenames.make_plan(m.read(), cfg, server.client(), {}, bbt.ZOTERO_ORG)
    server.modify(x['titre'], filename='renommé à la main.pdf')
    outcome = apply_plan(plan, write(plan, cfg), server.client(), cfg, TRIAL)
    assert list(outcome.conflicts) == [f['titre']] and 'filename' in outcome.conflicts[f['titre']]
    assert server.all_items[x['titre']]['filename'] == 'renommé à la main.pdf'


def test_server_rejects_filename_outside_imported_file(world, server):
    m, f, x = world
    res = server.client().write([{'key': x['lie'], 'version': server.all_items[x['lie']]['version'],
                                    'filename': 'autre.pdf'}])
    assert res.failures[x['lie']][0] == 400


@pytest.mark.parametrize('storage, online, renames, reason', [
    (bbt.ZOTERO_ORG, True, True, ''),
    (bbt.ZOTERO_ORG, False, False, 'introuvable'),
    (bbt.ZOTERO_ORG, None, False, 'faute d\'avoir vérifié'),
    (bbt.WEBDAV, True, False, 'WebDAV'),
    (bbt.NONE, True, False, 'désactivée'),
    (bbt.UNKNOWN, True, False, 'inconnue'),
])
def test_file_missing_by_storage(zotero, server, cfg, storage, online, renames, reason):
    m = World(zotero, server)
    att = m.pdf(m.item('Absent'), 'perdu.pdf', content=None)
    plan, report = filenames.make_plan(m.read(), cfg, server.client(), None if online is None else {att: online},
                                   storage)
    assert bool(plan.groups) == renames
    if renames:
        assert ops_by_key(plan)[att].after['filename'] == 'Durand - 2020 - Absent.pdf'
        assert 'stocké sur zotero.org' in report
    else:
        assert '## Laissés de côté' in report and reason in report and 'Durand - 2020 - Absent.pdf' in report
    assert filenames.missing(m.read()) == [att]


def test_skipped_cases_and_names_not_computable(zotero, server, cfg):
    m = World(zotero, server)
    taken_name = m.pdf(m.item('Titre'), 'scan.pdf', others=('durand - 2020 - titre.pdf',))
    m.pdf(m.item('Deux auteurs', authors=('Durand', 'Martin')), 'b.pdf')
    plan, report = filenames.make_plan(m.read(), cfg, server.client(), {}, bbt.ZOTERO_ORG)
    assert plan.groups == []
    assert f'{taken_name} · « scan.pdf » → « Durand - 2020 - Titre.pdf » · nom déjà pris' in report
    assert 'nom non calculé (conjonction' in report
    cfg.method.conjunction = 'et'
    plan, _ = filenames.make_plan(m.read(), cfg, server.client(), {}, bbt.ZOTERO_ORG)
    assert [op.after['filename'] for op in ops_by_key(plan).values()] == ['Durand et Martin - 2020 - Deux auteurs.pdf']


def test_confidential_item_hidden(zotero, server, cfg):
    m = World(zotero, server)
    secret = m.item('Dossier médical Dupont', tags=('_privé',))
    att = m.pdf(secret, 'dupont.pdf')
    m.pdf(m.item('Collision secrète', tags=('_privé',)), 'c.pdf', others=('Durand - 2020 - Collision secrète.pdf',))
    plan, report = filenames.make_plan(m.read(), cfg, server.client(), {}, bbt.ZOTERO_ORG)
    assert ops_by_key(plan)[att].after['filename'] == 'Durand - 2020 - Dossier médical Dupont.pdf'
    assert plan.groups[0].title == privacy.mask()
    assert 'Dupont' not in report and 'Collision' not in report and 'dupont.pdf' not in report
    assert f'{att} (fiche {secret}, {privacy.mask()}) · nom du fichier et titre de la pièce jointe' in report
    path = write(plan, cfg)
    assert 'Dossier médical' not in json.dumps([g.title for g in plans.load(path).groups])


def test_unsupported_template(world, cfg, server, zotero):
    m, f, x = world
    zotero.setting('attachmentRenameTemplate', '{{ title case="title" }}')
    with pytest.raises(filenames.UnsupportedTemplate, match='Renommer les fichiers…'):
        filenames.make_plan(m.read(), cfg, server.client(), {}, bbt.ZOTERO_ORG)


def test_late_local_copy(world, cfg, server):
    m, f, x = world
    b = m.read()
    server.modify(f['titre'], title='Changé ailleurs')
    with pytest.raises(SystemExit, match='pas encore reçu'):
        filenames.make_plan(b, cfg, server.client(), {}, bbt.ZOTERO_ORG)


def test_metadata_from_plan(zotero, server):
    m = World(zotero, server)
    key = m.item('Ancien titre', date='')
    b = m.read()
    item = b.by_key()[key]
    after = filenames.item_after(b, item, {'title': 'Nouveau', 'date': '2019-03', 'itemType': 'book',
                                        'creators': [{'creatorType': 'author', 'name': 'OCDE'}]})
    assert (after.type, after.title, after.creators, after.roles) == ('book', 'Nouveau', [('OCDE', '')], ['author'])
    assert after.fields['date'] == '2019-03-00 2019-03' and item.title == 'Ancien titre'
    assert filenames.date_multipart('printemps 1998') == '1998-00-00 printemps 1998'
    assert filenames.date_multipart('s. d.') == 's. d.'
    epub = {'filename': 'livre.epub', 'title': 'livre', 'contentType': 'application/epub+zip'}
    assert filenames.new_title(epub, 'A - Livre.epub', True, ' et ') == 'Livre numérique'
    assert filenames.new_title(epub, 'A - Livre.epub', True, None) is None
    assert filenames.new_title(epub, 'A - Livre.epub', False, None) == 'A - Livre'
    assert filenames.new_title(dict(epub, title='Mon livre'), 'A - Livre.epub', True, ' et ') is None


def test_command(world, cfg, server, monkeypatch, capsys):
    from zot_clean import api
    from zot_clean.cli import main
    m, f, x = world
    m.pdf(m.item('Absent'), 'perdu.pdf', content=None)
    m.read()
    cfg.workspace.mkdir()
    (cfg.workspace / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.zotero_dir.as_posix()}"\n', encoding='utf-8')
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())
    copies, copy_file = [], reader.shutil.copy2
    monkeypatch.setattr(reader.shutil, 'copy2', lambda source, target: (copies.append(source), copy_file(source, target)))
    assert main(['filenames', 'plan', '--offline', '--workspace', str(cfg.workspace)]) == 0
    # Sync check and library reading on a single copy of the database.
    assert copies == [cfg.database]
    output = capsys.readouterr().out
    assert '4 fichier(s) à renommer' in output and '--trial' in output
    report = next((cfg.workspace / 'plans').glob('*_noms_*.md')).read_text(encoding='utf-8')
    assert 'profil de Zotero introuvable' in report


def test_report_and_refusals_in_english(world, cfg, server, zotero):
    from zot_clean.lang import language
    m, f, x = world
    with language('en'):
        plan, report = filenames.make_plan(m.read(), cfg, server.client(), {}, bbt.ZOTERO_ORG)
    assert report.startswith('# File names') and '## After the trial' in report and '`zc show`' in report
    assert 'Zotero syncs files through zotero.org.' in report
    assert '1 main linked file outdated, left to the Zotero setting' in report
    assert plan.description.startswith('File names, ')
    zotero.setting('attachmentRenameTemplate', '{{ title case="title" }}')
    with language('en'):
        with pytest.raises(filenames.UnsupportedTemplate, match='Rename Files'):
            filenames.make_plan(m.read(), cfg, server.client(), {}, bbt.ZOTERO_ORG)
