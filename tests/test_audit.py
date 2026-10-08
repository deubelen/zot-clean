from pathlib import Path

from zot_clean import audit, bbt, reader
from zot_clean.config import Config
from zot_clean.lang import language


def run_audit(zotero, **options):
    cfg = Config(workspace=Path('.'), zotero_dir=zotero.folder)
    b = reader.read(zotero.save())
    return {s.title: s for s in audit.run_audit(b, cfg, **options)}, b


def test_library_in_order(zotero):
    roots = {n: zotero.collection(n) for n in ('Inbox', 'Projets', 'Fonds', 'Archives')}
    philo = zotero.collection('Philosophie', roots['Fonds'])
    f = zotero.item('Un article bien tenu', collections=(philo,), DOI='10.1/a', citationKey='durandArticle2020',
                     tags=('#norme', '1 à lire'))
    zotero.pdf(f, 'Durand - 2020 - Un article bien tenu.pdf')
    for n in ('Inbox', 'Projets', 'Archives'):
        zotero.item(f'Fiche de {n}', collections=(roots[n], philo), DOI=f'10.1/{n}', citationKey=f'k{n}')
    sections, _ = run_audit(zotero)
    to_review = [t for t, s in sections.items() if s.status == audit.TO_REVIEW]
    assert to_review == []


def test_without_collection(zotero):
    zotero.item('Orpheline')
    sections, _ = run_audit(zotero)
    s = sections['Références sans collection']
    assert s.status == audit.TO_REVIEW and '1 référence' in s.summary


def test_duplicates_by_doi_isbn_and_title(zotero):
    zotero.item('Premier', DOI='10.5/X')
    zotero.item('Autre titre', DOI='https://doi.org/10.5/x')
    zotero.item('Un livre', type_='book', ISBN='2-07-036822-X')
    zotero.item('Le même livre', type_='book', ISBN='978-2-07-036822-8')
    zotero.item('Radical Embodied Cognitive Science', type_='book', authors=('Chemero',), date='2009')
    zotero.item('Radical embodied cognitive science', type_='book', authors=('Chemero',), date='2009')
    sections, _ = run_audit(zotero)
    assert sections['Doublons probables'].summary.startswith('3 groupes')


def test_chapters_of_same_book_are_not_duplicates(zotero):
    for title in ('Introduction au volume', 'Second chapitre du volume'):
        zotero.item(title, type_='bookSection', ISBN='978-2-07-036822-8', DOI='10.9/livre')
    sections, _ = run_audit(zotero)
    assert sections['Doublons probables'].status == audit.OK


def test_missing_files_and_identical_pdfs(zotero):
    a, b_, c = (zotero.item(t) for t in ('A', 'B', 'C'))
    zotero.pdf(a, 'x.pdf', b'meme contenu')
    zotero.pdf(b_, 'y.pdf', b'meme contenu')
    zotero.pdf(c, 'absent.pdf', None)
    sections, _ = run_audit(zotero)
    assert sections['Fichiers absents'].summary.startswith('1 fichier absent')
    assert sections['PDF identiques'].summary.startswith('1 PDF rattaché')
    sections, _ = run_audit(zotero, fingerprints=False)
    assert sections['PDF identiques'].status == audit.INFO


def test_automatic_tags_and_variants(zotero):
    zotero.item('A', tags=(('Philosophy', 1), '#Norme', '#normes', 'À lire'))
    sections, _ = run_audit(zotero)
    s = sections['Tags']
    assert s.status == audit.TO_REVIEW
    assert '1 tag automatique' in s.summary and '1 groupe' in s.summary and '1 tag manuel hors' in s.summary


def test_confidential_tags_imported_batches_and_setting(zotero):
    # A tag carried only by a confidential item appears only by its identifier (D156).
    zotero.item('Secret', tags=('_privé', 'Patient Dupont'))
    # An item carrying many rare keywords, imported as manual tags (D153).
    zotero.item('Importée', tags=tuple(f'mot-clé {i}' for i in range(12)))
    sections, _ = run_audit(zotero, automatic=True)
    s = sections['Tags']
    text = s.summary + ' '.join(s.details) + ' '.join(s.points) + ' '.join(s.points.values())
    assert 'Dupont' not in text
    assert '12 tags manuels qui ont l\'air de mots-clés importés, sur 1 fiche' in s.summary
    assert 'réglage actif' in s.summary and 'réglage' in s.points and 'Décocher' in s.remedy
    sections, _ = run_audit(zotero, automatic=False)
    assert 'réglage' not in sections['Tags'].points


