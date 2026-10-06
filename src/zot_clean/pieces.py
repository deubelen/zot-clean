"""PDF identiques (D125) : copies d'un même fichier rattachées à plusieurs fiches, ou deux fois à la même.

`chercher` repère les groupes de copies et les écrit dans `suivi/pieces.toml`, où l'agent et l'utilisateur
décident, pour chacun, les copies à mettre à la corbeille et celles à rattacher à une autre fiche. `planifier`
en tire un plan, appliqué par `zc appliquer` comme les autres. Une copie qui porte des annotations ou des notes
n'est jamais mise à la corbeille : si elle est sur la mauvaise fiche, on la rattache à la bonne.
"""

import tomllib
from collections import defaultdict
from dataclasses import dataclass, field

from zot_clean import filtre
from zot_clean.audit import ecrire_toml, md5, nom_type, pdf_sur_disque
from zot_clean.config import Config
from zot_clean.doublons import _toml
from zot_clean.ecriture import Client
from zot_clean.lecture import Bibliotheque
from zot_clean.plans import Groupe, Operation, Plan

FICHIER = 'pieces.toml'
APPLIQUER, GARDER = 'appliquer', 'garder'

EN_TETE = """\
# PDF identiques repérés par `zc pieces chercher`, avec les décisions prises.
# Ce fichier se relit et se modifie à la main ou avec l'agent. `zc pieces chercher` le met à jour
# sans perdre les décisions, `zc pieces planifier` prépare le plan des groupes à appliquer.
# Les décisions s'écrivent avec `zc pieces accepter` (--corbeille, --rattacher) et `zc pieces refuser` (garder).
#
# decision  : "appliquer" (mettre à la corbeille et rattacher comme indiqué), "garder" (copies voulues, par exemple
#             un chapitre et le livre entier, à ne plus signaler) ou "" (à juger).
# corbeille : clés des copies à mettre à la corbeille. Une copie annotée ou portant une note est refusée.
# rattacher : copie -> fiche, pour déplacer une copie (annotée, par exemple) vers la bonne fiche.
# raison    : note libre.
"""


@dataclass
class Entree:
    copies: list[str]
    decision: str = ''
    corbeille: list[str] = field(default_factory=list)
    rattacher: dict = field(default_factory=dict)
    raison: str = ''


def charger(cfg: Config) -> list[Entree]:
    chemin = cfg.suivi / FICHIER
    if not chemin.is_file():
        return []
    try:
        brut = tomllib.loads(chemin.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f'{chemin} illisible ({e}). Corriger le fichier, ou le supprimer pour repartir de zéro.')
    res = []
    for g in brut.get('pdf', []):
        e = Entree(list(g['copies']), g.get('decision', ''), list(g.get('corbeille', [])),
                   dict(g.get('rattacher', {})), g.get('raison', ''))
        if e.decision not in ('', APPLIQUER, GARDER):
            raise SystemExit(f'{chemin} : décision inconnue « {e.decision} » pour {", ".join(e.copies)}.')
        res.append(e)
    return res


def _annotee(b: Bibliotheque, ids: dict[str, int], notes: set[int], cle: str) -> int:
    """Nombre d'annotations et de notes portées par une copie, sa note propre comprise (D206)."""
    i = ids.get(cle)
    return (b.annotations.get(i, 0) + (i in notes) + b.pieces[i].note) if i is not None else 0


def ecrire(cfg: Config, entrees: list[Entree], b: Bibliotheque) -> None:
    pieces = {p.cle: p for p in b.pieces.values()}
    ids = {p.cle: i for i, p in b.pieces.items()}
    notes = {p for p in b.notes.values() if p}
    masquees = filtre.cles_masquees(b, cfg)
    lignes = [EN_TETE]
    for e in entrees:
        lignes.append('[[pdf]]')
        # Les copies sont identiques : une seule fiche confidentielle masque tout le groupe (D126).
        cache = any(k in masquees for k in e.copies)
        for k in e.copies:
            p = pieces.get(k)
            fiche = b.elements.get(p.parent) if p else None
            if fiche:
                auteur = fiche.auteur or '?'
                n = _annotee(b, ids, notes, k)
                quoi = filtre.MASQUE if cache else f'{auteur} · {fiche.titre[:80]}'
                lignes.append(f'# {k} sur {fiche.cle} · {quoi} ({nom_type(fiche.type)}'
                              + (f', {n} annotation(s) ou note(s)' if n else '') + ')')
        lignes += [f'copies = {_toml(e.copies)}', f'decision = {_toml(e.decision)}',
                   f'corbeille = {_toml(e.corbeille)}', f'rattacher = {_toml(e.rattacher)}',
                   f'raison = {_toml(e.raison)}', '']
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    ecrire_toml(cfg.suivi / FICHIER, lignes)


