from pathlib import Path

from zot_clean import audit, bbt, lecture
from zot_clean.config import Config


def auditer(zotero, **options):
    cfg = Config(dossier_travail=Path('.'), dossier_zotero=zotero.dossier)
    b = lecture.lire(zotero.enregistrer())
    return {s.titre: s for s in audit.auditer(b, cfg, **options)}, b


def test_bibliotheque_en_ordre(zotero):
    racines = {n: zotero.collection(n) for n in ('Inbox', 'Projets', 'Fonds', 'Archives')}
    philo = zotero.collection('Philosophie', racines['Fonds'])
    f = zotero.fiche('Un article bien tenu', collections=(philo,), DOI='10.1/a', citationKey='durandArticle2020',
                     tags=('#norme', '1 à lire'))
    zotero.pdf(f, 'Durand - 2020 - Un article bien tenu.pdf')
    for n in ('Inbox', 'Projets', 'Archives'):
        zotero.fiche(f'Fiche de {n}', collections=(racines[n], philo), DOI=f'10.1/{n}', citationKey=f'k{n}')
    sections, _ = auditer(zotero)
    a_voir = [t for t, s in sections.items() if s.statut == audit.A_VOIR]
    assert a_voir == []


def test_sans_collection(zotero):
    zotero.fiche('Orpheline')
    sections, _ = auditer(zotero)
    s = sections['Références sans collection']
    assert s.statut == audit.A_VOIR and '1 référence' in s.resume


def test_doublons_par_doi_isbn_et_titre(zotero):
    zotero.fiche('Premier', DOI='10.5/X')
    zotero.fiche('Autre titre', DOI='https://doi.org/10.5/x')
    zotero.fiche('Un livre', type_='book', ISBN='2-07-036822-X')
    zotero.fiche('Le même livre', type_='book', ISBN='978-2-07-036822-8')
    zotero.fiche('Radical Embodied Cognitive Science', type_='book', auteurs=('Chemero',), date='2009')
    zotero.fiche('Radical embodied cognitive science', type_='book', auteurs=('Chemero',), date='2009')
    sections, _ = auditer(zotero)
    assert sections['Doublons probables'].resume.startswith('3 groupes')


def test_chapitres_d_un_meme_ouvrage_ne_sont_pas_des_doublons(zotero):
    for titre in ('Introduction au volume', 'Second chapitre du volume'):
        zotero.fiche(titre, type_='bookSection', ISBN='978-2-07-036822-8', DOI='10.9/livre')
    sections, _ = auditer(zotero)
    assert sections['Doublons probables'].statut == audit.OK


def test_fichiers_absents_et_pdf_identiques(zotero):
    a, b_, c = (zotero.fiche(t) for t in ('A', 'B', 'C'))
    zotero.pdf(a, 'x.pdf', b'meme contenu')
    zotero.pdf(b_, 'y.pdf', b'meme contenu')
    zotero.pdf(c, 'absent.pdf', None)
    sections, _ = auditer(zotero)
    assert sections['Fichiers absents'].resume.startswith('1 fichier absent')
    assert sections['PDF identiques'].resume.startswith('1 PDF rattaché')
    sections, _ = auditer(zotero, empreintes=False)
    assert sections['PDF identiques'].statut == audit.INFO


def test_tags_automatiques_et_variantes(zotero):
    zotero.fiche('A', tags=(('Philosophy', 1), '#Norme', '#normes', 'À lire'))
    sections, _ = auditer(zotero)
    s = sections['Tags']
    assert s.statut == audit.A_VOIR
    assert '1 tag automatique' in s.resume and '1 groupe' in s.resume and '1 tag manuel hors' in s.resume


