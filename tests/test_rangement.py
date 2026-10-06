"""Rangement, étape 5 (D112 à D122), sur une bibliothèque synthétique et le faux serveur."""

import itertools

import pytest

from faux_serveur import FauxServeur
from test_appliquer import ecrire, sauvegarde_factice
from zot_clean import appliquer as a, fonds as f, lecture, rangement as r
from zot_clean.appliquer import ESSAI, TOUT, appliquer
from zot_clean.config import Config
from zot_clean.ecriture import ErreurAPI

PLAN = """\
# 40 Fonds

## Psychologie

Esprit et comportement.

### Perception

Perception humaine.

#### Apprentissage perceptif

Apprendre à percevoir.

### Émotion

Émotions.

## Arts

Arts visuels.

# Concepts
"""


class Biblio:
    """Collections et fiches créées à la fois dans la base synthétique et sur le faux serveur, avec les mêmes clés."""

    def __init__(self, zotero, serveur):
        self.zotero, self.serveur = zotero, serveur
        serveur._n = itertools.count(10 ** 6)
        self.ids: dict[str, int] = {}

    def collection(self, nom, parent=None):
        cle = self.serveur.collection(nom, parent)
        self.ids[cle] = self.zotero.collection(nom, self.ids[parent] if parent else None, cle=cle)
        return cle

    def fiche(self, titre, *collections, **champs):
        cle = self.serveur._cle()
        self.zotero.fiche(titre, collections=tuple(self.ids[c] for c in collections), cle=cle, **champs)
        self.serveur.ajouter(title=titre, key=cle, collections=list(collections))
        return cle

    def lire(self):
        self.zotero.synchroniser(self.serveur.version)
        return lecture.lire(self.zotero.enregistrer())


@pytest.fixture
def serveur():
    return FauxServeur()


@pytest.fixture
def cfg(tmp_path, zotero):
    c = Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)
    c.dossier_travail.mkdir()
    c.methode.fonds, c.methode.archives, c.methode.projets = '40 Fonds', '80 Archives', ['20 Cours']
    return c


@pytest.fixture
def monde(zotero, serveur, cfg):
    bi = Biblio(zotero, serveur)
    k = {'Inbox': bi.collection('Inbox'), 'Fonds': bi.collection('40 Fonds'),
         'Archives': bi.collection('80 Archives'), 'Cours': bi.collection('20 Cours'), 'Vieux': bi.collection('Vieux')}
    k['Psy'] = bi.collection('Psychologie', k['Fonds'])
    k['Perception'] = bi.collection('Perception', k['Psy'])
    k['Emotions'] = bi.collection('Émotions', k['Psy'])
    k['Arts'] = bi.collection('Arts', k['Fonds'])
    k['Musees'] = bi.collection('Musées', k['Arts'])
    k['Ancien'] = bi.collection('Cours ancien', k['Vieux'])
    k['CoursPsy'] = bi.collection('Psy L1', k['Cours'])
    fiches = {
        'voir': bi.fiche('Learning to see', k['Perception'], k['CoursPsy']),
        'gibson': bi.fiche('Perceptual learning', k['Perception']),
        'peur': bi.fiche('Fear and faces', k['Emotions']),
        'musee': bi.fiche('Museum displays', k['Musees']),
        'vieux': bi.fiche('Une vieille chose', k['Vieux']),
        'manuel': bi.fiche('Introducing HTML5', k['Arts']),
        'ancien': bi.fiche('Syllabus 2019', k['Ancien']),
    }
    b = bi.lire()
    (cfg.dossier_travail / f.PLAN).write_text(PLAN, encoding='utf-8')
    rapport, suivi, _, _ = f.inventaire(b, cfg)
    sorts = {'40 Fonds/Psychologie': (f.THEME, 'Psychologie', []),
             '40 Fonds/Psychologie/Perception': (f.REPARTIR, '', ['Psychologie/Perception',
                                                                   'Psychologie/Perception/Apprentissage perceptif']),
             '40 Fonds/Psychologie/Émotions': (f.THEME, 'Psychologie/Émotion', []),
             '40 Fonds/Arts': (f.THEME, 'Arts', []), '40 Fonds/Arts/Musées': (f.THEME, 'Arts', []),
             'Vieux': (f.DISSOUDRE, '', []), 'Vieux/Cours ancien': (f.ARCHIVES, '', [])}
    for c in suivi.collections:
        if c.chemin in sorts:
            c.sort, c.cible, c.candidats = sorts[c.chemin]
    f.ecrire_suivi(cfg, suivi)
    k_ = f.controler(cfg)
    assert not k_.erreurs, k_.erreurs
    f.enregistrer(cfg, k_)
    r.ecrire(cfg, [
        r.Entree(fiches['voir'], r.DEPLACER, 'Psychologie/Perception/Apprentissage perceptif', decision=r.ACCEPTER),
        r.Entree(fiches['manuel'], r.CORBEILLE, source=r.CONSIGNE, decision=r.ACCEPTER),
        r.Entree(fiches['gibson'], r.DEPLACER, 'Psychologie/Perception/Apprentissage perceptif'),  # pas encore jugée
    ], b, set())
    return bi, k, fiches, b


