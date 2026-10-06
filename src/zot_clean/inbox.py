"""Tri des nouvelles références, gestion courante (D135).

Les références à trier sont celles de l'Inbox et celles qui n'ont aucune place
dans le fonds, qu'elles soient hors de toute collection ou arrivées directement
dans un projet. `preparer` cherche, pour
elles seules, les doublons, les identifiants, les types, les compléments et
les thèmes voisins. Les cas à juger vont dans les fichiers de suivi des étapes
2, 3 et 5 (`doublons.toml`, `metadonnees.toml`, `rangement.toml`), et un
rapport guide l'agent. `planifier` en tire un seul plan, avec les collections à
créer (thème nouveau ajouté à `plan.md`), les fusions, puis, fiche par fiche,
le changement de type, les champs, les collections et les tags. Les tags
suivent les règles acceptées de `suivi/tags.toml` (D155) : tags automatiques
et mots-clés importés retirés, variantes et états ramenés à leur forme. Les
tags manuels nouveaux hors familles sont seulement signalés.
Les étapes réutilisées gardent leurs règles (D62, D86, D116, D131, D134), le
tri ne fait que limiter leur examen à ces références.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from zot_clean import doublons, filtre, fonds as f, metadonnees as md, rangement as r, tags as tg
from zot_clean import noms
from zot_clean import cles as cles_citation
from zot_clean.audit import annee, nom_type, pluriel
from zot_clean.config import Config
from zot_clean.ecriture import Client
from zot_clean.lecture import Bibliotheque, Element, Types
from zot_clean.plans import Groupe, Operation, Plan
from zot_clean.sources import Services, norm

ETAPE = 'inbox'
CONTENEURS = ('publicationTitle', 'bookTitle', 'proceedingsTitle')

# Rang du renommage du fichier principal (D149), après le type (0), les champs (1), le rangement (2) et les tags (3).
RANG_NOM = 5


@dataclass
class ATrier:
    fiche: Element
    depuis: str  # clé de la collection de l'Inbox à quitter, vide pour une fiche hors de l'Inbox (rangée en plus)
    ou: list[str]  # chemins des collections actuelles


def _situation(a: ATrier, cfg: Config) -> str:
    """Où se trouve une référence à trier, pour le rapport : Inbox, hors de toute collection, projet ou ailleurs."""
    if a.depuis:
        return 'inbox'
    if not a.ou:
        return 'aucune'
    if any(c == p or c.startswith(p + '/') for c in a.ou for p in cfg.methode.projets):
        return 'projet'
    return 'ailleurs'


def sans_rangement(cfg: Config) -> str:
    """Pourquoi le tri ne peut pas ranger, vide s'il le peut (racine du fonds réglée, plan.md écrit)."""
    if motif := f.refus(cfg):
        return motif
    return '' if (cfg.dossier_travail / f.PLAN).is_file() else "plan.md n'existe pas encore (étape 4 du nettoyage)."


def a_trier(b: Bibliotheque, cfg: Config) -> list[ATrier]:
    """Fiches de l'Inbox, et fiches rangées aujourd'hui hors du fonds (sauf celles exclues par le filtre et celles
    laissées hors du fonds par décision, D176)."""
    return a_trier_et_laissees(b, cfg)[0]


def a_trier_et_laissees(b: Bibliotheque, cfg: Config) -> tuple[list[ATrier], list[ATrier]]:
    """Les fiches à trier, et à part celles qui le seraient sans avoir été laissées hors du fonds par décision."""
    e = r._Etat(b)
    inbox = e.racine(cfg.methode.inbox) if cfg.methode.inbox else None
    fonds = e.racine(cfg.methode.fonds) if cfg.methode.fonds and not sans_rangement(cfg) else None
    exclues = filtre.exclues(b, cfg)
    laissees = r.charger_laissees(b, cfg) if fonds is not None else set()
    res, mises_de_cote = [], []
    for el in b.fiches:
        cles = [e.cle[c] for c in el.collections]
        dans = [k for k in cles if inbox and e.sous(k, inbox)]
        hors_fonds = fonds is not None and el.id not in exclues and not any(e.sous(k, fonds) for k in cles)
        if dans or hors_fonds:
            a = ATrier(el, dans[0] if dans else '', sorted(e.chemin(k) for k in cles))
            (mises_de_cote if not dans and el.cle in laissees else res).append(a)
    return sorted(res, key=lambda a: norm(a.fiche.titre)), mises_de_cote