def test_duplicate_citation_keys(zotero):
    zotero.item('A', citationKey='cle2020')
    zotero.item('B', citationKey='cle2020')
    sections, _ = run_audit(zotero)
    assert '1 clé en double' in sections['Clés de citation'].summary


def use_citation_keys(zotero, state=None):
    cfg = Config(workspace=Path('.'), zotero_dir=zotero.folder)
    b = reader.read(zotero.save())
    from zot_clean.privacy import hidden_keys
    return audit.use_citation_keys(b, cfg, hidden_keys(b, cfg), state)


def bbt_active(**settings):
    return bbt.State(**dict(dict(installed=True, active=True, version='9.1.0', source=bbt.PROFILE), **settings))


def test_keys_compared_case_insensitive_except_bbt_setting(zotero):
    zotero.item('A', citationKey='Durand2020')
    zotero.item('B', citationKey='durand2020')
    s = use_citation_keys(zotero)
    assert s.status == audit.TO_REVIEW and '1 clé en double (sans tenir compte de la casse)' in s.summary
    assert 'en double · durand2020' in s.points and 'non détecté' in s.summary
    s = use_citation_keys(zotero, bbt_active(casing=True))
    assert '0 clé en double (casse distinguée' in s.summary and s.status == audit.OK


def test_bbt_version_and_formula(zotero):
    zotero.item('A', citationKey='durandA2020')
    s = use_citation_keys(zotero, bbt_active(formula='auth.lower + shorttitle(3, 3) + year'))
    assert s.status == audit.OK and 'Better BibTeX 9.1.0 actif' in s.summary and 'diffère' not in s.summary
    s = use_citation_keys(zotero, bbt_active(formula='auth + year'))
    assert s.status == audit.OK and '« auth + year »' in s.summary and 'diffère de celle de la méthode' in s.summary


def test_bbt_settings_to_watch(zotero):
    zotero.item('A', citationKey='durandA2020')
    zotero.item('B')
    s = use_citation_keys(zotero, bbt_active(regenerates=True, fill_after=0))
    assert s.status == audit.TO_REVIEW
    assert {'réglage · resetKeyOnChange', 'réglage · fillKeyAfter'} <= set(s.points)
    assert any('Regenerate citation key' in d for d in s.details)
    s = use_citation_keys(zotero, bbt_active(version='7.0.5'))
    assert {k for k in s.points if k.startswith('réglage')} == {'réglage · version'}
    assert 'trop ancienne' in s.summary


def test_fill_on_demand_without_item_without_key(zotero):
    zotero.item('A', citationKey='durandA2020')
    s = use_citation_keys(zotero, bbt_active(fill_after=0))
    assert s.status == audit.OK and not s.points


def test_citation_key_line_in_extra(zotero):
    zotero.item('A', citationKey='durandA2020', extra='Citation Key: durandA2020\ntex.ids: vieux')
    s = use_citation_keys(zotero, bbt_active())
    assert s.status == audit.TO_REVIEW and '1 référence dont Extra contient encore' in s.summary
    assert any(k.startswith('Extra · ') for k in s.points)


def test_bbt_disabled_and_confidential_duplicate_key(zotero):
    zotero.item('Secret', citationKey='durandSecret2020', tags=('_privé',))
    zotero.item('Autre', citationKey='durandsecret2020')
    s = use_citation_keys(zotero, bbt.State(installed=True, active=False, version='9.1.0', source=bbt.PROFILE))
    assert 'désactivé' in s.summary and 'Sans Better BibTeX actif' in s.remedy
    assert not any('ecret' in k or 'ecret' in v for k, v in s.points.items())
    assert any(audit.mask() in d for d in s.details)


