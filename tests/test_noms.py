"""Noms des fichiers calculés comme Zotero (étape 8, D148, D150).

Les valeurs attendues suivent le code de Zotero 10.0.5 (`getFileBaseNameFromItem`, `templates.mjs`,
`firstCreator` de `items.js`, `getValidFileName`, `getBestAttachments`)."""

import itertools
import json
from pathlib import Path

import pytest

from faux_serveur import FauxServeur
from test_annulation import annuler
from test_appliquer import ecrire, sauvegarde_factice
from zot_clean import bbt, config, filtre, lecture, noms, plans
from zot_clean.appliquer import ESSAI, TOUT, appliquer
from zot_clean.config import Config
from zot_clean.ecriture import Refus

DEFAUT = noms.MODELE_PAR_DEFAUT


def calculer(zotero, fiche: int, modele: str = DEFAUT, conjonction: str | None = ' et ', nom: str = 'x.pdf',
             **options) -> str:
    piece = zotero.pdf(fiche, nom, **options)
    b = lecture.lire(zotero.enregistrer())
    return noms.nom_attendu(b.elements[fiche], b.pieces[piece], b, noms.Modele.analyser(modele),
                            noms.Regles.de(b, conjonction))


@pytest.mark.parametrize('auteurs, attendu', [
    (('Durand',), 'Durand - 2020 - Titre.pdf'),
    (('Durand', 'Martin'), 'Durand et Martin - 2020 - Titre.pdf'),
    (('Durand', 'Martin', 'Petit'), 'Durand et al. - 2020 - Titre.pdf'),
    ((), '2020 - Titre.pdf'),
])
def test_modele_par_defaut_selon_le_nombre_d_auteurs(zotero, auteurs, attendu):
    assert calculer(zotero, zotero.fiche('Titre', auteurs=auteurs)) == attendu


def test_conjonction_anglaise(zotero):
    f = zotero.fiche('Titre', auteurs=('Durand', 'Martin'))
    assert calculer(zotero, f, conjonction=' and ') == 'Durand and Martin - 2020 - Titre.pdf'


def test_sans_annee_le_suffixe_disparait(zotero):
    # Un suffixe n'est ajouté qu'à une valeur non vide : « Auteur - Titre » (D150).
    assert calculer(zotero, zotero.fiche('Titre', date='')) == 'Durand - Titre.pdf'
    assert calculer(zotero, zotero.fiche('Titre', date='0000-00-00 s. d.')) == 'Durand - Titre.pdf'
    # Date que Zotero n'a pas su lire, gardée sans partie SQL : année vide.
    assert calculer(zotero, zotero.fiche('Titre', date='printemps')) == 'Durand - Titre.pdf'
    assert calculer(zotero, zotero.fiche('Titre', date='2019-03-00 mars 2019')) == 'Durand - 2019 - Titre.pdf'


def test_editeurs_puis_contributeurs_quand_le_role_principal_manque(zotero):
    seuls = zotero.fiche('Ouvrage', type_='book', auteurs=(), editeurs=('Dupont', 'Leroy'))
    assert calculer(zotero, seuls) == 'Dupont et Leroy - 2020 - Ouvrage.pdf'
    # Chapitre : l'auteur passe avant les directeurs saisis en premier.
    chapitre = zotero.fiche('Chapitre', type_='bookSection', auteurs=('Durand',), editeurs=('Dupont',))
    assert calculer(zotero, chapitre) == 'Durand - 2020 - Chapitre.pdf'
    contributeur = zotero.fiche('Note', auteurs=(), createurs=(('Roux', 'B.', 'contributor'),))
    assert calculer(zotero, contributeur) == 'Roux - 2020 - Note.pdf'
    traducteur = zotero.fiche('Traduction', auteurs=(), createurs=(('Roux', 'B.', 'translator'),))
    assert calculer(zotero, traducteur) == '2020 - Traduction.pdf'


def test_champs_de_base_propres_au_type(zotero):
    # Pour une affaire, title est caseName et la date est dateDecided, comme getField(…, true) dans Zotero.
    affaire = zotero.fiche('', type_='case', auteurs=('Cour',), date='', caseName='Arrêt Dupont',
                           dateDecided='2001-05-12 12 mai 2001')
    assert calculer(zotero, affaire) == 'Cour - 2001 - Arrêt Dupont.pdf'


