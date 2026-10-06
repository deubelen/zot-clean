"""Contrôle régulier, gestion courante (D137, D139 à D142).

Le contrôle vit dans `zc audit` (D139). Chaque audit garde un instantané de
ses points, identifiés par des clés sans titres, dans `suivi/audits/`, et son
rapport s'ouvre sur ce qui est apparu et ce qui est réglé depuis l'audit d'un
jour précédent. Un douzième contrôle compare `plan.md` et le fonds dans Zotero.

Le lien entre un thème et sa collection passe par le chemin. Pour reconnaître
un thème renommé, déplacé ou supprimé dans Zotero, `suivi/fonds-collections.json`
retient la clé de la collection de chaque thème où plan et Zotero concordent
(D140). `suivre` met alors `plan.md` et les chemins des fichiers de suivi à jour,
Zotero faisant foi après le nettoyage (D23).
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date

from zot_clean import filtre, fonds as f, rangement as r
from zot_clean.audit import A_VOIR, INFO, OK, Section, ligne, pluriel
from zot_clean.config import Config
from zot_clean.lecture import Bibliotheque

INSTANTANES = 'audits'
MEMOIRE = 'fonds-collections.json'
NOUVEAUX_MAX = 20
TITRE_PLAN = 'Plan du fonds'


# --- Comparaison de deux audits (D139) ------------------------------------------------

def instantane(sections: list[Section], b: Bibliotheque) -> dict:
    return {'chiffres': {'référence': len(b.fiches), 'pièce jointe': len(b.pieces), 'note': len(b.notes),
                         'collection': len(b.collections)},
            'points': {s.titre: sorted(s.points) for s in sections}}


def enregistrer_instantane(cfg: Config, inst: dict, jour: date) -> None:
    dossier = cfg.suivi / INSTANTANES
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f'audit-{jour:%Y-%m-%d}.json').write_text(json.dumps(inst, ensure_ascii=False, indent=1),
                                                          encoding='utf-8')


def precedent(cfg: Config, jour: date) -> tuple[date, dict] | None:
    """Instantané du dernier audit d'un jour antérieur, pour que deux audits du même jour comparent au même."""
    dossier = cfg.suivi / INSTANTANES
    trouves = []
    for p in dossier.glob('audit-*.json') if dossier.is_dir() else ():
        try:
            d = date.fromisoformat(p.stem.removeprefix('audit-'))
        except ValueError:
            continue
        if d < jour:
            trouves.append((d, p))
    if not trouves:
        return None
    d, p = max(trouves)
    try:
        return d, json.loads(p.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def sans_comparaison() -> list[str]:
    """Lignes du rapport quand aucun audit d'un jour précédent n'existe (D170)."""
    return ["## Comparaison", '',
            "Aucun audit d'un jour précédent, rien n'est comparé. Les audits suivants, faits un autre jour, "
            "compareront au dernier audit de ce jour-ci.", '']


def _ecart(n: int) -> str:
    return f' ({"+" if n > 0 else "−"}{abs(n)})' if n else ''


def evolution(sections: list[Section], inst: dict, avant: dict, jour_avant: date) -> list[str]:
    """Lignes Markdown de ce qui est apparu et réglé depuis `avant`. Un contrôle absent de l'instantané
    précédent n'est pas comparé, pour ne pas tout donner pour nouveau."""
    L = [f"## Depuis l'audit du {jour_avant:%d/%m/%Y}", '',
         f"Comparaison avec le dernier audit d'un jour précédent, celui du {jour_avant:%d/%m/%Y}. Un autre "
         "audit fait aujourd'hui compare au même, si bien que les corrections de la journée apparaissent comme "
         "réglées, et remplace ce rapport.", '']
    c0, c1 = avant.get('chiffres', {}), inst['chiffres']
    L += [', '.join(f'{pluriel(n, mot)}{_ecart(n - c0[mot]) if mot in c0 else ""}' for mot, n in c1.items())
          + '.', '']
    p0 = avant.get('points', {})
    rien = True
    for i, s in enumerate(sections, 1):
        if s.titre not in p0:
            continue
        nouveaux = [k for k in s.points if k not in set(p0[s.titre])]
        regles = len(set(p0[s.titre]) - set(s.points))
        if not nouveaux and not regles:
            continue
        rien = False
        morceaux = []
        if nouveaux:
            morceaux.append(f"{len(nouveaux)} nouveau{'x' if len(nouveaux) > 1 else ''}")
        if regles:
            morceaux.append(f"{regles} réglé{'s' if regles > 1 else ''}")
        L.append(f'- {i}. {s.titre}, {" et ".join(morceaux)}.')
        L += [f'  - {s.points[k]}' for k in nouveaux[:NOUVEAUX_MAX]]
        if len(nouveaux) > NOUVEAUX_MAX:
            L.append(f'  - … et {len(nouveaux) - NOUVEAUX_MAX} autres, dans la section du contrôle')
    if rien:
        L.append('Aucun point nouveau ni réglé.')
    return L + ['']


# --- Collections du fonds et gestes faits dans Zotero (D140) -------------------------

def lire_memoire(cfg: Config) -> dict[str, str]:
    chemin = cfg.suivi / MEMOIRE
    if not chemin.is_file():
        return {}
    try:
        return {str(k): str(v) for k, v in json.loads(chemin.read_text(encoding='utf-8')).items()}
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def ecrire_memoire(cfg: Config, memoire: dict[str, str]) -> None:
    cfg.suivi.mkdir(parents=True, exist_ok=True)
    (cfg.suivi / MEMOIRE).write_text(json.dumps(dict(sorted(memoire.items(), key=lambda x: x[1])),
                                                ensure_ascii=False, indent=1), encoding='utf-8')


def collections_du_fonds(b: Bibliotheque, cfg: Config) -> dict[str, str] | None:
    """Clé -> chemin relatif au fonds de chaque collection sous la racine du fonds, None sans racine."""
    e = r._Etat(b)
    racine = e.racine(cfg.methode.fonds) if cfg.methode.fonds else None
    if racine is None:
        return None
    prefixe = cfg.methode.fonds + '/'
    return {k: e.chemin(k).removeprefix(prefixe) for k in e.nom if k != racine and e.sous(k, racine)}


@dataclass
class Gestes:
    renommes: dict[str, tuple[str, str]] = field(default_factory=dict)  # clé -> (chemin du plan, chemin actuel)
    supprimes: dict[str, str] = field(default_factory=dict)  # clé -> chemin du plan
    crees: dict[str, str] = field(default_factory=dict)  # clé -> chemin actuel
    a_creer: list[str] = field(default_factory=list)  # chemins du plan sans collection, jamais vue
    trop_profonds: dict[str, str] = field(default_factory=dict)
    memoire: dict[str, str] = field(default_factory=dict)  # mémoire mise à jour

    def __bool__(self) -> bool:
        return bool(self.renommes or self.supprimes or self.crees)


def _sous_chemin(chemin: str, parent: str) -> str | None:
    """Reste de `chemin` sous `parent`, '' pour le parent lui-même, None hors de lui."""
    if chemin == parent:
        return ''
    return chemin[len(parent) + 1:] if chemin.startswith(parent + '/') else None


def gestes(plan: f.Plan, actuels: dict[str, str], memoire: dict[str, str], anciennes: set[str],
           profondeur_max: int) -> Gestes:
    """Écarts entre le plan et les collections du fonds, lus à travers la mémoire des clés. Une collection
    du suivi de l'étape 4 (`anciennes`) n'est pas un thème créé à la main, le rangement s'en occupe."""
    g = Gestes()
    occupes = set(actuels.values())
    for k, vu in memoire.items():
        if vu not in plan.noeuds:
            continue
        if k not in actuels:
            if vu not in occupes:
                g.supprimes[k] = vu
        elif actuels[k] != vu and actuels[k] not in plan.noeuds and vu not in occupes:
            g.renommes[k] = (vu, actuels[k])
    for k, ch in actuels.items():
        if ch.count('/') + 1 > profondeur_max:
            g.trop_profonds[k] = ch
        elif ch not in plan.noeuds and k not in g.renommes and k not in anciennes:
            g.crees[k] = ch
    connus = set(memoire.values()) | occupes
    g.a_creer = [ch for ch in plan.noeuds if ch not in connus]
    # Un parent renommé ou supprimé emporte ses sous-collections, seul le parent est retenu.
    g.renommes = {k: (a, n) for k, (a, n) in g.renommes.items()
                  if not any(k2 != k and (reste := _sous_chemin(a, a2)) and n == f'{n2}/{reste}'
                             for k2, (a2, n2) in g.renommes.items())}
    g.supprimes = {k: a for k, a in g.supprimes.items()
                   if not any(k2 != k and _sous_chemin(a, a2) for k2, a2 in g.supprimes.items())}
    g.crees = {k: c for k, c in g.crees.items()
               if not any(k2 != k and _sous_chemin(c, c2) for k2, c2 in g.crees.items())}
    # Mémoire : les thèmes où plan et Zotero concordent, et les gestes encore à suivre.
    g.memoire = {k: ch for k, ch in actuels.items() if ch in plan.noeuds}
    for k, vu in memoire.items():
        if k not in g.memoire and vu in plan.noeuds and vu not in occupes:
            g.memoire[k] = vu
    return g


def _plan(cfg: Config) -> f.Plan:
    return f.lire_plan((cfg.dossier_travail / f.PLAN).read_text(encoding='utf-8'), cfg)


def _anciennes(cfg: Config) -> set[str]:
    return {c.cle for c in f.charger_suivi(cfg).collections}


def examiner(b: Bibliotheque, cfg: Config) -> tuple[f.Plan, dict[str, str], Gestes] | None:
    actuels = collections_du_fonds(b, cfg)
    if actuels is None or not (cfg.dossier_travail / f.PLAN).is_file():
        return None
    plan = _plan(cfg)
    return plan, actuels, gestes(plan, actuels, lire_memoire(cfg), _anciennes(cfg), cfg.methode.profondeur_max)


def plan_du_fonds(b: Bibliotheque, cfg: Config, masquees: set[str] = frozenset()) -> tuple[Section, dict | None]:
    """Douzième contrôle (D139), et la mémoire des clés mise à jour (None si rien à retenir)."""
    from zot_clean import inbox
    if motif := inbox.sans_rangement(cfg):
        return Section(TITRE_PLAN, INFO, f'Contrôle sauté, {motif[0].lower() + motif[1:]}'), None
    vu = examiner(b, cfg)
    if vu is None:
        return Section(TITRE_PLAN, INFO, f'Contrôle sauté, pas de racine « {cfg.methode.fonds} » dans Zotero.'), None
    plan, actuels, g = vu
    m = cfg.methode
    points: dict[str, str] = {}
    for k, (a, n) in g.renommes.items():
        quoi = 'renommé' if a.rpartition('/')[0] == n.rpartition('/')[0] else 'déplacé'
        points[f'{quoi} · {k}'] = f'{quoi} dans Zotero : {a} → {n}'
    points |= {f'supprimé · {k}': f'supprimé dans Zotero : {a}' for k, a in g.supprimes.items()}
    points |= {f'créé · {k}': f'créé dans Zotero, absent de {f.PLAN} : {c}' for k, c in g.crees.items()}
    points |= {f'trop profond · {k}': f'au-delà de {m.profondeur_max} niveaux : {c}' for k, c in g.trop_profonds.items()}
    points |= {f'à créer · {c}': f'dans {f.PLAN}, pas encore dans Zotero : {c}' for c in g.a_creer}
    points |= {f'sans définition · {nd.chemin}': f'sans définition : {nd.chemin}'
               for nd in plan.noeuds.values() if not nd.definition and nd.chemin in actuels.values()}
    a_jour, _ = f.validation_a_jour(cfg)
    if not a_jour:
        points['validation'] = f'{f.PLAN} ou suivi/fonds.toml ont changé depuis la dernière validation'
    a_trier, laissees = inbox.a_trier_et_laissees(b, cfg)
    hors = [a.fiche for a in a_trier if not a.depuis]
    points |= {f'hors fonds · {e.cle}': f'hors du fonds : {ligne(e, masquees)}' for e in hors}
    effectifs: dict[str, int] = {}
    cle_de = {c.id: c.cle for c in b.collections.values()}
    for e in b.fiches:
        for c in e.collections:
            effectifs[cle_de[c]] = effectifs.get(cle_de[c], 0) + 1
    gros = sorted(((ch, effectifs.get(k, 0)) for k, ch in actuels.items()
                   if effectifs.get(k, 0) > m.seuil_sous_theme and ch.count('/') + 1 < m.profondeur_max),
                  key=lambda x: -x[1])
    points |= {f'gros · {ch}': f'plus de {m.seuil_sous_theme} références : {ch} ({n})' for ch, n in gros}
    graves = [p for p in points if not p.startswith('gros')]
    morceaux = [pluriel(len(g.renommes) + len(g.supprimes) + len(g.crees), 'thème') + ' changé'
                + ('s' if len(g.renommes) + len(g.supprimes) + len(g.crees) > 1 else '') + ' dans Zotero',
                pluriel(len(hors), 'référence') + ' hors du fonds (hors Inbox'
                + (f', sans compter {len(laissees)} laissée{"s" if len(laissees) > 1 else ""} hors du fonds par '
                   'décision)' if laissees else ')'),
                pluriel(sum(1 for p in points if p.startswith('sans définition')), 'thème') + ' sans définition',
                pluriel(len(gros), 'thème') + f' de plus de {m.seuil_sous_theme} références']
    if g.a_creer:
        morceaux.append(pluriel(len(g.a_creer), 'thème') + ' du plan pas encore dans Zotero')
    texte = ', '.join(morceaux) + '.'
    if not a_jour:
        texte += f' {f.PLAN} a changé depuis la dernière validation.'
    remede = ('Un thème changé dans Zotero se reporte dans plan.md par `zc fonds suivre`, puis l\'agent écrit les '
              'définitions manquantes. Les références hors du fonds passent par `zc inbox`, et celles qu\'on '
              'décide de laisser hors du fonds se notent par `zc fonds a-ranger --laisser`. Un thème trop gros se '
              'découpe en sous-thèmes à partir de `zc fonds titres`, seulement si le découpage est net. Un thème du '
              'plan pas encore dans Zotero est créé par `zc fonds planifier`.')
    statut = A_VOIR if graves else (INFO if points else OK)
    return Section(TITRE_PLAN, statut, texte, list(points.values()), remede, points), g.memoire


# --- Mise à jour de plan.md (D140) ---------------------------------------------------

def _titres(lignes: list[str]) -> list[tuple[int, int, str]]:
    """(index, niveau Markdown, nom) des titres hors blocs de code."""
    res, code = [], False
    for i, l in enumerate(lignes):
        if l.lstrip().startswith(('```', '~~~')):
            code = not code
            continue
        if not code and (t := re.match(r'^(#{1,6})\s+(.*?)\s*#*\s*$', l)):
            res.append((i, len(t.group(1)), t.group(2)))
    return res


def _sections(lignes: list[str], fonds: str) -> tuple[dict[str, tuple[int, int, int]], int]:
    """Chemin -> (début, fin, niveau Markdown) de chaque section du fonds, et la fin de la section du fonds."""
    titres = _titres(lignes)
    res, pile, dans, fin_fonds = {}, [], False, len(lignes)
    for j, (i, niv, nom) in enumerate(titres):
        if niv == 1:
            if dans:
                fin_fonds = i
                break
            dans = nom == fonds
            continue
        if not dans:
            continue
        del pile[niv - 2:]
        pile.append(nom)
        fin = next((i2 for i2, n2, _ in titres[j + 1:] if n2 <= niv), len(lignes))
        res['/'.join(pile)] = (i, fin, niv)
    if dans:
        for chemin, (i, fin, niv) in res.items():
            res[chemin] = (i, min(fin, fin_fonds), niv)
    return res, fin_fonds


def _inserer(lignes: list[str], fonds: str, parent: str, bloc: list[str]) -> list[str]:
    sections, fin_fonds = _sections(lignes, fonds)
    ou = sections[parent][1] if parent else fin_fonds
    while ou > 0 and not lignes[ou - 1].strip():
        ou -= 1
    # Une ligne vide avant le bloc, et après lui s'il n'en reste pas une avant le titre suivant.
    bloc = [''] + bloc + ([''] if ou < len(lignes) and lignes[ou].strip() else [])
    return lignes[:ou] + bloc + lignes[ou:]


def _sans_blancs_finaux(bloc: list[str]) -> list[str]:
    while bloc and not bloc[-1].strip():
        bloc = bloc[:-1]
    return bloc


def renommer(texte: str, fonds: str, ancien: str, nouveau: str) -> str:
    lignes = texte.splitlines()
    sections, _ = _sections(lignes, fonds)
    debut, fin, niv = sections[ancien]
    bloc = lignes[debut:fin]
    nouveau_niv = nouveau.count('/') + 2
    decalage = nouveau_niv - niv
    for i, n, _ in _titres(bloc):
        bloc[i] = '#' * (n + decalage) + bloc[i].lstrip('#')
    bloc[0] = '#' * nouveau_niv + ' ' + nouveau.rpartition('/')[2]
    if ancien.rpartition('/')[0] == nouveau.rpartition('/')[0]:
        lignes[debut:fin] = bloc
        return '\n'.join(lignes) + '\n'
    reste = lignes[:debut] + lignes[fin:]
    return '\n'.join(_inserer(reste, fonds, nouveau.rpartition('/')[0], _sans_blancs_finaux(bloc))) + '\n'


def supprimer(texte: str, fonds: str, chemin: str) -> str:
    lignes = texte.splitlines()
    debut, fin, _ = _sections(lignes, fonds)[0][chemin]
    return '\n'.join(lignes[:debut] + lignes[fin:]) + '\n'


def ajouter(texte: str, fonds: str, chemin: str) -> str:
    bloc = ['#' * (chemin.count('/') + 2) + ' ' + chemin.rpartition('/')[2]]
    return '\n'.join(_inserer(texte.splitlines(), fonds, chemin.rpartition('/')[0], bloc)) + '\n'


@dataclass
class Suivi:
    texte: str = ''
    renommages: dict[str, str] = field(default_factory=dict)  # ancien chemin -> nouveau, sous-thèmes compris
    supprimes: list[str] = field(default_factory=list)
    ajoutes: list[str] = field(default_factory=list)
    ignores: list[str] = field(default_factory=list)
    lignes: list[str] = field(default_factory=list)  # ce qui change, lisible


def suivre(b: Bibliotheque, cfg: Config) -> Suivi | None:
    """Nouveau texte de plan.md, d'après les gestes faits dans Zotero. None sans plan ou sans fonds.

    Renommages et ajouts se font en plusieurs passes, chacun dès que son parent est dans le texte (un
    thème peut être déplacé sous un thème lui-même créé à la main). Les suppressions viennent à la fin."""
    vu = examiner(b, cfg)
    if vu is None:
        return None
    plan, actuels, g = vu
    fonds = cfg.methode.fonds
    texte = (cfg.dossier_travail / f.PLAN).read_text(encoding='utf-8')
    s = Suivi()
    cibles = {n + (f'/{reste}' if reste else '') for a, n in g.renommes.values()
              for ch in plan.noeuds if (reste := _sous_chemin(ch, a)) is not None}
    ops: list[tuple] = [('r', a, n) for a, n in sorted(g.renommes.values(), key=lambda x: x[0].count('/'))]
    ops += [('a', ch) for c in sorted(g.crees.values())
            for ch in sorted(x for x in actuels.values() if _sous_chemin(x, c) is not None) if ch not in cibles]
    while ops:
        reste_a_faire = []
        for op in ops:
            sections, _ = _sections(texte.splitlines(), fonds)
            chemin = op[-1]
            parent = chemin.rpartition('/')[0]
            if parent and parent not in sections:
                reste_a_faire.append(op)
                continue
            if op[0] == 'a':
                if chemin.count('/') + 1 > cfg.methode.profondeur_max:
                    s.ignores.append(chemin)
                    continue
                texte = ajouter(texte, fonds, chemin)
                s.ajoutes.append(chemin)
                s.lignes.append(f'ajouté, définition à écrire : {chemin}')
                continue
            _, a, n = op
            courant = s.renommages.get(a, a)
            if courant not in sections:
                s.ignores.append(n)
                continue
            texte = renommer(texte, fonds, courant, n)
            for ch in plan.noeuds:
                if (reste := _sous_chemin(ch, a)) is not None:
                    s.renommages[ch] = n + (f'/{reste}' if reste else '')
            quoi = 'renommé' if a.rpartition('/')[0] == n.rpartition('/')[0] else 'déplacé'
            s.lignes.append(f'{quoi} : {a} → {n}')
        if len(reste_a_faire) == len(ops):
            s.ignores += [op[-1] for op in reste_a_faire]
            break
        ops = reste_a_faire
    for a in sorted(g.supprimes.values()):
        courant = s.renommages.get(a, a)
        if courant not in _sections(texte.splitlines(), fonds)[0]:
            continue
        texte = supprimer(texte, fonds, courant)
        s.supprimes += [ch for ch in plan.noeuds if _sous_chemin(ch, a) is not None]
        s.lignes.append(f'retiré, avec ses sous-thèmes : {courant}')
    s.ignores += [ch for ch in g.trop_profonds.values() if ch not in s.ignores]
    s.texte = texte
    return s


def _renommer_chemin(ch: str, renommages: dict[str, str]) -> str:
    return renommages.get(ch, ch)


def reporter(b: Bibliotheque, cfg: Config, s: Suivi) -> list[str]:
    """Écrit plan.md et reporte les chemins changés dans suivi/fonds.toml et suivi/rangement.toml. Les
    références à un thème supprimé y sont retirées. Rend ce qui a été retiré, lisible."""
    retraits = []
    perdus = set(s.supprimes)
    (cfg.dossier_travail / f.PLAN).write_text(s.texte, encoding='utf-8')
    fs = f.charger_suivi(cfg)
    existantes = {c.cle for c in b.collections.values()}
    gardees = []
    for c in fs.collections:
        if c.sort in (f.THEME, f.REPARTIR):
            if c.cible in perdus and c.cle not in existantes:
                retraits.append(f'suivi/fonds.toml : collection {c.cle}, devenue « {c.cible} », supprimée')
                continue
            c.cible = _renommer_chemin(c.cible, s.renommages) if c.cible not in perdus else c.cible
            c.candidats = [_renommer_chemin(x, s.renommages) for x in c.candidats if x not in perdus]
        gardees.append(c)
    fs.collections = gardees
    tags = {}
    for t, cible in fs.tags.items():
        if cible in perdus:
            retraits.append(f'suivi/fonds.toml : tag « {t} », relié à « {cible} »')
        else:
            tags[t] = _renommer_chemin(cible, s.renommages)
    fs.tags = tags
    if (cfg.suivi / f.FICHIER).is_file():
        f.ecrire_suivi(cfg, fs)
    if (cfg.suivi / r.FICHIER).is_file():
        entrees, n = [], 0
        for e in r.charger(cfg):
            if e.cible in perdus:
                n += 1
                continue
            e.cible = _renommer_chemin(e.cible, s.renommages)
            entrees.append(e)
        if n:
            retraits.append(f'suivi/rangement.toml : {pluriel(n, "décision")} vers un thème supprimé')
        r.ecrire(cfg, entrees, b, filtre.exclues(b, cfg))
    return retraits


# --- Titres d'un thème (D141) ----------------------------------------------------------

def titres(b: Bibliotheque, cfg: Config, chemin: str, jour: date | None = None) -> tuple[str, int]:
    """Tous les titres d'un thème et de ses sous-thèmes, avec la définition du plan, pour que l'agent
    propose des sous-thèmes (D109). Les fiches confidentielles restent masquées (D126)."""
    actuels = collections_du_fonds(b, cfg) or {}
    cles = {k: ch for k, ch in actuels.items() if _sous_chemin(ch, chemin) is not None}
    if chemin not in actuels.values():
        raise KeyError(f'Aucune collection « {chemin} » sous « {cfg.methode.fonds} ».')
    masquees = filtre.cles_masquees(b, cfg)
    plan = _plan(cfg) if (cfg.dossier_travail / f.PLAN).is_file() else None
    cle_de = {c.id: c.cle for c in b.collections.values()}
    par: dict[str, list] = {}
    for e in b.fiches:
        for c in e.collections:
            if cle_de[c] in cles:
                par.setdefault(cles[cle_de[c]], []).append(e)
    n = len({e.cle for v in par.values() for e in v})
    L = [f'# Titres de « {chemin} », {(jour or date.today()):%d/%m/%Y}', '',
         f"{pluriel(n, 'référence')}. Liste complète, pour proposer des sous-thèmes nets. "
         f'Un sous-thème se déclare dans {f.PLAN} avec sa définition, puis `zc fonds valider`, et les références '
         'y vont par des entrées « déplacer » de suivi/rangement.toml (`depuis` = clé de la collection quittée), '
         'puis `zc fonds planifier`.']
    for ch in sorted(set(cles.values())):
        nd = plan.noeuds.get(ch) if plan else None
        k = next(x for x, c in cles.items() if c == ch)
        fiches = sorted(par.get(ch, []), key=lambda e: e.titre.lower())
        L += ['', f'## {ch} ({k}), {pluriel(len(fiches), "référence")}', '']
        if nd and nd.definition:
            L += [f'Définition. {nd.definition}'] + ([f'Inclut. {nd.inclut}'] if nd.inclut else []) + (
                [f'Exclut. {nd.exclut}'] if nd.exclut else []) + ['']
        L += [f'- {ligne(e, masquees)}' for e in fiches]
    return '\n'.join(L) + '\n', n