def test_tags_confidentiels_lots_importes_et_reglage(zotero):
    # Un tag porté seulement par une fiche confidentielle n'apparaît que par son identifiant (D156).
    zotero.fiche('Secret', tags=('_privé', 'Patient Dupont'))
    # Une fiche qui porte beaucoup de mots-clés rares, importés en tags manuels (D153).
    zotero.fiche('Importée', tags=tuple(f'mot-clé {i}' for i in range(12)))
    sections, _ = auditer(zotero, automatiques=True)
    s = sections['Tags']
    texte = s.resume + ' '.join(s.details) + ' '.join(s.points) + ' '.join(s.points.values())
    assert 'Dupont' not in texte
    assert '12 tags manuels qui ont l\'air de mots-clés importés, sur 1 fiche' in s.resume
    assert 'réglage actif' in s.resume and 'réglage' in s.points and 'Décocher' in s.remede
    sections, _ = auditer(zotero, automatiques=False)
    assert 'réglage' not in sections['Tags'].points


def test_cles_de_citation_en_double(zotero):
    zotero.fiche('A', citationKey='cle2020')
    zotero.fiche('B', citationKey='cle2020')
    sections, _ = auditer(zotero)
    assert '1 clé en double' in sections['Clés de citation'].resume


def cles_citation(zotero, etat=None):
    cfg = Config(dossier_travail=Path('.'), dossier_zotero=zotero.dossier)
    b = lecture.lire(zotero.enregistrer())
    from zot_clean.filtre import cles_masquees
    return audit.cles_citation(b, cfg, cles_masquees(b, cfg), etat)


def bbt_actif(**reglages):
    return bbt.Etat(**dict(dict(installe=True, actif=True, version='9.1.0', source=bbt.PROFIL), **reglages))


def test_cles_comparees_sans_casse_sauf_reglage_de_bbt(zotero):
    zotero.fiche('A', citationKey='Durand2020')
    zotero.fiche('B', citationKey='durand2020')
    s = cles_citation(zotero)
    assert s.statut == audit.A_VOIR and '1 clé en double (sans tenir compte de la casse)' in s.resume
    assert 'en double · durand2020' in s.points and 'non détecté' in s.resume
    s = cles_citation(zotero, bbt_actif(casse=True))
    assert '0 clé en double (casse distinguée' in s.resume and s.statut == audit.OK


def test_version_et_formule_de_bbt(zotero):
    zotero.fiche('A', citationKey='durandA2020')
    s = cles_citation(zotero, bbt_actif(formule='auth.lower + shorttitle(3, 3) + year'))
    assert s.statut == audit.OK and 'Better BibTeX 9.1.0 actif' in s.resume and 'diffère' not in s.resume
    s = cles_citation(zotero, bbt_actif(formule='auth + year'))
    assert s.statut == audit.OK and '« auth + year »' in s.resume and 'diffère de celle de la méthode' in s.resume


def test_reglages_de_bbt_a_surveiller(zotero):
    zotero.fiche('A', citationKey='durandA2020')
    zotero.fiche('B')
    s = cles_citation(zotero, bbt_actif(regenere=True, remplissage=0))
    assert s.statut == audit.A_VOIR
    assert {'réglage · resetKeyOnChange', 'réglage · fillKeyAfter'} <= set(s.points)
    assert any('Regenerate citation key' in d for d in s.details)
    s = cles_citation(zotero, bbt_actif(version='7.0.5'))
    assert {k for k in s.points if k.startswith('réglage')} == {'réglage · version'}
    assert 'trop ancienne' in s.resume


def test_remplissage_sur_demande_sans_fiche_sans_cle(zotero):
    zotero.fiche('A', citationKey='durandA2020')
    s = cles_citation(zotero, bbt_actif(remplissage=0))
    assert s.statut == audit.OK and not s.points


def test_ligne_citation_key_dans_extra(zotero):
    zotero.fiche('A', citationKey='durandA2020', extra='Citation Key: durandA2020\ntex.ids: vieux')
    s = cles_citation(zotero, bbt_actif())
    assert s.statut == audit.A_VOIR and '1 référence dont Extra contient encore' in s.resume
    assert any(k.startswith('Extra · ') for k in s.points)


