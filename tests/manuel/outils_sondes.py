"""Outils communs aux sondes en plusieurs phases (tags, clés de citation, noms des fichiers).

Une sonde écrit par l'API sur le compte de test, l'utilisateur synchronise le profil de test dans Zotero,
puis la sonde relit la copie locale de `zotero.sqlite` (par `zot_clean.lecture`), le dossier `storage/` et
l'API. L'état d'une phase à l'autre (clés créées, valeurs attendues, version du serveur) est gardé dans
`<dossier de travail>/sondes/<nom>.json`. Chaque vérification affiche « réussi » ou « échoué » avec ce
qui a été observé. Ce qui ne se voit que dans Zotero est posé en question, à la fin de la sortie.
"""

import argparse
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manuel import peupler  # noqa: E402
from zot_clean import config, ecriture, lecture  # noqa: E402

SYNCHRONISER = ('Synchroniser le profil de test dans Zotero (bouton de synchronisation en haut à droite), '
                'attendre la fin, puis relancer.')


def arguments(doc: str, phases: dict[str, str]) -> argparse.Namespace:
    """`--dossier` et une phase obligatoire parmi `phases` (nom -> aide)."""
    p = argparse.ArgumentParser(description=doc.splitlines()[0], epilog=doc.split('\n\n', 1)[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--dossier', type=Path, required=True, help='dossier de travail du compte de test (~/zc-test)')
    g = p.add_mutually_exclusive_group(required=True)
    for nom, aide in phases.items():
        g.add_argument(f'--{nom}', dest='phase', action='store_const', const=nom, help=aide)
    return p.parse_args()


class Sonde:
    def __init__(self, nom: str, dossier: Path):
        self.nom = nom
        self.cfg = config.charger(dossier.expanduser().resolve())
        env = config.lire_env(self.cfg.dossier_travail)
        info = peupler.verifier_cle(env.get('ZOTERO_API_KEY', ''))
        peupler.verifier_compte_test(env, os.environ.get('ZC_COMPTE_TEST'), info.utilisateur)
        self.client = ecriture.depuis_config(self.cfg)
        self.fichier_etat = self.cfg.dossier_travail / 'sondes' / f'{nom}.json'
        self.resultats: list[tuple[bool, str]] = []
        self.questions: list[str] = []

    # --- état d'une phase à l'autre ---

    def etat(self) -> dict:
        if not self.fichier_etat.is_file():
            raise SystemExit(f'Aucun état de la sonde dans {self.fichier_etat}. Lancer d\'abord la phase --preparer.')
        return json.loads(self.fichier_etat.read_text(encoding='utf-8'))

    def enregistrer(self, etat: dict) -> None:
        self.fichier_etat.parent.mkdir(parents=True, exist_ok=True)
        self.fichier_etat.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding='utf-8')

    def nouvel_etat(self) -> dict:
        if self.fichier_etat.is_file():
            raise SystemExit(f'{self.fichier_etat} existe déjà : une sonde précédente n\'a pas été nettoyée. '
                             'Lancer --nettoyer d\'abord.')
        return {}

    # --- sortie ---

    def verifier(self, condition: bool, message: str, observe: str = '') -> bool:
        self.resultats.append((condition, message))
        print(f"{'réussi ' if condition else 'échoué '} {message}" + (f' (observé : {observe})' if observe else ''))
        return condition

    def question(self, texte: str) -> None:
        self.questions.append(texte)

    def bilan(self, suite: str = '') -> int:
        if self.questions:
            print('\nÀ regarder dans Zotero, réponses à noter :')
            for i, q in enumerate(self.questions, 1):
                print(f'  Q{i}. {q}')
        echecs = [m for ok, m in self.resultats if not ok]
        if self.resultats:
            print(f'\n{len(self.resultats) - len(echecs)} vérification(s) sur {len(self.resultats)} réussie(s).')
        if suite:
            print(f'\nEnsuite : {suite}')
        return 1 if echecs else 0

    # --- API ---

    def requete(self, methode: str, chemin: str, en_tetes: dict | None = None, admis: tuple[int, ...] = (), **kw):
        """Requête avec des en-têtes en plus de ceux de pyzotero (`Client._requete` fixe les siens)."""
        h = self.client.zot.default_headers() | (en_tetes or {})
        r = self.client.zot.client.request(methode, self.client.zot.endpoint + chemin, headers=h, **kw)
        if r.status_code >= 400 and r.status_code not in admis:
            raise RuntimeError(f'{methode} {chemin} : {r.status_code} {r.text[:300]}')
        return r

    def ecrire(self, objets: list[dict]) -> ecriture.Resultat:
        """Modifie des éléments, avec leur version actuelle lue juste avant."""
        actuels = self.client.fiches([o['key'] for o in objets])
        return self.client.ecrire([o | {'version': actuels[o['key']]['version']} for o in objets])

    def joindre_pdf(self, parent: str, nom_fichier: str) -> str:
        """Téléverse un petit PDF propre à la sonde sous `nom_fichier`, rattaché à `parent`. Renvoie la clé."""
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / nom_fichier
            f.write_bytes(peupler.pdf(f'zc sonde {self.nom} {secrets.token_hex(6)}'))
            res = self.client.zot.attachment_simple([str(f)], parent)
        if res.get('failure'):
            raise SystemExit(f'Envoi du PDF {nom_fichier} refusé : {res["failure"]}')
        return next(iter(res.get('success', []) + res.get('unchanged', [])))['key']

    def tag_sur_serveur(self, nom: str) -> int:
        """Nombre d'éléments qui portent ce tag sur le serveur, 0 s'il n'existe plus."""
        r = self.requete('GET', f'{self.client.prefixe}/tags/{quote(nom, safe="")}', admis=(404,))
        if r.status_code == 404 or not r.json():
            return 0
        return sum(int(t.get('meta', {}).get('numItems', 0)) for t in r.json())

    def reglage(self, nom: str) -> tuple[object, int]:
        """Valeur et version d'un réglage synchronisé (`tagColors`…), (None, 0) s'il n'existe pas."""
        r = self.requete('GET', f'{self.client.prefixe}/settings/{nom}', admis=(404,))
        if r.status_code == 404:
            return None, 0
        d = r.json()
        return d.get('value'), int(d.get('version', 0))

    def ecrire_reglage(self, nom: str, valeur) -> None:
        """Écrit un réglage synchronisé, ou le supprime si `valeur` est vide."""
        version = {'If-Unmodified-Since-Version': str(self.client.version_serveur())}
        if valeur:
            self.requete('POST', f'{self.client.prefixe}/settings', version, json={nom: {'value': valeur}})
        else:
            self.requete('DELETE', f'{self.client.prefixe}/settings/{nom}', version, admis=(404,))

    def supprimer(self, fiches: list[str]) -> None:
        """Suppression définitive des fiches et de leurs descendants (annotations, pièces jointes, notes),
        des plus profonds aux fiches, chacun avec sa version lue juste avant."""
        for fiche in fiches:
            ordre = []
            if fiche in self.client.fiches([fiche]):
                for enfant in self.client.enfants(fiche):
                    if enfant.get('itemType') == 'attachment':
                        ordre += [a['key'] for a in self.client.enfants(enfant['key'])]
                    ordre.append(enfant['key'])
            for cle in ordre + [fiche]:
                actuel = self.client.fiches([cle])
                if cle not in actuel:
                    continue
                self.requete('DELETE', f'{self.client.prefixe}/items/{cle}',
                             {'If-Unmodified-Since-Version': str(actuel[cle]['version'])}, admis=(404,))

    # --- copie locale ---

    def copie_locale(self, etat: dict, cles: list[str], exiger_envoi: bool = True) -> lecture.Bibliotheque:
        """Lit la copie locale et s'arrête si Zotero n'a pas encore reçu les dernières écritures de la sonde,
        ou, avec `exiger_envoi`, s'il a des changements locaux non envoyés sur ces éléments (ils feraient un
        conflit avec l'écriture suivante)."""
        bib = lecture.lire(self.cfg.base)
        locaux = bib.par_cle()
        manquent = [k for k in cles if k not in locaux]
        if bib.version < etat.get('version', 0) or manquent:
            raise SystemExit(f'La copie locale n\'a pas reçu les dernières écritures (version locale {bib.version}, '
                             f'attendue {etat.get("version", 0)} au moins, {len(manquent)} élément(s) absent(s)). '
                             + SYNCHRONISER)
        non_envoyes = [k for k in cles if not locaux[k].synced]
        if exiger_envoi and non_envoyes:
            raise SystemExit(f'{len(non_envoyes)} élément(s) de la sonde ont des changements locaux pas encore '
                             f'envoyés au serveur ({", ".join(non_envoyes)}). ' + SYNCHRONISER)
        return bib

    def stockage(self, cle: str) -> Path:
        return self.cfg.dossier_zotero / 'storage' / cle

    def noms_de_tags_locaux(self) -> set[str]:
        return noms_de_tags(self.cfg.base)

    def reglage_local(self, nom: str) -> object:
        return reglage_local(self.cfg.base, nom)


def noms_de_tags(base: Path) -> set[str]:
    """Tous les noms de la table `tags`, y compris ceux qu'aucun élément ne porte plus.

    `lecture.lire` ne voit que les tags portés (par `itemTags`), d'où cette lecture directe, réservée aux
    sondes."""
    with tempfile.TemporaryDirectory(prefix='zot-clean-') as tmp:
        db = sqlite3.connect(lecture.copier(base, Path(tmp)))
        try:
            lecture.verifier_schema(db)
            return {n for (n,) in db.execute('select name from tags')}
        finally:
            db.close()


def reglage_local(base: Path, nom: str, bibliotheque: int = lecture.BIBLIOTHEQUE_PERSO) -> object:
    """Valeur d'un réglage synchronisé dans la copie locale (`syncedSettings`), None s'il n'y est pas."""
    with tempfile.TemporaryDirectory(prefix='zot-clean-') as tmp:
        db = sqlite3.connect(lecture.copier(base, Path(tmp)))
        try:
            ligne = db.execute('select value from syncedSettings where setting = ? and libraryID = ?',
                               (nom, bibliotheque)).fetchone()
        except sqlite3.OperationalError:
            return None
        finally:
            db.close()
    return json.loads(ligne[0]) if ligne else None


def fichiers_visibles(dossier: Path) -> list[str]:
    """Noms des fichiers d'un dossier de `storage/`, sans les fichiers cachés de Zotero (`.zotero-ft-cache`…),
    dans la casse et la forme Unicode du disque."""
    if not dossier.is_dir():
        return []
    return sorted(f.name for f in dossier.iterdir() if f.is_file() and not f.name.startswith('.'))


def meme_nom(a: str, b: str) -> bool:
    """Même nom, casse comprise, quelle que soit la forme Unicode (macOS décompose parfois les accents)."""
    return unicodedata.normalize('NFC', a) == unicodedata.normalize('NFC', b)