def ops_par_cle(plan):
    return {op.cle: op for g in plan.groupes for op in g.operations}


def test_plan_de_la_premiere_passe(monde, cfg, serveur):
    bi, k, fiches, b = monde
    plan, rapport = r.planifier(b, cfg, serveur.client())
    ops = ops_par_cle(plan)
    # Émotions renommée sur place, clé gardée (D113).
    assert ops[k['Emotions']].apres == {'name': 'Émotion'} and ops[k['Emotions']].genre == 'collections'
    # Sous-thème créé sous Perception, la fiche jugée y passe et quitte Perception (D115).
    creee = next(op for op in ops.values() if op.creation and op.apres['name'] == 'Apprentissage perceptif')
    assert creee.apres == {'name': 'Apprentissage perceptif', 'parentCollection': k['Perception']}
    assert ops[fiches['voir']].apres['collections'] == [k['CoursPsy'], creee.cle]
    assert fiches['gibson'] not in ops  # proposition non acceptée
    # Musées fusionnée dans Arts puis à la corbeille, Vieux dissoute, Cours ancien archivée (D117, D113).
    assert ops[fiches['musee']].apres['collections'] == [k['Arts']]
    assert ops[k['Musees']].apres == {'deleted': True} and ops[k['Vieux']].apres == {'deleted': True}
    # Archivée à son chemin actuel (cible par défaut), sous une collection « Vieux » créée dans les archives.
    vieux_archive = next(op for op in ops.values() if op.creation and op.apres['name'] == 'Vieux')
    assert vieux_archive.apres['parentCollection'] == k['Archives']
    assert ops[k['Ancien']].apres == {'parentCollection': vieux_archive.cle}
    assert ops[fiches['manuel']].apres == {'deleted': True}
    # Groupes dans l'ordre de l'arbre (D120) : Psychologie/Perception/… avant Émotion avant Arts, corbeille à la fin.
    titres = [g.titre for g in plan.groupes]
    assert titres.index('40 Fonds/Psychologie/Perception/Apprentissage perceptif') < titres.index(
        '40 Fonds/Psychologie/Émotion') < titres.index('40 Fonds/Arts')
    assert plan.groupes[-1].titre == 'fiches à la corbeille'
    # Les fiches de Vieux (dissoute) et de Cours ancien (archivée) n'ont plus de place dans le fonds (D20).
    assert 'Fiches sans place dans le fonds' in rapport and '2 fiche(s)' in rapport
    assert 'Musées dans 40 Fonds/Arts' in rapport