def test_bbt_desactive_et_cle_double_confidentielle(zotero):
    zotero.fiche('Secret', citationKey='durandSecret2020', tags=('_privé',))
    zotero.fiche('Autre', citationKey='durandsecret2020')
    s = cles_citation(zotero, bbt.Etat(installe=True, actif=False, version='9.1.0', source=bbt.PROFIL))
    assert 'désactivé' in s.resume and 'Sans Better BibTeX actif' in s.remede
    assert not any('ecret' in k or 'ecret' in v for k, v in s.points.items())
    assert any(audit.MASQUE in d for d in s.details)


def test_noms_attendus_d_apres_le_modele_de_zotero(zotero):
    # D148, D150 : seul le fichier principal compte, une fiche sans année donne « Auteur - Titre ».
    f = zotero.fiche('A')
    principal = zotero.pdf(f, 'scan0001.pdf', ajout='2026-01-01')
    zotero.pdf(f, 'copie.pdf', b'autre', ajout='2026-02-01')
    sans_annee = zotero.fiche('B', date='')
    zotero.pdf(sans_annee, 'Durand - B.pdf')
    zotero.pdf(zotero.fiche('Lié'), 'lie.pdf', mode=2)
    sections, b = auditer(zotero)
    s = sections['Noms des fichiers']
    assert s.statut == audit.A_VOIR
    assert s.resume.startswith("1 fichier principal sur 2 porte le nom attendu d'après le modèle de Zotero, 1 est en "
                               "retard sur sa fiche (1 présent).")
    assert '1 PDF secondaire sous un autre nom' in s.resume and '1 fichier lié principal' in s.resume
    cle = b.pieces[principal].cle
    assert list(s.points) == [cle] and s.points[cle] == f'{cle} · scan0001.pdf → Durand - 2020 - A.pdf · présent'


def test_noms_absents_sur_zotero_org_ou_introuvables(zotero):
    a, b_ = zotero.fiche('A'), zotero.fiche('B')
    zotero.pdf(a, 'a.pdf', None)
    zotero.pdf(b_, 'b.pdf', None)
    _, b = auditer(zotero)
    cles = audit.absents_importes(b)
    sections, _ = auditer(zotero, en_ligne={cles[0]: True, cles[1]: False})
    assert '2 sont en retard sur leur fiche (1 sur zotero.org, 1 introuvable)' in sections['Noms des fichiers'].resume
    sections, _ = auditer(zotero)
    assert '(2 absents du disque)' in sections['Noms des fichiers'].resume
    # D158 : sous WebDAV ou sans synchronisation des fichiers, un fichier absent est listé, jamais renommé.
    from zot_clean import bbt
    sections, _ = auditer(zotero, en_ligne={cles[0]: True, cles[1]: False}, stockage=bbt.WEBDAV)
    assert '(2 absents, non renommés)' in sections['Noms des fichiers'].resume


def test_noms_ecartes_et_renommage_echoue(zotero):
    f = zotero.fiche('Titre')
    zotero.pdf(f, 'scan.pdf', autres=('Durand - 2020 - Titre.pdf',))
    g = zotero.fiche('Autre')
    echoue = zotero.pdf(g, 'Durand - 2020 - Autre.pdf', None, autres=('ancien.pdf',))
    sections, b = auditer(zotero)
    s = sections['Noms des fichiers']
    assert '(1 écarté)' in s.resume and 'déjà pris' in ' '.join(s.details)
    cle = b.pieces[echoue].cle
    assert '1 pièce jointe pointe vers un fichier absent' in s.resume
    assert s.points[f'renommage échoué · {cle}'].endswith('contient ancien.pdf')


def test_noms_modele_regle_ou_hors_sous_ensemble(zotero):
    f = zotero.fiche('Titre')
    zotero.pdf(f, '2020 Titre.pdf')
    zotero.reglage('attachmentRenameTemplate', '{{ year suffix=" " }}{{ title }}')
    sections, _ = auditer(zotero)
    assert sections['Noms des fichiers'].statut == audit.OK
    # Repli sur l'expression régulière, année facultative.
    zotero.reglage('attachmentRenameTemplate', '{{ if year }}{{ year }}{{ endif }}')
    g = zotero.fiche('Sans année', date='')
    zotero.pdf(g, 'Durand - Sans année.pdf')
    sections, _ = auditer(zotero)
    s = sections['Noms des fichiers']
    assert s.resume.startswith('Modèle de Zotero que zot-clean ne sait pas calculer (condition « if »). 1 PDF hors')