def test_titre_long_tronque_a_100_unites_puis_sans_espace_final(zotero):
    titre = 'Mot ' * 30
    assert calculer(zotero, zotero.fiche(titre)) == f"Durand - 2020 - {('Mot ' * 25).strip()}.pdf"


def test_caracteres_hors_du_plan_de_base_comptes_double_et_retires(zotero):
    # JavaScript compte un emoji pour deux unités, et getValidFileName en retire les deux moitiés.
    assert calculer(zotero, zotero.fiche('A' * 99 + '😀b')) == 'Durand - 2020 - ' + 'A' * 99 + '.pdf'
    assert calculer(zotero, zotero.fiche('Un 😀 deux')) == 'Durand - 2020 - Un  deux.pdf'


def test_caracteres_interdits_balises_et_point_initial(zotero):
    f = zotero.fiche('Pourquoi? Le "vrai" : a/b <i>c</i>|d*', auteurs=('Durand',))
    assert calculer(zotero, f) == 'Durand - 2020 - Pourquoi Le vrai  ab cd.pdf'
    sans_rien = zotero.fiche('.cache', auteurs=(), date='')
    assert calculer(zotero, sans_rien) == 'cache.pdf'
    vide = zotero.fiche('', auteurs=(), date='')
    assert calculer(zotero, vide) == '_.pdf'


def test_extension_du_fichier_ou_du_type(zotero):
    f = zotero.fiche('Titre')
    assert calculer(zotero, f, nom='sans-extension') == 'Durand - 2020 - Titre.pdf'
    assert calculer(zotero, f, nom='ABSENT.PDF', contenu=None) == 'Durand - 2020 - Titre.PDF'
    assert calculer(zotero, f, nom='livre.epub', type_contenu='application/epub+zip') == 'Durand - 2020 - Titre.epub'


def test_suffixe_qui_se_repeterait_ecrit_une_fois(zotero):
    f = zotero.fiche('Titre')
    assert calculer(zotero, f, '{{ firstCreator suffix="-" }}-{{ year }}') == 'Durand-2020.pdf'
    # Un suffixe déjà présent à la fin de la valeur n'est pas ajouté.
    g = zotero.fiche('Titre -', auteurs=())
    assert calculer(zotero, g, '{{ title suffix=" -" }}{{ year }}') == 'Titre -2020.pdf'