def test_application_puis_annulation(monde, cfg, serveur):
    bi, k, fiches, b = monde
    plan, rapport = r.planifier(b, cfg, serveur.client())
    chemin = ecrire(plan, cfg)
    appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    sauvegarde_factice(cfg)
    bilan = appliquer(plan, chemin, serveur.client(), cfg, TOUT)
    assert not bilan.conflits and not bilan.erreurs
    assert serveur.collections[k['Emotions']]['name'] == 'Émotion'
    assert serveur.collections[k['Musees']]['deleted'] is True
    assert serveur.elements[fiches['manuel']]['deleted'] is True
    nouvelle = next(c for c, d in serveur.collections.items() if d['name'] == 'Apprentissage perceptif')
    assert nouvelle in serveur.elements[fiches['voir']]['collections']


def test_sous_theme_deja_cree_reconnu(monde, cfg, serveur, zotero):
    """Une passe suivante retrouve le sous-thème créé par la précédente, par son chemin (D119)."""
    bi, k, fiches, _ = monde
    sous = bi.collection('Apprentissage perceptif', k['Perception'])
    b = bi.lire()
    plan, _ = r.planifier(b, cfg, serveur.client())
    ops = ops_par_cle(plan)
    assert not any(op.creation and op.apres['name'] == 'Apprentissage perceptif' for op in ops.values())
    assert ops[fiches['voir']].apres['collections'] == [k['CoursPsy'], sous]


def test_racines_a_la_demande(monde, cfg, serveur):
    bi, k, fiches, b = monde
    plan, _ = r.planifier(b, cfg, serveur.client())
    assert not any(op.nature == 'racine' for g in plan.groupes for op in g.operations)
    plan, _ = r.planifier(b, cfg, serveur.client(), avec_racines=True)
    derniers = [op for g in plan.groupes[-3:] for op in g.operations if op.nature == 'racine']
    assert {op.apres['name'] for op in derniers} == {'Fonds', 'Archives', 'Cours'}


def test_concordance_apres_renommage_des_racines(monde, cfg, serveur, zotero):
    bi, k, fiches, _ = monde
    zotero.db.execute("update collections set collectionName = 'Fonds' where key = ?", (k['Fonds'],))
    with pytest.raises(SystemExit, match='à reporter dans config.toml'):
        r.planifier(bi.lire(), cfg, serveur.client())


def test_structure_modifiee_depuis_la_validation(monde, cfg, serveur):
    bi, k, fiches, b = monde
    (cfg.dossier_travail / f.PLAN).write_text(PLAN.replace('# Concepts', '## Sociologie\n\nSociétés.\n\n# Concepts'),
                                               encoding='utf-8')
    with pytest.raises(SystemExit, match='pas validé'):
        r.planifier(b, cfg, serveur.client())


def test_rien_a_faire_quand_tout_est_en_place(zotero, serveur, cfg):
    bi = Biblio(zotero, serveur)
    fonds = bi.collection('40 Fonds')
    psy = bi.collection('Psychologie', fonds)
    bi.fiche('Titre', psy)
    b = bi.lire()
    (cfg.dossier_travail / f.PLAN).write_text('# 40 Fonds\n\n## Psychologie\n\nDéfinition.\n', encoding='utf-8')
    _, suivi, _, _ = f.inventaire(b, cfg)
    assert suivi.collections[0].sort == f.THEME  # prérempli : déjà à sa place dans le plan
    f.ecrire_suivi(cfg, suivi)
    f.enregistrer(cfg, f.controler(cfg))
    plan, _ = r.planifier(b, cfg, serveur.client())
    assert plan.groupes == []


