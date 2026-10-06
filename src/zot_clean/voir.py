"""Fiches montrées en entier à l'agent (`zc voir`, D127).

Pour juger un groupe de doublons, des PDF identiques ou un cas de métadonnées,
l'agent lit les champs complets des fiches et le début du texte de leurs PDF,
en local, avant de solliciter l'utilisateur. Une clé de pièce jointe désigne
sa fiche. Une fiche confidentielle (D126) n'est jamais montrée, ni le texte
des PDF si `exclure_texte_integral` est réglé. Le texte des notes n'est jamais
montré, seulement leur nombre.
"""

from pathlib import Path

from zot_clean import filtre
from zot_clean.audit import annee, conseil_telechargement, est_pdf, nom_type, norm
from zot_clean.config import Config
from zot_clean.lecture import Bibliotheque

PAGES = 2
CARACTERES = 1500
# Rôles de Zotero autres qu'auteur, montrés pour juger un chapitre (auteur du chapitre ou directeur de l'ouvrage ?).
ROLES = {'editor': 'directeur', 'seriesEditor': 'directeur de collection', 'translator': 'traducteur',
         'contributor': 'contributeur', 'bookAuthor': "auteur de l'ouvrage", 'reviewedAuthor': 'auteur recensé'}


def texte_pdf(chemin: Path, pages: int = PAGES, limite: int = CARACTERES) -> str:
    """Début du texte d'un PDF, ou une explication entre parenthèses quand il n'y en a pas."""
    import logging
    from pypdf import PdfReader
    # pypdf signale chaque irrégularité d'un PDF (polices, objets mal placés) : bruit sans intérêt pour juger.
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    try:
        lecteur = PdfReader(chemin)
        texte = ' '.join((page.extract_text() or '') for page in lecteur.pages[:pages])
    except Exception as e:  # PDF abîmé, chiffré ou hors norme : pypdf lève des erreurs très variées
        return f'(texte illisible : {type(e).__name__})'
    texte = ' '.join(''.join(c for c in texte if c.isprintable()).split())
    if not texte:
        return '(aucun texte, PDF scanné sans reconnaissance de caractères ?)'
    # Polices mal encodées : pypdf rend une suite de symboles. Un vrai texte est fait de lettres à plus de 75 %.
    if sum(c.isalpha() or c.isspace() for c in texte) < 0.75 * len(texte):
        return '(texte illisible, polices du PDF mal encodées)'
    return texte[:limite] + (' […]' if len(texte) > limite else '')


def decrire(b: Bibliotheque, cfg: Config, cles: list[str]) -> str:
    par_cle = b.par_cle()
    pieces = {p.cle: p for p in b.pieces.values()}
    masquees = filtre.cles_masquees(b, cfg)
    L, absents = [], []
    for cle in dict.fromkeys(cles):
        piece = pieces.get(cle)
        fiche = b.elements.get(piece.parent) if piece else par_cle.get(cle)
        if fiche is None:
            L += [f'## {cle}', '', 'Aucune fiche ni pièce jointe de cette clé.', '']
            continue
        if cle in masquees or fiche.cle in masquees:
            L += [f'## {fiche.cle} · {filtre.MASQUE}', '',
                  "Exclue par le filtre de confidentialité. Demander à l'utilisateur de la regarder dans Zotero.", '']
            continue
        L += _fiche(b, cfg, fiche, piece.cle if piece else '', absents, masquees)
    if absents := list(dict.fromkeys(absents)):
        # D168 : sans le fichier, ni le texte ni l'empreinte du PDF ne peuvent servir à juger.
        from zot_clean import bbt
        n = len(absents)
        L += [f"**Attention.** {n} PDF de ces fiches {'sont absents' if n > 1 else 'est absent'} du disque "
              f"({', '.join(absents)}), leur texte n'a pas pu être lu. "
              + conseil_telechargement(bbt.stockage_fichiers(cfg.dossier_zotero), 'les lire'), '']
    return '\n'.join(L)