def test_variables_et_parametres_courants(zotero):
    f = zotero.fiche('Titre long', auteurs=(), createurs=(('Durand', 'Anne', 'author'), ('Martin', 'Paul', 'author'),
                                                          ('Petit', 'Léa', 'author'), ('Roux', 'Ève', 'editor')),
                     publicationTitle='Revue', date='2020-02-03 3 février 2020')
    cas = {
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
    b_avant = None
    for modele, attendu in cas.items():
        piece = zotero.pdf(f, 'x.pdf', None)
        b_avant = lecture.lire(zotero.enregistrer())
        regles = noms.Regles.de(b_avant, ' et ')
        base = noms.nom_de_base(b_avant.elements[f], noms.Modele.analyser(modele), regles)
        assert base == attendu, modele
    assert piece in b_avant.pieces


def test_titre_de_la_piece_jointe(zotero):
    f = zotero.fiche('Titre')
    assert calculer(zotero, f, '{{ year suffix=" " }}{{ attachmentTitle }}', titre='Version auteur') == \
        '2020 Version auteur.pdf'


@pytest.mark.parametrize('modele, motif', [
    ('{{ if year }}{{ year }}{{ endif }}', 'condition'),
    ('{{ title match="\\d+" }}', 'match'),
    ('{{ title replaceFrom="a" replaceTo="b" }}', 'replaceFrom'),
    ('{{ title case="title" }}', 'title'),
    ('{{ itemType localize="true" }}', 'localize'),
])
def test_modele_hors_du_sous_ensemble(modele, motif):
    with pytest.raises(noms.ModeleNonPrisEnCharge, match=motif):
        noms.Modele.analyser(modele)


def test_modele_lu_dans_zotero(zotero):
    b = lecture.lire(zotero.enregistrer())
    assert noms.modele_de(b) == DEFAUT
    zotero.reglage('attachmentRenameTemplate', '{{ year }} {{ title }}')
    assert noms.modele_de(lecture.lire(zotero.enregistrer())) == '{{ year }} {{ title }}'
    # Un modèle mal formé est remplacé par le modèle par défaut, comme dans Zotero.
    zotero.reglage('attachmentRenameTemplate', '{{ year }')
    assert noms.modele_de(lecture.lire(zotero.enregistrer())) == DEFAUT
    zotero.reglage('attachmentRenameTemplate', '{{ if year }}x')
    assert noms.modele_de(lecture.lire(zotero.enregistrer())) == DEFAUT


def test_conjonction_deduite_des_noms_existants(zotero, tmp_path):
    for i, nom in enumerate(('Durand and Martin - 2020 - Un.pdf', 'Durand and Martin - 2020 - Deux.pdf',
                             'Durand et Martin - 2020 - Trois.pdf', 'Durand et Martin - 1999 - Quatre.pdf')):
        f = zotero.fiche(['Un', 'Deux', 'Trois', 'Quatre'][i], auteurs=('Durand', 'Martin'))
        zotero.pdf(f, nom)
    b = lecture.lire(zotero.enregistrer())
    modele = noms.Modele.analyser(DEFAUT)
    # Le quatrième nom date d'anciennes métadonnées : il ne compte pas.
    assert noms.deduire_conjonction(b, modele) == (' and ', 2)
    cfg = config.Config(dossier_travail=tmp_path)
    assert noms.conjonction(b, cfg, modele) == ' and '
    cfg.methode.conjonction = 'et'
    assert noms.conjonction(b, cfg, modele) == ' et '


def test_conjonction_inconnue(zotero, tmp_path):
    f = zotero.fiche('Titre', auteurs=('Durand', 'Martin'))
    zotero.pdf(f, 'scan.pdf')
    b = lecture.lire(zotero.enregistrer())
    modele = noms.Modele.analyser(DEFAUT)
    assert noms.conjonction(b, config.Config(dossier_travail=tmp_path), modele) is None
    with pytest.raises(noms.ConjonctionInconnue):
        noms.nom_de_base(b.elements[f], modele, noms.Regles.de(b))


def test_piece_principale_comme_zotero(zotero):
    f = zotero.fiche('Titre', url='https://editeur.org/article')
    recent = zotero.pdf(f, 'recent.pdf', ajout='2026-03-01')
    ancien = zotero.pdf(f, 'ancien.pdf', ajout='2026-02-01')
    html = zotero.pdf(f, 'page.html', ajout='2025-01-01', type_contenu='text/html', mode=1)
    b = lecture.lire(zotero.enregistrer())
    assert noms.piece_principale(b, b.elements[f]).id == ancien
    # Le PDF dont l'URL est celle de la fiche passe avant un PDF plus ancien.
    venu = zotero.pdf(f, 'venu.pdf', ajout='2026-04-01', mode=1, url='https://editeur.org/article')
    b = lecture.lire(zotero.enregistrer())
    assert [p.id for p in noms.pieces_de(b, b.elements[f])] == [venu, ancien, recent, html]
    # Un instantané seul est la pièce principale, mais Zotero ne le renomme pas.
    g = zotero.fiche('Page')
    zotero.pdf(g, 'page.html', type_contenu='text/html', mode=1)
    lien = zotero.fiche('Lien')
    zotero.pdf(lien, 'https://exemple.org', mode=3, type_contenu='')
    lie = zotero.fiche('Lié')
    zotero.pdf(lie, 'lie.pdf', mode=2)
    b = lecture.lire(zotero.enregistrer())
    assert not noms.renommable(noms.piece_principale(b, b.elements[g]))
    assert noms.piece_principale(b, b.elements[lien]) is None
    assert not noms.renommable(noms.piece_principale(b, b.elements[lie]))
    assert noms.renommable(noms.piece_principale(b, b.elements[lie]), lies=True)
    assert [e.id for e, _ in noms.principales(b)] == [f]


def test_cas_ecartes(zotero):
    f = zotero.fiche('Titre')
    p = zotero.pdf(f, 'scan.pdf', autres=('durand - 2020 - titre.pdf',))
    b = lecture.lire(zotero.enregistrer())
    piece = b.pieces[p]
    assert 'déjà pris' in noms.motif_ecarte(piece, 'Durand - 2020 - Titre.pdf')
    # Changer la seule casse du fichier lui-même n'est pas une collision.
    assert noms.motif_ecarte(piece, 'SCAN.pdf') is None
    assert 'Windows' in noms.motif_ecarte(piece, 'Titre.')
    assert 'réservé' in noms.motif_ecarte(piece, 'CON.pdf')
    assert 'réservé' in noms.motif_ecarte(piece, 'nul .pdf')
    assert noms.motif_ecarte(piece, 'Console.pdf') is None
    assert 'octets' in noms.motif_ecarte(piece, 'é' * 130 + '.pdf')
    assert 'chemin' in noms.motif_ecarte(piece, 'a' * 240 + '.pdf')


def test_renommage_local_echoue(zotero):
    f = zotero.fiche('Titre')
    echoue = zotero.pdf(f, 'Durand - 2020 - Titre.pdf', None, autres=('ancien.pdf',))
    absent = zotero.pdf(zotero.fiche('Autre'), 'perdu.pdf', None)
    b = lecture.lire(zotero.enregistrer())
    assert noms.autre_fichier(b.pieces[echoue]) == 'ancien.pdf'
    assert noms.autre_fichier(b.pieces[absent]) is None


def test_ancien_config_avec_modele_fichier(tmp_path):
    (tmp_path / 'config.toml').write_text("[methode]\nmodele_fichier = '^.+$'\nconjonction = \"and\"\n",
                                          encoding='utf-8')
    cfg = config.charger(Path(tmp_path))
    assert cfg.methode.conjonction == 'and' and not hasattr(cfg.methode, 'modele_fichier')


# Plan de l'étape 8 (D147, D149, D150, D158)

MODES_API = {0: 'imported_file', 1: 'imported_url', 2: 'linked_file'}


class Monde:
    """Fiches et pièces jointes créées à la fois dans la base synthétique et sur le faux serveur, avec les mêmes
    clés. `synchroniser` fait ce que fait Zotero après une écriture par l'API : fichier renommé sur le disque,
    chemin et titre de la pièce jointe repris du serveur (D161)."""

    def __init__(self, zotero, serveur):
        self.zotero, self.serveur = zotero, serveur
        serveur._n = itertools.count(10 ** 6)
        self.ids: dict[str, int] = {}

    def fiche(self, titre, auteurs=('Durand',), date='2020', **champs):
        cle = self.serveur._cle()
        self.ids[cle] = self.zotero.fiche(titre, auteurs=auteurs, date=date, cle=cle, **champs)
        self.serveur.ajouter(key=cle, title=titre, date=date,
                             creators=[{'creatorType': 'author', 'lastName': a, 'firstName': 'A.'} for a in auteurs],
                             **{k: v for k, v in champs.items() if k != 'tags'})
        return cle

    def pdf(self, parent, nom, titre=None, contenu=b'%PDF-1.4 factice', mode=0, type_contenu='application/pdf',
            **options):
        cle = self.serveur._cle()
        titre = nom if titre is None else titre
        self.ids[cle] = self.zotero.pdf(self.ids[parent], nom, contenu, cle=cle, titre=titre, mode=mode,
                                        type_contenu=type_contenu, **options)
        self.serveur.ajouter('attachment', key=cle, parentItem=parent, linkMode=MODES_API[mode], title=titre,
                             contentType=type_contenu, **({'path': f'/Documents/{nom}'} if mode == 2
                                                          else {'filename': nom, 'md5': 'abc'}))
        return cle

    def synchroniser(self):
        db = self.zotero.db
        titre = db.execute("select fieldID from fields where fieldName = 'title'").fetchone()[0]
        for cle, iid in self.ids.items():
            d = self.serveur.elements[cle]
            if d.get('itemType') != 'attachment' or 'filename' not in d:
                continue
            ancien = db.execute('select path from itemAttachments where itemID = ?', (iid,)).fetchone()[0]
            ancien = ancien.removeprefix('storage:')
            dossier = self.zotero.dossier / 'storage' / cle
            if ancien != d['filename'] and (dossier / ancien).is_file():
                (dossier / ancien).rename(dossier / d['filename'])
            db.execute('update itemAttachments set path = ? where itemID = ?', (f"storage:{d['filename']}", iid))
            db.execute('delete from itemData where itemID = ? and fieldID = ?', (iid, titre))
            self.zotero._champs(iid, {'title': d.get('title', '')})

    def lire(self):
        self.zotero.synchroniser(self.serveur.version)
        return lecture.lire(self.zotero.enregistrer())


@pytest.fixture
def serveur():
    return FauxServeur()


@pytest.fixture
def cfg(tmp_path, zotero):
    return Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)