def test_action_inconnue(cfg):
    cfg.suivi.mkdir(parents=True)
    (cfg.suivi / r.FICHIER).write_text('[[fiche]]\ncle = "AAAA2222"\naction = "jeter"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match='action inconnue'):
        r.charger(cfg)


def test_a_ranger_et_propositions_des_tags(monde, cfg, serveur, zotero):
    """D121 : paquets des fiches à répartir et sans place, propositions tirées des tags, filtre respecté."""
    bi, k, fiches, _ = monde
    tagguee = bi.fiche('Perceptual expertise', k['Perception'], tags=('apprentissage visuel',))
    bi.fiche('Carnet privé', k['Perception'], tags=('_privé',))
    b = bi.lire()
    s = f.charger_suivi(cfg)
    s.tags['apprentissage visuel'] = 'Psychologie/Perception/Apprentissage perceptif'
    f.ecrire_suivi(cfg, s)
    rapport, paquets, ajouts = r.a_ranger(b, cfg)
    perception = next(p for p in paquets if p.depuis == k['Perception'])
    # « voir » et « gibson » sont déjà dans rangement.toml, la fiche privée est omise.
    assert [el.cle for el in perception.fiches] == [tagguee]
    assert 'Carnet privé' not in rapport and 'Apprendre à percevoir.' in rapport
    assert ajouts == 1
    entree = next(x for x in r.charger(cfg) if x.cle == tagguee)
    assert (entree.action, entree.source, entree.decision, entree.depuis) == (r.DEPLACER, r.TAG, '', k['Perception'])
    sans = next(p for p in paquets if p.source == 'sans place dans le fonds')
    assert {el.cle for el in sans.fiches} == {fiches['vieux'], fiches['ancien']}
    assert sans.candidats == ['Psychologie', 'Arts']
    # Relancé, rien n'est proposé deux fois.
    assert r.a_ranger(b, cfg)[2] == 0


def test_a_ranger_cree_le_fichier_des_decisions(monde, cfg):
    """Sans rangement.toml, `a-ranger` l'écrit avec son en-tête et un exemple commenté, qui se lit sans entrée et
    dont l'exemple, décommenté, est une entrée valide (répétition du pilote)."""
    bi, k, fiches, _ = monde
    bi.fiche('Sans collection')
    (cfg.suivi / r.FICHIER).unlink()
    rapport, _, _ = r.a_ranger(bi.lire(), cfg)
    texte = (cfg.suivi / r.FICHIER).read_text(encoding='utf-8')
    assert texte == r.EN_TETE and r.charger(cfg) == []
    exemple = texte.split('# [[fiche]]', 1)[1]
    (cfg.suivi / r.FICHIER).write_text('[[fiche]]' + exemple.replace('\n# ', '\n'), encoding='utf-8')
    assert [(x.cle, x.action, x.cible) for x in r.charger(cfg)] == [('ABCD2345', r.DEPLACER, 'Psychologie/Perception')]
    assert 'Paquet 2 · sans place dans le fonds (depuis = "")' in rapport
    assert 'Une vieille chose · Article de revue · aussi dans Vieux\n' in rapport
    assert 'Sans collection · Article de revue · hors de toute collection' in rapport


def test_resume_refuse_pour_une_fiche_exclue(monde, cfg):
    bi, k, fiches, _ = monde
    privee = bi.fiche('Carnet privé', k['Perception'], tags=('_privé',), abstractNote='secret')
    publique = bi.fiche('Public', k['Perception'], abstractNote='Un résumé.')
    b = bi.lire()
    assert 'Un résumé.' in r.resume(b, cfg, publique)
    with pytest.raises(SystemExit, match='exclue'):
        r.resume(b, cfg, privee)


def test_commandes_a_ranger_et_planifier(monde, cfg, serveur, monkeypatch, capsys):
    from zot_clean import ecriture
    bi, k, fiches, b = monde
    from zot_clean.cli import main
    (cfg.dossier_travail / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.dossier_zotero.as_posix()}"\n[methode]\nfonds = "40 Fonds"\n'
        'archives = "80 Archives"\nprojets = ["20 Cours"]\n', encoding='utf-8')
    monkeypatch.setattr(ecriture, 'depuis_config', lambda cfg: serveur.client())
    dossier = ['--dossier', str(cfg.dossier_travail)]
    assert main(['fonds', 'a-ranger', *dossier]) == 0
    assert 'paquet(s)' in capsys.readouterr().out
    assert list((cfg.dossier_travail / 'rapports').glob('fonds-a-ranger-*.md'))
    assert main(['fonds', 'planifier', *dossier]) == 0
    sortie = capsys.readouterr()
    assert '--essai' in sortie.out and 'État visé calculé' in sortie.err
    # Un refus sort avec un code non nul et son message sur la sortie d'erreur (répétition du pilote).
    assert main(['fonds', 'a-ranger', '--examinees', k['Arts'], *dossier]) == 1
    assert "n'est pas une collection à répartir" in capsys.readouterr().err


