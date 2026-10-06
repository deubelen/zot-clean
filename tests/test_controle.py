"""Contrôle régulier (D137, D139 à D141), sur la bibliothèque synthétique de test_inbox."""

from datetime import date

from test_inbox import cfg, faux, monde, serveur  # noqa: F401 (fixtures)
from zot_clean import controle as k, fonds as f, rangement as r
from zot_clean.audit import A_VOIR, Section


def _zotero(m, sql: str, *args):
    m.zotero.db.execute(sql, args)
    m.serveur.version += 1


def test_evolution_entre_deux_audits():
    avant = {'chiffres': {'référence': 10}, 'points': {'Doublons probables': ['A/B', 'C/D']}}
    sections = [Section('Doublons probables', A_VOIR, '', points={'C/D': 'C / D', 'E/F': 'E / F'}),
                Section('Plan du fonds', A_VOIR, '', points={'x': 'x'})]

    class B:
        fiches, pieces, notes, collections = [1] * 12, [], [], []
    inst = k.instantane(sections, B)
    texte = '\n'.join(k.evolution(sections, inst, avant, date(2026, 10, 1)))
    assert "Depuis l'audit du 01/10/2026" in texte and '12 références (+2)' in texte
    assert '1. Doublons probables, 1 nouveau et 1 réglé.' in texte and '  - E / F' in texte
    assert 'Plan du fonds' not in texte  # contrôle absent de l'audit précédent, pas comparé
    # D170 : le rapport dit à quel audit il compare, et qu'un audit du même jour compare au même.
    assert "dernier audit d'un jour précédent, celui du 01/10/2026" in texte
    assert "Aucun audit d'un jour précédent" in '\n'.join(k.sans_comparaison())


def test_instantane_precedent(cfg):
    k.enregistrer_instantane(cfg, {'points': {}}, date(2026, 9, 30))
    k.enregistrer_instantane(cfg, {'points': {'a': []}}, date(2026, 10, 2))
    k.enregistrer_instantane(cfg, {'points': {'b': []}}, date(2026, 10, 3))
    jour, inst = k.precedent(cfg, date(2026, 10, 3))
    assert jour == date(2026, 10, 2) and 'a' in inst['points']


def test_renommage_et_creation_suivis(monde, cfg):
    m, cles, fiches, b = monde
    section, memoire = k.plan_du_fonds(b, cfg)
    assert memoire == {cles['Psy']: 'Psychologie', cles['Perception']: 'Psychologie/Perception', cles['Arts']: 'Arts'}
    assert f'hors fonds · {fiches["projet"]}' in section.points and 'validation' not in section.points
    k.ecrire_memoire(cfg, memoire)
    r.ecrire(cfg, [r.Entree(fiches['nouvelle'], r.DEPLACER, 'Psychologie/Perception', cles['Inbox'],
                            decision=r.ACCEPTER)], b, set())

    # Dans Zotero, Perception est renommée et un thème Musées est créé sous Arts.
    _zotero(m, 'update collections set collectionName = ? where key = ?', 'Perception visuelle', cles['Perception'])
    musees = m.collection('Musées', cles['Arts'])
    b = m.lire()
    section, _ = k.plan_du_fonds(b, cfg)
    assert section.points[f'renommé · {cles["Perception"]}'].endswith('Psychologie/Perception → Psychologie/Perception visuelle')
    assert f'créé · {musees}' in section.points

    s = k.suivre(b, cfg)
    assert '### Perception visuelle\n\nPerception humaine.\n\n## Arts' in s.texte
    assert 'Arts visuels.\n\n### Musées\n\n# Concepts' in s.texte
    k.reporter(b, cfg, s)
    assert f.charger_suivi(cfg).collections and not f.controler(cfg).erreurs
    assert {c.cible for c in f.charger_suivi(cfg).collections if c.cle == cles['Perception']} == {'Psychologie/Perception visuelle'}
    assert r.charger(cfg)[0].cible == 'Psychologie/Perception visuelle'
    # Une fois suivi, plus rien à signaler sur ces thèmes, sauf la définition à écrire.
    f.enregistrer(cfg, f.controler(cfg))
    section, memoire = k.plan_du_fonds(b, cfg)
    assert memoire[cles['Perception']] == 'Psychologie/Perception visuelle' and memoire[musees] == 'Arts/Musées'
    assert set(p for p in section.points if not p.startswith('hors fonds')) == {'sans définition · Arts/Musées'}


def test_deplacement_et_suppression_suivis(monde, cfg):
    m, cles, fiches, b = monde
    k.ecrire_memoire(cfg, k.plan_du_fonds(b, cfg)[1])
    _zotero(m, 'update collections set parentCollectionID = ? where key = ?', m.ids[cles['Psy']], cles['Arts'])
    _zotero(m, 'insert into deletedCollections (collectionID) values (?)', m.ids[cles['Perception']])
    b = m.lire()
    s = k.suivre(b, cfg)
    assert s.lignes == ['déplacé : Arts → Psychologie/Arts', 'retiré, avec ses sous-thèmes : Psychologie/Perception']
    assert s.texte.endswith('## Psychologie\n\nEsprit et comportement.\n\n### Arts\n\nArts visuels.\n\n# Concepts\n')
    k.reporter(b, cfg, s)
    assert not f.controler(cfg).erreurs
    assert cles['Perception'] not in {c.cle for c in f.charger_suivi(cfg).collections}


def test_titres_d_un_theme(monde, cfg):
    m, cles, fiches, b = monde
    rapport, n = k.titres(b, cfg, 'Psychologie')
    assert n == 1 and '## Psychologie/Perception' in rapport and 'Définition. Perception humaine.' in rapport
    assert 'The ecological approach to visual perception' in rapport