@pytest.fixture
def monde(zotero, serveur):
    m = Monde(zotero, serveur)
    f = {'juste': m.fiche('Déjà bien nommé'), 'titre': m.fiche('Titre court'), 'deux': m.fiche('Deux PDF'),
         'casse': m.fiche('casse'), 'autre': m.fiche('Autre retard'), 'lie': m.fiche('Fichier lié')}
    x = {'juste': m.pdf(f['juste'], 'Durand - 2020 - Déjà bien nommé.pdf'),
         # Titre égal à l'ancien nom, seul PDF de la fiche : il devient « PDF ».
         'titre': m.pdf(f['titre'], 'scan.pdf'),
         # Deux PDF : le titre de la pièce principale, égal à l'ancien nom sans extension (casse ignorée), devient le
         # nouveau nom sans extension. Le second PDF n'est pas renommé.
         'deux': m.pdf(f['deux'], 'article.pdf', titre='ARTICLE', ajout='2026-01-01'),
         'second': m.pdf(f['deux'], 'annexe.pdf', ajout='2026-02-01'),
         'casse': m.pdf(f['casse'], 'Durand - 2020 - Casse.pdf', titre='Texte intégral'),
         'autre': m.pdf(f['autre'], 'x.pdf', titre='PDF'),
         'lie': m.pdf(f['lie'], 'lie.pdf', mode=2)}
    return m, f, x