def test_rapport_lisible(monde, cfg, serveur):
    bi, k, fiches, b = monde
    _, rapport = r.planifier(b, cfg, serveur.client())
    assert 'création de « Apprentissage perceptif » sous 40 Fonds/Psychologie/Perception' in rapport
    assert '« Émotions » renommée « Émotion »' in rapport
    assert 'Vieux à la corbeille' in rapport


def test_copie_locale_en_retard_sur_le_serveur(monde, cfg, serveur):
    """Après une passe, tant que Zotero n'a pas reçu les changements, planifier refuse : sinon les collections
    créées par la passe, absentes de la copie locale, seraient recréées (trouvé sur la vraie bibliothèque)."""
    bi, k, fiches, b = monde
    serveur.collection('Apprentissage perceptif', k['Perception'])  # créée par une passe, pas encore reçue
    with pytest.raises(SystemExit, match='pas encore reçu'):
        r.planifier(b, cfg, serveur.client())


def test_copie_en_retard_rattrapee_par_l_api(monde, cfg, serveur):
    """D171 : une passe que Zotero n'a pas encore reçue est lue sur zotero.org, sans attendre la synchronisation.
    La collection créée par la passe n'est donc pas recréée."""
    bi, k, fiches, b = monde
    nouvelle = serveur.collection('Apprentissage perceptif', k['Perception'])  # créée par une passe
    serveur.modifier(fiches['voir'], collections=[k['CoursPsy'], nouvelle])
    serveur.collections[k['Vieux']].update(deleted=True, version=serveur.version + 1)
    serveur.version += 1
    serveur.supprimer(fiches['ancien'])
    messages = []
    b2 = a.lire_a_jour(cfg, serveur.client(), messages.append, lire=lambda: b)
    assert b2.version == serveur.version and len(messages) == 1 and '4 changement(s)' in messages[0]
    par_cle = b2.par_cle()
    assert fiches['ancien'] not in par_cle
    assert {b2.chemin(c) for c in par_cle[fiches['voir']].collections} == {
        '20 Cours/Psy L1', '40 Fonds/Psychologie/Perception/Apprentissage perceptif'}
    assert 'Vieux' not in {c.nom for c in b2.collections.values()}
    plan, _ = r.planifier(b2, cfg, serveur.client())  # ne refuse plus
    assert not any(op.creation and op.apres.get('name') == 'Apprentissage perceptif'
                   for g in plan.groupes for op in g.operations)


def test_copie_a_jour_sans_rattrapage(monde, cfg, serveur):
    bi, k, fiches, b = monde
    messages, client = [], serveur.client()
    assert a.lire_a_jour(cfg, client, messages.append, lire=lambda: b) is b
    assert not messages and not any('since' in c for _, c in serveur.requetes)


def test_decisions_en_chaine(monde, cfg, serveur):
    """Émotions vers Perception, puis Perception vers Apprentissage perceptif : la fiche va directement dans le
    sous-thème, sans garder Perception, qu'elle n'a jamais eue (trouvé sur la vraie bibliothèque)."""
    bi, k, fiches, b = monde
    entrees = r.charger(cfg) + [
        r.Entree(fiches['peur'], r.DEPLACER, 'Psychologie/Perception', k['Emotions'], decision=r.ACCEPTER),
        r.Entree(fiches['peur'], r.DEPLACER, 'Psychologie/Perception/Apprentissage perceptif', k['Perception'],
                 decision=r.ACCEPTER)]
    r.ecrire(cfg, entrees, b, set())
    plan, _ = r.planifier(b, cfg, serveur.client())
    ops = ops_par_cle(plan)
    creee = next(op for op in ops.values() if op.creation and op.apres['name'] == 'Apprentissage perceptif')
    assert ops[fiches['peur']].apres['collections'] == [creee.cle]


