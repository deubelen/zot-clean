"""Tags, étape 6 (D151 à D156), sur une bibliothèque synthétique et le faux serveur."""

import itertools

import pytest

from faux_serveur import FauxServeur
from test_appliquer import ecrire as ecrire_plan, sauvegarde_factice
from zot_clean import annulation, lecture, plans, rangement as r, tags as t, voir
from zot_clean.appliquer import ESSAI, TOUT, appliquer
from zot_clean.config import Config
from zot_clean.lecture import Element

PLAN = """\
# Fonds

## Psychologie

Esprit et comportement.

### Perception

Perception humaine.

### Émotion

Émotions.

## Arts

Arts visuels.

# Concepts
"""


def api(tags) -> list[dict]:
    return [{'tag': x} if isinstance(x, str) else ({'tag': x[0], 'type': 1} if x[1] == 1 else {'tag': x[0]})
            for x in tags]


class Monde:
    """Éléments créés à la fois dans la base synthétique et sur le faux serveur, avec les mêmes clés et tags."""

    def __init__(self, zotero, serveur):
        self.zotero, self.serveur = zotero, serveur
        serveur._n = itertools.count(10 ** 6)
        self.ids: dict[str, int] = {}

    def collection(self, nom, parent=None):
        cle = self.serveur.collection(nom, parent)
        self.ids[cle] = self.zotero.collection(nom, self.ids[parent] if parent else None, cle=cle)
        return cle

    def fiche(self, titre, *collections, tags=(), **champs):
        cle = self.serveur._cle()
        self.ids[cle] = self.zotero.fiche(titre, collections=tuple(self.ids[c] for c in collections), cle=cle,
                                          tags=tags, **champs)
        self.serveur.ajouter(title=titre, key=cle, collections=list(collections), tags=api(tags))
        return cle

    def pdf(self, parent, tags=()):
        cle = self.serveur._cle()
        self.ids[cle] = self.zotero.pdf(self.ids[parent], f'{cle}.pdf', cle=cle, tags=tags)
        self.serveur.ajouter('attachment', key=cle, parentItem=parent, tags=api(tags))
        return cle

    def annotation(self, piece, tags=()):
        cle = self.serveur._cle()
        self.ids[cle] = self.zotero.annotation(self.ids[piece], tags=tags, cle=cle)
        self.serveur.ajouter('annotation', key=cle, parentItem=piece, tags=api(tags))
        return cle

    def synchroniser(self):
        """Tags du serveur reportés dans la base locale, comme après une synchronisation de Zotero."""
        for cle, iid in self.ids.items():
            if cle in self.serveur.elements:
                self.zotero.db.execute('delete from itemTags where itemID = ?', (iid,))
                self.zotero.tags(iid, [(x['tag'], x.get('type', 0)) for x in self.serveur.elements[cle]['tags']])

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
    c.methode.fonds = 'Fonds'
    (c.dossier_travail / 'plan.md').write_text(PLAN, encoding='utf-8')
    return c


@pytest.fixture
def monde(zotero, serveur):
    m = Monde(zotero, serveur)
    k = {'Inbox': m.collection('Inbox'), 'Fonds': m.collection('Fonds')}
    k['Psy'] = m.collection('Psychologie', k['Fonds'])
    k['Perception'] = m.collection('Perception', k['Psy'])
    k['Emotion'] = m.collection('Émotion', k['Psy'])
    k['Arts'] = m.collection('Arts', k['Fonds'])
    P, E = k['Perception'], k['Emotion']
    x = {
        'f1': m.fiche('Learning to see', P, tags=(('Humans', 1), ('Attention', 1), 'to read', 'perception visuelle',
                                                   'mémoire', ('Vision', 1))),
        'f2': m.fiche('Perceptual learning', P, tags=(('Humans', 1), ('Attention', 1), 'perception visuelle', '3 lu',
                                                       'to read')),
        'f3': m.fiche('Fear and faces', E, tags=(('Attention', 1), 'émotion', 'mémoire')),
        'f4': m.fiche('Emotional memory', E, tags=(('Attention', 1), ('Emotion', 1))),
        'f5': m.fiche('Moods', E, tags=(('Attention', 1), 'emotions', 'Machine-Learning')),
        'f6': m.fiche('Une chose', k['Arts'], tags=('truc divers', 'machine learning')),
        'f7': m.fiche('Rouge et noir', k['Arts'], tags=('rouge', '_zotfile')),
        'f8': m.fiche('Sans collection', tags=('perception visuelle',)),
        'f9': m.fiche('Importée', k['Arts'], tags=tuple(f'mot-clé {i}' for i in range(10))),
        'secret': m.fiche('Dossier médical', tags=('_privé', 'patient Dupont', ('Secretauto', 1))),
    }
    x['pdf'] = m.pdf(x['f1'], tags=(('PDF-auto', 1),))
    x['annotation'] = m.annotation(x['pdf'], tags=('à revoir',))
    m.zotero.couleur('rouge')
    m.zotero.recherche('Vision', 'Vision')
    return m, k, x