def test_noms_conjonction_inconnue(zotero):
    zotero.pdf(zotero.fiche('Titre', auteurs=('Durand', 'Martin')), 'scan.pdf')
    sections, _ = auditer(zotero)
    s = sections['Noms des fichiers']
    assert s.statut == audit.INFO and '1 nom non calculé' in s.resume


def test_synchronisation(zotero):
    zotero.fiche('Pas encore remontée', synced=False)
    zotero.fiche('Clé cassée', cle='bad-key')
    sections, _ = auditer(zotero)
    s = sections['Synchronisation']
    assert s.statut == audit.A_VOIR and '1 élément à clé invalide' in s.resume


def test_rapport_markdown(zotero):
    zotero.fiche('Orpheline')
    sections, b = auditer(zotero)
    texte = audit.rapport(list(sections.values()), b)
    assert texte.startswith('# Audit de la bibliothèque Zotero')
    assert '## 2. Références sans collection' in texte and 'Orpheline' in texte


def test_pdf_identiques_voulus_ou_sur_fiche_a_la_corbeille(zotero, tmp_path):
    """Un groupe jugé voulu dans suivi/pieces.toml, et la copie d'une fiche mise à la corbeille, ne sont plus
    signalés (D125)."""
    from zot_clean import lecture, pieces
    from zot_clean.config import Config
    cfg = Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)
    livre, chapitre, jetee, gardee = (zotero.fiche(t) for t in ('Livre', 'Chapitre', 'Jetée', 'Gardée'))
    zotero.pdf(livre, 'l.pdf', b'livre')
    zotero.pdf(chapitre, 'l.pdf', b'livre')
    zotero.pdf(jetee, 'j.pdf', b'meme')
    zotero.pdf(gardee, 'j.pdf', b'meme')
    zotero.corbeille(jetee)
    b = lecture.lire(zotero.enregistrer())
    assert audit.pdf_identiques(b, cfg).resume.startswith('1 PDF rattaché')
    entrees = pieces.chercher(b, cfg)
    entrees[0].decision = pieces.GARDER
    pieces.ecrire(cfg, entrees, b)
    assert audit.pdf_identiques(b, cfg).statut == audit.OK


def test_fiche_confidentielle_masquee(zotero):
    secrete = zotero.fiche('Mon dossier médical', tags=('_privé',))
    zotero.pdf(secrete, 'Mon dossier médical.pdf', None)
    zotero.fiche('Mon dossier médical', tags=('_privé',))
    sections, b = auditer(zotero)
    texte = audit.rapport(list(sections.values()), b)
    assert 'médical' not in texte and 'fiche confidentielle' in texte
    assert sections['Doublons probables'].resume.startswith('1 groupe')


def test_groupe_avec_une_fiche_confidentielle_masque_en_entier(zotero):
    c = zotero.collection('Santé')
    a = zotero.fiche('Mon dossier médical', tags=('_privé',), collections=(c,), DOI='10.1/a')
    b_ = zotero.fiche('Mon dossier médical', collections=(c,), DOI='10.1/b')
    zotero.pdf(a, 'x.pdf', b'meme contenu')
    # Fiche jumelle sans manque relevé ailleurs (collection, DOI, nom de fichier attendu) : seuls les groupes la montrent.
    zotero.pdf(b_, 'Durand - 2020 - Mon dossier médical.pdf', b'meme contenu')
    sections, b = auditer(zotero)
    texte = audit.rapport(list(sections.values()), b)
    assert 'médical' not in texte


def test_accords_et_noms_des_types():
    assert audit.pluriel(0, 'pièce jointe') == '0 pièce jointe'
    assert audit.pluriel(2, 'pièce jointe') == '2 pièces jointes'
    assert audit.pluriel(3, 'PDF') == '3 PDF' and audit.pluriel(2, 'fois') == '2 fois'
    assert audit.nom_type('bookSection') == 'Chapitre de livre' and audit.nom_type('inconnu') == 'inconnu'