# --- Préparation ------------------------------------------------------------------

def _auteur(el: Element) -> str:
    """Premier auteur, nom et initiale du prénom : « Zhang » seul réunirait trop de personnes."""
    for (nom, prenom), role in zip(el.createurs, el.roles):
        if role == 'author':
            return norm(f'{nom} {prenom[:1]}')
    return norm(f'{el.createurs[0][0]} {el.createurs[0][1][:1]}') if el.createurs else ''


def _voisins(b: Bibliotheque, cfg: Config, cles: set[str]):
    """Thèmes du fonds des autres fiches, par premier auteur et par revue ou ouvrage."""
    e = r._Etat(b)
    fonds = e.racine(cfg.methode.fonds) if cfg.methode.fonds else None
    par_auteur: dict[str, Counter] = {}
    par_conteneur: dict[str, Counter] = {}
    if fonds is None:
        return par_auteur, par_conteneur
    prefixe = cfg.methode.fonds + '/'
    for el in b.fiches:
        if el.cle in cles:
            continue
        themes = [e.chemin(e.cle[c]).removeprefix(prefixe) for c in el.collections
                  if e.cle[c] != fonds and e.sous(e.cle[c], fonds)]
        if not themes:
            continue
        if a := _auteur(el):
            par_auteur.setdefault(a, Counter()).update(themes)
        if c := norm(next((el.champs[k] for k in CONTENEURS if el.champs.get(k)), '')):
            par_conteneur.setdefault(c, Counter()).update(themes)
    return par_auteur, par_conteneur