def entrees(suivi):
    return {e.nom: e for e in suivi.tags}


def test_inventaire(monde, cfg):
    m, k, x = monde
    rapport, suivi = t.inventaire(m.lire(), cfg)
    e = entrees(suivi)
    # Exception à la règle globale par l'effectif, répartie sur deux thèmes : concept (D152, D154).
    assert (e['Attention'].sort, e['Attention'].cible, e['Attention'].dispersion) == (t.CONCEPT, '#attention', 2)
    assert (e['mémoire'].sort, e['mémoire'].cible) == (t.CONCEPT, '#mémoire')
    # La cible d'un groupe de variantes est jugée sur toutes les fiches du groupe : elle double le thème Émotion.
    assert (e['émotion'].effectif, e['émotion'].sort, e['émotion'].theme) == (3, t.SUPPRIMER, 'Psychologie/Émotion')
    # Automatique rare : retiré par la règle, sans entrée. Cité par une recherche : entrée obligatoire (D156).
    assert 'Humans' not in e and 'PDF-auto' not in e
    assert e['Vision'].recherches == ['Vision'] and e['Vision'].classe == t.DOUTEUX
    # État venu d'une autre habitude.
    assert (e['to read'].sort, e['to read'].cible) == (t.ETAT, '1 à lire')
    # Porté par une seule fiche : évident à supprimer.
    assert (e['truc divers'].sort, e['truc divers'].classe) == (t.SUPPRIMER, t.EVIDENT)
    # Concentré dans un thème : le double, et la fiche hors du thème est proposée au rangement (D154).
    pv = e['perception visuelle']
    assert (pv.sort, pv.theme) == (t.SUPPRIMER, 'Psychologie/Perception')
    assert [(a.cle, a.action, a.cible, a.source) for a in suivi.a_ranger] == [
        (x['f8'], r.AJOUTER, 'Psychologie/Perception', r.TAG)]
    # Variantes : pluriel douteux, tirets et casse évidents.
    # Le groupe dont la cible est proposée à la suppression est réuni à l'entrée de celle-ci, pour ne pas proposer à
    # la fois de ramener des noms à un tag et de supprimer ce tag.
    assert 'émotion' not in {g.cible for g in suivi.variantes}
    assert set(e['émotion'].variantes) == {'Emotion', 'emotions'}
    assert 'avec ses variantes' in rapport and "réuni(s) à l'entrée" in rapport
    ml = next(g for g in suivi.variantes if 'machine learning' in g.noms)
    assert ml.classe == t.EVIDENT and set(ml.noms) == {'machine learning', 'Machine-Learning'}
    assert 'Emotion' not in e and 'emotions' not in e
    # Protégés et techniques : pas de proposition (D151).
    assert not {'rouge', '_zotfile', '_privé', '3 lu'} & set(e)
    assert 'rouge (tag coloré' in rapport and '_zotfile (tag technique' in rapport
    # Mots-clés importés (D153).
    assert suivi.resume_importes.startswith('1 fiche') and not any(n.startswith('mot-clé') for n in e)
    # Tag de fiche confidentielle, masqué partout (D156).
    assert 'patient Dupont' not in rapport and t.identifiant('patient Dupont') in rapport
    assert 'Dossier médical' not in rapport
    # Tags d'enfants.
    assert 'à revoir (1 élément(s), dont 1 annotation(s))' in rapport


def test_suivi_ecrit_et_decisions_gardees(monde, cfg):
    m, k, x = monde
    b = m.lire()
    _, suivi = t.inventaire(b, cfg)
    t.ecrire(cfg, suivi, b)
    texte = (cfg.suivi / t.FICHIER).read_text(encoding='utf-8')
    assert '[automatiques]' in texte and '[importes]' in texte and '[[variantes]]' in texte
    assert '# Durand 2020, « Learning to see »' in texte and 'patient Dupont' not in texte
    assert [a.cle for a in r.charger(cfg)] == [x['f8']]
    # L'agent change une proposition, l'utilisateur en accepte une autre : la relance garde tout.
    s = t.charger(cfg)
    s.automatiques = t.ACCEPTER
    for e in s.tags:
        if e.nom == 'Attention':
            e.cible, e.source = '#attention visuelle', t.AGENT
        if e.nom == 'truc divers':
            e.decision = t.ACCEPTER
    s.variantes[0].decision = t.REFUSER
    t.ecrire(cfg, s, b)
    _, suivi2 = t.inventaire(m.lire(), cfg)
    e = entrees(suivi2)
    assert suivi2.automatiques == t.ACCEPTER
    assert (e['Attention'].cible, e['Attention'].source) == ('#attention visuelle', t.AGENT)
    assert e['truc divers'].decision == t.ACCEPTER
    assert suivi2.variantes[0].decision == t.REFUSER
    # La proposition de rangement en attente protège le tag, son entrée reste et ne s'applique pas encore.
    assert suivi2.a_ranger == [] and 'perception visuelle' in e


