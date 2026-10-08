"""Access to the Zotero web API (D13, D33). The only module that writes to Zotero.

`pyzotero` provides authentication, headers and the HTTP client (which the tests
replace with a fake server). Requests go through `_request`, which waits after a
429 or a `Backoff` header and retries after a 5xx or a network drop. Writes are
made in batches of at most 50 (POST), with the version of each object, and
return the outcome of each object (`success`, `unchanged`, `failed`), which
`pyzotero.update_items` does not pass on.
"""

import json
import sys
import time
from dataclasses import dataclass, field

import httpx2
from pyzotero import zotero

from zot_clean.config import Config, read_env
from zot_clean.lang import L

BATCH = 50
ATTEMPTS = 5
BATCHES_WITHOUT_PROGRESS = 4  # beyond that, the read is reported on the error output, every five batches


def _to_stderr(message: str) -> None:
    print(message, file=sys.stderr)


class APIError(Exception):
    pass


class _Changing(Exception):
    """The library changed on the server during a read made of several requests."""


class Refusal(Exception):
    """Write refused by a safeguard (trial, backup, synchronization, account)."""


@dataclass
class Result:
    succeeded: dict[str, dict] = field(default_factory=dict)  # key -> returned object, with its new version
    unchanged: set[str] = field(default_factory=set)
    failures: dict[str, tuple[int, str]] = field(default_factory=dict)  # key -> (code, message)


@dataclass
class Changes:
    """Objects modified on the server since a given version, as the API returns them (D171)."""
    version: int  # library version on the server at the time of the read
    all_items: list[dict] = field(default_factory=list)  # `data` of each item, trash included
    collections: list[dict] = field(default_factory=list)
    deleted_items: list[str] = field(default_factory=list)  # permanently deleted
    deleted_collections: list[str] = field(default_factory=list)
    settings: dict[str, object] = field(default_factory=dict)
    deleted_settings: list[str] = field(default_factory=list)
    searches: list[dict] = field(default_factory=list)  # saved searches, `data` from the API
    deleted_searches: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return (len(self.all_items) + len(self.collections) + len(self.deleted_items)
                + len(self.deleted_collections) + len(self.settings) + len(self.deleted_settings)
                + len(self.searches) + len(self.deleted_searches))