def ops_par_cle(plan):
    return {op.cle: op for g in plan.groupes for op in g.operations}


def test_plan_essai_application_relance_et_annulation(monde, cfg, serveur):
    m, f, x = monde
    plan, rapport = noms.planifier(m.lire(), cfg, serveur.client(), {}, bbt.ZOTERO_ORG)
    ops = ops_par_cle(plan)
    assert plan.etape == 'noms' and set(ops) == {x['titre'], x['deux'], x['casse'], x['autre']}
    assert ops[x['titre']].avant == {'filename': 'scan.pdf', 'title': 'scan.pdf'}
    assert ops[x['titre']].apres == {'filename': 'Durand - 2020 - Titre court.pdf', 'title': 'PDF'}
    assert ops[x['deux']].apres == {'filename': 'Durand - 2020 - Deux PDF.pdf', 'title': 'Durand - 2020 - Deux PDF'}
    assert ops[x['casse']].apres == {'filename': 'Durand - 2020 - casse.pdf'}  # la casse seule change
    assert ops[x['autre']].apres == {'filename': 'Durand - 2020 - Autre retard.pdf'}
    assert [g.id for g in plan.groupes] == [f['autre'], f['casse'], f['deux'], f['titre']]
    assert 'synchronisation de Zotero' in rapport and '`zc voir`' in rapport
    assert '1 fichier lié principal en retard' in rapport

    cfg.ecriture.essai = 2
    chemin = ecrire(plan, cfg)
    bilan = appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    assert bilan.faits == [f['autre'], f['casse']] and bilan.restants == 2
    assert serveur.elements[x['casse']]['filename'] == 'Durand - 2020 - casse.pdf'
    assert serveur.elements[x['casse']]['md5'] == 'abc'
    with pytest.raises(Refus, match='sauvegarde'):
        appliquer(plan, chemin, serveur.client(), cfg, TOUT)

    # Après l'essai, Zotero renomme les fichiers : une relance ne planifie que le reste.
    m.synchroniser()
    reste, _ = noms.planifier(m.lire(), cfg, serveur.client(), {}, bbt.ZOTERO_ORG)
    assert {g.id for g in reste.groupes} == {f['deux'], f['titre']}
    sauvegarde_factice(cfg)
    bilan = appliquer(plan, chemin, serveur.client(), cfg, TOUT)
    assert sorted(bilan.faits) == sorted([f['deux'], f['titre']]) and not bilan.conflits
    assert serveur.elements[x['titre']]['title'] == 'PDF'
    assert serveur.elements[x['second']]['filename'] == 'annexe.pdf'
    m.synchroniser()
    b = m.lire()
    assert (m.zotero.dossier / 'storage' / x['titre'] / 'Durand - 2020 - Titre court.pdf').is_file()
    fin, _ = noms.planifier(b, cfg, serveur.client(), {}, bbt.ZOTERO_ORG)
    assert fin.groupes == []

    # L'annulation remet les anciens noms et titres.
    p_ann, _, c_ann = annuler(chemin, serveur, cfg)
    appliquer(p_ann, c_ann, serveur.client(), cfg, ESSAI)
    appliquer(p_ann, c_ann, serveur.client(), cfg, TOUT)
    assert serveur.elements[x['titre']]['filename'] == 'scan.pdf'
    assert serveur.elements[x['titre']]['title'] == 'scan.pdf'
    assert serveur.elements[x['casse']]['filename'] == 'Durand - 2020 - Casse.pdf'
    assert serveur.elements[x['deux']]['title'] == 'ARTICLE'


