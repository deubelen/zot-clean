import pytest

from fake_server import FakeServer
from zot_clean.api import APIError


@pytest.fixture
def server():
    return FakeServer()


def test_items_by_key_trash_included(server):
    a = server.add(title='A')
    b = server.add(title='B', deleted=1)
    res = server.client().items([a, b, 'ABSENTE2'])
    assert set(res) == {a, b} and res[b]['deleted'] == 1


def test_items_in_batches_of_50(server):
    keys = [server.add(title=str(i)) for i in range(120)]
    assert len(server.client().items(keys)) == 120
    assert len([r for r in server.requests if r[0] == 'GET']) == 3


def test_writing_returns_fate_of_each_object(server):
    a = server.add(title='A')
    b = server.add(title='B')
    c = server.add(title='C')
    va, vb, vc = (server.all_items[k]['version'] for k in (a, b, c))
    server.modify(c, title='C modifié ailleurs')
    res = server.client().write([{'key': a, 'version': va, 'title': 'A2'},
                                   {'key': b, 'version': vb, 'title': 'B'},
                                   {'key': c, 'version': vc, 'title': 'C2'}])
    assert set(res.succeeded) == {a} and res.succeeded[a]['version'] > va
    assert res.unchanged == {b}
    assert res.failures[c][0] == 412
    assert server.all_items[a]['title'] == 'A2' and server.all_items[c]['title'] == 'C modifié ailleurs'


def test_more_than_50_objects_rejected(server):
    with pytest.raises(ValueError):
        server.client().write([{'key': 'X', 'version': 1}] * 51)


def test_retries_after_429_and_5xx(server):
    a = server.add(title='A')
    server.outages = [429, 503, 500]
    assert a in server.client().items([a])


def test_gives_up_after_repeated_failures(server):
    server.outages = [503] * 10
    with pytest.raises(APIError):
        server.client().items(['AAAAAAAA'])


def test_4xx_error_without_retry(server):
    server.outages = [403]
    with pytest.raises(APIError, match='403'):
        server.client().items(['AAAAAAAA'])
    assert len(server.requests) == 1


def test_children(server):
    p = server.add(title='Parent')
    server.add('attachment', parentItem=p, title='PDF')
    server.add('note', parentItem=p, note='n')
    server.add('note', note='isolée')
    assert len(server.client().children(p)) == 2


def test_create_gives_valid_keys(server):
    from zot_clean.reader import VALID_KEY
    keys = server.client().create([{'itemType': 'book', 'title': f'Livre {i}'} for i in range(60)])
    assert len(keys) == 60 and all(VALID_KEY.match(c) for c in keys)
    assert server.all_items[keys[59]]['title'] == 'Livre 59'


def test_file_stored_on_server_or_not(server):
    # D133 : redirect to the file if it is stored, 404 otherwise.
    server.files.add('PRESENT2')
    client = server.client()
    assert client.file_online('PRESENT2') and not client.file_online('ABSENT22')


def test_waits_and_progress_reported(server):
    """A wait imposed by the server and a long read are reported, instead of leaving the command silent
    (pilot rehearsal, first filing pass left silent for several minutes)."""
    a = server.add(title='A')
    client, messages = server.client(), []
    client.notify = messages.append
    server.outages = [503]
    client.items([a])
    assert messages == ['zotero.org répond 503, nouvel essai, attente de 5 s.']
    messages.clear()
    client.items([a] + [f'X{i:07d}' for i in range(250)])
    assert messages == ['250/251 éléments lus sur zotero.org', '251/251 éléments lus sur zotero.org']


def test_changes_of_library_changing_during_reading():
    # D187 : all the responses of a catch-up come from the same version, otherwise it starts over.
    from fake_server import FakeServer
    server = FakeServer()
    for i in range(150):
        server.add(title=f'Fiche {i}')
    server.set_setting('tagColors', [{'name': 'lu', 'color': '#FF0000'}])
    search = server.search('Mes lectures', [{'condition': 'tag', 'operator': 'is', 'value': 'lu'}])
    start_dir = server.version
    server.drop_setting('tagColors')
    server.delete_search(search)
    pages = []

    def concurrent_change():
        pages.append(1)
        if len(pages) == 1:
            server.add(title='Ajoutée pendant la lecture')
    server.during_read = concurrent_change
    ch = server.client().changes(0)
    assert len(ch.all_items) == 151 and ch.version == server.version
    assert ch.deleted_settings == ['tagColors'] and ch.deleted_searches == [search]
    assert server.client().changes(start_dir).size == 3  # the added item and the two deletions

    server.during_read = lambda: server.add(title='Encore une')
    with pytest.raises(APIError, match='change sans cesse'):
        server.client().changes(0)


def test_waits_and_progress_reported_in_english(server):
    from zot_clean.lang import language
    a = server.add(title='A')
    client, messages = server.client(), []
    client.notify = messages.append
    server.outages = [503]
    with language('en'):
        client.items([a])
        assert messages == ['zotero.org answers 503, trying again, waiting 5 s.']
        messages.clear()
        client.items([a] + [f'X{i:07d}' for i in range(250)])
    assert messages == ['250/251 items read on zotero.org', '251/251 items read on zotero.org']