def test_collection_examinee(monde, cfg, serveur, zotero):
    """Une collection à répartir entièrement jugée : ses fiches laissées en place ne sont plus présentées, celles qui
    y arrivent ensuite le sont (D124)."""
    bi, k, fiches, b = monde
    entrees = r.charger(cfg)
    with pytest.raises(SystemExit, match='attente'):  # la proposition sur « gibson » n'est pas jugée
        r.marquer_examinees(b, cfg, [k['Perception']])
    for x in entrees:
        x.decision = x.decision or r.REFUSER
    r.ecrire(cfg, entrees, b, set())
    restee = bi.fiche('Laissée en place, sans entrée', k['Perception'])
    _, paquets, _ = r.a_ranger(bi.lire(), cfg)
    assert [el.cle for p in paquets if p.depuis == k['Perception'] for el in p.fiches] == [restee]
    assert r.marquer_examinees(bi.lire(), cfg, [k['Perception']]) == {'40 Fonds/Psychologie/Perception': 3}
    nouvelle = bi.fiche('Arrivée ensuite', k['Perception'])
    _, paquets, _ = r.a_ranger(bi.lire(), cfg)
    assert [el.cle for p in paquets if p.depuis == k['Perception'] for el in p.fiches] == [nouvelle]
    with pytest.raises(SystemExit, match="n'est pas une collection à répartir"):
        r.marquer_examinees(b, cfg, [k['Arts']])


def _divers(bi, cfg, b, candidats):
    """Donne le sort « répartir » à la collection « Divers » et revalide le plan."""
    divers = next(c.cle for c in b.collections.values() if c.nom == 'Divers')
    _, suivi, _, _ = f.inventaire(b, cfg)
    for c in suivi.collections:
        if c.cle == divers:
            c.sort, c.candidats = f.REPARTIR, candidats
    f.ecrire_suivi(cfg, suivi)
    f.enregistrer(cfg, f.controler(cfg))
    return divers


def test_collection_repartie_examinee_a_la_corbeille(monde, cfg, serveur):
    """Une collection à répartir hors du plan, une fois examinée, va à la corbeille même si des fiches y ont été
    laissées, puisqu'elles ont leur place ailleurs ou sont présentées comme sans place (D167). Une fiche arrivée
    ensuite la retient jusqu'à ce qu'elle soit jugée."""
    bi, k, fiches, _ = monde
    divers = bi.collection('Divers')
    laissee = bi.fiche('Déjà en psychologie', divers, k['Psy'])
    partie = bi.fiche('Des musées', divers)
    b = bi.lire()
    _divers(bi, cfg, b, ['Psychologie', 'Arts'])
    r.ecrire(cfg, r.charger(cfg) + [r.Entree(partie, r.DEPLACER, 'Arts', divers, decision=r.ACCEPTER)], b, set())
    plan, _ = r.planifier(b, cfg, serveur.client())
    assert divers not in ops_par_cle(plan)  # « Déjà en psychologie » y reste, collection pas encore examinée
    r.marquer_examinees(b, cfg, [divers])
    plan, rapport = r.planifier(b, cfg, serveur.client())
    ops = ops_par_cle(plan)
    assert ops[divers].apres == {'deleted': True} and laissee not in ops
    assert 'corbeille : Divers (répartie et examinée)' in [g.titre for g in plan.groupes]
    assert '## Collections réparties' in rapport and '- Divers, 1 fiche laissée' in rapport
    bi.fiche('Arrivée après examen', divers)
    plan, _ = r.planifier(bi.lire(), cfg, serveur.client())
    assert divers not in ops_par_cle(plan)