def decider(entrees: list[Entree], b: Bibliotheque, corbeille=(), rattacher: dict | None = None, garder=(),
            raison: str = '') -> tuple[int, int]:
    """Décisions prises par commande (D177, sur le modèle de D172), au lieu d'écrire le fichier à la main. Chaque
    groupe se désigne par la clé de l'une de ses copies. `corbeille` et `rattacher` (copie -> fiche) donnent ce qu'il
    faut faire des copies d'un groupe à appliquer, `garder` les groupes dont les copies sont voulues. Seuls les
    groupes encore à juger changent. Renvoie le nombre de groupes à appliquer et gardés."""
    rattacher = rattacher or {}
    a_juger = {k: e for e in entrees if not e.decision for k in e.copies}
    connues = {k for e in entrees for k in e.copies}
    demandes = [*corbeille, *rattacher, *garder]
    if inconnues := [k for k in demandes if k not in a_juger]:
        absentes = [k for k in inconnues if k not in connues]
        decidees = [k for k in inconnues if k in connues]
        morceaux = []
        if absentes:
            morceaux.append(f'Aucun groupe de {FICHIER} ne contient la copie {", ".join(absentes)}. Vérifier la clé '
                            '(celle de la pièce jointe, non de la fiche), ou relancer `zc pieces chercher`.')
        if decidees:
            morceaux.append(f'Le groupe de {", ".join(decidees)} est déjà décidé. Une décision prise se change à la '
                            'main dans le fichier.')
        raise SystemExit(' '.join(morceaux))
    if double := set(corbeille) & set(rattacher):
        raise SystemExit(f'{", ".join(sorted(double))} : une même copie ne va pas à la fois à la corbeille et sur une '
                         'autre fiche.')
    ids = {p.cle: i for i, p in b.pieces.items()}
    notes = {p for p in b.notes.values() if p}
    if annotees := [k for k in corbeille if _annotee(b, ids, notes, k)]:
        raise SystemExit(f'{", ".join(annotees)} porte des annotations ou des notes et ne va pas à la corbeille. '
                         'La rattacher plutôt à la bonne fiche (--rattacher), et mettre l\'autre copie à la corbeille.')
    fiches = {e.cle for e in b.fiches}
    if pas_fiche := [f for f in rattacher.values() if f not in fiches]:
        raise SystemExit(f'{", ".join(pas_fiche)} n\'est pas une fiche de la bibliothèque.')
    appliquees = {id(a_juger[k]): a_juger[k] for k in [*corbeille, *rattacher]}
    gardees = {id(a_juger[k]): a_juger[k] for k in garder}
    if appliquees.keys() & gardees.keys():
        raise SystemExit('Un même groupe ne peut pas être à la fois appliqué et gardé.')
    for k in corbeille:
        if k not in a_juger[k].corbeille:
            a_juger[k].corbeille.append(k)
    for k, f in rattacher.items():
        a_juger[k].rattacher[k] = f
    for e in appliquees.values():
        if set(e.copies) <= set(e.corbeille):
            raise SystemExit(f'Toutes les copies de {", ".join(e.copies)} iraient à la corbeille, il faut en garder '
                             'une.')
        e.decision, e.raison = APPLIQUER, raison or e.raison
    for e in gardees.values():
        e.decision, e.raison = GARDER, raison or e.raison
    return len(appliquees), len(gardees)


def groupes_identiques(b: Bibliotheque) -> list[list[str]]:
    """Clés des copies de chaque PDF présent plusieurs fois, sur des fiches différentes ou sur la même."""
    par_taille = defaultdict(list)
    for p in pdf_sur_disque(b):
        if p.parent in b.elements:
            par_taille[p.fichier.stat().st_size].append(p)
    par_empreinte = defaultdict(list)
    for meme in par_taille.values():
        if len(meme) > 1:
            for p in meme:
                par_empreinte[md5(p.fichier)].append(p.cle)
    return sorted(sorted(g) for g in par_empreinte.values() if len(g) > 1)


def chercher(b: Bibliotheque, cfg: Config) -> list[Entree]:
    anciennes = {frozenset(e.copies): e for e in charger(cfg)}
    entrees = [anciennes.get(frozenset(g)) or Entree(g) for g in groupes_identiques(b)]
    entrees.sort(key=lambda e: e.decision != '')
    ecrire(cfg, entrees, b)
    return entrees


def avertissement(b: Bibliotheque, cfg: Config, entrees: list[Entree]) -> str:
    """Ce que `chercher` n'a pas pu voir ou ne règle pas lui-même. Les PDF absents du disque, jamais comparés
    (D168), et les fiches qui partagent un PDF sans figurer dans `suivi/doublons.toml`. C'est `zc doublons
    chercher` qui les y propose (D125), avec ses autres indices, plutôt que ce fichier-ci qui ne voit qu'un PDF."""
    from zot_clean import bbt
    from zot_clean.audit import rappel_absents
    from zot_clean.doublons import charger_suivi
    parent = {p.cle: b.elements[p.parent].cle for p in b.pieces.values() if p.parent in b.elements}
    groupes = [set(g.cles) for g in charger_suivi(cfg)]
    hors = 0
    for e in entrees:
        fiches = {parent[k] for k in e.copies if k in parent}
        if not e.decision and len(fiches) > 1 and not any(fiches <= g for g in groupes):
            hors += 1
    morceaux = []
    if hors:
        morceaux.append(f"{hors} PDF partagé{'s' if hors > 1 else ''} par des fiches différentes qui ne figurent pas "
                        "encore dans suivi/doublons.toml. Relancer `zc doublons chercher`, qui propose ces fiches "
                        "comme doublons à juger, et les fusionner d'abord si c'en sont.")
    if rappel := rappel_absents(b, bbt.stockage_fichiers(cfg.dossier_zotero)):
        morceaux.append(rappel)
    return ' '.join(morceaux)