def test_expected_names_from_zotero_template(zotero):
    # D148, D150: only the main file counts, an item without a year gives « Auteur - Titre ».
    f = zotero.item('A')
    main = zotero.pdf(f, 'scan0001.pdf', date_added='2026-01-01')
    zotero.pdf(f, 'copie.pdf', b'autre', date_added='2026-02-01')
    no_year = zotero.item('B', date='')
    zotero.pdf(no_year, 'Durand - B.pdf')
    zotero.pdf(zotero.item('Lié'), 'lie.pdf', mode=2)
    sections, b = run_audit(zotero)
    s = sections['Noms des fichiers']
    assert s.status == audit.TO_REVIEW
    assert s.summary.startswith("1 fichier principal sur 2 porte le nom attendu d'après le modèle de Zotero, 1 est en "
                               "retard sur sa fiche (1 présent).")
    assert '1 PDF secondaire sous un autre nom' in s.summary and '1 fichier lié principal' in s.summary
    key = b.attachments[main].key
    assert list(s.points) == [key] and s.points[key] == f'{key} · scan0001.pdf → Durand - 2020 - A.pdf · présent'


def test_names_missing_on_zotero_org_or_not_found(zotero):
    a, b_ = zotero.item('A'), zotero.item('B')
    zotero.pdf(a, 'a.pdf', None)
    zotero.pdf(b_, 'b.pdf', None)
    _, b = run_audit(zotero)
    keys = audit.missing_imported(b)
    sections, _ = run_audit(zotero, online={keys[0]: True, keys[1]: False})
    assert '2 sont en retard sur leur fiche (1 sur zotero.org, 1 introuvable)' in sections['Noms des fichiers'].summary
    sections, _ = run_audit(zotero)
    assert '(2 absents du disque)' in sections['Noms des fichiers'].summary
    # D158: under WebDAV or without file sync, a missing file is listed, never renamed.
    from zot_clean import bbt
    sections, _ = run_audit(zotero, online={keys[0]: True, keys[1]: False}, storage=bbt.WEBDAV)
    assert '(2 absents, non renommés)' in sections['Noms des fichiers'].summary


def test_skipped_names_and_failed_renaming(zotero):
    f = zotero.item('Titre')
    zotero.pdf(f, 'scan.pdf', others=('Durand - 2020 - Titre.pdf',))
    g = zotero.item('Autre')
    failed = zotero.pdf(g, 'Durand - 2020 - Autre.pdf', None, others=('ancien.pdf',))
    sections, b = run_audit(zotero)
    s = sections['Noms des fichiers']
    assert '(1 écarté)' in s.summary and 'déjà pris' in ' '.join(s.details)
    key = b.attachments[failed].key
    assert '1 pièce jointe pointe vers un fichier absent' in s.summary
    assert s.points[f'renommage échoué · {key}'].endswith('contient ancien.pdf')


def test_names_template_rule_or_outside_subset(zotero):
    f = zotero.item('Titre')
    zotero.pdf(f, '2020 Titre.pdf')
    zotero.setting('attachmentRenameTemplate', '{{ year suffix=" " }}{{ title }}')
    sections, _ = run_audit(zotero)
    assert sections['Noms des fichiers'].status == audit.OK
    # Fallback on the regular expression, year optional.
    zotero.setting('attachmentRenameTemplate', '{{ if year }}{{ year }}{{ endif }}')
    g = zotero.item('Sans année', date='')
    zotero.pdf(g, 'Durand - Sans année.pdf')
    sections, _ = run_audit(zotero)
    s = sections['Noms des fichiers']
    assert s.summary.startswith('Modèle de Zotero que zot-clean ne sait pas calculer (condition « if »). 1 PDF hors')


def test_names_unknown_conjunction(zotero):
    zotero.pdf(zotero.item('Titre', authors=('Durand', 'Martin')), 'scan.pdf')
    sections, _ = run_audit(zotero)
    s = sections['Noms des fichiers']
    assert s.status == audit.INFO and '1 nom non calculé' in s.summary


def test_sync(zotero):
    zotero.item('Pas encore remontée', synced=False)
    zotero.item('Clé cassée', key='bad-key')
    sections, _ = run_audit(zotero)
    s = sections['Synchronisation']
    assert s.status == audit.TO_REVIEW and '1 élément à clé invalide' in s.summary