def preparer(b: Bibliotheque, cfg: Config, services: Services, client: Client, schema: Types,
             afficher=None, jour: date | None = None) -> tuple[str, list[ATrier]]:
    liste, laissees = a_trier_et_laissees(b, cfg)
    cles = {a.fiche.cle for a in liste}
    masquees = filtre.cles_masquees(b, cfg)
    groupes = [g for g in doublons.chercher(b, cfg) if g.decision != doublons.DISTINCT and set(g.cles) & cles]
    p_ty, _ = md.types(b, cfg, services, client, schema, afficher, cles=cles)
    p_id, _ = md.identifiants(b, cfg, services, client, afficher, cles=cles)
    p_co, _ = md.completer(b, cfg, services, client, afficher, cles=cles)
    cas = [c for c in md.charger_suivi(cfg) if c.cle in cles and not c.decision]
    entrees = {x.cle: x for x in r.charger(cfg)}
    par_auteur, par_conteneur = _voisins(b, cfg, cles)
    refus_fonds = sans_rangement(cfg)
    regles = _regles_tags(b, cfg)
    sans_cle = cles_citation.signaler_sans_cle(b, cfg)

    jour = jour or date.today()
    if not refus_fonds:
        r.creer_si_absent(cfg)
    situations = Counter(_situation(a, cfg) for a in liste)
    hors = [f'{situations["aucune"]} hors de toute collection', f'{situations["projet"]} dans un projet']
    if situations['ailleurs']:
        hors.append(f'{situations["ailleurs"]} dans une autre collection hors du fonds (archives, collection hors plan)')
    L = [f'# Tri de l\'Inbox, {jour:%d/%m/%Y}', '',
         f"{pluriel(len(liste), 'référence')} à trier, {situations['inbox']} dans l'Inbox et "
         f"{len(liste) - situations['inbox']} sans place dans le fonds, dont " + ', '.join(hors) + '.'
         + (f" {pluriel(len(laissees), 'autre référence laissée')} hors du fonds par décision "
            f"(`zc fonds a-ranger --laisser`), non présentée{'s' if len(laissees) > 1 else ''}." if laissees else ''),
         '']
    if groupes:
        L += [f"**Doublons.** {pluriel(len(groupes), 'groupe')} à juger dans `suivi/doublons.toml` : "
              + ', '.join(' / '.join(g.cles) for g in groupes) + '.', '']
    evidents = sum(c.classe == 'évident' for c in cas)
    corrigees = {g.id for p in (p_ty, p_id, p_co) for g in p.groupes}
    L += [f"**Métadonnées.** Corrections sûres pour {pluriel(len(corrigees), 'fiche')}. "
          f"{len(cas)} cas à juger dans `suivi/metadonnees.toml` (dont {evidents} évident(s))"
          + (' : ' + ', '.join(f'{c.cle} ({c.probleme})' for c in cas) if cas else '') + '.', '']
    if refus_fonds:
        L += [f'**Rangement.** Impossible pour l\'instant : {refus_fonds}', '']
    else:
        L += ['**Rangement.** Pour chaque référence, écrire une table `[[fiche]]` dans `suivi/rangement.toml`, comme '
              'l\'exemple de son en-tête, avec `cible` = chemin du thème dans `plan.md` (sans la racine du fonds). '
              'Pour une référence de l\'Inbox, `action = "déplacer"` et `depuis` = la clé donnée ci-dessous. Pour une '
              'référence hors de toute collection, `action = "ajouter"` sans `depuis` (« déplacer » reviendrait au '
              'même). Pour une référence d\'un projet, `action = "ajouter"` sans `depuis`, et elle reste dans son '
              'projet. Les thèmes et leurs définitions sont dans `plan.md`. Faire approuver avant d\'écrire '
              '`decision = "accepter"`. Sans thème qui convienne, proposer le plus proche ou un nouveau thème (ajouté à '
              '`plan.md` avec sa définition, puis `zc fonds valider`), la référence restant où elle est en attendant.',
              '',
              'Les thèmes voisins d\'une référence sont ceux où sont rangées d\'autres fiches du même premier auteur ou '
              'de la même revue ou du même ouvrage. « Aucun thème voisin trouvé » veut dire qu\'aucune fiche rangée '
              'dans le fonds ne partage cet auteur ni ce titre de revue ou d\'ouvrage.', '']
    if regles:
        L += ['**Tags.** Les règles acceptées de `suivi/tags.toml` s\'appliqueront au plan. Un tag signalé « hors '
              'familles, sans règle » est à soumettre à l\'utilisateur, qui le garde, le convertit en concept ou le '
              'supprime (entrée `[[tag]]` de `suivi/tags.toml`).', '']
    if sans_cle and any(not a.fiche.champs.get('citationKey', '').strip() for a in liste):
        L += ['**Clés de citation.** Une référence « sans clé de citation » n\'a pas reçu la sienne de Better BibTeX. '
              'Proposer à l\'utilisateur de la remplir dans Zotero par clic droit, Better BibTeX › Fill.', '']
    L += ['## Références', '']
    for a in liste:
        el = a.fiche
        if el.cle in masquees:
            L.append(f'- {el.cle} · {filtre.MASQUE}' + (f' · depuis = "{a.depuis}"' if a.depuis else '')
                     + (' · sans clé de citation' if sans_cle and not el.champs.get('citationKey', '').strip() else ''))
            continue
        conteneur = next((el.champs[k] for k in CONTENEURS if el.champs.get(k)), '')
        tags = ', '.join(n for n, _ in el.tags)
        ligne = (f'- {el.cle} · {el.auteur or "?"}, {annee(el) or "s. d."}, {el.titre[:100] or "(sans titre)"} · '
                 f'{nom_type(el.type)}' + (f' · dans « {conteneur[:60]} »' if conteneur else '')
                 + f" · dans {', '.join(a.ou) or 'aucune collection'}"
                 + (f' · depuis = "{a.depuis}"' if a.depuis else ' · action « ajouter », sans depuis'
                    + (', reste dans son projet' if _situation(a, cfg) == 'projet' else ''))
                 + (f' · tags {tags}' if tags else ''))
        if x := entrees.get(el.cle):
            ligne += f' · déjà dans rangement.toml : {x.action} → {x.cible} ({x.decision or "à approuver"})'
        if regles and (nouveaux := tg.a_signaler(el, regles, cfg)):
            ligne += ' · tags hors familles, sans règle : ' + ', '.join(nouveaux)
        # Clé de citation absente alors que Better BibTeX, actif, la remplit d'habitude à l'arrivée (D146).
        if sans_cle and not el.champs.get('citationKey', '').strip():
            ligne += ' · sans clé de citation'
        L.append(ligne)
        voisins = []
        for nom, index, cle in (('même auteur', par_auteur, _auteur(el)),
                                ('même revue ou ouvrage', par_conteneur, norm(conteneur))):
            if cle and cle in index:
                voisins.append(f'{nom} : ' + ', '.join(f'{t} ({n})' for t, n in index[cle].most_common(3)))
        if refus_fonds:
            continue
        L.append('  - thèmes voisins, ' + ' ; '.join(voisins) if voisins else '  - aucun thème voisin trouvé')
    return '\n'.join(L) + '\n', liste


