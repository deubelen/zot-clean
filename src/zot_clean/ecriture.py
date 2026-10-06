"""Accès à l'API web de Zotero (D13, D33). Seul module qui écrit dans Zotero.

`pyzotero` fournit l'authentification, les en-têtes et le client HTTP (que les
tests remplacent par un faux serveur). Les requêtes passent par `_requete`, qui
attend après un 429 ou un en-tête `Backoff` et réessaie après un 5xx ou une
coupure réseau. Les écritures se font par lots de 50 au plus (POST), avec la
version de chaque objet, et renvoient le sort de chaque objet (`success`,
`unchanged`, `failed`), que `pyzotero.update_items` ne transmet pas.
"""

import json
import sys
import time
from dataclasses import dataclass, field

import httpx2
from pyzotero import zotero

from zot_clean.config import Config, lire_env

LOT = 50
ESSAIS = 5
LOTS_SANS_PROGRESSION = 4  # au-delà, la lecture se signale sur la sortie d'erreur, tous les cinq lots


def _sur_la_sortie_d_erreur(message: str) -> None:
    print(message, file=sys.stderr)


class ErreurAPI(Exception):
    pass


class _Changeante(Exception):
    """La bibliothèque a changé sur le serveur pendant une lecture en plusieurs requêtes."""


class Refus(Exception):
    """Écriture refusée par un garde-fou (essai, sauvegarde, synchronisation, compte)."""


@dataclass
class Resultat:
    reussis: dict[str, dict] = field(default_factory=dict)  # clé -> objet renvoyé, avec sa nouvelle version
    inchanges: set[str] = field(default_factory=set)
    echecs: dict[str, tuple[int, str]] = field(default_factory=dict)  # clé -> (code, message)


@dataclass
class Changements:
    """Objets modifiés sur le serveur depuis une version donnée, tels que l'API les rend (D171)."""
    version: int  # version de la bibliothèque sur le serveur au moment de la lecture
    elements: list[dict] = field(default_factory=list)  # `data` de chaque élément, corbeille comprise
    collections: list[dict] = field(default_factory=list)
    elements_supprimes: list[str] = field(default_factory=list)  # supprimés définitivement
    collections_supprimees: list[str] = field(default_factory=list)
    reglages: dict[str, object] = field(default_factory=dict)
    reglages_supprimes: list[str] = field(default_factory=list)
    recherches: list[dict] = field(default_factory=list)  # recherches enregistrées, `data` de l'API
    recherches_supprimees: list[str] = field(default_factory=list)

    @property
    def nombre(self) -> int:
        return (len(self.elements) + len(self.collections) + len(self.elements_supprimes)
                + len(self.collections_supprimees) + len(self.reglages) + len(self.reglages_supprimes)
                + len(self.recherches) + len(self.recherches_supprimees))