def test_markdown_report(zotero):
    zotero.item('Orpheline')
    sections, b = run_audit(zotero)
    text = audit.report(list(sections.values()), b)
    assert text.startswith('# Audit de la bibliothèque Zotero')
    assert '## 2. Références sans collection' in text and 'Orpheline' in text


def test_identical_pdfs_wanted_or_on_trashed_item(zotero, tmp_path):
    """A group judged wanted in suivi/pieces.toml, and the copy of an item moved to the trash, are no longer
    reported (D125)."""
    from zot_clean import reader, attachments
    from zot_clean.config import Config
    cfg = Config(workspace=tmp_path / 'travail', zotero_dir=zotero.folder)
    book, chapter, discarded, kept_item = (zotero.item(t) for t in ('Livre', 'Chapitre', 'Jetée', 'Gardée'))
    zotero.pdf(book, 'l.pdf', b'livre')
    zotero.pdf(chapter, 'l.pdf', b'livre')
    zotero.pdf(discarded, 'j.pdf', b'meme')
    zotero.pdf(kept_item, 'j.pdf', b'meme')
    zotero.trash(discarded)
    b = reader.read(zotero.save())
    assert audit.identical_pdfs(b, cfg).summary.startswith('1 PDF rattaché')
    entries = attachments.find(b, cfg)
    entries[0].decision = attachments.KEEP
    attachments.write(cfg, entries, b)
    assert audit.identical_pdfs(b, cfg).status == audit.OK


def test_confidential_item_hidden(zotero):
    secret_item = zotero.item('Mon dossier médical', tags=('_privé',))
    zotero.pdf(secret_item, 'Mon dossier médical.pdf', None)
    zotero.item('Mon dossier médical', tags=('_privé',))
    sections, b = run_audit(zotero)
    text = audit.report(list(sections.values()), b)
    assert 'médical' not in text and 'fiche confidentielle' in text
    assert sections['Doublons probables'].summary.startswith('1 groupe')


def test_group_with_confidential_item_fully_hidden(zotero):
    c = zotero.collection('Santé')
    a = zotero.item('Mon dossier médical', tags=('_privé',), collections=(c,), DOI='10.1/a')
    b_ = zotero.item('Mon dossier médical', collections=(c,), DOI='10.1/b')
    zotero.pdf(a, 'x.pdf', b'meme contenu')
    # Twin item with no gap reported elsewhere (collection, DOI, expected file name): only the groups show it.
    zotero.pdf(b_, 'Durand - 2020 - Mon dossier médical.pdf', b'meme contenu')
    sections, b = run_audit(zotero)
    text = audit.report(list(sections.values()), b)
    assert 'médical' not in text


def test_agreement_and_type_names():
    assert audit.plural(0, 'pièce jointe') == '0 pièce jointe'
    assert audit.plural(2, 'pièce jointe') == '2 pièces jointes'
    assert audit.plural(3, 'PDF') == '3 PDF' and audit.plural(2, 'fois') == '2 fois'
    assert audit.type_name('bookSection') == 'Chapitre de livre' and audit.type_name('inconnu') == 'inconnu'


def test_missing_files_recoverable_or_lost(zotero):
    # D133: the audit says which ones are still on zotero.org.
    a, b_ = zotero.item('A'), zotero.item('B')
    zotero.pdf(a, 'a.pdf', None)
    zotero.pdf(b_, 'b.pdf', None)
    _, b = run_audit(zotero)
    keys = audit.missing_imported(b)
    assert len(keys) == 2
    sections, _ = run_audit(zotero, online={keys[0]: True, keys[1]: False})
    s = sections['Fichiers absents']
    assert s.summary.startswith('2 fichiers absents du disque, dont 1 encore sur zotero.org (récupérable) et 1 introuvable.')
    assert s.details[0].startswith(keys[0]) and s.details[0].endswith('sur zotero.org')
    assert s.details[1].endswith('introuvable')
    sections, _ = run_audit(zotero, cause='pas de clé API')
    assert '(non vérifiés sur zotero.org, pas de clé API)' in sections['Fichiers absents'].summary