# --- Plan -------------------------------------------------------------------------

def _regles_tags(b: Bibliotheque, cfg: Config) -> 'tg.Regles | None':
    """Règles acceptées de l'étape 6, None tant que `suivi/tags.toml` n'existe pas (D155)."""
    if not (cfg.suivi / tg.FICHIER).is_file():
        return None
    return tg.regles(tg.charger(cfg), cfg, b)


def _fusionner_champs(ops: list[Operation]) -> Operation | None:
    """Identifiants et compléments d'une même fiche en une seule opération, les identifiants l'emportant."""
    if not ops:
        return None
    avant, apres = {}, {}
    for op in reversed(ops):
        avant |= op.avant
        apres |= op.apres
    return Operation(ops[0].cle, avant, apres, 1, ' ; '.join(op.nature for op in ops if op.nature))


def planifier(b: Bibliotheque, cfg: Config, services: Services, client: Client, schema: Types,
              afficher=None) -> tuple[Plan, str]:
    liste = a_trier(b, cfg)
    cles = {a.fiche.cle for a in liste}
    masquees = filtre.cles_masquees(b, cfg)
    e = r._Etat(b)
    inbox = e.racine(cfg.methode.inbox) if cfg.methode.inbox else None
    de_l_inbox = {k for k in e.nom if inbox and e.sous(k, inbox)}

    # 1. Fusions des doublons jugés qui touchent une référence à trier. La fiche gardée quitte l'Inbox si elle
    #    garde une autre collection.
    p_d, _ = doublons.planifier(cfg, client, b)
    fusions = [g for g in p_d.groupes if any(op.cle in cles for op in g.operations)]
    for g in fusions:
        for op in g.operations:
            if 'collections' in op.apres:
                hors = [k for k in op.apres['collections'] if k not in de_l_inbox]
                if hors:
                    op.apres['collections'] = hors
                if sorted(op.apres['collections']) == sorted(op.avant.get('collections') or []):
                    del op.apres['collections'], op.avant['collections']
    fusionnees = {op.cle for g in fusions for op in g.operations}
    reste = cles - fusionnees

    # 2. Type, identifiants et compléments.
    p_ty, _ = md.types(b, cfg, services, client, schema, afficher, cles=reste)
    p_id, _ = md.identifiants(b, cfg, services, client, afficher, cles=reste)
    p_co, _ = md.completer(b, cfg, services, client, afficher, cles=reste)
    ops: dict[str, list[Operation]] = {}
    for g in p_ty.groupes:
        ops.setdefault(g.id, []).append(g.operations[0])
    champs = {}
    for p in (p_id, p_co):
        for g in p.groupes:
            champs.setdefault(g.id, []).append(g.operations[0])
    for cle, liste_ops in champs.items():
        ops.setdefault(cle, []).append(_fusionner_champs(liste_ops))

    # 2 bis. Clés de citation en double qui touchent une référence triée, départagées selon D144 dans le groupe de
    #        la référence (D146). La clé de la référence elle-même rejoint ses champs, au rang 1.
    departage, caches_cles = cles_citation.departage_inbox(b, cfg, client, reste, fusionnees)
    for cle, op in departage:
        rang1 = [o for o in ops.get(cle, []) if o.rang == 1 and o.cle == cle]
        if op.cle == cle and rang1:
            ops[cle].remove(rang1[0])
            op = _fusionner_champs([rang1[0], op])
        ops.setdefault(cle, []).append(op)

    # 3. Collections, d'après les décisions acceptées de rangement.toml (D116), et thèmes nouveaux à créer.
    creations: list[Operation] = []
    probleme = sans_rangement(cfg)
    if not probleme:
        p_r, _ = r.planifier(b, cfg, client)
        a_creer = {op.cle: op for g in p_r.groupes for op in g.operations if op.genre == 'collections' and op.creation}
        voulues = set()
        for g in p_r.groupes:
            for op in g.operations:
                if op.genre == 'items' and op.cle in reste:
                    ops.setdefault(op.cle, []).append(Operation(op.cle, op.avant, op.apres, 2, 'rangement'))
                    voulues |= set(op.apres['collections']) - set(op.avant['collections'])
        while voulues:  # une collection à créer, et ses parents à créer
            k = voulues.pop()
            if k in a_creer and a_creer[k] not in creations:
                creations.append(a_creer[k])
                if parent := a_creer[k].apres.get('parentCollection'):
                    voulues.add(parent)
        creations.reverse()

    # 4. Tags des fiches triées et de leurs enfants, d'après les règles acceptées (D155). L'« avant » est relu par l'API.
    if (regles := _regles_tags(b, cfg)):
        fiches_ids = {par.id for par in b.fiches if par.cle in reste}
        visees = {el.cle: v for el in b.elements.values() if tg.fiche_de(b, el) in fiches_ids
                  and tg.normaliser('tags', (v := tg.tags_vises(el, regles)))
                  != tg.normaliser('tags', [{'tag': n, 'type': t} for n, t in el.tags])}
        par_cle_el = b.par_cle()
        for cle, d in client.fiches(list(visees)).items():
            el = par_cle_el[cle]
            avant = list(d.get('tags') or [])
            apres = tg._viser(tg._tags_api(d), el.type == 'annotation', regles, el.id).tags
            if tg.normaliser('tags', apres) == tg.normaliser('tags', avant):
                continue
            fiche = b.elements[tg.fiche_de(b, el)].cle
            ops.setdefault(fiche, []).append(Operation(cle, {'tags': avant}, {'tags': apres}, 3, 'tags'))

    # 5. Nom du fichier principal des fiches dont le plan change les créateurs, la date, le titre ou le type, ou
    #    qu'il fusionne (D149), calculé sur les métadonnées d'après le plan.
    maitres = {next(op.cle for op in g.operations if op.rang == 1): g for g in fusions}
    renommages, remarques_noms = noms.pour_le_tri(
        b, cfg, client, [(c, o, False) for c, o in ops.items()] + [(c, g.operations, True) for c, g in maitres.items()],
        RANG_NOM)
    for cle, op in renommages.items():
        (maitres[cle].operations if cle in maitres else ops[cle]).append(op)

    groupes = []
    if creations:
        groupes.append(Groupe('collections', 'thèmes nouveaux', creations))
    for i, g in enumerate(fusions, 1):
        groupes.append(Groupe(f'fusion-{i}', g.titre, g.operations))
    titres = {g.id: g.titre for p in (p_ty, p_id, p_co) for g in p.groupes}
    par_cle = b.par_cle()
    for cle in sorted(ops, key=lambda k: norm(par_cle[k].titre) if k in par_cle else k):
        titre = (filtre.MASQUE if cle in masquees | caches_cles
                 else titres.get(cle) or (par_cle[cle].titre[:80] if cle in par_cle else ''))
        groupes.append(Groupe(cle, titre, sorted(ops[cle], key=lambda op: op.rang)))
    plan = Plan(ETAPE, client.utilisateur, groupes,
                description=f"Tri de l'Inbox, {pluriel(len(groupes), 'groupe')}.")
    # Un groupe dont la clé de citation est partagée avec une fiche confidentielle est montré sans valeurs (D126).
    rapport = _rapport(plan, liste, masquees | caches_cles, e, probleme)
    if remarques_noms:
        rapport += '\n## Noms des fichiers laissés\n\n' + '\n'.join(f'- {x}' for x in remarques_noms) + '\n'
    return plan, rapport


