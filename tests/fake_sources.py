"""Fake responses from Crossref, OpenAlex and doi.org, without network (D45)."""

import urllib.parse

import httpx2


def crossref_work(doi, title, authors=(('Özgen', 'Emre'),), year=2002, type_='journal-article', **others):
    m = {'DOI': doi, 'type': type_, 'title': [title], 'issued': {'date-parts': [[year, 8, 1]]},
         'author': [{'family': f, 'given': g} for f, g in authors]}
    m.update(others)
    return m


def unimarc_record(title, author=('Bourdieu', 'Pierre'), year='1979', publisher='Éditions de Minuit', place='Paris',
                   isbn='2-7073-0275-9', pages='670 p.', collection='Le Sens commun', language='fre',
                   translator=None, xml_prefix='mxc:'):
    """UNIMARC record in XML, in the BnF format (mxc: prefix) or the Sudoc format (no prefix)."""
    def field_name(tag, *under):
        return (f'<{xml_prefix}datafield tag="{tag}" ind1=" " ind2=" ">'
                + ''.join(f'<{xml_prefix}subfield code="{c}">{v}</{xml_prefix}subfield>' for c, v in under if v)
                + f'</{xml_prefix}datafield>')
    body = [field_name('010', ('a', isbn)), field_name('101', ('a', language)), field_name('200', ('a', title)),
             field_name('210', ('a', place), ('c', publisher), ('d', year)), field_name('215', ('a', pages)),
             field_name('225', ('a', collection)), field_name('700', ('a', author[0]), ('b', author[1]), ('4', '070'))]
    if translator:
        body.append(field_name('702', ('a', translator[0]), ('b', translator[1]), ('4', '730')))
    return f'<{xml_prefix}record>' + ''.join(body) + f'</{xml_prefix}record>'


def sru_response(records):
    return ('<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/"><srw:records>'
            + ''.join(f'<srw:record><srw:recordData>{n}</srw:recordData></srw:record>' for n in records)
            + '</srw:records></srw:searchRetrieveResponse>')


class FakeServices:
    def __init__(self):
        self.crossref: dict[str, dict] = {}  # lowercase doi -> message
        self.crossref_search: list[dict] = []  # results returned for any search
        self.openalex: dict[str, dict] = {}
        self.openalex_search: list[dict] = []
        self.handles: set[str] = set()  # DOIs known to doi.org outside Crossref and OpenAlex
        self.bnf: dict[str, str] = {}  # ISBN in digits -> record
        self.bnf_search: list[str] = []
        self.sudoc: dict[str, str] = {}
        self.openlibrary: dict[str, dict] = {}
        self.openlibrary_search: list[dict] = []
        self.requests: list[str] = []

    def add(self, **kw):
        m = crossref_work(**kw)
        self.crossref[m['DOI'].lower()] = m
        return m

    def client(self) -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(self.handle))

    def handle(self, req: httpx2.Request) -> httpx2.Response:
        host, path = req.url.host, urllib.parse.unquote(req.url.path)
        self.requests.append(f'{host}{path}')
        if host == 'api.crossref.org':
            if path == '/works':
                return httpx2.Response(200, json={'message': {'items': self.crossref_search}})
            doi = path.removeprefix('/works/').lower()
            if doi in self.crossref:
                return httpx2.Response(200, json={'message': self.crossref[doi]})
            return httpx2.Response(404)
        if host == 'api.openalex.org':
            if path == '/works':
                if any(c in req.url.params.get('search', '') for c in '?.:'):
                    return httpx2.Response(400, json={'error': 'Invalid query parameters'})
                return httpx2.Response(200, json={'results': self.openalex_search})
            doi = path.removeprefix('/works/doi:').lower()
            if doi in self.openalex:
                return httpx2.Response(200, json=self.openalex[doi])
            return httpx2.Response(404)
        if host == 'catalogue.bnf.fr':
            q = req.url.params.get('query', '')
            if q.startswith('bib.isbn adj'):
                isbn = q.split('"')[1]
                return httpx2.Response(200, text=sru_response([self.bnf[isbn]] if isbn in self.bnf else []))
            return httpx2.Response(200, text=sru_response(self.bnf_search))
        if host == 'www.sudoc.fr':
            if path.startswith('/services/isbn2ppn/'):
                isbn = path.removeprefix('/services/isbn2ppn/').split('&')[0]
                if isbn in self.sudoc:
                    return httpx2.Response(200, json={'sudoc': {'query': {'result': {'ppn': f'P{isbn}'}}}})
                return httpx2.Response(200, json={'sudoc': {'error': 'Aucune notice'}})
            return httpx2.Response(200, text=self.sudoc.get(path.strip('/').removesuffix('.xml')[1:], ''))
        if host == 'openlibrary.org':
            if path == '/search.json':
                return httpx2.Response(200, json={'docs': self.openlibrary_search})
            if path.startswith('/isbn/'):
                d = self.openlibrary.get(path.removeprefix('/isbn/').removesuffix('.json'))
                return httpx2.Response(200, json=d) if d else httpx2.Response(404)
            if path.startswith('/authors/'):
                return httpx2.Response(200, json={'name': path.removeprefix('/authors/').removesuffix('.json')})
            return httpx2.Response(404)
        if host == 'doi.org':
            doi = path.removeprefix('/api/handles/').lower()
            is_known = doi in self.handles or doi in self.crossref or doi in self.openalex
            return httpx2.Response(200 if is_known else 404, json={'responseCode': 1 if is_known else 100})
        return httpx2.Response(404)