def test_collection_repartie_avec_sa_sous_collection(monde, cfg, serveur):
    """Une collection à répartir et sa sous-collection, toutes deux examinées, vont à la corbeille dans la même passe
    (la seconde passe n'était nécessaire que pour le parent, répétition du pilote)."""
    bi, k, fiches, _ = monde
    divers = bi.collection('Divers')
    sous = bi.collection('À trier', divers)
    bi.fiche('Déjà en psychologie', sous, k['Psy'])
    b = bi.lire()
    _, suivi, _, _ = f.inventaire(b, cfg)
    for c in suivi.collections:
        if c.cle in (divers, sous):
            c.sort, c.candidats = f.REPARTIR, ['Psychologie']
    f.ecrire_suivi(cfg, suivi)
    f.enregistrer(cfg, f.controler(cfg))
    r.marquer_examinees(b, cfg, [divers, sous])
    plan, rapport = r.planifier(b, cfg, serveur.client())
    ops = ops_par_cle(plan)
    assert ops[divers].apres == ops[sous].apres == {'deleted': True}
    assert 'garde des sous-collections' not in rapport

def test_fiche_presentee_dans_un_seul_paquet(monde, cfg, serveur):
    """Une fiche d'une collection à répartir hors du plan, sans autre place dans le fonds, n'est présentée que dans
    le paquet de sa collection, pas aussi parmi les fiches sans place (trouvé à la répétition du pilote)."""
    bi, k, fiches, _ = monde
    seule = bi.fiche('Seule dans Divers', bi.collection('Divers'))
    b = bi.lire()
    _divers(bi, cfg, b, ['Arts'])
    _, paquets, _ = r.a_ranger(b, cfg)
    assert [p.source for p in paquets if seule in {el.cle for el in p.fiches}] == ['Divers']


def test_lecture_facultative_sans_zotero_org(monde, cfg, serveur):
    """Une commande qui ne fait que lire (`zc voir`) se contente de la copie locale si zotero.org ne répond pas."""
    bi, k, fiches, b = monde
    serveur.pannes = [503] * 5
    messages = []
    assert a.lire_a_jour(cfg, serveur.client(), messages.append, lire=lambda: b, facultatif=True) is b
    assert 'injoignable' in messages[0]
    serveur.pannes = [503] * 5
    with pytest.raises(ErreurAPI):
        a.lire_a_jour(cfg, serveur.client(), lire=lambda: b)


def test_archive_sans_cible_ne_bouge_plus(monde, cfg, serveur):
    """Une collection archivée sans cible va à son chemin actuel sous les archives. À la passe suivante, elle y est
    déjà : rien ne la redéplace vers « Archives/Archives/… » (répétition du pilote)."""
    bi, k, fiches, b = monde
    plan, _ = r.planifier(b, cfg, serveur.client())
    chemin = ecrire(plan, cfg)
    appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    sauvegarde_factice(cfg)
    assert not appliquer(plan, chemin, serveur.client(), cfg, TOUT).conflits
    b2 = a.lire_a_jour(cfg, serveur.client(), lire=lambda: b)
    assert b2.chemin(next(c for c in b2.collections.values() if c.cle == k['Ancien']).id) == \
        '80 Archives/Vieux/Cours ancien'
    plan2, _ = r.planifier(b2, cfg, serveur.client())
    assert plan2.groupes == [], [g.titre for g in plan2.groupes]