def test_conflit_si_le_nom_change_entre_temps(monde, cfg, serveur):
    m, f, x = monde
    plan, _ = noms.planifier(m.lire(), cfg, serveur.client(), {}, bbt.ZOTERO_ORG)
    serveur.modifier(x['titre'], filename='renommé à la main.pdf')
    bilan = appliquer(plan, ecrire(plan, cfg), serveur.client(), cfg, ESSAI)
    assert list(bilan.conflits) == [f['titre']] and 'filename' in bilan.conflits[f['titre']]
    assert serveur.elements[x['titre']]['filename'] == 'renommé à la main.pdf'


def test_serveur_refuse_filename_hors_fichier_importe(monde, serveur):
    m, f, x = monde
    res = serveur.client().ecrire([{'key': x['lie'], 'version': serveur.elements[x['lie']]['version'],
                                    'filename': 'autre.pdf'}])
    assert res.echecs[x['lie']][0] == 400


@pytest.mark.parametrize('stockage, en_ligne, renomme, raison', [
    (bbt.ZOTERO_ORG, True, True, ''),
    (bbt.ZOTERO_ORG, False, False, 'introuvable'),
    (bbt.ZOTERO_ORG, None, False, 'faute d\'avoir vérifié'),
    (bbt.WEBDAV, True, False, 'WebDAV'),
    (bbt.AUCUNE, True, False, 'désactivée'),
    (bbt.INCONNU, True, False, 'inconnue'),
])
def test_fichier_absent_selon_le_stockage(zotero, serveur, cfg, stockage, en_ligne, renomme, raison):
    m = Monde(zotero, serveur)
    pj = m.pdf(m.fiche('Absent'), 'perdu.pdf', contenu=None)
    plan, rapport = noms.planifier(m.lire(), cfg, serveur.client(), None if en_ligne is None else {pj: en_ligne},
                                   stockage)
    assert bool(plan.groupes) == renomme
    if renomme:
        assert ops_par_cle(plan)[pj].apres['filename'] == 'Durand - 2020 - Absent.pdf'
        assert 'stocké sur zotero.org' in rapport
    else:
        assert '## Laissés de côté' in rapport and raison in rapport and 'Durand - 2020 - Absent.pdf' in rapport
    assert noms.absents(m.lire()) == [pj]


def test_cas_ecartes_et_noms_incalculables(zotero, serveur, cfg):
    m = Monde(zotero, serveur)
    pris = m.pdf(m.fiche('Titre'), 'scan.pdf', autres=('durand - 2020 - titre.pdf',))
    m.pdf(m.fiche('Deux auteurs', auteurs=('Durand', 'Martin')), 'b.pdf')
    plan, rapport = noms.planifier(m.lire(), cfg, serveur.client(), {}, bbt.ZOTERO_ORG)
    assert plan.groupes == []
    assert f'{pris} · « scan.pdf » → « Durand - 2020 - Titre.pdf » · nom déjà pris' in rapport
    assert 'nom non calculé (conjonction' in rapport
    cfg.methode.conjonction = 'et'
    plan, _ = noms.planifier(m.lire(), cfg, serveur.client(), {}, bbt.ZOTERO_ORG)
    assert [op.apres['filename'] for op in ops_par_cle(plan).values()] == ['Durand et Martin - 2020 - Deux auteurs.pdf']