def planifier(cfg: Config, client: Client, b: Bibliotheque) -> tuple[Plan, str]:
    entrees = [e for e in charger(cfg) if e.decision == APPLIQUER]
    ids = {p.cle: i for i, p in b.pieces.items()}
    notes = {p for p in b.notes.values() if p}
    masquees = filtre.cles_masquees(b, cfg)
    donnees = client.fiches(sorted({k for e in entrees for k in e.copies} | {f for e in entrees
                                                                            for f in e.rattacher.values()}))
    groupes, refus, details = [], [], []
    for e in entrees:
        if motif := _refus(e, donnees, b, ids, notes):
            refus.append((e, motif))
            continue
        ops = [Operation(k, {'deleted': False}, {'deleted': True}, nature='corbeille', enfants=[])
               for k in e.corbeille]  # copie sans annotation au plan, et qui doit le rester (D182)
        ops += [Operation(k, {'parentItem': donnees[k]['parentItem']}, {'parentItem': f}, nature='rattacher')
                for k, f in e.rattacher.items() if donnees[k].get('parentItem') != f]
        if not ops:
            continue
        gid = str(len(groupes) + 1)
        cache = any(k in masquees for k in e.copies + list(e.rattacher.values()))
        titre = filtre.MASQUE if cache else donnees[e.copies[0]].get('title', '')
        groupes.append(Groupe(gid, titre[:80], ops))
        details.append(_detail(gid, e, donnees, titre))
    plan = Plan('pieces', client.utilisateur, groupes, description=f'PDF identiques, {len(groupes)} groupe(s).')
    return plan, _rapport(plan, refus, details, sum(1 for e in charger(cfg) if not e.decision))


def _refus(e: Entree, donnees: dict, b: Bibliotheque, ids: dict, notes: set) -> str:
    inconnues = [k for k in e.corbeille + list(e.rattacher) if k not in e.copies]
    if inconnues:
        return f"{', '.join(inconnues)} ne fait pas partie des copies du groupe"
    if set(e.corbeille) & set(e.rattacher):
        return 'une même copie est à la fois mise à la corbeille et rattachée'
    if set(e.copies) <= set(e.corbeille):
        return 'toutes les copies iraient à la corbeille, il faut en garder une'
    manquantes = [k for k in e.copies + list(e.rattacher.values()) if k not in donnees]
    if manquantes:
        return f"introuvable(s) sur le serveur : {', '.join(manquantes)}"
    if any(donnees[k].get('deleted') for k in e.corbeille):
        return 'une copie est déjà à la corbeille'
    annotees = [k for k in e.corbeille if _annotee(b, ids, notes, k)]
    if annotees:
        return (f"{', '.join(annotees)} porte des annotations ou des notes et ne va pas à la corbeille. "
                'La rattacher plutôt à la bonne fiche, et mettre l\'autre copie à la corbeille')
    pas_fiche = [f for f in e.rattacher.values() if donnees[f].get('itemType') in ('attachment', 'note')]
    if pas_fiche:
        return f"{', '.join(pas_fiche)} n'est pas une fiche"
    return ''


def _detail(gid: str, e: Entree, donnees: dict, titre: str) -> list[str]:
    r = [f'### Groupe {gid}. {titre[:90]}', '']
    r += [f"- corbeille {k} (copie sur {donnees[k].get('parentItem')})" for k in e.corbeille]
    r += [f"- rattacher {k} : {donnees[k].get('parentItem')} → {f}" for k, f in e.rattacher.items()]
    r += [f'- raison : {e.raison}'] if e.raison else []
    return r + ['']


def _rapport(plan: Plan, refus: list, details: list, a_juger: int) -> str:
    L = ['# PDF identiques', '',
         f'{len(plan.groupes)} groupe(s), {plan.nb_operations} opération(s). Les copies mises à la corbeille y '
         'restent 30 jours (réglage par défaut de Zotero), le temps de revenir en arrière avec `zc annuler`.']
    if a_juger:
        L += ['', f'{a_juger} groupe(s) encore sans décision dans `suivi/{FICHIER}`.']
    if refus:
        L += ['', '## Groupes écartés', '']
        L += [f"- {', '.join(e.copies)} : {motif}." for e, motif in refus]
    L += ['', '## Détail', '']
    for d in details:
        L += d
    return '\n'.join(L) + '\n'