def test_fichiers_absents_recuperables_ou_perdus(zotero):
    # D133 : l'audit dit lesquels sont encore sur zotero.org.
    a, b_ = zotero.fiche('A'), zotero.fiche('B')
    zotero.pdf(a, 'a.pdf', None)
    zotero.pdf(b_, 'b.pdf', None)
    _, b = auditer(zotero)
    cles = audit.absents_importes(b)
    assert len(cles) == 2
    sections, _ = auditer(zotero, en_ligne={cles[0]: True, cles[1]: False})
    s = sections['Fichiers absents']
    assert s.resume.startswith('2 fichiers absents du disque, dont 1 encore sur zotero.org (récupérable) et 1 introuvable.')
    assert s.details[0].startswith(cles[0]) and s.details[0].endswith('sur zotero.org')
    assert s.details[1].endswith('introuvable')
    sections, _ = auditer(zotero, motif='pas de clé API')
    assert '(non vérifiés sur zotero.org, pas de clé API)' in sections['Fichiers absents'].resume


def test_fichiers_absents_selon_la_synchronisation_des_fichiers(zotero):
    # D157 : sous WebDAV ou sans synchronisation, Zotero ne cherche plus les fichiers sur zotero.org.
    a, b_ = zotero.fiche('A'), zotero.fiche('B')
    zotero.pdf(a, 'a.pdf', None)
    zotero.pdf(b_, 'b.pdf', None)
    _, b = auditer(zotero)
    cles = audit.absents_importes(b)
    en_ligne = {cles[0]: True, cles[1]: False}
    sections, _ = auditer(zotero, en_ligne=en_ligne, stockage=bbt.WEBDAV)
    s = sections['Fichiers absents']
    assert s.resume.startswith('2 fichiers absents du disque, dont 1 encore sur zotero.org (à télécharger depuis la '
                               'bibliothèque en ligne) et 1 absent de zotero.org (peut-être sur le serveur WebDAV).')
    assert s.resume.endswith('Zotero synchronise les fichiers par WebDAV.')
    assert s.details[1].endswith('pas sur zotero.org') and 'serveur WebDAV' in s.remede
    sections, _ = auditer(zotero, en_ligne=en_ligne, stockage=bbt.AUCUNE)
    s = sections['Fichiers absents']
    assert ', dont 1 encore sur zotero.org (à télécharger depuis la bibliothèque en ligne) et 1 introuvable.' in s.resume
    assert s.resume.endswith('La synchronisation des fichiers est désactivée dans Zotero.')
    assert 'ne retélécharge donc rien' in s.remede
    sections, _ = auditer(zotero, en_ligne=en_ligne, stockage=bbt.ZOTERO_ORG)
    s = sections['Fichiers absents']
    assert '(récupérable) et 1 introuvable.' in s.resume and s.resume.endswith('par zotero.org.')
    assert 'qui le retélécharge' in s.remede


def test_pdf_absents_non_controles(zotero):
    """D168 : sans les fichiers sur le disque, le contrôle des PDF identiques ne dit pas « OK »."""
    a, b_ = zotero.fiche('A'), zotero.fiche('B')
    zotero.pdf(a, 'a.pdf', None)
    zotero.pdf(b_, 'b.pdf', None)
    sections, b = auditer(zotero)
    s = sections['PDF identiques']
    assert s.statut == audit.NON_CONTROLE and '2 PDF absents du disque, non comparés' in s.resume
    assert '« au moment de la synchronisation »' in s.remede
    assert 'WebDAV' in audit.pdf_identiques(b, None, stockage=bbt.WEBDAV).remede
    assert 'ne les téléchargera donc pas' in audit.pdf_identiques(b, None, stockage=bbt.AUCUNE).remede
    texte = audit.rapport(list(sections.values()), b)
    assert '1 non contrôlé faute de fichiers sur le disque' in texte
    zotero.pdf(a, 'c.pdf', b'meme')
    zotero.pdf(b_, 'd.pdf', b'meme')
    sections, _ = auditer(zotero)
    assert sections['PDF identiques'].statut == audit.A_VOIR