def _fiche(b: Bibliotheque, cfg: Config, fiche, designee: str, absents: list[str] | None = None,
           masquees: frozenset[str] | set[str] = frozenset()) -> list[str]:
    L = [f'## {fiche.cle} · {nom_type(fiche.type)}', '']
    champs = dict(fiche.champs)
    if 'date' in champs:  # Zotero range « 2018-00-00 2018 » : la date triable, puis la date telle que saisie
        champs['date'] = champs['date'].split(' ', 1)[-1]
    if 'title' in champs:
        L.append(f"- title : {champs.pop('title')}")
    L += [f'- {k} : {v}' for k, v in sorted(champs.items()) if v]
    if fiche.createurs:
        L.append('- créateurs : ' + ' ; '.join(
            (f'{n}, {p}' if p else n) + (f' ({ROLES.get(r, r)})' if r and r != 'author' else '')
            for (n, p), r in zip(fiche.createurs, fiche.roles)))
    if fiche.collections:
        L.append('- collections : ' + ' ; '.join(sorted(b.chemin(c) for c in fiche.collections)))
    if fiche.tags:
        L.append('- tags : ' + ', '.join(n + (' (auto)' if t == 1 else '') for n, t in fiche.tags))
    nb_notes = sum(1 for parent in b.notes.values() if parent == fiche.id)
    if nb_notes:
        L.append(f'- notes : {nb_notes}')
    for i, p in sorted(b.pieces.items(), key=lambda x: x[1].cle):
        if p.parent != fiche.id:
            continue
        if p.cle in masquees:  # pièce jointe exclue sous une fiche publique (D188)
            L += ['', f'### Pièce jointe {p.cle} · {filtre.MASQUE}']
            continue
        nom = p.fichier.name if p.fichier else p.chemin
        absent = p.fichier is not None and not p.fichier.is_file()
        details = [x for x in (f'{b.annotations[i]} annotation(s)' if b.annotations.get(i) else '',
                               'clé demandée' if p.cle == designee else '',
                               'fichier absent du disque' if absent else '') if x]
        L += ['', f"### Pièce jointe {p.cle} · {nom}" + (f" ({', '.join(details)})" if details else '')]
        if not est_pdf(p):
            continue
        if absent and absents is not None:
            absents.append(p.cle)
        if cfg.confidentialite.exclure_texte_integral:
            L.append('(texte des PDF exclu par la configuration)')
        elif p.fichier is None or absent:
            L.append('(fichier absent du disque, texte non lu)')
        else:
            L.append(texte_pdf(p.fichier))
    return L + ['']


def decrire_tag(b: Bibliotheque, cfg: Config, nom: str, limite: int = 50) -> str:
    """Éléments qui portent un tag (`zc voir --tag`, D156), pour juger son sort : titre, auteur, année et
    collections des fiches, avec le type du tag. Un nom d'identifiant confidentiel désigne son tag."""
    from zot_clean import tags as t
    u = t.usages(b, cfg)
    nom = next((n for n in u if u[n].confidentiel and t.identifiant(n) == nom), nom)
    if nom not in u:
        proches = sorted(n for n in u if t.forme(n, cfg) == t.forme(nom, cfg) and not u[n].confidentiel)
        return f'Aucun élément ne porte le tag « {nom} ».' + (
            f" Noms de même forme : {', '.join(proches)}." if proches else '')
    x = u[nom]
    affiche = t.identifiant(nom) if x.confidentiel else nom
    masquees = filtre.cles_masquees(b, cfg)
    L = [f'# Tag « {affiche} »', '',
         f"{x.type_lisible}, porté par {len(x.elements)} élément(s), soit {len(x.fiches)} fiche(s) directement ou par "
         f"un enfant, dans {x.dispersion} thème(s) du fonds" + (f" ({', '.join(th for th, _ in x.themes.most_common())})"
                                                               if x.themes else '') + '.']
    if x.couleur:
        L.append(f'Tag coloré ({x.rang_couleur}, {x.couleur}).')
    if x.recherches:
        L.append('Cité par les recherches enregistrées ' + ', '.join(f'« {r} »' for r in x.recherches) + '.')
    L.append('')
    elements = sorted((b.elements[i] for i in x.elements),
                      key=lambda e: (e.cle in masquees, not e.est_fiche, norm(e.titre), e.cle))
    for el in elements[:limite]:
        typ = dict(el.tags).get(nom, 0)
        auto = ' (automatique)' if typ == 1 else ''
        if el.cle in masquees:
            L.append(f'- {el.cle} · {filtre.MASQUE}{auto}')
            continue
        fiche = el if el.est_fiche else b.elements.get(t.fiche_de(b, el) or -1)
        enfant = {'attachment': 'pièce jointe', 'note': 'note', 'annotation': 'annotation'}.get(el.type, el.type)
        quoi = '' if el.est_fiche else f'{enfant} de '
        cols = ' ; '.join(sorted(b.chemin(c) for c in fiche.collections)) if fiche else ''
        if fiche is None:
            L.append(f'- {el.cle} · {enfant} isolée{auto}')
        else:
            L.append(f'- {el.cle} · {quoi}{fiche.auteur or "?"}, {annee(fiche) or "s. d."}, '
                     f'{fiche.titre[:100] or "(sans titre)"}{auto}' + (f' · {cols}' if cols else ' · aucune collection'))
    if len(elements) > limite:
        L.append(f'- … et {len(elements) - limite} autre(s)')
    return '\n'.join(L) + '\n'
