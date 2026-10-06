"""Filtre de confidentialité (D18, D65, D66).

Désigne les fiches à ne jamais transmettre à l'agent ni chercher par leur titre
chez un service extérieur. Une fiche est exclue si elle porte un tag de
`tags_exclus`, ou si elle est rangée dans une collection de
`collections_exclues` ou dans l'une de ses sous-collections. Une collection se
désigne par son chemin (« Fonds/Privé ») ou par son nom seul. Un tag d'exclusion
vaut quelles que soient ses majuscules et sa forme Unicode (D190). Une pièce
jointe ou une note qui porte ce tag est exclue avec ses annotations, et une
fiche exclue avec ses pièces jointes, ses notes et leurs annotations (D188).

Une fiche exclue reste traitée par les étapes qui n'ont pas besoin de la lire
(doublons, identifiants). Tout ce que `zc` écrit et que l'agent peut lire
(audit, suivi, rapports, plans) n'en montre que la clé (D126).
"""

import unicodedata

from zot_clean.config import Config
from zot_clean.lecture import Bibliotheque

MASQUE = '(fiche confidentielle)'


def forme(nom: str) -> str:
    """Forme d'un tag d'exclusion, sans majuscules ni variante Unicode (D190)."""
    return unicodedata.normalize('NFC', nom).casefold()


def tags_exclus(cfg: Config) -> set[str]:
    return {forme(t) for t in cfg.confidentialite.tags_exclus}


def tag_exclu(nom: str, cfg: Config) -> bool:
    return forme(nom) in tags_exclus(cfg)


def exclues(b: Bibliotheque, cfg: Config) -> set[int]:
    tags = tags_exclus(cfg)
    noms = set(cfg.confidentialite.collections_exclues)
    cols = {c for c in b.collections if _exclue(b, c, noms)}
    return {e.id for e in b.elements.values()
            if any(forme(n) in tags for n, _ in e.tags) or e.collections & cols}


def _exclue(b: Bibliotheque, cid: int, noms: set[str]) -> bool:
    while cid is not None:
        if b.collections[cid].nom in noms or b.chemin(cid) in noms:
            return True
        cid = b.collections[cid].parent
    return False


def cles_masquees(b: Bibliotheque, cfg: Config) -> set[str]:
    """Clés des éléments exclus et de leur descendance (pièces jointes, notes, annotations), dont rien ne s'écrit
    hors de la clé (D126, D188)."""
    ids = exclues(b, cfg)
    pieces = {i for i, p in b.pieces.items() if i in ids or p.parent in ids}
    cles = {b.elements[i].cle for i in ids}
    cles |= {b.pieces[i].cle for i in pieces}
    cles |= {b.elements[n].cle for n, parent in b.notes.items() if parent in ids and n in b.elements}
    cles |= {b.elements[a].cle for a, p in b.annotation_de.items() if p in pieces and a in b.elements}
    return cles