def test_inbox_vide_et_racines_dont_on_peut_se_passer(zotero):
    """Une Inbox vide n'est pas une collection vide à signaler, et l'audit dit comment se passer d'une racine."""
    zotero.collection('Inbox')
    zotero.fiche('Rangée', collections=(zotero.collection('Philosophie', zotero.collection('Fonds')),))
    sections, _ = auditer(zotero)
    s = sections['Structure des collections']
    assert '0 collection vide' in s.resume and 'Racines de la méthode absentes : Projets, Archives.' in s.resume
    assert '`projets = []`, `archives = ""`' in s.remede and 'section [methode]' in s.remede


def test_fichiers_en_ligne_retenus_d_un_audit_a_l_autre(zotero, tmp_path, monkeypatch, capsys):
    # Un fichier trouvé sur zotero.org n'y est plus demandé tant que la version de sa pièce jointe ne change pas.
    # Un fichier introuvable, ou d'une pièce jointe jamais synchronisée (version 0), est redemandé à chaque audit.
    from faux_serveur import FauxServeur
    from zot_clean import ecriture
    from zot_clean.cli import main
    serveur = FauxServeur()
    f = zotero.fiche('A')
    pieces = {nom: zotero.pdf(f, f'{nom}.pdf', None) for nom in ('en_ligne', 'perdu', 'neuf')}
    for nom, version in (('en_ligne', 7), ('perdu', 8)):
        zotero.db.execute('update items set version = ? where itemID = ?', (version, pieces[nom]))
    cles = {nom: zotero.db.execute('select key from items where itemID = ?', (iid,)).fetchone()[0]
            for nom, iid in pieces.items()}
    serveur.fichiers = {cles['en_ligne'], cles['neuf']}
    zotero.enregistrer()
    travail = tmp_path / 'travail'
    travail.mkdir()
    (travail / 'config.toml').write_text(f'[zotero]\ndossier = "{zotero.dossier.as_posix()}"\n', encoding='utf-8')
    monkeypatch.setattr(ecriture, 'depuis_config', lambda cfg: serveur.client())

    def auditer_et_compter():
        serveur.requetes.clear()
        assert main(['audit', '--sans-empreintes', '--dossier', str(travail)]) == 0
        demandes = sorted(chemin.split('/')[-2] for _, chemin in serveur.requetes if chemin.endswith('/file'))
        return demandes, capsys.readouterr().out

    demandes, premier = auditer_et_compter()
    assert demandes == sorted(cles.values())
    assert 'dont 2 encore sur zotero.org (récupérables) et 1 introuvable' in premier
    demandes, second = auditer_et_compter()
    assert demandes == sorted([cles['perdu'], cles['neuf']]) and second == premier
    # Pièce jointe modifiée depuis (version reçue par la synchronisation) : redemandée.
    zotero.db.execute('update items set version = 9 where itemID = ?', (pieces['en_ligne'],))
    zotero.enregistrer()
    serveur.fichiers.discard(cles['en_ligne'])
    demandes, troisieme = auditer_et_compter()
    assert demandes == sorted(cles.values()) and 'dont 1 encore sur zotero.org' in troisieme
    # `--rafraichir` des sources vide `cache/*.json`, pas cette mémoire.
    assert not list((travail / 'cache').glob('*.json')) and (travail / 'cache' / 'zotero').is_dir()


def test_bibliotheque_jamais_synchronisee_signalee(zotero):
    """Sans clé, l'audit fonctionne, et dit qu'il faudra la synchronisation pour nettoyer."""
    assert auditer(zotero)[0]['Synchronisation'].statut == audit.OK
    zotero.compte(None)
    s = auditer(zotero)[0]['Synchronisation']
    assert s.statut == audit.A_VOIR and s.resume.startswith("Zotero n'a jamais synchronisé")
    assert 'Réglages › Synchronisation' in s.remede