def test_charger_refuse_un_fichier_incoherent(cfg):
    cfg.suivi.mkdir(parents=True)
    chemin = cfg.suivi / t.FICHIER
    chemin.write_text('[[tag]]\nnom = "x"\nsort = "jeter"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match='sort inconnu'):
        t.charger(cfg)
    chemin.write_text('[[tag]]\nnom = "x"\nsort = "concept"\ncible = "x"\ndecision = "accepter"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match='doit commencer par « # »'):
        t.charger(cfg)
    chemin.write_text('[[tag]]\nnom = "x"\nsort = "état"\ncible = "lu"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match="ni un état ni une marque"):
        t.charger(cfg)
    chemin.write_text('[[variantes]]\nnoms = ["a"]\ncible = "_privé"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match='filtre de confidentialité'):
        t.charger(cfg)


def test_formes():
    cfg = Config(dossier_travail=None)
    assert t.forme('#Émotions', cfg) == t.forme('émotion', cfg) == t.forme('EMOTION', cfg)
    assert t.forme('chevaux', cfg) == t.forme('cheval', cfg) and t.forme('réseaux', cfg) == t.forme('réseau', cfg)
    assert t.forme_faible('Machine-Learning', cfg) == t.forme_faible('machine learning', cfg)
    assert t.forme_faible('émotions', cfg) != t.forme_faible('émotion', cfg)
    assert t.forme('_lu', cfg) != t.forme('lu', cfg)
    assert t.forme('記憶', cfg) == '記憶' and t.forme('★', cfg) == '★'


def accepter_tout(cfg, b, sauf=(), garder=('émotion',)):
    """Toutes les propositions acceptées, sauf `sauf` (laissées en attente). « émotion », qui double le thème
    Émotion, est gardé."""
    _, suivi = t.inventaire(b, cfg)
    suivi.automatiques = suivi.importes = t.ACCEPTER
    for e in suivi.tags:
        if e.nom in garder:
            e.sort = t.GARDER
        if e.nom not in sauf:
            e.decision = t.ACCEPTER
    for g in suivi.variantes:
        g.decision = t.ACCEPTER
    suivi.a_ranger = []
    t.ecrire(cfg, suivi, b)


def element(*tags, type_='journalArticle'):
    return Element(1, 'AAAAAAAA', type_, '', True, tags=list(tags))


def test_tags_vises(monde, cfg):
    m, k, x = monde
    b = m.lire()
    accepter_tout(cfg, b)
    s = t.charger(cfg)
    for e in s.tags:
        if e.nom == 'Vision':
            e.sort = t.GARDER
    t.ecrire(cfg, s, b)
    R = t.regles(t.charger(cfg), cfg, b)
    # Deux variantes sur une même fiche : une seule forme, posée en manuel.
    assert t.tags_vises(element(('Emotion', 1), ('emotions', 0)), R) == [{'tag': 'émotion'}]
    # Deux états : le plus avancé l'emporte.
    assert t.tags_vises(element(('to read', 0), ('3 lu', 0)), R) == [{'tag': '3 lu'}]
    assert t.tags_vises(element(('to read', 0)), R) == [{'tag': '1 à lire'}]
    # Automatique gardé : son type reste. Converti en concept : manuel.
    assert t.tags_vises(element(('Vision', 1), ('Attention', 1), ('Humans', 1)), R) == [
        {'tag': 'Vision', 'type': 1}, {'tag': '#attention'}]
    # Protégés, filtre et tag de fiche confidentielle intacts, sauf la règle globale.
    assert t.tags_vises(element(('_privé', 0), ('rouge', 0), ('_zotfile', 1), ('patient Dupont', 0),
                                ('Secretauto', 1)), R) == [
        {'tag': '_privé'}, {'tag': 'rouge'}, {'tag': '_zotfile', 'type': 1}, {'tag': 'patient Dupont'}]
    # Mots-clés importés retirés, sauf sur une annotation.
    assert t.tags_vises(element(('mot-clé 1', 0)), R) == []
    assert t.tags_vises(element(('mot-clé 1', 0), type_='annotation'), R) == [{'tag': 'mot-clé 1'}]
    # Tag manuel nouveau, à signaler au tri (D155).
    assert t.a_signaler(element(('inédit', 0), ('#concept', 0), ('3 lu', 0)), R, cfg) == ['inédit']


def test_recherche_enregistree_bloque_la_suppression(monde, cfg):
    m, k, x = monde
    b = m.lire()
    accepter_tout(cfg, b, sauf=('Vision',))
    R = t.regles(t.charger(cfg), cfg, b)
    assert {'tag': 'Vision', 'type': 1} in t.tags_vises(b.par_cle()[x['f1']], R)
    accepter_tout(cfg, b)
    R = t.regles(t.charger(cfg), cfg, b)
    assert all(v['tag'] != 'Vision' for v in t.tags_vises(b.par_cle()[x['f1']], R))


def test_protege_ne_change_que_par_l_utilisateur(monde, cfg):
    m, k, x = monde
    b = m.lire()
    accepter_tout(cfg, b)
    s = t.charger(cfg)
    s.tags.append(t.Entree('rouge', sort=t.SUPPRIMER, source=t.AGENT, decision=t.ACCEPTER))
    s.tags.append(t.Entree(t.identifiant('patient Dupont'), sort=t.SUPPRIMER, source=t.UTILISATEUR,
                           decision=t.ACCEPTER))
    s.tags.append(t.Entree('_privé', sort=t.SUPPRIMER, source=t.UTILISATEUR, decision=t.ACCEPTER))
    t.ecrire(cfg, s, b)
    R = t.regles(t.charger(cfg), cfg, b)
    assert any('« rouge » est protégé' in p for p in R.problemes)
    assert any('filtre de confidentialité' in p for p in R.problemes)
    assert t.tags_vises(element(('rouge', 0), ('patient Dupont', 0), ('_privé', 0)), R) == [
        {'tag': 'rouge'}, {'tag': '_privé'}]


def test_plan_essai_application_annulation_relance(monde, cfg, serveur):
    m, k, x = monde
    b = m.lire()
    accepter_tout(cfg, b)
    plan, rapport = t.planifier(b, cfg, serveur.client())
    ops = {op.cle: op for g in plan.groupes for op in g.operations}
    # Une opération par élément, liste complète, enfants compris, rien pour un élément inchangé.
    assert x['f7'] not in ops and x['annotation'] not in ops
    assert ops[x['pdf']].apres == {'tags': []}
    assert {d['tag'] for d in ops[x['f1']].apres['tags']} == {'#attention', '1 à lire', '#mémoire'}
    assert ops[x['f4']].apres['tags'] == [{'tag': '#attention'}, {'tag': 'émotion'}]
    assert ops[x['secret']].apres['tags'] == [{'tag': '_privé'}, {'tag': 'patient Dupont'}]
    # Les cinq premiers groupes couvrent chaque sorte de changement.
    sortes = {s for op in ops.values() for s in op.nature.split(', ')}
    premiers = {s for g in plan.groupes[:5] for op in g.operations for s in op.nature.split(', ')}
    assert premiers == sortes and {'automatique', 'importé', 'variante', 'état', 'concept', 'suppression'} <= sortes
    assert '## Essai' in rapport and 'patient Dupont' not in rapport and 'Dossier médical' not in rapport
    assert '« Vision » cite « Vision »' in rapport

    chemin = ecrire_plan(plan, cfg)
    appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    sauvegarde_factice(cfg)
    # Un tag posé dans Zotero entre-temps met la fiche en conflit.
    serveur.modifier(x['f6'], tags=[{'tag': 'truc divers'}, {'tag': 'machine learning'}, {'tag': 'ajouté'}])
    bilan = appliquer(plan, chemin, serveur.client(), cfg, TOUT)
    assert list(bilan.conflits) == [x['f6']] and not bilan.erreurs
    assert serveur.elements[x['f4']]['tags'] == [{'tag': '#attention'}, {'tag': 'émotion'}]
    assert serveur.elements[x['f9']]['tags'] == []

    # Annulation : les tags d'avant reviennent, types compris.
    journaux = annulation.journaux_vises(chemin, cfg)
    p_ann, _ = annulation.planifier(journaux, serveur.client(), set())
    c_ann = plans.ecrire(p_ann, cfg.plans, '# annulation')
    appliquer(p_ann, c_ann, serveur.client(), cfg, ESSAI)
    appliquer(p_ann, c_ann, serveur.client(), cfg, TOUT)
    assert serveur.elements[x['f4']]['tags'] == [{'tag': 'Attention', 'type': 1}, {'tag': 'Emotion', 'type': 1}]
    assert serveur.elements[x['pdf']]['tags'] == [{'tag': 'PDF-auto', 'type': 1}]



def test_relance_apres_application(monde, cfg, serveur):
    """Une passe appliquée puis reçue par Zotero : plus rien à faire (D119). Une passe interrompue ne replanifie que
    les éléments restants."""
    m, k, x = monde
    accepter_tout(cfg, m.lire())
    plan, _ = t.planifier(m.lire(), cfg, serveur.client())
    chemin = ecrire_plan(plan, cfg)
    appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    m.synchroniser()
    reste, _ = t.planifier(m.lire(), cfg, serveur.client())
    assert {g.id for g in reste.groupes} == {g.id for g in plan.groupes[cfg.ecriture.essai:]}
    sauvegarde_factice(cfg)
    bilan = appliquer(plan, chemin, serveur.client(), cfg, TOUT)
    assert not bilan.conflits and not bilan.erreurs
    m.synchroniser()
    fin, _ = t.planifier(m.lire(), cfg, serveur.client())
    assert fin.groupes == []


def test_copie_locale_en_retard(monde, cfg, serveur):
    m, k, x = monde
    b = m.lire()
    serveur.modifier(x['f1'], title='Changé ailleurs')
    with pytest.raises(SystemExit, match='pas encore reçu'):
        t.planifier(b, cfg, serveur.client())


def test_voir_tag(monde, cfg):
    m, k, x = monde
    b = m.lire()
    texte = voir.decrire_tag(b, cfg, 'Attention')
    assert 'automatique, porté par 5 élément(s)' in texte and 'Learning to see' in texte
    assert 'Fonds/Psychologie/Perception' in texte and '(automatique)' in texte
    assert 'Noms de même forme : Emotion, emotions, émotion.' in voir.decrire_tag(b, cfg, 'Émotion')
    secret = voir.decrire_tag(b, cfg, t.identifiant('patient Dupont'))
    assert 'patient Dupont' not in secret and 'Dossier médical' not in secret and '(fiche confidentielle)' in secret
    assert 'annotation de Durand' in voir.decrire_tag(b, cfg, 'à revoir')


def test_commandes(monde, cfg, serveur, monkeypatch, capsys):
    from zot_clean import ecriture
    from zot_clean.cli import main
    m, k, x = monde
    m.lire()
    (cfg.dossier_travail / 'config.toml').write_text(
        f'[zotero]\ndossier = "{cfg.dossier_zotero.as_posix()}"\n[methode]\nfonds = "Fonds"\ncouleurs = []\n',
        encoding='utf-8')
    monkeypatch.setattr(ecriture, 'depuis_config', lambda cfg: serveur.client())
    dossier = ['--dossier', str(cfg.dossier_travail)]
    assert main(['tags', 'inventaire', *dossier]) == 0
    sortie = capsys.readouterr().out
    assert 'Règle à approuver' in sortie and 'tag(s) à juger' in sortie
    assert list((cfg.dossier_travail / 'rapports').glob('tags-inventaire-*.md'))
    assert main(['tags', 'planifier', *dossier]) == 0
    assert 'Rien à faire' in capsys.readouterr().out  # aucune règle acceptée
    assert main(['tags', 'refuser', 'Inconnu', *dossier]) == 1
    assert '« Inconnu » ne figure pas' in capsys.readouterr().err
    assert main(['tags', 'accepter', 'truc divers', '--regle-automatiques', *dossier]) == 0
    assert '2 règle(s) acceptée(s)' in capsys.readouterr().out
    assert main(['tags', 'ajouter', 'rouge', '--sort', 'supprimer', '--utilisateur', *dossier]) == 0
    assert main(['tags', 'planifier', *dossier]) == 0
    assert 'Plan :' in capsys.readouterr().out
    assert main(['voir', '--tag', 'mémoire', *dossier]) == 0
    assert 'Fear and faces' in capsys.readouterr().out
    assert main(['voir', *dossier]) == 1


def test_decisions_par_commande(monde, cfg):
    """D177 : les règles se décident par commande, par nom de tag, et seules celles qui attendent changent. La
    réécriture garde l'en-tête, le résumé de la règle globale et les titres de chaque entrée."""
    m, k, x = monde
    b = m.lire()
    _, suivi = t.inventaire(b, cfg)
    t.ecrire(cfg, suivi, b)
    s = t.charger(cfg)
    assert s.resume_automatiques == suivi.resume_automatiques and s.resume_importes == suivi.resume_importes
    with pytest.raises(SystemExit, match='« inconnu » ne figure pas'):
        t.decider(s, cfg, t.ACCEPTER, ['inconnu'])
    with pytest.raises(SystemExit, match='--variantes'):  # un groupe n'est pas une entrée [[tag]]
        t.decider(s, cfg, t.ACCEPTER, ['Machine-Learning'])
    with pytest.raises(SystemExit, match='sans cible'):
        t.decider(s, cfg, t.ACCEPTER, ['truc divers'], sort='concept')
    s = t.charger(cfg)
    evidents = {e.nom for e in s.tags if e.classe == t.EVIDENT and e.sort}
    assert 'truc divers' in evidents
    n = t.decider(s, cfg, t.ACCEPTER, ['Attention'], evidents=True, sauf=['truc divers', 'machine learning'],
                  regles=['automatiques'], cible='#attention visuelle')
    assert n == 1 + 1 + len(evidents) - 1 + sum(g.classe == t.EVIDENT for g in s.variantes) - 1
    assert t.decider(s, cfg, t.REFUSER, ['truc divers'], ['machine learning'], regles=['importes']) == 3
    assert t.decider(s, cfg, t.ACCEPTER, ['mémoire'], sort='garder') == 1
    t.ecrire(cfg, s, b)
    texte = (cfg.suivi / t.FICHIER).read_text(encoding='utf-8')
    assert texte.startswith(t.EN_TETE) and f'[automatiques]\n# {suivi.resume_automatiques}\n' in texte
    assert '# Durand 2020, « Learning to see »' in texte
    relu = t.charger(cfg)
    e = entrees(relu)
    assert (relu.automatiques, relu.importes) == (t.ACCEPTER, t.REFUSER)
    assert (e['Attention'].decision, e['Attention'].cible, e['Attention'].source) == (
        t.ACCEPTER, '#attention visuelle', t.AGENT)
    assert (e['mémoire'].sort, e['mémoire'].cible, e['mémoire'].source) == (t.GARDER, '', t.AGENT)
    assert e['truc divers'].decision == t.REFUSER and e['to read'].decision == ''
    assert next(g for g in relu.variantes if 'machine learning' in g.noms).decision == t.REFUSER
    # Ce qui est décidé ne change plus par commande.
    with pytest.raises(SystemExit, match='rien à juger sous ce nom'):
        t.decider(relu, cfg, t.ACCEPTER, ['truc divers'])
    with pytest.raises(SystemExit, match='déjà décidée'):
        t.decider(relu, cfg, t.REFUSER, regles=['automatiques'])
    # Entrée nouvelle pour un tag sans entrée, ici protégé, à la demande de l'utilisateur.
    assert t.ajouter(relu, cfg, b, ['rouge'], 'supprimer', utilisateur=True) == 1
    with pytest.raises(SystemExit, match='déjà une entrée'):
        t.ajouter(relu, cfg, b, ['Attention'], 'garder')
    with pytest.raises(SystemExit, match='Aucun tag « absent »'):
        t.ajouter(relu, cfg, b, ['absent'], 'garder')
    t.ecrire(cfg, relu, b)
    rouge = entrees(t.charger(cfg))['rouge']
    assert (rouge.sort, rouge.source, rouge.decision, rouge.effectif) == (t.SUPPRIMER, t.UTILISATEUR, t.ACCEPTER, 1)


NFC, NFD, MELE = 'été', 'été', 'été'  # même nom affiché, trois formes Unicode


def test_decisions_par_commande_sous_plusieurs_formes_unicode(cfg):
    """Deux entrées dont les noms ne diffèrent que par la forme Unicode s'affichent pareil. Le nom exact désigne la
    sienne seule. Une autre forme est refusée quand elle en désigne plusieurs, avec leurs points de code."""
    s = t.Suivi(tags=[t.Entree(NFC, sort=t.GARDER), t.Entree(NFD, sort=t.GARDER), t.Entree('ok', sort=t.GARDER)],
                variantes=[t.Variantes([NFC, 'ete'], 'été (a)'), t.Variantes([NFD, 'Ete'], 'été (b)'),
                           t.Variantes(['hiver', 'Hiver'], 'hiver')])
    assert t.decider(s, cfg, t.ACCEPTER, [NFC]) == 1
    assert [e.decision for e in s.tags] == [t.ACCEPTER, '', '']
    with pytest.raises(SystemExit, match=r"forme Unicode.*'\\xe9t\\xe9'.*'e\\u0301te\\u0301'"):
        t.decider(s, cfg, t.ACCEPTER, ['ok', MELE])
    assert s.tags[2].decision == ''  # rien n'a changé avant le refus
    assert t.decider(s, cfg, t.REFUSER, [NFD]) == 1 and s.tags[1].decision == t.REFUSER
    # Même logique pour les groupes, désignés par l'un de leurs noms.
    with pytest.raises(SystemExit, match='forme Unicode'):
        t.decider(s, cfg, t.ACCEPTER, variantes=[MELE])
    assert t.decider(s, cfg, t.ACCEPTER, variantes=[NFD]) == 1
    assert [g.decision for g in s.variantes] == ['', t.ACCEPTER, '']
    # Un groupe qui porte lui-même plusieurs formes du nom reste désigné par chacune, sans refus.
    s = t.Suivi(variantes=[t.Variantes([NFC, NFD], 'été')])
    assert t.decider(s, cfg, t.ACCEPTER, variantes=[MELE]) == 1 and s.variantes[0].decision == t.ACCEPTER


def test_ajouter_enregistre_le_nom_reel_du_tag(zotero, tmp_path):
    """`zc tags ajouter` retient le nom tel qu'il est porté dans la bibliothèque, pour que la règle s'y applique, et
    refuse un nom qui désigne plusieurs tags ne différant que par leur forme Unicode."""
    cfg = Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)
    cfg.dossier_travail.mkdir()
    a = zotero.fiche('A', tags=(NFD, 'café', 'reste'))  # « été » décomposé, « café » composé
    b = lecture.lire(zotero.enregistrer())
    s = t.Suivi()
    assert t.ajouter(s, cfg, b, [NFC, 'cafe\u0301'], 'supprimer') == 2
    assert [e.nom for e in s.tags] == ['café', NFD] and [e.effectif for e in s.tags] == [1, 1]
    with pytest.raises(SystemExit, match='déjà une entrée'):
        t.ajouter(s, cfg, b, [MELE], 'garder')
    t.ecrire(cfg, s, b)
    relu = t.charger(cfg)
    assert [e.nom for e in relu.tags] == ['café', NFD]
    R = t.regles(relu, cfg, b)
    assert t.tags_vises(b.elements[a], R) == [{'tag': 'reste'}]
    # Deux tags réels sous deux formes, et un nom tapé sous une troisième, qui n'en désigne aucun exactement.
    zotero.fiche('B', tags=(NFC,))
    b = lecture.lire(zotero.enregistrer())
    with pytest.raises(SystemExit, match=r"plusieurs tags.*'\\xe9t\\xe9'.*'e\\u0301te\\u0301'"):
        t.ajouter(t.Suivi(), cfg, b, [MELE], 'supprimer')
    s = t.Suivi()
    assert t.ajouter(s, cfg, b, [NFC], 'supprimer') == 1 and [e.nom for e in s.tags] == [NFC]


def test_marque_technique_jamais_proposee_en_concept(zotero, tmp_path):
    from zot_clean import tags as tg
    from zot_clean.config import Config
    cfg = Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)
    for i in range(6):
        zotero.fiche(f'Fiche {i}', tags=(('/unread', 1),))
    from zot_clean import lecture
    b = lecture.lire(zotero.enregistrer())
    a = tg._Analyse(b, cfg)
    e = a.proposer(tg.Entree('/unread'))
    assert e.sort == tg.SUPPRIMER and e.classe == tg.EVIDENT and 'marque technique' in e.note


def test_tag_qui_double_un_theme_reste_sur_les_fiches_pas_encore_rangees(monde, cfg):
    # D154 : « perception visuelle » double Psychologie/Perception. Il quitte f1, déjà rangée, mais reste sur f8,
    # qui n'est pas encore dans le thème, même quand la décision de la ranger a déjà été prise ailleurs.
    m, k, x = monde
    b = m.lire()
    accepter_tout(cfg, b)
    R = t.regles(t.charger(cfg), cfg, b)
    par_cle = b.par_cle()
    assert 'perception visuelle' not in {d['tag'] for d in t.tags_vises(par_cle[x['f1']], R)}
    assert 'perception visuelle' in {d['tag'] for d in t.tags_vises(par_cle[x['f8']], R)}
    assert any('perception visuelle' in p and 'rangement' in p for p in R.problemes)


def test_variantes_fondues_dans_la_suppression_de_leur_cible(monde, cfg):
    m, k, x = monde
    b = m.lire()
    accepter_tout(cfg, b, garder=())
    texte = (cfg.suivi / t.FICHIER).read_text(encoding='utf-8')
    assert 'variantes = [' in texte
    R = t.regles(t.charger(cfg), cfg, b)
    # Acceptée, l'entrée supprime le tag et ses variantes sur les fiches déjà dans le thème.
    par_cle = b.par_cle()
    assert t.tags_vises(par_cle[x['f4']], R) == [{'tag': '#attention'}]
    assert t.tags_vises(par_cle[x['f5']], R) == [{'tag': '#attention'}, {'tag': '#machine learning'}]
    # Une relance ne recrée pas le groupe de variantes.
    _, suivi = t.inventaire(m.lire(), cfg)
    assert 'émotion' not in {g.cible for g in suivi.variantes}
    assert set(entrees(suivi)['émotion'].variantes) == {'Emotion', 'emotions'}


def test_casse_des_cibles_et_nom_de_concept(zotero, tmp_path):
    cfg = Config(dossier_travail=tmp_path / 'travail', dossier_zotero=zotero.dossier)
    for titre, tag in (('A', '#Mémoire'), ('B', '#memoire'), ('C', '#Apprentissage'), ('D', '#apprentissage'),
                       ('E', '#Kant'), ('F', '#Kants')):
        zotero.fiche(titre, tags=(tag,))
    b = lecture.lire(zotero.enregistrer())
    groupes, _ = t._Analyse(b, cfg).groupes()
    cibles = {g.cible for g in groupes}
    # Les capitales ne restent que si tous les noms en portent (nom propre).
    assert {'#mémoire', '#apprentissage'} < cibles and len(cibles) == 3
    assert all(c.startswith('#K') for c in cibles - {'#mémoire', '#apprentissage'})
    assert t.nom_de_concept('Embodied_Cognition', cfg) == '#embodied cognition'
    assert t.nom_de_concept("TDAH chez l'Adulte", cfg) == "#TDAH chez l'adulte"


def test_couleurs_des_tags_de_la_methode(monde, cfg, serveur):
    """D175 : les tags de la méthode reçoivent leur couleur et les premiers rangs (touches 1, 2, 3…), même encore
    inutilisés. Un tag de la méthode déjà coloré garde sa couleur, les autres tags colorés suivent. Premier groupe du
    plan, donc dans l'essai, et annulable."""
    m, k, x = monde
    serveur.regler('tagColors', [{'name': 'perso', 'color': '#000000'}, {'name': '3 lu', 'color': '#123456'}])
    b = m.lire()
    plan, rapport = t.planifier(b, cfg, serveur.client())
    g = plan.groupes[0]
    assert g.id == 'tagColors' and g.operations[0].genre == 'settings'
    voulues = [('1 à lire', '#FF6666'), ('2 en cours', '#FF8C19'), ('3 lu', '#123456'), ('★ essentiel', '#FFD400'),
               ('papier', '#A28AE5'), ('perso', '#000000')]
    assert [(c['name'], c['color']) for c in g.operations[0].apres['value']] == voulues
    assert '## Couleurs' in rapport and '- 6. perso (#000000), gardait le rang 1, touche changée' in rapport
    assert '- 3. 3 lu' in rapport  # rang changé (2 → 3)
    assert not any(gr.id == 'tagColors' for gr in plan.groupes[1:])

    chemin = ecrire_plan(plan, cfg)
    appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    assert [(c['name'], c['color']) for c in serveur.reglages['tagColors']['value']] == voulues
    # Rien à refaire ensuite.
    assert t._couleurs(cfg, serveur.reglages['tagColors']['value']) is None

    journaux = annulation.journaux_vises(chemin, cfg)
    p_ann, _ = annulation.planifier(journaux, serveur.client(), set())
    c_ann = plans.ecrire(p_ann, cfg.plans, '# annulation')
    appliquer(p_ann, c_ann, serveur.client(), cfg, ESSAI)
    sauvegarde_factice(cfg)
    appliquer(p_ann, c_ann, serveur.client(), cfg, TOUT)
    assert serveur.reglages['tagColors']['value'] == [{'name': 'perso', 'color': '#000000'},
                                                      {'name': '3 lu', 'color': '#123456'}]


def test_couleurs_creees_puis_retirees_par_l_annulation(monde, cfg, serveur):
    m, k, x = monde
    b = m.lire()
    plan, _ = t.planifier(b, cfg, serveur.client())
    assert plan.groupes[0].operations[0].avant == {'value': None}
    chemin = ecrire_plan(plan, cfg)
    appliquer(plan, chemin, serveur.client(), cfg, ESSAI)
    assert len(serveur.reglages['tagColors']['value']) == 5
    p_ann, _ = annulation.planifier(annulation.journaux_vises(chemin, cfg), serveur.client(), set())
    c_ann = plans.ecrire(p_ann, cfg.plans, '# annulation')
    appliquer(p_ann, c_ann, serveur.client(), cfg, ESSAI)
    sauvegarde_factice(cfg)
    appliquer(p_ann, c_ann, serveur.client(), cfg, TOUT)
    assert 'tagColors' not in serveur.reglages
