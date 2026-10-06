"""Journal des écritures (D16, D37, D38).

Un fichier JSON Lines par exécution d'un plan, `journal/<date>_<étape>.jsonl`.
Une ligne `en-tete`, une ligne `intention` par élément juste avant l'envoi de
son lot (objet complet d'avant relu par l'API, champs à écrire), une ligne
`element` par élément écrit (les mêmes, et la nouvelle version), ajoutée dès
que son lot est confirmé, une ligne `groupe` par groupe traité, une ligne
`fin`. Un journal sans ligne de fin est celui d'une exécution interrompue.

Une intention sans élément qui la confirme, dans le même journal ou un journal
suivant du même plan, est une écriture dont on ne sait pas si Zotero l'a faite
(réponse perdue, interruption, D178). La reprise du plan la confirme si elle
trouve les valeurs écrites, et l'annulation la défait sans risque, puisqu'elle
ne touche qu'un champ resté à la valeur écrite.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from zot_clean import __version__

FAITS = ('fait', 'partiel')  # statuts d'un groupe qu'une reprise ne refait pas


def maintenant() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


class Journal:
    def __init__(self, dossier: Path, etape: str):
        dossier.mkdir(parents=True, exist_ok=True)
        base = f'{datetime.now():%Y-%m-%d_%H%M%S}_{etape}'
        self.chemin = dossier / f'{base}.jsonl'
        n = 1
        while self.chemin.exists():
            n += 1
            self.chemin = dossier / f'{base}_{n}.jsonl'
        self._f = self.chemin.open('a', encoding='utf-8')

    def _ligne(self, **d):
        self._f.write(json.dumps(d, ensure_ascii=False) + '\n')
        self._f.flush()

    def en_tete(self, **d):
        self._ligne(type='en-tete', debut=maintenant(), zc=__version__, **d)

    def intention(self, groupe: str, rang: int, avant: dict, ecrit: dict, genre: str = 'items',
                  cree: bool = False) -> dict:
        """Écriture sur le point de partir, inscrite avant l'envoi (D178)."""
        d = _decrire('intention', groupe, rang, avant, ecrit, genre, cree)
        self._ligne(**d)
        return d

    def element(self, groupe: str, rang: int, avant: dict, ecrit: dict, version: int, genre: str = 'items',
                cree: bool = False):
        """`avant` est l'objet relu avant l'écriture, réduit à sa clé pour une collection créée."""
        self._ligne(**_decrire('element', groupe, rang, avant, ecrit, genre, cree), version=version)

    def groupe(self, id_: str, statut: str, detail: str = ''):
        self._ligne(type='groupe', id=id_, statut=statut, detail=detail)

    def fin(self, **bilan):
        self._ligne(type='fin', fin=maintenant(), **bilan)
        self.fermer()

    def fermer(self):
        if not self._f.closed:
            self._f.close()


def _decrire(type_: str, groupe: str, rang: int, avant: dict, ecrit: dict, genre: str, cree: bool) -> dict:
    extra = ({'genre': genre} if genre != 'items' else {}) | ({'cree': True} if cree else {})
    return dict(type=type_, groupe=groupe, rang=rang, cle=avant['key'], avant=avant, ecrit=ecrit, **extra)


def lire(chemin: Path) -> list[dict]:
    lignes = []
    for l in chemin.read_text(encoding='utf-8').splitlines():
        try:
            lignes.append(json.loads(l))
        except json.JSONDecodeError:
            break  # dernière ligne tronquée par une interruption
    return lignes


@dataclass
class Resume:
    chemin: Path
    en_tete: dict
    groupes: dict[str, str] = field(default_factory=dict)  # id -> statut
    elements: int = 0
    termine: bool = False


def resumer(chemin: Path) -> Resume:
    lignes = lire(chemin)
    r = Resume(chemin, lignes[0] if lignes and lignes[0].get('type') == 'en-tete' else {})
    for l in lignes:
        if l['type'] == 'groupe':
            r.groupes[l['id']] = l['statut']
        elif l['type'] == 'element':
            r.elements += 1
        elif l['type'] == 'fin':
            r.termine = True
    return r


REGISTRE = 'commandes.jsonl'  # durée de chaque commande (D173), qui n'est pas un journal d'écritures


def tous(dossier: Path) -> list[Resume]:
    return [resumer(p) for p in sorted(dossier.glob('*.jsonl')) if p.name != REGISTRE] if dossier.is_dir() else []


def du_plan(dossier: Path, empreinte: str) -> list[Resume]:
    return [r for r in tous(dossier) if r.en_tete.get('empreinte') == empreinte]


def _faits(dossier: Path, empreinte: str) -> list[tuple[Resume, set[str]]]:
    """Groupes faits par chaque journal du plan, moins ceux qu'une annulation de ce journal a défaits. Un plan
    recalculé à l'identique après son annulation a la même empreinte, et doit pouvoir se réappliquer. Une
    annulation ne peut viser qu'un journal déjà écrit, l'ordre des noms n'a donc pas à être consulté."""
    journaux = tous(dossier)
    res = []
    for r in journaux:
        if r.en_tete.get('empreinte') != empreinte:
            continue
        faits = {g for g, s in r.groupes.items() if s in FAITS}
        for a in journaux:
            if r.chemin.name in a.en_tete.get('annule', []):
                faits -= {g for g, s in a.groupes.items() if s in FAITS}
        res.append((r, faits))
    return res


def en_suspens(chemins: list[Path]) -> dict[tuple[str, str], dict]:
    """Intentions que rien ne confirme, par (groupe, clé), en lisant les journaux dans l'ordre (D178)."""
    res: dict[tuple[str, str], dict] = {}
    for chemin in sorted(chemins):
        for l in lire(chemin):
            if l['type'] == 'intention':
                res[l['groupe'], l['cle']] = l
            elif l['type'] == 'element':
                res.pop((l['groupe'], l['cle']), None)
    return res


def groupes_faits(dossier: Path, empreinte: str) -> set[str]:
    return {g for _, faits in _faits(dossier, empreinte) for g in faits}


def essai_fait(dossier: Path, empreinte: str) -> bool:
    return any(r.en_tete.get('mode') == 'essai' and faits for r, faits in _faits(dossier, empreinte))