def test_fiche_confidentielle_masquee(zotero, serveur, cfg):
    m = Monde(zotero, serveur)
    secret = m.fiche('Dossier médical Dupont', tags=('_privé',))
    pj = m.pdf(secret, 'dupont.pdf')
    m.pdf(m.fiche('Collision secrète', tags=('_privé',)), 'c.pdf', autres=('Durand - 2020 - Collision secrète.pdf',))
    plan, rapport = noms.planifier(m.lire(), cfg, serveur.client(), {}, bbt.ZOTERO_ORG)
    assert ops_par_cle(plan)[pj].apres['filename'] == 'Durand - 2020 - Dossier médical Dupont.pdf'
    assert plan.groupes[0].titre == filtre.MASQUE
    assert 'Dupont' not in rapport and 'Collision' not in rapport and 'dupont.pdf' not in rapport
    assert f'{pj} (fiche {secret}, {filtre.MASQUE}) · nom du fichier et titre de la pièce jointe' in rapport
    chemin = ecrire(plan, cfg)
    assert 'Dossier médical' not in json.dumps([g.titre for g in plans.charger(chemin).groupes])


def test_modele_non_pris_en_charge(monde, cfg, serveur, zotero):
    m, f, x = monde
    zotero.reglage('attachmentRenameTemplate', '{{ title case="title" }}')
    with pytest.raises(noms.ModeleNonPrisEnCharge, match='Renommer les fichiers…'):
        noms.planifier(m.lire(), cfg, serveur.client(), {}, bbt.ZOTERO_ORG)


def test_copie_locale_en_retard(monde, cfg, serveur):
    m, f, x = monde
    b = m.lire()
    serveur.modifier(f['titre'], title='Changé ailleurs')
    with pytest.raises(SystemExit, match='pas encore reçu'):
        noms.planifier(b, cfg, serveur.client(), {}, bbt.ZOTERO_ORG)


def test_metadonnees_d_apres_un_plan(zotero, serveur):
    m = Monde(zotero, serveur)
    cle = m.fiche('Ancien titre', date='')
    b = m.lire()
    fiche = b.par_cle()[cle]
    apres = noms.fiche_apres(b, fiche, {'title': 'Nouveau', 'date': '2019-03', 'itemType': 'book',
                                        'creators': [{'creatorType': 'author', 'name': 'OCDE'}]})
    assert (apres.type, apres.titre, apres.createurs, apres.roles) == ('book', 'Nouveau', [('OCDE', '')], ['author'])
    assert apres.champs['date'] == '2019-03-00 2019-03' and fiche.titre == 'Ancien titre'
    assert noms.date_multipart('printemps 1998') == '1998-00-00 printemps 1998'
    assert noms.date_multipart('s. d.') == 's. d.'
    epub = {'filename': 'livre.epub', 'title': 'livre', 'contentType': 'application/epub+zip'}
    assert noms.nouveau_titre(epub, 'A - Livre.epub', True, ' et ') == 'Livre numérique'
    assert noms.nouveau_titre(epub, 'A - Livre.epub', True, None) is None
    assert noms.nouveau_titre(epub, 'A - Livre.epub', False, None) == 'A - Livre'
    assert noms.nouveau_titre(dict(epub, title='Mon livre'), 'A - Livre.epub', True, ' et ') is None


def test_commande(monde, cfg, serveur, monkeypatch, capsys):
    from zot_clean import ecriture
    from zot_clean.cli import main
    m, f, x = monde
    m.pdf(m.fiche('Absent'), 'perdu.pdf', contenu=None)
    m.lire()
    cfg.dossier_travail.mkdir()
    (cfg.dossier_travail / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.dossier_zotero.as_posix()}"\n', encoding='utf-8')
    monkeypatch.setattr(ecriture, 'depuis_config', lambda cfg: serveur.client())
    assert main(['noms', 'planifier', '--hors-ligne', '--dossier', str(cfg.dossier_travail)]) == 0
    sortie = capsys.readouterr().out
    assert '4 fichier(s) à renommer' in sortie and '--essai' in sortie
    rapport = next((cfg.dossier_travail / 'plans').glob('*_noms_*.md')).read_text(encoding='utf-8')
    assert 'profil de Zotero introuvable' in rapport