class Client:
    def __init__(self, utilisateur: int | str, cle: str, client_http: httpx2.Client | None = None, attendre=time.sleep,
                 signaler=_sur_la_sortie_d_erreur):
        self.utilisateur = int(utilisateur)
        self.zot = zotero.Zotero(self.utilisateur, 'user', cle, client=client_http)
        self._attendre = attendre
        self.signaler = signaler  # attentes et progression, pour qu'une commande longue ne reste pas muette

    @property
    def prefixe(self) -> str:
        return f'/users/{self.utilisateur}'

    def uri(self, cle: str) -> str:
        """Adresse d'une fiche, telle que Zotero l'écrit dans les relations."""
        return f'http://zotero.org/users/{self.utilisateur}/items/{cle}'

    def _requete(self, methode: str, chemin: str, admis: tuple[int, ...] = (), entetes: dict | None = None,
                 **kw) -> httpx2.Response:
        for essai in range(ESSAIS):
            try:
                r = self.zot.client.request(methode, self.zot.endpoint + chemin,
                                            headers=self.zot.default_headers() | (entetes or {}), **kw)
            except httpx2.TransportError:
                if essai == ESSAIS - 1:
                    raise ErreurAPI(f'{methode} {chemin} : Zotero injoignable.') from None
                self._patienter(5 * (essai + 1), 'zotero.org injoignable, nouvel essai')
                continue
            if r.status_code == 429:
                self._patienter(int(r.headers.get('Retry-After', 5)), 'zotero.org demande de ralentir, nouvel essai')
                continue
            if r.status_code >= 500 and essai < ESSAIS - 1:
                self._patienter(5 * (essai + 1), f'zotero.org répond {r.status_code}, nouvel essai')
                continue
            if r.status_code >= 400 and r.status_code not in admis:
                raise ErreurAPI(f'{methode} {chemin} : réponse {r.status_code} de Zotero ({r.text[:200]}).')
            if 'Backoff' in r.headers:
                self._patienter(int(r.headers['Backoff']), 'zotero.org, chargé, demande une pause avant la requête suivante')
            return r
        raise ErreurAPI(f'{methode} {chemin} : Zotero ne répond pas, réessayer plus tard.')

    def _patienter(self, secondes: int, motif: str) -> None:
        """Attente imposée par le serveur, toujours signalée : un Backoff peut durer plusieurs minutes."""
        if secondes > 0:
            self.signaler(f'{motif}, attente de {secondes} s.')
        self._attendre(secondes)

    def _progression(self, faits: int, total: int, quoi: str) -> None:
        if total > LOT * LOTS_SANS_PROGRESSION and (faits == total or faits // LOT % 5 == 0):
            self.signaler(f'{faits}/{total} {quoi} sur zotero.org')

    def fichier_en_ligne(self, cle: str) -> bool:
        """Le fichier d'une pièce jointe est-il stocké sur zotero.org (D133) ? Une redirection vers le
        fichier s'il existe, 404 sinon. HEAD répond toujours 200, d'où un GET sans suivre la redirection."""
        r = self._requete('GET', f'{self.prefixe}/items/{cle}/file', admis=(404,), follow_redirects=False)
        return 300 <= r.status_code < 400

    def fiches(self, cles: list[str]) -> dict[str, dict]:
        """Données actuelles des éléments demandés, corbeille comprise. Une clé absente du résultat n'existe plus."""
        res = {}
        cles = list(dict.fromkeys(cles))
        for i in range(0, len(cles), LOT):
            r = self._requete('GET', f'{self.prefixe}/items', params={
                'itemKey': ','.join(cles[i:i + LOT]), 'includeTrashed': 1, 'limit': LOT, 'format': 'json'})
            res.update({o['key']: o['data'] for o in r.json()})
            self._progression(min(i + LOT, len(cles)), len(cles), 'éléments lus')
        return res

    def version_serveur(self) -> int:
        """Version actuelle de la bibliothèque sur le serveur."""
        r = self._requete('GET', f'{self.prefixe}/items', params={'limit': 1, 'format': 'keys'})
        return int(r.headers.get('Last-Modified-Version', 0))

    def collections(self, cles: list[str]) -> dict[str, dict]:
        """Données actuelles des collections demandées, corbeille comprise. Une clé absente n'existe pas ou plus."""
        res = {}
        cles = list(dict.fromkeys(cles))
        for i in range(0, len(cles), LOT):
            r = self._requete('GET', f'{self.prefixe}/collections', params={
                'collectionKey': ','.join(cles[i:i + LOT]), 'includeTrashed': 1, 'limit': LOT, 'format': 'json'})
            res.update({o['key']: o['data'] for o in r.json()})
            self._progression(min(i + LOT, len(cles)), len(cles), 'collections lues')
        return res

    @staticmethod
    def _meme_version(r: httpx2.Response, versions: set[int]) -> None:
        """Toutes les réponses d'une même lecture doivent venir de la même version de la bibliothèque (D187)."""
        if v := int(r.headers.get('Last-Modified-Version', 0)):
            versions.add(v)
        if len(versions) > 1:
            raise _Changeante()

    def _depuis(self, genre: str, version: int, versions: set[int]) -> list[dict]:
        """Objets d'un genre modifiés depuis `version`, corbeille comprise."""
        res, debut = [], 0
        while True:
            r = self._requete('GET', f'{self.prefixe}/{genre}', params={
                'since': version, 'includeTrashed': 1, 'limit': 100, 'start': debut, 'format': 'json'})
            self._meme_version(r, versions)
            page = r.json()
            res += [o['data'] for o in page]
            debut += len(page)
            if not page or debut >= int(r.headers.get('Total-Results', debut)):
                return res

    def changements(self, version: int) -> 'Changements':
        """Ce qui a changé sur le serveur depuis `version` (D171) : fiches et autres éléments, collections,
        recherches enregistrées, suppressions définitives, réglages synchronisés. Si la bibliothèque change pendant
        la lecture, celle-ci recommence, comme le demande la documentation de synchronisation de Zotero (D187)."""
        for essai in range(ESSAIS):
            if essai:
                self._patienter(2, 'la bibliothèque change sur zotero.org pendant la lecture, nouvel essai')
            versions: set[int] = set()
            try:
                elements = self._depuis('items', version, versions)
                collections = self._depuis('collections', version, versions)
                recherches = self._depuis('searches', version, versions)
                r = self._requete('GET', f'{self.prefixe}/deleted', params={'since': version})
                self._meme_version(r, versions)
                supprimes = r.json() or {}
                r = self._requete('GET', f'{self.prefixe}/settings', params={'since': version})
                self._meme_version(r, versions)
                reglages = r.json() or {}
            except _Changeante:
                continue
            return Changements(max(versions, default=0), elements, collections,
                               list(supprimes.get('items') or []), list(supprimes.get('collections') or []),
                               {k: v.get('value') for k, v in reglages.items() if isinstance(v, dict)},
                               list(supprimes.get('settings') or []), recherches,
                               list(supprimes.get('searches') or []))
        raise ErreurAPI('La bibliothèque change sans cesse sur zotero.org pendant la lecture (synchronisation en '
                        'cours ?). Relancer la commande dans un instant.')

    def reglages(self, noms: list[str]) -> dict[str, dict]:
        """Réglages synchronisés de la bibliothèque (D175), sous la forme {key, version, value}. Un réglage absent a
        la version 0 et la valeur None, comme un objet qu'on peut créer."""
        res = {}
        for nom in dict.fromkeys(noms):
            r = self._requete('GET', f'{self.prefixe}/settings/{nom}', admis=(404,))
            d = r.json() if r.status_code == 200 else {}
            res[nom] = {'key': nom, 'version': int(d.get('version', 0)), 'value': d.get('value')}
        return res

    def lire(self, cles: list[str], genre: str = 'items') -> dict[str, dict]:
        if genre == 'settings':
            return self.reglages(cles)
        return self.collections(cles) if genre == 'collections' else self.fiches(cles)

    def enfants(self, cle: str) -> list[dict]:
        """Pièces jointes et notes d'une fiche, corbeille comprise."""
        res, debut = [], 0
        while True:
            r = self._requete('GET', f'{self.prefixe}/items/{cle}/children',
                              params={'includeTrashed': 1, 'limit': 100, 'start': debut, 'format': 'json'})
            page = r.json()
            res += [o['data'] for o in page]
            debut += len(page)
            if not page or debut >= int(r.headers.get('Total-Results', debut)):
                return res

    def _pages(self, chemin: str) -> list[dict]:
        res, debut = [], 0
        while True:
            r = self._requete('GET', chemin, params={'limit': 100, 'start': debut, 'format': 'json'})
            page = r.json()
            res += [o['data'] for o in page]
            debut += len(page)
            if not page or debut >= int(r.headers.get('Total-Results', debut)):
                return res

    def contenu(self, cle: str, genre: str = 'items') -> list[str]:
        """Clés de ce que contient un élément hors corbeille : enfants d'une fiche ou annotations d'une pièce
        jointe, fiches et sous-collections d'une collection (D182, D183)."""
        if genre == 'collections':
            objets = (self._pages(f'{self.prefixe}/collections/{cle}/items')
                      + self._pages(f'{self.prefixe}/collections/{cle}/collections'))
        else:
            objets = self.enfants(cle)
        return [o['key'] for o in objets if not o.get('deleted')]

    def ecrire(self, objets: list[dict], genre: str = 'items') -> Resultat:
        """Modifie jusqu'à 50 éléments ou collections. Chaque objet porte `key`, `version` et les seuls champs à
        changer. Une collection se crée avec sa clé et `version` 0 (D114)."""
        if len(objets) > LOT:
            raise ValueError(f'{len(objets)} objets, {LOT} au plus par lot')
        if not objets:
            return Resultat()
        if genre == 'settings':
            return self._ecrire_reglages(objets)
        r = self._requete('POST', f'{self.prefixe}/{genre}', json=objets)
        d = r.json()
        res = Resultat()
        for i, obj in (d.get('successful') or {}).items():
            res.reussis[objets[int(i)]['key']] = obj
        res.inchanges = {objets[int(i)]['key'] for i in (d.get('unchanged') or {})}
        for i, e in (d.get('failed') or {}).items():
            res.echecs[objets[int(i)]['key']] = (int(e.get('code', 0)), e.get('message', ''))
        return res

    def _ecrire_reglages(self, objets: list[dict]) -> Resultat:
        """Un réglage par requête, avec sa version (0 pour le créer) : 412 s'il a changé depuis (D175)."""
        res = Resultat()
        for o in objets:
            if o['value'] in (None, []):  # retour à l'absence du réglage, Zotero refuse une liste vide
                # La sonde du 04/10/2026 montre que zotero.org ne refuse pas une suppression à version périmée : le
                # socle, qui relit le réglage juste avant, reste le seul contrôle. Déjà absent, rien à faire.
                r = self._requete('DELETE', f'{self.prefixe}/settings/{o["key"]}', admis=(404, 412),
                                  entetes={'If-Unmodified-Since-Version': str(o['version'])})
                if r.status_code == 404:
                    res.inchanges.add(o['key'])
                    continue
            else:
                r = self._requete('POST', f'{self.prefixe}/settings', admis=(412,),
                                  json={o['key']: {'value': o['value'], 'version': o['version']}})
            if r.status_code == 412:
                res.echecs[o['key']] = (412, 'réglage modifié depuis la version donnée')
            else:
                res.reussis[o['key']] = {'version': int(r.headers.get('Last-Modified-Version', 0))}
        return res

    def creer(self, objets: list[dict], genre: str = 'items') -> list[str]:
        """Crée des éléments ou des collections (`genre`), par lots de 50. Renvoie leurs clés, dans l'ordre.

        Seule façon de créer un élément, puisque Zotero attribue alors lui-même des clés valides."""
        cles = []
        for i in range(0, len(objets), LOT):
            lot = objets[i:i + LOT]
            d = self._requete('POST', f'{self.prefixe}/{genre}', json=lot).json()
            if d.get('failed'):
                raise ErreurAPI(f"Création refusée par Zotero : {json.dumps(d['failed'], ensure_ascii=False)[:300]}")
            cles += [d['success'][str(j)] for j in range(len(lot))]
        return cles


def depuis_config(cfg: Config) -> Client:
    env = lire_env(cfg.dossier_travail)
    if not env.get('ZOTERO_API_KEY') or not env.get('ZOTERO_USER_ID'):
        raise SystemExit("Aucune clé API dans .env. Lancer `zc init` dans ce dossier pour l'enregistrer.")
    return Client(env['ZOTERO_USER_ID'], env['ZOTERO_API_KEY'])