def test_missing_files_by_file_sync(zotero):
    # D157: under WebDAV or without sync, Zotero no longer looks for files on zotero.org.
    a, b_ = zotero.item('A'), zotero.item('B')
    zotero.pdf(a, 'a.pdf', None)
    zotero.pdf(b_, 'b.pdf', None)
    _, b = run_audit(zotero)
    keys = audit.missing_imported(b)
    online = {keys[0]: True, keys[1]: False}
    sections, _ = run_audit(zotero, online=online, storage=bbt.WEBDAV)
    s = sections['Fichiers absents']
    assert s.summary.startswith('2 fichiers absents du disque, dont 1 encore sur zotero.org (à télécharger depuis la '
                               'bibliothèque en ligne) et 1 absent de zotero.org (peut-être sur le serveur WebDAV).')
    assert s.summary.endswith('Zotero synchronise les fichiers par WebDAV.')
    assert s.details[1].endswith('pas sur zotero.org') and 'serveur WebDAV' in s.remedy
    sections, _ = run_audit(zotero, online=online, storage=bbt.NONE)
    s = sections['Fichiers absents']
    assert ', dont 1 encore sur zotero.org (à télécharger depuis la bibliothèque en ligne) et 1 introuvable.' in s.summary
    assert s.summary.endswith('La synchronisation des fichiers est désactivée dans Zotero.')
    assert 'ne retélécharge donc rien' in s.remedy
    sections, _ = run_audit(zotero, online=online, storage=bbt.ZOTERO_ORG)
    s = sections['Fichiers absents']
    assert '(récupérable) et 1 introuvable.' in s.summary and s.summary.endswith('par zotero.org.')
    assert 'qui le retélécharge' in s.remedy


def test_missing_pdfs_not_checked(zotero):
    """D168: without the files on disk, the identical-PDF check does not say « OK »."""
    a, b_ = zotero.item('A'), zotero.item('B')
    zotero.pdf(a, 'a.pdf', None)
    zotero.pdf(b_, 'b.pdf', None)
    sections, b = run_audit(zotero)
    s = sections['PDF identiques']
    assert s.status == audit.NOT_CHECKED and '2 PDF absents du disque, non comparés' in s.summary
    assert '« au moment de la synchronisation »' in s.remedy
    assert 'WebDAV' in audit.identical_pdfs(b, None, storage=bbt.WEBDAV).remedy
    assert 'ne les téléchargera donc pas' in audit.identical_pdfs(b, None, storage=bbt.NONE).remedy
    text = audit.report(list(sections.values()), b)
    assert '1 non contrôlé faute de fichiers sur le disque' in text
    zotero.pdf(a, 'c.pdf', b'meme')
    zotero.pdf(b_, 'd.pdf', b'meme')
    sections, _ = run_audit(zotero)
    assert sections['PDF identiques'].status == audit.TO_REVIEW


def test_empty_inbox_and_dispensable_roots(zotero):
    """An empty Inbox is not an empty collection to report, and the audit says how to do without a root."""
    zotero.collection('Inbox')
    zotero.item('Rangée', collections=(zotero.collection('Philosophie', zotero.collection('Fonds')),))
    sections, _ = run_audit(zotero)
    s = sections['Structure des collections']
    assert '0 collection vide' in s.summary and 'Racines de la méthode absentes : Projets, Archives.' in s.summary
    assert '`projets = []`, `archives = ""`' in s.remedy and 'section [methode]' in s.remedy


