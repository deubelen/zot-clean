import pytest

from faux_serveur import FauxServeur
from zot_clean.ecriture import ErreurAPI


@pytest.fixture
def serveur():
    return FauxServeur()


def test_fiches_par_cle_corbeille_comprise(serveur):
    a = serveur.ajouter(title='A')
    b = serveur.ajouter(title='B', deleted=1)
    res = serveur.client().fiches([a, b, 'ABSENTE2'])
    assert set(res) == {a, b} and res[b]['deleted'] == 1


def test_fiches_par_lots_de_50(serveur):
    cles = [serveur.ajouter(title=str(i)) for i in range(120)]
    assert len(serveur.client().fiches(cles)) == 120
    assert len([r for r in serveur.requetes if r[0] == 'GET']) == 3


def test_ecriture_rend_le_sort_de_chaque_objet(serveur):
    a = serveur.ajouter(title='A')
    b = serveur.ajouter(title='B')
    c = serveur.ajouter(title='C')
    va, vb, vc = (serveur.elements[k]['version'] for k in (a, b, c))
    serveur.modifier(c, title='C modifié ailleurs')
    res = serveur.client().ecrire([{'key': a, 'version': va, 'title': 'A2'},
                                   {'key': b, 'version': vb, 'title': 'B'},
                                   {'key': c, 'version': vc, 'title': 'C2'}])
    assert set(res.reussis) == {a} and res.reussis[a]['version'] > va
    assert res.inchanges == {b}
    assert res.echecs[c][0] == 412
    assert serveur.elements[a]['title'] == 'A2' and serveur.elements[c]['title'] == 'C modifié ailleurs'


def test_plus_de_50_objets_refuse(serveur):
    with pytest.raises(ValueError):
        serveur.client().ecrire([{'key': 'X', 'version': 1}] * 51)


def test_nouveaux_essais_apres_429_et_5xx(serveur):
    a = serveur.ajouter(title='A')
    serveur.pannes = [429, 503, 500]
    assert a in serveur.client().fiches([a])


def test_abandon_apres_pannes_repetees(serveur):
    serveur.pannes = [503] * 10
    with pytest.raises(ErreurAPI):
        serveur.client().fiches(['AAAAAAAA'])


def test_erreur_4xx_sans_nouvel_essai(serveur):
    serveur.pannes = [403]
    with pytest.raises(ErreurAPI, match='403'):
        serveur.client().fiches(['AAAAAAAA'])
    assert len(serveur.requetes) == 1


def test_enfants(serveur):
    p = serveur.ajouter(title='Parent')
    serveur.ajouter('attachment', parentItem=p, title='PDF')
    serveur.ajouter('note', parentItem=p, note='n')
    serveur.ajouter('note', note='isolée')
    assert len(serveur.client().enfants(p)) == 2


def test_creation_rend_des_cles_valides(serveur):
    from zot_clean.lecture import CLE_VALIDE
    cles = serveur.client().creer([{'itemType': 'book', 'title': f'Livre {i}'} for i in range(60)])
    assert len(cles) == 60 and all(CLE_VALIDE.match(c) for c in cles)
    assert serveur.elements[cles[59]]['title'] == 'Livre 59'


def test_fichier_stocke_sur_le_serveur_ou_non(serveur):
    # D133 : redirection vers le fichier s'il est stocké, 404 sinon.
    serveur.fichiers.add('PRESENT2')
    client = serveur.client()
    assert client.fichier_en_ligne('PRESENT2') and not client.fichier_en_ligne('ABSENT22')


def test_attentes_et_progression_signalees(serveur):
    """Une attente imposée par le serveur et une longue lecture se signalent, au lieu de laisser la commande muette
    (répétition du pilote, première passe du rangement restée silencieuse plusieurs minutes)."""
    a = serveur.ajouter(title='A')
    client, messages = serveur.client(), []
    client.signaler = messages.append
    serveur.pannes = [503]
    client.fiches([a])
    assert messages == ['zotero.org répond 503, nouvel essai, attente de 5 s.']
    messages.clear()
    client.fiches([a] + [f'X{i:07d}' for i in range(250)])
    assert messages == ['250/251 éléments lus sur zotero.org', '251/251 éléments lus sur zotero.org']


def test_changements_d_une_bibliotheque_qui_change_pendant_la_lecture():
    # D187 : toutes les réponses d'un rattrapage viennent de la même version, sinon il recommence.
    from faux_serveur import FauxServeur
    serveur = FauxServeur()
    for i in range(150):
        serveur.ajouter(title=f'Fiche {i}')
    serveur.regler('tagColors', [{'name': 'lu', 'color': '#FF0000'}])
    recherche = serveur.recherche('Mes lectures', [{'condition': 'tag', 'operator': 'is', 'value': 'lu'}])
    depart = serveur.version
    serveur.retirer_reglage('tagColors')
    serveur.supprimer_recherche(recherche)
    pages = []

    def modification_concurrente():
        pages.append(1)
        if len(pages) == 1:
            serveur.ajouter(title='Ajoutée pendant la lecture')
    serveur.pendant_lecture = modification_concurrente
    ch = serveur.client().changements(0)
    assert len(ch.elements) == 151 and ch.version == serveur.version
    assert ch.reglages_supprimes == ['tagColors'] and ch.recherches_supprimees == [recherche]
    assert serveur.client().changements(depart).nombre == 3  # la fiche ajoutée et les deux suppressions

    serveur.pendant_lecture = lambda: serveur.ajouter(title='Encore une')
    with pytest.raises(ErreurAPI, match='change sans cesse'):
        serveur.client().changements(0)