class Client:
    def __init__(self, user: int | str, key: str, client_http: httpx2.Client | None = None, wait=time.sleep,
                 notify=_to_stderr):
        self.user = int(user)
        self.zot = zotero.Zotero(self.user, 'user', key, client=client_http)
        self._wait = wait
        self.notify = notify  # waits and progress, so that a long command does not stay silent

    @property
    def prefix(self) -> str:
        return f'/users/{self.user}'

    def uri(self, key: str) -> str:
        """Address of an item, as Zotero writes it in relations."""
        return f'http://zotero.org/users/{self.user}/items/{key}'

    def _request(self, method: str, path: str, allowed: tuple[int, ...] = (), headers: dict | None = None,
                 **kw) -> httpx2.Response:
        for trial in range(ATTEMPTS):
            try:
                r = self.zot.client.request(method, self.zot.endpoint + path,
                                            headers=self.zot.default_headers() | (headers or {}), **kw)
            except httpx2.TransportError:
                if trial == ATTEMPTS - 1:
                    raise APIError(L(en=f'{method} {path}: Zotero unreachable.',
                                     fr=f'{method} {path} : Zotero injoignable.')) from None
                self._pause(5 * (trial + 1), L(en='zotero.org unreachable, trying again',
                                               fr='zotero.org injoignable, nouvel essai'))
                continue
            if r.status_code == 429:
                self._pause(int(r.headers.get('Retry-After', 5)),
                            L(en='zotero.org asks to slow down, trying again',
                              fr='zotero.org demande de ralentir, nouvel essai'))
                continue
            if r.status_code >= 500 and trial < ATTEMPTS - 1:
                self._pause(5 * (trial + 1), L(en=f'zotero.org answers {r.status_code}, trying again',
                                               fr=f'zotero.org répond {r.status_code}, nouvel essai'))
                continue
            if r.status_code >= 400 and r.status_code not in allowed:
                raise APIError(L(en=f'{method} {path}: response {r.status_code} from Zotero ({r.text[:200]}).',
                                 fr=f'{method} {path} : réponse {r.status_code} de Zotero ({r.text[:200]}).'))
            if 'Backoff' in r.headers:
                self._pause(int(r.headers['Backoff']),
                            L(en='zotero.org, under load, asks for a pause before the next request',
                              fr='zotero.org, chargé, demande une pause avant la requête suivante'))
            return r
        raise APIError(L(en=f'{method} {path}: Zotero does not answer, try again later.',
                         fr=f'{method} {path} : Zotero ne répond pas, réessayer plus tard.'))

    def _pause(self, seconds: int, cause: str) -> None:
        """Wait imposed by the server, always reported. A Backoff can last several minutes."""
        if seconds > 0:
            self.notify(L(en=f'{cause}, waiting {seconds} s.', fr=f'{cause}, attente de {seconds} s.'))
        self._wait(seconds)

    def _progress(self, done: int, total: int, what: str) -> None:
        if total > BATCH * BATCHES_WITHOUT_PROGRESS and (done == total or done // BATCH % 5 == 0):
            self.notify(L(en=f'{done}/{total} {what} on zotero.org', fr=f'{done}/{total} {what} sur zotero.org'))

    def file_online(self, key: str) -> bool:
        """Is the file of an attachment stored on zotero.org (D133)? A redirect to the file if it exists, 404
        otherwise. HEAD always answers 200, hence a GET that does not follow the redirect."""
        r = self._request('GET', f'{self.prefix}/items/{key}/file', allowed=(404,), follow_redirects=False)
        return 300 <= r.status_code < 400

    def items(self, keys: list[str]) -> dict[str, dict]:
        """Current data of the requested items, trash included. A key missing from the result no longer exists."""
        res = {}
        keys = list(dict.fromkeys(keys))
        for i in range(0, len(keys), BATCH):
            r = self._request('GET', f'{self.prefix}/items', params={
                'itemKey': ','.join(keys[i:i + BATCH]), 'includeTrashed': 1, 'limit': BATCH, 'format': 'json'})
            res.update({o['key']: o['data'] for o in r.json()})
            self._progress(min(i + BATCH, len(keys)), len(keys),
                           L(en='items read', fr='éléments lus'))
        return res

    def server_version(self) -> int:
        """Current version of the library on the server."""
        r = self._request('GET', f'{self.prefix}/items', params={'limit': 1, 'format': 'keys'})
        return int(r.headers.get('Last-Modified-Version', 0))

    def collections(self, keys: list[str]) -> dict[str, dict]:
        """Current data of the requested collections, trash included. A missing key does not exist (any more)."""
        res = {}
        keys = list(dict.fromkeys(keys))
        for i in range(0, len(keys), BATCH):
            r = self._request('GET', f'{self.prefix}/collections', params={
                'collectionKey': ','.join(keys[i:i + BATCH]), 'includeTrashed': 1, 'limit': BATCH, 'format': 'json'})
            res.update({o['key']: o['data'] for o in r.json()})
            self._progress(min(i + BATCH, len(keys)), len(keys),
                           L(en='collections read', fr='collections lues'))
        return res

    @staticmethod
    def _same_version(r: httpx2.Response, versions: set[int]) -> None:
        """All the responses of one read must come from the same version of the library (D187)."""
        if v := int(r.headers.get('Last-Modified-Version', 0)):
            versions.add(v)
        if len(versions) > 1:
            raise _Changing()

    def _since(self, kind: str, version: int, versions: set[int]) -> list[dict]:
        """Objects of one kind modified since `version`, trash included."""
        res, start = [], 0
        while True:
            r = self._request('GET', f'{self.prefix}/{kind}', params={
                'since': version, 'includeTrashed': 1, 'limit': 100, 'start': start, 'format': 'json'})
            self._same_version(r, versions)
            page = r.json()
            res += [o['data'] for o in page]
            start += len(page)
            if not page or start >= int(r.headers.get('Total-Results', start)):
                return res

    def changes(self, version: int) -> 'Changes':
        """What changed on the server since `version` (D171): items and other elements, collections,
        saved searches, permanent deletions, synchronized settings. If the library changes during the
        read, the read starts over, as the Zotero sync documentation requires (D187)."""
        for trial in range(ATTEMPTS):
            if trial:
                self._pause(2, L(en='the library changes on zotero.org during the read, trying again',
                             fr='la bibliothèque change sur zotero.org pendant la lecture, nouvel essai'))
            versions: set[int] = set()
            try:
                all_items = self._since('items', version, versions)
                collections = self._since('collections', version, versions)
                searches = self._since('searches', version, versions)
                r = self._request('GET', f'{self.prefix}/deleted', params={'since': version})
                self._same_version(r, versions)
                deleted = r.json() or {}
                r = self._request('GET', f'{self.prefix}/settings', params={'since': version})
                self._same_version(r, versions)
                settings = r.json() or {}
            except _Changing:
                continue
            return Changes(max(versions, default=0), all_items, collections,
                               list(deleted.get('items') or []), list(deleted.get('collections') or []),
                               {k: v.get('value') for k, v in settings.items() if isinstance(v, dict)},
                               list(deleted.get('settings') or []), searches,
                               list(deleted.get('searches') or []))
        raise APIError(L(en='The library keeps changing on zotero.org during the read (sync in progress?). '
                            'Run the command again in a moment.',
                         fr='La bibliothèque change sans cesse sur zotero.org pendant la lecture (synchronisation en '
                            'cours ?). Relancer la commande dans un instant.'))

    def settings(self, names: list[str]) -> dict[str, dict]:
        """Synchronized settings of the library (D175), as {key, version, value}. A missing setting has
        version 0 and value None, like an object that can be created."""
        res = {}
        for name in dict.fromkeys(names):
            r = self._request('GET', f'{self.prefix}/settings/{name}', allowed=(404,))
            d = r.json() if r.status_code == 200 else {}
            res[name] = {'key': name, 'version': int(d.get('version', 0)), 'value': d.get('value')}
        return res

    def read(self, keys: list[str], kind: str = 'items') -> dict[str, dict]:
        if kind == 'settings':
            return self.settings(keys)
        return self.collections(keys) if kind == 'collections' else self.items(keys)

    def children(self, key: str) -> list[dict]:
        """Attachments and notes of an item, trash included."""
        res, start = [], 0
        while True:
            r = self._request('GET', f'{self.prefix}/items/{key}/children',
                              params={'includeTrashed': 1, 'limit': 100, 'start': start, 'format': 'json'})
            page = r.json()
            res += [o['data'] for o in page]
            start += len(page)
            if not page or start >= int(r.headers.get('Total-Results', start)):
                return res

    def _pages(self, path: str) -> list[dict]:
        res, start = [], 0
        while True:
            r = self._request('GET', path, params={'limit': 100, 'start': start, 'format': 'json'})
            page = r.json()
            res += [o['data'] for o in page]
            start += len(page)
            if not page or start >= int(r.headers.get('Total-Results', start)):
                return res

    def content(self, key: str, kind: str = 'items') -> list[str]:
        """Keys of what an element contains outside the trash: children of an item or annotations of an
        attachment, items and subcollections of a collection (D182, D183)."""
        if kind == 'collections':
            objects = (self._pages(f'{self.prefix}/collections/{key}/items')
                      + self._pages(f'{self.prefix}/collections/{key}/collections'))
        else:
            objects = self.children(key)
        return [o['key'] for o in objects if not o.get('deleted')]

    def write(self, objects: list[dict], kind: str = 'items') -> Result:
        """Modifies up to 50 items or collections. Each object carries `key`, `version` and only the fields to
        change. A collection is created with its key and `version` 0 (D114)."""
        if len(objects) > BATCH:
            raise ValueError(L(en=f'{len(objects)} objects, at most {BATCH} per batch',
                               fr=f'{len(objects)} objets, {BATCH} au plus par lot'))
        if not objects:
            return Result()
        if kind == 'settings':
            return self._write_settings(objects)
        r = self._request('POST', f'{self.prefix}/{kind}', json=objects)
        d = r.json()
        res = Result()
        for i, obj in (d.get('successful') or {}).items():
            res.succeeded[objects[int(i)]['key']] = obj
        res.unchanged = {objects[int(i)]['key'] for i in (d.get('unchanged') or {})}
        for i, e in (d.get('failed') or {}).items():
            res.failures[objects[int(i)]['key']] = (int(e.get('code', 0)), e.get('message', ''))
        return res

    def _write_settings(self, objects: list[dict]) -> Result:
        """One setting per request, with its version (0 to create it). 412 if it changed since (D175)."""
        res = Result()
        for o in objects:
            if o['value'] in (None, []):  # back to the setting being absent, Zotero refuses an empty list
                # The probe of 04/10/2026 shows that zotero.org does not refuse a deletion with an outdated version, so
                # the common layer, which rereads the setting just before, is the only check. Already absent: nothing.
                r = self._request('DELETE', f'{self.prefix}/settings/{o["key"]}', allowed=(404, 412),
                                  headers={'If-Unmodified-Since-Version': str(o['version'])})
                if r.status_code == 404:
                    res.unchanged.add(o['key'])
                    continue
            else:
                r = self._request('POST', f'{self.prefix}/settings', allowed=(412,),
                                  json={o['key']: {'value': o['value'], 'version': o['version']}})
            if r.status_code == 412:
                res.failures[o['key']] = (412, L(en='setting modified since the given version',
                                                 fr='réglage modifié depuis la version donnée'))
            else:
                res.succeeded[o['key']] = {'version': int(r.headers.get('Last-Modified-Version', 0))}
        return res

    def create(self, objects: list[dict], kind: str = 'items') -> list[str]:
        """Creates items or collections (`kind`), in batches of 50. Returns their keys, in order.

        The only way to create an item, since Zotero then assigns valid keys itself."""
        keys = []
        for i in range(0, len(objects), BATCH):
            batch = objects[i:i + BATCH]
            d = self._request('POST', f'{self.prefix}/{kind}', json=batch).json()
            if d.get('failed'):
                raise APIError(L(en=f"Creation refused by Zotero: {json.dumps(d['failed'], ensure_ascii=False)[:300]}",
                                 fr=f"Création refusée par Zotero : {json.dumps(d['failed'], ensure_ascii=False)[:300]}"))
            keys += [d['success'][str(j)] for j in range(len(batch))]
        return keys


def from_config(cfg: Config) -> Client:
    env = read_env(cfg.workspace)
    if not env.get('ZOTERO_API_KEY') or not env.get('ZOTERO_USER_ID'):
        raise SystemExit(L(en='No API key in .env. Run `zc init` in this folder to save one.',
                           fr="Aucune clé API dans .env. Lancer `zc init` dans ce dossier pour l'enregistrer."))
    return Client(env['ZOTERO_USER_ID'], env['ZOTERO_API_KEY'])