def test_online_files_kept_from_one_audit_to_next(zotero, tmp_path, monkeypatch, capsys):
    # A file found on zotero.org is no longer requested there as long as its attachment's version does not change.
    # A file not found, or of an attachment never synced (version 0), is requested again at every audit.
    from fake_server import FakeServer
    from zot_clean import api
    from zot_clean.cli import main
    server = FakeServer()
    f = zotero.item('A')
    attachments = {name: zotero.pdf(f, f'{name}.pdf', None) for name in ('en_ligne', 'perdu', 'neuf')}
    for name, version in (('en_ligne', 7), ('perdu', 8)):
        zotero.db.execute('update items set version = ? where itemID = ?', (version, attachments[name]))
    keys = {name: zotero.db.execute('select key from items where itemID = ?', (iid,)).fetchone()[0]
            for name, iid in attachments.items()}
    server.files = {keys['en_ligne'], keys['neuf']}
    zotero.save()
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n', encoding='utf-8')
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())

    def run_audit_and_count():
        server.requests.clear()
        assert main(['audit', '--no-hashes', '--workspace', str(workspace)]) == 0
        requested = sorted(path.split('/')[-2] for _, path in server.requests if path.endswith('/file'))
        return requested, capsys.readouterr().out

    requested, first = run_audit_and_count()
    assert requested == sorted(keys.values())
    assert 'dont 2 encore sur zotero.org (récupérables) et 1 introuvable' in first
    requested, second = run_audit_and_count()
    assert requested == sorted([keys['perdu'], keys['neuf']]) and second == first
    # Attachment modified since (version received through sync): requested again.
    zotero.db.execute('update items set version = 9 where itemID = ?', (attachments['en_ligne'],))
    zotero.save()
    server.files.discard(keys['en_ligne'])
    requested, third = run_audit_and_count()
    assert requested == sorted(keys.values()) and 'dont 1 encore sur zotero.org' in third
    # `--rafraichir` of the sources empties `cache/*.json`, not this memory.
    assert not list((workspace / 'cache').glob('*.json')) and (workspace / 'cache' / 'zotero').is_dir()


def test_library_never_synced_reported(zotero):
    """Without a key, the audit works, and says that sync will be needed to clean up."""
    assert run_audit(zotero)[0]['Synchronisation'].status == audit.OK
    zotero.account(None)
    s = run_audit(zotero)[0]['Synchronisation']
    assert s.status == audit.TO_REVIEW and s.summary.startswith("Zotero n'a jamais synchronisé")
    assert 'Réglages › Synchronisation' in s.remedy


def test_report_in_english(zotero):
    zotero.item('Orpheline')
    with language('en'):
        sections, b = run_audit(zotero)
        s = sections['Items without a collection']
        assert s.status == audit.TO_REVIEW and s.summary.startswith('1 item in no collection.')
        assert sections['Sync'].summary == '0 items and 0 collections not synced yet, 0 items with an invalid key.'
        text = audit.report(list(sections.values()), b, None)
        assert '| To review | 2. Items without a collection |' in text
        assert '*What cleanup can do about it.*' in text and 'Read-only, nothing was modified.' in text
        assert audit.type_name('bookSection') == 'Book Section' and audit.status_label(audit.NOT_CHECKED) == 'Not checked'
        assert audit.line(b.items[0]).endswith('· Orpheline')


def test_audit_warns_when_zotero_is_behind_zotero_org(zotero, tmp_path, monkeypatch, capsys):
    """D242, pilot bench (4 pilots out of 4): an audit run right after a plan, before Zotero synced, gave the figures
    of before without a word. It still reads the local copy (D171), and says so."""
    from fake_server import FakeServer
    from zot_clean import api
    from zot_clean.cli import main
    zotero.item('A')
    local = reader.read(zotero.save()).version
    workspace = tmp_path / 'travail'
    workspace.mkdir()
    (workspace / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.folder.as_posix()}"\n', encoding='utf-8')
    server = FakeServer()
    monkeypatch.setattr(api, 'from_config', lambda cfg: server.client())
    server.version = local
    assert main(['audit', '--no-hashes', '--workspace', str(workspace)]) == 0
    assert "pas encore reçu" not in capsys.readouterr().out
    server.version = local + 5
    assert main(['audit', '--no-hashes', '--workspace', str(workspace)]) == 0
    assert "Zotero n'a pas encore reçu les derniers changements" in capsys.readouterr().out
    report = next((workspace / 'rapports').glob('audit-*.md')).read_text(encoding='utf-8')
    assert report.split('\n')[2].startswith("> **Attention.** Zotero n'a pas encore reçu")
    assert main(['audit', '--offline', '--no-hashes', '--workspace', str(workspace)]) == 0
    assert "pas encore reçu" not in capsys.readouterr().out