def test_fiches_laissees_hors_du_fonds(monde, cfg, serveur):
    """D176 : une fiche sans place, vue et laissée hors du fonds par décision, ne revient plus dans `a-ranger`, le tri
    de l'Inbox ni le point 12 de l'audit, qui la compte à part. Elle revient si ses collections changent."""
    from zot_clean import controle, inbox
    bi, k, fiches, _ = monde
    vague = bi.fiche('Notes diverses')  # hors de toute collection
    dans_inbox = bi.fiche('À trier', k['Inbox'])
    b = bi.lire()

    def sans_place(b):
        return {el.cle for p in r.a_ranger(b, cfg)[1] if not p.depuis for el in p.fiches}

    assert vague in sans_place(b) and vague in {a.fiche.cle for a in inbox.a_trier(b, cfg)}
    section, _ = controle.plan_du_fonds(b, cfg)
    assert f'hors fonds · {vague}' in section.points
    # Refus : une fiche de l'Inbox, une fiche déjà dans le fonds, une fiche avec une décision en attente.
    with pytest.raises(SystemExit, match="Inbox"):
        r.laisser(b, cfg, [dans_inbox])
    with pytest.raises(SystemExit, match='déjà sa place'):
        r.laisser(b, cfg, [fiches['peur']])
    r.ecrire(cfg, r.charger(cfg) + [r.Entree(vague, r.DEPLACER, 'Arts')], b, set())
    with pytest.raises(SystemExit, match='en attente ou acceptée'):
        r.laisser(b, cfg, [vague])
    r.ecrire(cfg, [x for x in r.charger(cfg) if x.cle != vague] + [r.Entree(vague, r.DEPLACER, 'Arts',
                                                                         decision=r.REFUSER)], b, set())
    assert r.laisser(b, cfg, [vague, fiches['ancien']]) == sorted([vague, fiches['ancien']])

    assert vague not in sans_place(b)
    rapport, _, _ = r.a_ranger(b, cfg)
    assert 'Fiches laissées hors du fonds par décision' in rapport
    liste, laissees = inbox.a_trier_et_laissees(b, cfg)
    assert vague not in {a.fiche.cle for a in liste} and vague in {a.fiche.cle for a in laissees}
    assert dans_inbox in {a.fiche.cle for a in liste}
    section, _ = controle.plan_du_fonds(b, cfg)
    assert f'hors fonds · {vague}' not in section.points
    assert 'laissées hors du fonds par décision' in section.resume
    # Le plan de rangement les compte à part. « Cours ancien » est archivée sans changer de clé, sa fiche reste
    # laissée. « Vieux » va à la corbeille, sa fiche n'est pas laissée et reste comptée sans place.
    _, rapport = r.planifier(b, cfg, serveur.client())
    assert '1 fiche(s) n\'auront aucune place' in rapport and '2 autres fiches laissées hors du fonds' in rapport

    # Rangée dans une autre collection, la fiche revient (sa décision refusée retirée, sinon `a-ranger` l'omet).
    r.ecrire(cfg, [x for x in r.charger(cfg) if x.cle != vague], b, set())
    serveur.modifier(vague, collections=[k['Vieux']])
    b2 = a.lire_a_jour(cfg, serveur.client(), lire=lambda: b)
    assert vague in sans_place(b2) and vague in {x.fiche.cle for x in inbox.a_trier(b2, cfg)}


def test_commande_laisser(monde, cfg, serveur, monkeypatch, capsys):
    from zot_clean.cli import main
    bi, k, fiches, b = monde
    (cfg.dossier_travail / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.dossier_zotero.as_posix()}"\n[methode]\nfonds = "40 Fonds"\n'
        'archives = "80 Archives"\nprojets = ["20 Cours"]\n', encoding='utf-8')
    dossier = ['--dossier', str(cfg.dossier_travail)]
    assert main(['fonds', 'a-ranger', '--laisser', fiches['ancien'], *dossier]) == 0
    assert '1 fiche(s) laissée(s) hors du fonds' in capsys.readouterr().out
    assert (cfg.suivi / r.LAISSEES).is_file()
    assert main(['fonds', 'a-ranger', '--laisser', fiches['peur'], *dossier]) == 1
    assert 'déjà sa place' in capsys.readouterr().err
