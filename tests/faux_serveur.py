"""Faux serveur de l'API web de Zotero, en mémoire (D45).

Reproduit le sous-ensemble utilisé par `zot_clean.ecriture` : lecture de fiches
par clé (corbeille comprise), enfants d'une fiche, écriture par lots avec la
version de chaque objet (sémantique PATCH, 412 si la version ne correspond
plus). Un nouveau `filename` n'est accepté que pour un fichier importé. Les
collections ont leur propre magasin, se lisent par clé et se créent
avec une clé fournie et la version 0, comme l'a vérifié la sonde sur le compte
de test (D114). Les pannes (429, 5xx) se programment dans `pannes`. Branché sur
`pyzotero` par `httpx2.MockTransport`, sans réseau. `reponses_perdues` fait
perdre la réponse d'une écriture que le serveur a pourtant faite.
"""

import copy
import itertools
import json
import re

import httpx2

from zot_clean.ecriture import Client

ALPHABET = '23456789ABCDEFGHIJKLMNPQRSTUVWXYZ'


class FauxServeur:
    def __init__(self, utilisateur: int = 4242):
        self.utilisateur = utilisateur
        self.version = 100
        self.elements: dict[str, dict] = {}
        self.collections: dict[str, dict] = {}
        self.pannes: list[int] = []  # codes à renvoyer aux prochaines requêtes, dans l'ordre
        self.requetes: list[tuple[str, str]] = []
        self.avant_ecriture = None  # fonction appelée juste avant d'appliquer un POST (modification concurrente)
        self.fichiers: set[str] = set()  # pièces jointes dont le fichier est stocké sur le serveur (D133)
        self.supprimes: dict[str, dict[str, int]] = {'items': {}, 'collections': {}, 'searches': {},
                                                     'settings': {}}  # clé -> version
        self.recherches: dict[str, dict] = {}
        self.pendant_lecture = None  # fonction appelée à chaque page d'une lecture `since` (changement concurrent)
        self.reglages: dict[str, dict] = {}  # nom -> {value, version}
        self.reponses_perdues = 0  # prochaines écritures faites par le serveur dont la réponse se perd (D178)
        self._n = itertools.count(1)

    def client(self) -> Client:
        return Client(self.utilisateur, 'CLE-DE-TEST', httpx2.Client(transport=httpx2.MockTransport(self.traiter)),
                      attendre=lambda s: None)

    def ajouter(self, type_: str = 'journalArticle', **champs) -> str:
        cle = champs.pop('key', None) or self._cle()
        self.version += 1
        data = {'key': cle, 'version': self.version, 'itemType': type_, 'dateAdded': '2026-01-01T00:00:00Z'}
        if type_ not in ('note', 'attachment', 'annotation'):
            data.update(title='', creators=[], date='', DOI='', ISBN='', extra='', collections=[], tags=[],
                        relations={})
        else:
            data.update(tags=[], relations={})
        data.update(champs)
        self.elements[cle] = data
        return cle

    def collection(self, nom: str, parent: str | None = None, **champs) -> str:
        cle = champs.pop('key', None) or self._cle()
        self.version += 1
        self.collections[cle] = {'key': cle, 'version': self.version, 'name': nom,
                                 'parentCollection': parent or False, 'relations': {}, **champs}
        return cle

    def modifier(self, cle: str, **champs):
        """Modification faite ailleurs (dans Zotero, par une synchronisation)."""
        self.version += 1
        self.elements[cle].update(champs, version=self.version)

    def supprimer(self, cle: str):
        """Suppression définitive faite ailleurs (corbeille vidée)."""
        self.version += 1
        genre = 'items' if self.elements.pop(cle, None) else 'collections'
        if genre == 'collections':
            del self.collections[cle]
        self.supprimes[genre][cle] = self.version

    def regler(self, nom: str, valeur):
        self.version += 1
        self.reglages[nom] = {'value': valeur, 'version': self.version}

    def retirer_reglage(self, nom: str):
        self.version += 1
        del self.reglages[nom]
        self.supprimes['settings'][nom] = self.version

    def recherche(self, nom: str, conditions: list[dict], **champs) -> str:
        cle = champs.pop('key', None) or self._cle()
        self.version += 1
        self.recherches[cle] = {'key': cle, 'version': self.version, 'name': nom, 'conditions': conditions, **champs}
        return cle

    def supprimer_recherche(self, cle: str):
        self.version += 1
        del self.recherches[cle]
        self.supprimes['searches'][cle] = self.version

    def _depuis(self, magasin: dict, req: httpx2.Request) -> httpx2.Response:
        depuis = int(req.url.params['since'])
        debut, limite = int(req.url.params.get('start', 0)), int(req.url.params.get('limit', 25))
        tous = [self._objet(d) for d in magasin.values() if d['version'] > depuis]
        r = httpx2.Response(200, json=tous[debut:debut + limite], headers={
            'Total-Results': str(len(tous)), 'Last-Modified-Version': str(self.version)})
        if self.pendant_lecture:  # après la réponse, comme un changement fait entre deux requêtes
            self.pendant_lecture()
        return r

    def _cle(self) -> str:
        n, cle = next(self._n), ''
        for _ in range(8):
            n, r = divmod(n, len(ALPHABET))
            cle = ALPHABET[r] + cle
        return cle

    def _objet(self, d: dict) -> dict:
        return {'key': d['key'], 'version': d['version'], 'data': copy.deepcopy(d)}

    def traiter(self, req: httpx2.Request) -> httpx2.Response:
        r = self._traiter(req)
        if req.method in ('POST', 'DELETE') and self.reponses_perdues and r.status_code < 300:
            self.reponses_perdues -= 1
            raise httpx2.ReadTimeout('réponse perdue', request=req)
        return r

    def _traiter(self, req: httpx2.Request) -> httpx2.Response:
        chemin = req.url.path
        self.requetes.append((req.method, chemin))
        if self.pannes:
            return httpx2.Response(self.pannes.pop(0), headers={'Retry-After': '0'}, text='panne programmée')
        prefixe = f'/users/{self.utilisateur}/items'
        if req.method == 'GET' and chemin == prefixe and req.url.params.get('format') == 'keys':
            return httpx2.Response(200, text='\n'.join(self.elements),
                                   headers={'Last-Modified-Version': str(self.version)})
        if req.method == 'GET' and chemin == prefixe and 'since' in req.url.params:
            return self._depuis(self.elements, req)
        if req.method == 'GET' and chemin == f'/users/{self.utilisateur}/collections' and 'since' in req.url.params:
            return self._depuis(self.collections, req)
        if req.method == 'GET' and chemin == f'/users/{self.utilisateur}/searches' and 'since' in req.url.params:
            return self._depuis(self.recherches, req)
        if req.method == 'GET' and chemin == f'/users/{self.utilisateur}/deleted':
            depuis = int(req.url.params['since'])
            return httpx2.Response(200, json={g: [k for k, v in d.items() if v > depuis]
                                              for g, d in self.supprimes.items()},
                                   headers={'Last-Modified-Version': str(self.version)})
        if (m := re.fullmatch(f'/users/{self.utilisateur}/settings/(\\w+)', chemin)) and req.method == 'GET':
            if m.group(1) not in self.reglages:
                return httpx2.Response(404, text='Not found')
            return httpx2.Response(200, json=self.reglages[m.group(1)])
        if m and req.method == 'DELETE':
            # Comme zotero.org à la sonde de D175, la suppression d'un réglage ne contrôle pas sa version.
            if m.group(1) not in self.reglages:
                return httpx2.Response(404, text='Not found')
            self.version += 1
            del self.reglages[m.group(1)]
            return httpx2.Response(204, headers={'Last-Modified-Version': str(self.version)})
        if req.method == 'POST' and chemin == f'/users/{self.utilisateur}/settings':
            for nom, d in json.loads(req.content).items():
                if d['value'] == []:
                    return httpx2.Response(400, text="'value' array cannot be empty")
                if d.get('version', 0) != self.reglages.get(nom, {}).get('version', 0):
                    return httpx2.Response(412, text='réglage modifié')
            self.version += 1
            for nom, d in json.loads(req.content).items():
                self.reglages[nom] = {'value': d['value'], 'version': self.version}
            return httpx2.Response(204, headers={'Last-Modified-Version': str(self.version)})
        if req.method == 'GET' and chemin == f'/users/{self.utilisateur}/settings':
            depuis = int(req.url.params['since'])
            return httpx2.Response(200, json={k: v for k, v in self.reglages.items() if v['version'] > depuis},
                                   headers={'Last-Modified-Version': str(self.version)})
        if req.method == 'GET' and chemin == prefixe:
            cles = req.url.params.get('itemKey', '').split(',')
            corbeille = req.url.params.get('includeTrashed') == '1'
            res = [self._objet(self.elements[k]) for k in cles
                   if k in self.elements and (corbeille or not self.elements[k].get('deleted'))]
            return httpx2.Response(200, json=res, headers={'Total-Results': str(len(res)),
                                                           'Last-Modified-Version': str(self.version)})
        if req.method == 'GET' and (m := re.fullmatch(prefixe + r'/(\w+)/file', chemin)):
            if m.group(1) in self.fichiers:
                return httpx2.Response(302, headers={'Location': f'https://stockage.invalid/{m.group(1)}'})
            return httpx2.Response(404, text='Not found')
        if req.method == 'GET' and (m := re.fullmatch(prefixe + r'/(\w+)/children', chemin)):
            res = [self._objet(d) for d in self.elements.values() if d.get('parentItem') == m.group(1)]
            return httpx2.Response(200, json=res, headers={'Total-Results': str(len(res))})
        if req.method == 'GET' and (m := re.fullmatch(f'/users/{self.utilisateur}/collections/(\\w+)/(items|collections)',
                                                      chemin)):
            if m.group(2) == 'items':
                res = [d for d in self.elements.values() if m.group(1) in d.get('collections', [])
                       and not d.get('deleted')]
            else:
                res = [d for d in self.collections.values() if d.get('parentCollection') == m.group(1)]
            return httpx2.Response(200, json=[self._objet(d) for d in res], headers={'Total-Results': str(len(res))})
        if req.method == 'GET' and chemin == f'/users/{self.utilisateur}/collections':
            cles = req.url.params.get('collectionKey', '').split(',')
            corbeille = req.url.params.get('includeTrashed') == '1'
            res = [self._objet(self.collections[k]) for k in cles
                   if k in self.collections and (corbeille or not self.collections[k].get('deleted'))]
            return httpx2.Response(200, json=res, headers={'Total-Results': str(len(res))})
        if req.method == 'POST' and chemin == f'/users/{self.utilisateur}/collections':
            return self._ecrire(json.loads(req.content), self.collections)
        if req.method == 'POST' and chemin == prefixe:
            if self.avant_ecriture:
                self.avant_ecriture()
            return self._ecrire(json.loads(req.content))
        return httpx2.Response(404, text='route inconnue du faux serveur')

    def _ecrire(self, objets: list[dict], magasin: dict | None = None) -> httpx2.Response:
        if len(objets) > 50:
            return httpx2.Response(413, text='plus de 50 objets')
        magasin = self.elements if magasin is None else magasin
        nouvelle = self.version + 1
        rep = {'successful': {}, 'success': {}, 'unchanged': {}, 'failed': {}}
        for i, o in enumerate(objets):
            i = str(i)
            if refus := self._refus(o, magasin):
                rep['failed'][i] = {'key': o.get('key'), 'code': 400, 'message': refus}
                continue
            if 'key' not in o or (o.get('version') == 0 and o['key'] not in magasin):
                cle = o.get('key') or self._cle()
                magasin[cle] = dict({k: v for k, v in o.items() if k != 'version'}, key=cle, version=nouvelle)
                if magasin is self.collections:
                    magasin[cle].setdefault('parentCollection', False)
                rep['success'][i] = cle
                rep['successful'][i] = self._objet(magasin[cle])
                continue
            d = magasin.get(o['key'])
            if d is None:
                rep['failed'][i] = {'key': o['key'], 'code': 404, 'message': 'élément introuvable'}
                continue
            if o.get('version') != d['version']:
                rep['failed'][i] = {'key': o['key'], 'code': 412, 'message': 'élément modifié depuis la version donnée'}
                continue
            champs = {k: v for k, v in o.items() if k not in ('key', 'version')}
            if all(d.get(k) == v for k, v in champs.items()):
                rep['unchanged'][i] = o['key']
                continue
            for k, v in champs.items():
                if (k == 'deleted' and not v) or (k == 'parentItem' and v is False):
                    d.pop(k, None)
                else:
                    d[k] = v
            d['version'] = nouvelle
            rep['success'][i] = o['key']
            rep['successful'][i] = self._objet(d)
        if rep['success']:
            self.version = nouvelle
        return httpx2.Response(200, json=rep, headers={'Last-Modified-Version': str(self.version)})

    def _refus(self, o: dict, magasin: dict) -> str:
        """Références vers un parent ou une collection inexistants, refusées par Zotero. Un nouveau `filename`
        n'est accepté que pour un fichier importé, dont le serveur garde le contenu (D161)."""
        if 'filename' in o and magasin is self.elements and o.get('key') in self.elements:
            d = self.elements[o['key']]
            if d.get('itemType') != 'attachment' or d.get('linkMode') not in ('imported_file', 'imported_url'):
                return 'filename réservé aux fichiers importés'
        if o.get('parentItem') and o['parentItem'] not in self.elements:
            return 'parent introuvable'
        if magasin is self.collections and o.get('parentCollection') and o['parentCollection'] not in self.collections:
            return 'collection parente introuvable'
        if any(c not in self.collections for c in o.get('collections', [])) and self.collections:
            return 'collection introuvable'
        return ''
