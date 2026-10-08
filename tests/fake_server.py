"""Fake server of the Zotero web API, in memory (D45).

Reproduces the subset used by `zot_clean.api`: reading items
by key (trash included), children of an item, batch writes with the
version of each object (PATCH semantics, 412 if the version no longer
matches). A new `filename` is accepted only for an imported file. Collections
have their own store, are read by key and are created
with a supplied key and version 0, as the probe checked on the test account
(D114). Outages (429, 5xx) are scheduled in `outages`. Plugged into
`pyzotero` through `httpx2.MockTransport`, without network. `lost_responses` makes
the response of a write the server did perform get lost.
"""

import copy
import itertools
import json
import re

import httpx2

from zot_clean.api import Client

ALPHABET = '23456789ABCDEFGHIJKLMNPQRSTUVWXYZ'


class FakeServer:
    def __init__(self, user: int = 4242):
        self.user = user
        self.version = 100
        self.all_items: dict[str, dict] = {}
        self.collections: dict[str, dict] = {}
        self.outages: list[int] = []  # codes to return to the next requests, in order
        self.requests: list[tuple[str, str]] = []
        self.before_write = None  # function called just before applying a POST (concurrent change)
        self.files: set[str] = set()  # attachments whose file is stored on the server (D133)
        self.deleted: dict[str, dict[str, int]] = {'items': {}, 'collections': {}, 'searches': {},
                                                     'settings': {}}  # key -> version
        self.searches: dict[str, dict] = {}
        self.during_read = None  # function called at each page of a `since` read (concurrent change)
        self.settings: dict[str, dict] = {}  # name -> {value, version}
        self.lost_responses = 0  # next writes done by the server whose response is lost (D178)
        self._n = itertools.count(1)

    def client(self) -> Client:
        return Client(self.user, 'CLE-DE-TEST', httpx2.Client(transport=httpx2.MockTransport(self.handle)),
                      wait=lambda s: None)

    def add(self, type_: str = 'journalArticle', **fields) -> str:
        key = fields.pop('key', None) or self._key()
        self.version += 1
        data = {'key': key, 'version': self.version, 'itemType': type_, 'dateAdded': '2026-01-01T00:00:00Z'}
        if type_ not in ('note', 'attachment', 'annotation'):
            data.update(title='', creators=[], date='', DOI='', ISBN='', extra='', collections=[], tags=[],
                        relations={})
        else:
            data.update(tags=[], relations={})
        data.update(fields)
        self.all_items[key] = data
        return key

    def collection(self, name: str, parent: str | None = None, **fields) -> str:
        key = fields.pop('key', None) or self._key()
        self.version += 1
        self.collections[key] = {'key': key, 'version': self.version, 'name': name,
                                 'parentCollection': parent or False, 'relations': {}, **fields}
        return key

    def modify(self, key: str, **fields):
        """Change made elsewhere (in Zotero, by a synchronisation)."""
        self.version += 1
        self.all_items[key].update(fields, version=self.version)

    def delete(self, key: str):
        """Permanent deletion made elsewhere (trash emptied)."""
        self.version += 1
        kind = 'items' if self.all_items.pop(key, None) else 'collections'
        if kind == 'collections':
            del self.collections[key]
        self.deleted[kind][key] = self.version

    def set_setting(self, name: str, value):
        self.version += 1
        self.settings[name] = {'value': value, 'version': self.version}

    def drop_setting(self, name: str):
        self.version += 1
        del self.settings[name]
        self.deleted['settings'][name] = self.version

    def search(self, name: str, conditions: list[dict], **fields) -> str:
        key = fields.pop('key', None) or self._key()
        self.version += 1
        self.searches[key] = {'key': key, 'version': self.version, 'name': name, 'conditions': conditions, **fields}
        return key

    def delete_search(self, key: str):
        self.version += 1
        del self.searches[key]
        self.deleted['searches'][key] = self.version

    def _since(self, store: dict, req: httpx2.Request) -> httpx2.Response:
        origin = int(req.url.params['since'])
        start, limit = int(req.url.params.get('start', 0)), int(req.url.params.get('limit', 25))
        all_entries = [self._object(d) for d in store.values() if d['version'] > origin]
        r = httpx2.Response(200, json=all_entries[start:start + limit], headers={
            'Total-Results': str(len(all_entries)), 'Last-Modified-Version': str(self.version)})
        if self.during_read:  # after the response, like a change made between two requests
            self.during_read()
        return r

    def _key(self) -> str:
        n, key = next(self._n), ''
        for _ in range(8):
            n, r = divmod(n, len(ALPHABET))
            key = ALPHABET[r] + key
        return key

    def _object(self, d: dict) -> dict:
        return {'key': d['key'], 'version': d['version'], 'data': copy.deepcopy(d)}

    def handle(self, req: httpx2.Request) -> httpx2.Response:
        r = self._handle(req)
        if req.method in ('POST', 'DELETE') and self.lost_responses and r.status_code < 300:
            self.lost_responses -= 1
            raise httpx2.ReadTimeout('réponse perdue', request=req)
        return r

    def _handle(self, req: httpx2.Request) -> httpx2.Response:
        path = req.url.path
        self.requests.append((req.method, path))
        if self.outages:
            return httpx2.Response(self.outages.pop(0), headers={'Retry-After': '0'}, text='panne programmée')
        prefix = f'/users/{self.user}/items'
        if req.method == 'GET' and path == prefix and req.url.params.get('format') == 'keys':
            return httpx2.Response(200, text='\n'.join(self.all_items),
                                   headers={'Last-Modified-Version': str(self.version)})
        if req.method == 'GET' and path == prefix and 'since' in req.url.params:
            return self._since(self.all_items, req)
        if req.method == 'GET' and path == f'/users/{self.user}/collections' and 'since' in req.url.params:
            return self._since(self.collections, req)
        if req.method == 'GET' and path == f'/users/{self.user}/searches' and 'since' in req.url.params:
            return self._since(self.searches, req)
        if req.method == 'GET' and path == f'/users/{self.user}/deleted':
            origin = int(req.url.params['since'])
            return httpx2.Response(200, json={g: [k for k, v in d.items() if v > origin]
                                              for g, d in self.deleted.items()},
                                   headers={'Last-Modified-Version': str(self.version)})
        if (m := re.fullmatch(f'/users/{self.user}/settings/(\\w+)', path)) and req.method == 'GET':
            if m.group(1) not in self.settings:
                return httpx2.Response(404, text='Not found')
            return httpx2.Response(200, json=self.settings[m.group(1)])
        if m and req.method == 'DELETE':
            # Like zotero.org in the D175 probe, deleting a setting does not check its version.
            if m.group(1) not in self.settings:
                return httpx2.Response(404, text='Not found')
            self.version += 1
            del self.settings[m.group(1)]
            return httpx2.Response(204, headers={'Last-Modified-Version': str(self.version)})
        if req.method == 'POST' and path == f'/users/{self.user}/settings':
            for name, d in json.loads(req.content).items():
                if d['value'] == []:
                    return httpx2.Response(400, text="'value' array cannot be empty")
                if d.get('version', 0) != self.settings.get(name, {}).get('version', 0):
                    return httpx2.Response(412, text='réglage modifié')
            self.version += 1
            for name, d in json.loads(req.content).items():
                self.settings[name] = {'value': d['value'], 'version': self.version}
            return httpx2.Response(204, headers={'Last-Modified-Version': str(self.version)})
        if req.method == 'GET' and path == f'/users/{self.user}/settings':
            origin = int(req.url.params['since'])
            return httpx2.Response(200, json={k: v for k, v in self.settings.items() if v['version'] > origin},
                                   headers={'Last-Modified-Version': str(self.version)})
        if req.method == 'GET' and path == prefix:
            keys = req.url.params.get('itemKey', '').split(',')
            trash = req.url.params.get('includeTrashed') == '1'
            res = [self._object(self.all_items[k]) for k in keys
                   if k in self.all_items and (trash or not self.all_items[k].get('deleted'))]
            return httpx2.Response(200, json=res, headers={'Total-Results': str(len(res)),
                                                           'Last-Modified-Version': str(self.version)})
        if req.method == 'GET' and (m := re.fullmatch(prefix + r'/(\w+)/file', path)):
            if m.group(1) in self.files:
                return httpx2.Response(302, headers={'Location': f'https://stockage.invalid/{m.group(1)}'})
            return httpx2.Response(404, text='Not found')
        if req.method == 'GET' and (m := re.fullmatch(prefix + r'/(\w+)/children', path)):
            res = [self._object(d) for d in self.all_items.values() if d.get('parentItem') == m.group(1)]
            return httpx2.Response(200, json=res, headers={'Total-Results': str(len(res))})
        if req.method == 'GET' and (m := re.fullmatch(f'/users/{self.user}/collections/(\\w+)/(items|collections)',
                                                      path)):
            if m.group(2) == 'items':
                res = [d for d in self.all_items.values() if m.group(1) in d.get('collections', [])
                       and not d.get('deleted')]
            else:
                res = [d for d in self.collections.values() if d.get('parentCollection') == m.group(1)]
            return httpx2.Response(200, json=[self._object(d) for d in res], headers={'Total-Results': str(len(res))})
        if req.method == 'GET' and path == f'/users/{self.user}/collections':
            keys = req.url.params.get('collectionKey', '').split(',')
            trash = req.url.params.get('includeTrashed') == '1'
            res = [self._object(self.collections[k]) for k in keys
                   if k in self.collections and (trash or not self.collections[k].get('deleted'))]
            return httpx2.Response(200, json=res, headers={'Total-Results': str(len(res))})
        if req.method == 'POST' and path == f'/users/{self.user}/collections':
            return self._write(json.loads(req.content), self.collections)
        if req.method == 'POST' and path == prefix:
            if self.before_write:
                self.before_write()
            return self._write(json.loads(req.content))
        return httpx2.Response(404, text='route inconnue du faux serveur')

    def _write(self, objects: list[dict], store: dict | None = None) -> httpx2.Response:
        if len(objects) > 50:
            return httpx2.Response(413, text='plus de 50 objets')
        store = self.all_items if store is None else store
        new = self.version + 1
        resp = {'successful': {}, 'success': {}, 'unchanged': {}, 'failed': {}}
        for i, o in enumerate(objects):
            i = str(i)
            if refusal := self._refusal(o, store):
                resp['failed'][i] = {'key': o.get('key'), 'code': 400, 'message': refusal}
                continue
            if 'key' not in o or (o.get('version') == 0 and o['key'] not in store):
                key = o.get('key') or self._key()
                store[key] = dict({k: v for k, v in o.items() if k != 'version'}, key=key, version=new)
                if store is self.collections:
                    store[key].setdefault('parentCollection', False)
                resp['success'][i] = key
                resp['successful'][i] = self._object(store[key])
                continue
            d = store.get(o['key'])
            if d is None:
                resp['failed'][i] = {'key': o['key'], 'code': 404, 'message': 'élément introuvable'}
                continue
            if o.get('version') != d['version']:
                resp['failed'][i] = {'key': o['key'], 'code': 412, 'message': 'élément modifié depuis la version donnée'}
                continue
            fields = {k: v for k, v in o.items() if k not in ('key', 'version')}
            if all(d.get(k) == v for k, v in fields.items()):
                resp['unchanged'][i] = o['key']
                continue
            for k, v in fields.items():
                if (k == 'deleted' and not v) or (k == 'parentItem' and v is False):
                    d.pop(k, None)
                else:
                    d[k] = v
            d['version'] = new
            resp['success'][i] = o['key']
            resp['successful'][i] = self._object(d)
        if resp['success']:
            self.version = new
        return httpx2.Response(200, json=resp, headers={'Last-Modified-Version': str(self.version)})

    def _refusal(self, o: dict, store: dict) -> str:
        """References to a nonexistent parent or collection, refused by Zotero. A new `filename`
        is accepted only for an imported file, whose content the server keeps (D161)."""
        if 'filename' in o and store is self.all_items and o.get('key') in self.all_items:
            d = self.all_items[o['key']]
            if d.get('itemType') != 'attachment' or d.get('linkMode') not in ('imported_file', 'imported_url'):
                return 'filename réservé aux fichiers importés'
        if o.get('parentItem') and o['parentItem'] not in self.all_items:
            return 'parent introuvable'
        if store is self.collections and o.get('parentCollection') and o['parentCollection'] not in self.collections:
            return 'collection parente introuvable'
        if any(c not in self.collections for c in o.get('collections', [])) and self.collections:
            return 'collection introuvable'
        return ''