def _rapport(plan: Plan, liste: list[ATrier], masquees: set[str], e, probleme: str) -> str:
    fiches = {op.cle for g in plan.groupes for op in g.operations if op.genre == 'items'}
    creees = {op.cle: op for g in plan.groupes for op in g.operations if op.creation}

    def nom(k: str) -> str:
        if k in e.nom:
            return e.chemin(k)
        op = creees.get(k)
        return f"{nom(op.apres['parentCollection'])}/{op.apres['name']} (nouveau)" if op else k

    L = ['# Tri de l\'Inbox', '',
         f"{pluriel(len(fiches), 'élément')} à modifier en {pluriel(len(plan.groupes), 'groupe')}. Rien n'est "
         "remplacé dans les champs déjà remplis. Les tags suivent les règles acceptées de suivi/tags.toml.", '']
    if probleme:
        L += [f'Rangement laissé de côté : {probleme}', '']
    for g in plan.groupes:
        if g.id == 'collections':
            L += ['## Thèmes créés', ''] + [f'- {nom(op.cle)}' for op in g.operations] + ['', '## Références', '']
            continue
        if g.id.startswith('fusion-'):
            L.append(f'- fusion « {g.titre} » : ' + ', '.join(op.nature for op in g.operations if op.nature))
            continue
        morceaux = []
        for op in g.operations:
            if op.rang == 0:
                morceaux.append(f"type → {nom_type(op.apres.get('itemType', ''))}")
            elif op.rang == 3:
                av = {t['tag'] for t in op.avant['tags']}
                ap = {t['tag'] for t in op.apres['tags']}
                quoi = '' if op.cle == g.id else f' ({op.cle})'
                if g.id in masquees:
                    morceaux.append(f'tags{quoi} : {len(av - ap)} retiré(s), {len(ap - av)} posé(s)')
                else:
                    morceaux.append(f'tags{quoi} : ' + ', '.join([f'− {t}' for t in sorted(av - ap)]
                                                              + [f'+ {t}' for t in sorted(ap - av)]))
            elif op.rang == RANG_NOM:
                morceaux.append(f'fichier {op.cle} : {noms.decrire(op, g.id in masquees)}')
            elif op.rang == 1:
                quoi = '' if op.cle == g.id else f' ({op.cle})'  # clé de citation d'une autre fiche (D146)
                morceaux.append(f'champs{quoi} ' + ', '.join(op.apres) if g.id in masquees else
                                f'champs{quoi} ' + ', '.join(f'{k} = {str(v)[:50]!r}' for k, v in op.apres.items()))
            else:
                entrees = [k for k in op.apres['collections'] if k not in op.avant['collections']]
                sorties = [k for k in op.avant['collections'] if k not in op.apres['collections']]
                morceaux.append('rangement ' + ', '.join([f'quitte {nom(k)}' for k in sorties]
                                                       + [f'entre dans {nom(k)}' for k in entrees]))
        L.append(f'- {g.id} « {g.titre} » : ' + ' ; '.join(morceaux))
    rangees = {op.cle for g in plan.groupes for op in g.operations if op.rang == 2}
    rangees |= {op.cle for g in plan.groupes if g.id.startswith('fusion-') for op in g.operations}
    restent = [a for a in liste if a.depuis and a.fiche.cle not in rangees]
    if restent:
        L += ['', f"{pluriel(len(restent), 'référence')} reste(nt) dans l'Inbox, sans décision de rangement acceptée : "
              + ', '.join(a.fiche.cle for a in restent) + '.']
    sans_place = [a for a in liste if not a.depuis and a.fiche.cle not in rangees and not probleme]
    if sans_place:
        L += ['', f"{pluriel(len(sans_place), 'référence')} reste(nt) sans place dans le fonds, sans décision de "
              'rangement acceptée : ' + ', '.join(a.fiche.cle for a in sans_place) + '.']
    return '\n'.join(L) + '\n'
