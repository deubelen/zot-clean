"""Ligne de commande `zc`."""

import argparse
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

from zot_clean import __version__

# Messages d'argparse en français (D4). argparse les fait passer par ses fonctions `_` et `ngettext`, remplacées ici.
# Un message absent de la table (autre version de Python) reste en anglais. Clés reprises telles quelles des versions
# 3.11 à 3.14 d'argparse.
MESSAGES_ARGPARSE = {
    'usage: ': 'usage : ',
    '%(heading)s:': '%(heading)s :',
    'positional arguments': 'arguments',
    'optional arguments': 'options',
    'options': 'options',
    'show this help message and exit': 'affiche cette aide',
    "show program's version number and exit": 'affiche la version',
    ' (default: %(default)s)': ' (par défaut, %(default)s)',
    'the following arguments are required: %s': 'arguments obligatoires manquants : %s',
    'one of the arguments %s is required': "l'un des arguments %s est obligatoire",
    'unrecognized arguments: %s': 'arguments non reconnus : %s',
    'invalid choice: %(value)r (choose from %(choices)s)': 'choix invalide : %(value)r (au choix : %(choices)s)',
    'invalid choice: %(value)r, maybe you meant %(closest)r?': 'choix invalide : %(value)r, peut-être %(closest)r ?',
    'unknown parser %(parser_name)r (choices: %(choices)s)':
        'commande inconnue : %(parser_name)r (au choix : %(choices)s)',
    'invalid %(type)s value: %(value)r': 'valeur invalide (%(type)s) : %(value)r',
    '%(prog)s: error: %(message)s\n': '%(prog)s : erreur : %(message)s\n',
    'argument %(argument_name)s: %(message)s': 'argument %(argument_name)s : %(message)s',
    'expected one argument': 'une valeur attendue',
    'expected at most one argument': 'une valeur au plus attendue',
    'expected at least one argument': 'au moins une valeur attendue',
    'expected %s argument': '%s valeur attendue',
    'expected %s arguments': '%s valeurs attendues',
    'not allowed with argument %s': "incompatible avec l'argument %s",
    'ambiguous option: %(option)s could match %(matches)s': 'option ambiguë : %(option)s peut désigner %(matches)s',
    'ignored explicit argument %r': 'valeur %r non admise par cette option',
    'unexpected option string: %s': 'option inattendue : %s',
}


def _traduire_pluriel(singulier: str, pluriel: str, n: int) -> str:
    message = singulier if n == 1 else pluriel
    return MESSAGES_ARGPARSE.get(message, message)


argparse._ = lambda message: MESSAGES_ARGPARSE.get(message, message)
argparse.ngettext = _traduire_pluriel

# Commandes pas encore disponibles, avec leur jalon (D31), listées dans l'aide. `trier`, prévue pour la v0.3, est
# devenue `zc inbox` (D135) et n'y figure plus.
A_VENIR: dict[str, tuple[str, str]] = {}


_secret_refuse = False


def _lire_a_jour(cfg):
    """Bibliothèque à jour pour une commande qui ne fait que lire (D171, D174). Copie locale seule si zotero.org est
    injoignable."""
    from zot_clean import appliquer as a, ecriture, lecture
    try:
        client = ecriture.depuis_config(cfg)
    except SystemExit:  # pas de clé API : la copie locale seule
        return lecture.lire(cfg.base)
    return a.lire_a_jour(cfg, client, _progression, facultatif=True)


def _progression(message: str) -> None:
    """Ligne de progression d'une commande longue, sur la sortie d'erreur pour ne pas se mêler au résultat."""
    print(message, file=sys.stderr)


def _secret_hors_terminal(_invite: str) -> str:
    """Hors d'un terminal, aucune clé n'est demandée. Le message ne s'affiche qu'une fois par lancement."""
    global _secret_refuse
    if not _secret_refuse:
        _secret_refuse = True
        print("Pas de terminal interactif (zc init lancé par un agent ou un script ?). Les clés ne doivent pas passer "
              "par un agent. Relancer `zc init` soi-même dans un terminal pour les saisir.")
    return ''


def _demander(invite: str) -> str:
    try:
        return input(invite)
    except EOFError:
        return ''


def init(args) -> int:
    import getpass
    from zot_clean import init as i
    secret = getpass.getpass if sys.stdin.isatty() else _secret_hors_terminal
    return i.initialiser(args.dossier.resolve(), args.dossier_zotero, args.maj, _demander, secret, print)


def audit(args) -> int:
    from zot_clean import audit as a, config, lecture
    cfg = config.charger(args.dossier)
    try:
        b = lecture.lire(cfg.base)
    except (FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 2
    client = _client_du_compte(cfg, b, args.hors_ligne)
    en_ligne, motif = (_fichiers_en_ligne(cfg, b, a.absents_importes(b), client) if not args.hors_ligne
                       else (None, 'option --hors-ligne'))
    sections = a.auditer(b, cfg, empreintes=not args.sans_empreintes, en_ligne=en_ligne, motif=motif)
    from zot_clean import controle as k, filtre
    section, memoire = k.plan_du_fonds(b, cfg, filtre.cles_masquees(b, cfg))
    sections.append(section)
    jour = date.today()
    inst = k.instantane(sections, b)
    avant = k.precedent(cfg, jour)
    evolution = k.evolution(sections, inst, avant[1], avant[0]) if avant else k.sans_comparaison()
    cfg.rapports.mkdir(parents=True, exist_ok=True)
    sortie = cfg.rapports / f'audit-{jour:%Y-%m-%d}.md'
    sortie.write_text(a.rapport(sections, b, jour, evolution), encoding='utf-8')
    k.enregistrer_instantane(cfg, inst, jour)
    if memoire is not None:
        k.ecrire_memoire(cfg, memoire)
    for i, s in enumerate(sections, 1):
        print(f'{s.statut:7} {i:2}. {s.titre} : {s.resume}')
    if avant:
        changes = [l for l in evolution if l.startswith('- ')]
        print(f"\nDepuis l'audit du {avant[0]:%d/%m/%Y} : " + (f'{len(changes)} contrôle(s) avec du nouveau ou du réglé, '
              'détail en tête du rapport.' if changes else 'aucun point nouveau ni réglé.'))
    else:
        print("\nAucun audit d'un jour précédent, rien n'est comparé.")
    print(f'\nRapport complet : {sortie}')
    return 0


def _client_du_compte(cfg, b, hors_ligne: bool):
    """Client de la clé pour l'audit, None sans clé (audit de la seule copie locale, comme avant). Refus si la clé
    n'est pas celle du compte synchronisé, comme pour toute commande qui se sert de la clé. L'audit est
    la première commande d'une séance, et le refus y arrive avant un rapport complet sur lequel on préparerait un
    travail que toutes les commandes suivantes refuseraient. Les fichiers absents y seraient d'ailleurs cherchés
    dans une autre bibliothèque, et tous donnés pour perdus. `--hors-ligne` ne se sert pas de la clé, l'audit de la
    copie locale se fait, avec le refus en avertissement."""
    from zot_clean import appliquer as a, ecriture
    try:
        client = ecriture.depuis_config(cfg)
    except SystemExit:
        return None
    try:
        a.controler_compte(client.utilisateur, b.compte)
    except ecriture.Refus as e:
        if hors_ligne:
            print(f'Attention. {e}\n')
            return None
        raise ecriture.Refus(f"{e}\nEn attendant, `zc audit --hors-ligne` fait l'audit de la seule bibliothèque "
                             'de cet ordinateur, sans se servir de la clé.') from None
    return client


# Fichiers trouvés sur zotero.org, clé de la pièce jointe -> version de l'élément. Hors de `cache/*.json`, que
# `--rafraichir` vide pour les seules sources de métadonnées.
EN_LIGNE = Path('zotero') / 'fichiers_en_ligne.json'


def _fichiers_en_ligne(cfg, b, cles: list[str], client=None) -> tuple[dict[str, bool] | None, str]:
    """Fichiers absents du disque encore stockés sur zotero.org (D133), ou None et la raison. Un fichier trouvé est
    retenu avec la version de sa pièce jointe et n'est plus demandé tant qu'elle ne change pas. Un fichier introuvable
    est redemandé à chaque fois, puisqu'il peut arriver d'un autre ordinateur avant que Zotero ne reçoive la nouvelle
    version, et ces fichiers perdus sont peu nombreux."""
    from zot_clean import ecriture
    if not cles:
        return {}, ''
    versions = {p.cle: p.version for p in b.pieces.values() if p.version}  # 0 : jamais synchronisée
    fichier = cfg.cache / EN_LIGNE
    try:
        memoire = json.loads(fichier.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        memoire = {}
    # Seules restent les pièces jointes encore là et inchangées.
    memoire = {k: v for k, v in memoire.items() if v and versions.get(k) == v} if isinstance(memoire, dict) else {}
    res = {cle: True for cle in cles if cle in memoire}
    a_chercher = [cle for cle in cles if cle not in res]

    def retenir():
        try:
            fichier.parent.mkdir(parents=True, exist_ok=True)
            fichier.write_text(json.dumps(memoire, sort_keys=True), encoding='utf-8')
        except OSError:
            pass  # sans mémoire, le prochain audit redemande ces fichiers

    if not a_chercher:
        retenir()
        return res, ''
    try:
        client = client or ecriture.depuis_config(cfg)
    except SystemExit:
        return None, 'pas de clé API'
    try:
        for i, cle in enumerate(a_chercher, 1):
            res[cle] = client.fichier_en_ligne(cle)
            if res[cle] and versions.get(cle):
                memoire[cle] = versions[cle]
            if i % 50 == 0 or i == len(a_chercher):
                print(f'{i}/{len(a_chercher)} fichiers absents cherchés sur zotero.org', file=sys.stderr)
                retenir()
    except ecriture.ErreurAPI:
        retenir()
        return None, 'zotero.org injoignable'
    return res, ''


def _inbox(args, preparer: bool) -> int:
    from zot_clean import appliquer as a, config, ecriture, inbox as i, lecture, metadonnees as m, plans, sources
    from zot_clean.ecriture import ErreurAPI, Refus
    cfg = config.charger(args.dossier)
    try:
        if avert := a.controler_synchronisation(cfg):
            print(f'Attention. {avert}')
        client = ecriture.depuis_config(cfg)
        b = lecture.lire(cfg.base) if preparer else a.lire_a_jour(cfg, client, _progression)
        a.controler_compte(client.utilisateur, b.compte)  # déjà fait par `lire_a_jour`, pas par la seule lecture
        services = sources.depuis_config(cfg)
        schema = lecture.lire_types(cfg.base)
        if preparer:
            rapport, liste = i.preparer(b, cfg, services, client, schema, m.afficher_progression)
        else:
            plan, rapport = i.planifier(b, cfg, services, client, schema, m.afficher_progression)
        for avert in services.avertissements():
            print(f'Attention. {avert}')
    except (Refus, ErreurAPI, FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 1
    if preparer:
        cfg.rapports.mkdir(parents=True, exist_ok=True)
        sortie = cfg.rapports / f'inbox-{date.today():%Y-%m-%d}.md'
        sortie.write_text(rapport, encoding='utf-8')
        print(f'{len(liste)} référence(s) à trier.\nRapport : {sortie}')
        print('Juger les cas des fichiers de suivi et écrire le rangement, puis `zc inbox planifier`.')
        return 0
    if not plan.groupes:
        print('Rien à faire : aucune décision acceptée, aucune correction sûre pour les références à trier.')
        return 0
    chemin = plans.ecrire(plan, cfg.plans, rapport)
    print(f'{len(plan.groupes)} groupe(s), {plan.nb_operations} opération(s).')
    print(f"Plan : {chemin}\nRapport : {chemin.with_suffix('.md')}")
    if a._petit_plan_de_gestion(plan, cfg):  # D138
        print(f'Plan de tri de moins de {cfg.ecriture.petit_plan_de_gestion} fiches, il s\'applique d\'un coup, sans '
              f'essai ni sauvegarde récente. Relire le rapport, puis `zc appliquer {chemin} --tout`.')
    else:
        print(f'Relire le rapport, puis `zc appliquer {chemin} --essai`.')
    return 0


def inbox_preparer(args) -> int:
    return _inbox(args, True)


def inbox_planifier(args) -> int:
    return _inbox(args, False)


def sauvegarder(args) -> int:
    from zot_clean import config, sauvegarde
    from zot_clean.ecriture import Refus
    cfg = config.charger(args.dossier)
    try:
        info = sauvegarde.sauvegarder(cfg)
    except Refus as e:
        print(e, file=sys.stderr)
        return 1
    methode = 'clone du dossier Zotero' if info.methode == 'clone' else 'copie de la base seule'
    print(f'Sauvegarde faite ({methode}, {info.taille / 1e6:.0f} Mo) : {info.dossier}')
    return 0


def _statut_plan(plan, chemin, cfg) -> None:
    from zot_clean import appliquer as a, journal
    faits = journal.groupes_faits(cfg.journal, plan.empreinte)
    print(f'Plan {chemin.name} ({plan.etape}) : {len(plan.groupes)} groupe(s), {plan.nb_operations} opération(s).')
    if plan.description:
        print(plan.description)
    print(f"Rapport lisible : {chemin.with_suffix('.md')}")
    if len(faits) == len(plan.groupes):
        print('Plan entièrement appliqué.')
    elif faits:
        print(f'{len(faits)} groupe(s) déjà appliqué(s). Suite : `zc appliquer {chemin} --tout`.')
    elif a._petit_plan_de_gestion(plan, cfg):
        print(f'Rien d\'appliqué. Petit plan de tri, il s\'applique d\'un coup, sans essai, avec '
              f'`zc appliquer {chemin} --tout`, puis vérifier avec `zc voir`.')
    else:
        print(f'Rien d\'appliqué. Étape suivante : `zc appliquer {chemin} --essai` '
              f'({min(cfg.ecriture.essai, len(plan.groupes))} groupe(s)), puis vérifier avec `zc voir`.')


def appliquer(args) -> int:
    from zot_clean import appliquer as a, config, ecriture, plans
    from zot_clean.ecriture import ErreurAPI, Refus
    cfg = config.charger(args.dossier)
    chemin = args.plan.resolve()
    plan = plans.charger(chemin)
    if recents := plans.plus_recents(chemin, plan):
        print(f'Attention. Un plan plus récent de la même étape existe ({recents[-1]}). Celui-ci a sans doute été '
              "remplacé. Appliquer le plus récent, sauf raison de garder celui-ci.")
    if not (args.essai or args.tout):
        _statut_plan(plan, chemin, cfg)
        return 0
    from zot_clean import bbt, cles
    if cfg.methode.cles_citation and (etat := bbt.detecter(cfg.dossier_zotero)).present and etat.regenere:
        print(f'Attention. {cles.REGENERE}')  # chaque fiche écrite changerait de clé (D146)
    try:
        bilan = a.appliquer(plan, chemin, ecriture.depuis_config(cfg), cfg, a.ESSAI if args.essai else a.TOUT)
    except (Refus, ErreurAPI) as e:
        print(e, file=sys.stderr)
        return 1
    for avert in bilan.avertissements:
        print(f'Attention. {avert}')
    if bilan.journal is None and bilan.restants:  # D179
        print(f"L'essai de ce plan est déjà fait, il reste {bilan.restants} groupe(s). Vérifier l'essai avec "
              f"`zc voir`, puis `zc appliquer {chemin} --tout`.")
        return 0
    if bilan.journal is None:
        print('Rien à appliquer, tous les groupes de ce plan sont déjà faits.')
        return 0
    print(f'{len(bilan.faits)} groupe(s) appliqué(s), {bilan.elements_ecrits} élément(s) modifié(s).')
    arretes = {g: d for g, d in (bilan.conflits | bilan.erreurs).items() if g in bilan.arretes}
    for titre, d in (('Appliqués en partie', bilan.partiels),
                     ('Arrêtés après une partie des écritures, à vérifier', arretes),
                     ('Conflits, laissés intacts', {g: d for g, d in bilan.conflits.items() if g not in arretes}),
                     ('Erreurs, laissées intactes', {g: d for g, d in bilan.erreurs.items() if g not in arretes})):
        if d:
            print(f'{titre} :')
            for g, detail in d.items():
                print(f'  groupe {g} : {detail}')
    print(f'Journal : {bilan.journal}')
    touches = [op.cle for g in plan.groupes if g.id in bilan.faits or g.id in bilan.partiels
               for op in g.operations if op.genre == 'items']
    touches += [c for g in plan.groupes if g.id in bilan.arretes for op in g.operations
                if op.genre == 'items' and (c := op.cle) in bilan.arretes[g.id]]
    if touches:  # ce que l'essai a touché, pour le vérifier (D174)
        touches = list(dict.fromkeys(touches))
        print(f"Vérifier : zc voir {' '.join(touches[:20])}" + (f' (et {len(touches) - 20} autres)' if len(touches) > 20 else ''))
    if bilan.restants:
        suite = '--tout' if args.essai else '--tout (reprend là où il s\'est arrêté)'
        print(f'{bilan.restants} groupe(s) restant(s). Vérifier l\'essai avec `zc voir`, puis `zc appliquer {chemin} {suite}`.')
    elif args.essai and not (bilan.conflits or bilan.erreurs or bilan.partiels):
        print("Le plan est petit, l'essai l'a appliqué en entier : `--tout` n'aura rien à faire. Vérifier avec `zc voir`.")
    return 1 if bilan.conflits or bilan.erreurs else 0


def annuler(args) -> int:
    from zot_clean import annulation, appliquer as a, config, ecriture, filtre, lecture, plans
    from zot_clean.ecriture import ErreurAPI, Refus
    cfg = config.charger(args.dossier)
    journaux = annulation.journaux_vises(args.cible.resolve(), cfg)
    client = ecriture.depuis_config(cfg)
    try:
        b = lecture.lire(cfg.base)
        masquees = filtre.cles_masquees(b, cfg)
    except (FileNotFoundError, lecture.SchemaInconnu):
        b, masquees = None, None  # base illisible : toutes les fiches masquées dans le rapport (D126)
    try:
        if b is not None:  # base illisible : `zc appliquer`, qui la relit, refusera s'il le faut
            a.controler_compte(client.utilisateur, b.compte)
        plan, rapport = annulation.planifier(journaux, client, masquees)
    except (ErreurAPI, Refus) as e:
        print(e, file=sys.stderr)
        return 1
    if not plan.groupes:
        print("Rien d'annulable (aucun élément écrit, ou éléments disparus).")
        print(rapport)
        return 1
    chemin = plans.ecrire(plan, cfg.plans, rapport)
    print(f"Plan d'annulation : {chemin}\nRapport : {chemin.with_suffix('.md')}")
    print(f'Relire le rapport, puis `zc appliquer {chemin} --essai`.')
    return 0


def doublons_chercher(args) -> int:
    from zot_clean import config, doublons as d, lecture
    cfg = config.charger(args.dossier)
    try:
        b = _lire_a_jour(cfg)
    except (FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 2
    entrees = d.chercher(b, cfg)
    surs = sum(1 for e in entrees if e.classe == d.SUR and not e.decision)
    a_juger = sum(1 for e in entrees if e.classe == d.A_JUGER and not e.decision)
    fusion = sum(1 for e in entrees if e.decision == d.FUSIONNER)
    distincts = sum(1 for e in entrees if e.decision == d.DISTINCT)
    print(f'{surs} groupe(s) sûr(s) et {a_juger} à juger sans décision, {fusion} à fusionner, '
          f'{distincts} jugé(s) distinct(s).')
    print(f'Groupes à lire dans {cfg.suivi / d.FICHIER}, décisions à écrire avec `zc doublons accepter` '
          f"{'(--surs pour tous les groupes sûrs) ' if surs else ''}et `zc doublons refuser`, puis "
          '`zc doublons planifier`.')
    return 0


def doublons_planifier(args) -> int:
    from zot_clean import appliquer as a, config, doublons as d, ecriture, lecture, plans
    from zot_clean.ecriture import ErreurAPI, Refus
    cfg = config.charger(args.dossier)
    try:
        if avert := a.controler_synchronisation(cfg):
            print(f'Attention. {avert}')
        b = a.lire_a_jour(cfg, ecriture.depuis_config(cfg), _progression)
        plan, rapport = d.planifier(cfg, ecriture.depuis_config(cfg), b)
    except (Refus, ErreurAPI, FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 1
    if not plan.groupes:
        print('Aucun groupe à fusionner. Décider les groupes avec `zc doublons accepter` (--surs pour tous les '
              'groupes sûrs).')
        return 0
    chemin = plans.ecrire(plan, cfg.plans, rapport)
    print(f'{len(plan.groupes)} groupe(s) à fusionner, {plan.nb_operations} opération(s).')
    if avert := d.avertissement(b, cfg, plan):  # fichiers pas encore téléchargés (D168)
        print(f'Attention. {avert}')
    print(f"Plan : {chemin}\nRapport : {chemin.with_suffix('.md')}")
    print(f'Relire le rapport, puis `zc appliquer {chemin} --essai`.')
    return 0


def doublons_decider(args) -> int:
    """`zc doublons accepter` (fusionner) et `zc doublons refuser` (distinct), D177."""
    from zot_clean import config, doublons as d
    cfg = config.charger(args.dossier)
    refuser = args.action_suivi == 'refuser'
    cles = [k.upper() for k in args.cles]
    surs, conserver = getattr(args, 'surs', False), [k.upper() for k in getattr(args, 'conserver', [])]
    if not (cles or surs or conserver):
        raise SystemExit('Donner la clé d\'une fiche de chaque groupe' + ('.' if refuser else ', ou --surs.'))
    entrees = d.charger_suivi(cfg)
    if refuser:
        fusion, distincts = d.decider(entrees, distinct=cles, raison=args.raison or '')
    else:
        fusion, distincts = d.decider(entrees, surs, cles, conserver=conserver,
                                      sauf=[k.upper() for k in args.sauf])
    d.ecrire_suivi(cfg, entrees, _lire_a_jour(cfg))
    print(f'{fusion} groupe(s) à fusionner, {distincts} jugé(s) distinct(s), dans {cfg.suivi / d.FICHIER}. Lancer '
          '`zc doublons planifier` pour obtenir le plan.')
    return 0


def pieces_chercher(args) -> int:
    from zot_clean import config, lecture, pieces as p
    cfg = config.charger(args.dossier)
    try:
        b = _lire_a_jour(cfg)
    except (FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 2
    entrees = p.chercher(b, cfg)
    a_juger = sum(1 for e in entrees if not e.decision)
    print(f'{len(entrees)} PDF présent(s) en plusieurs copies, dont {a_juger} sans décision.')
    if avert := p.avertissement(b, cfg, entrees):  # fichiers absents (D168), doublons révélés par un PDF
        print(f'Attention. {avert}')
    print(f'Groupes à lire dans {cfg.suivi / p.FICHIER}, décisions à écrire avec `zc pieces accepter` et '
          '`zc pieces refuser`, puis `zc pieces planifier`.')
    return 0


def pieces_decider(args) -> int:
    """`zc pieces accepter` (appliquer) et `zc pieces refuser` (garder), D177."""
    from zot_clean import config, pieces as p
    cfg = config.charger(args.dossier)
    entrees = p.charger(cfg)
    b = _lire_a_jour(cfg)
    if args.action_suivi == 'refuser':
        appliques, gardes = p.decider(entrees, b, garder=[k.upper() for k in args.copies], raison=args.raison or '')
    else:
        rattacher = {}
        for texte in args.rattacher:
            copie, _, fiche = texte.partition('=')
            if not copie.strip() or not fiche.strip():
                raise SystemExit(f'« {texte} » : écrire COPIE=FICHE (clé de la copie, clé de la bonne fiche).')
            rattacher[copie.strip().upper()] = fiche.strip().upper()
        if not args.corbeille and not rattacher:
            raise SystemExit('Donner les copies à mettre à la corbeille (--corbeille) ou à rattacher (--rattacher).')
        appliques, gardes = p.decider(entrees, b, [k.upper() for k in args.corbeille], rattacher,
                                      raison=args.raison or '')
    p.ecrire(cfg, entrees, b)
    print(f'{appliques} groupe(s) à appliquer, {gardes} gardé(s), dans {cfg.suivi / p.FICHIER}. Lancer '
          '`zc pieces planifier` pour obtenir le plan.')
    return 0


def pieces_planifier(args) -> int:
    from zot_clean import appliquer as a, config, ecriture, lecture, pieces as p, plans
    from zot_clean.ecriture import ErreurAPI, Refus
    cfg = config.charger(args.dossier)
    try:
        if avert := a.controler_synchronisation(cfg):
            print(f'Attention. {avert}')
        b = a.lire_a_jour(cfg, ecriture.depuis_config(cfg), _progression)
        plan, rapport = p.planifier(cfg, ecriture.depuis_config(cfg), b)
    except (Refus, ErreurAPI, FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 1
    if not plan.groupes:
        print('Rien à faire. Décider les groupes avec `zc pieces accepter` (--corbeille, --rattacher).')
        return 0
    chemin = plans.ecrire(plan, cfg.plans, rapport)
    print(f'{len(plan.groupes)} groupe(s), {plan.nb_operations} opération(s).')
    print(f"Plan : {chemin}\nRapport : {chemin.with_suffix('.md')}")
    print(f'Relire le rapport, puis `zc appliquer {chemin} --essai`.')
    return 0


def _metadonnees(args, sous_etape: str) -> int:
    from zot_clean import appliquer as a, config, ecriture, lecture, metadonnees as m, plans, sources
    from zot_clean.ecriture import ErreurAPI, Refus
    cfg = config.charger(args.dossier)
    if not cfg.sources.contact and sous_etape == 'identifiants':
        print('Attention. Aucune adresse de contact dans config.toml ([sources] contact). Crossref et OpenAlex '
              "répondent plus lentement aux requêtes anonymes. Pour les accélérer, y écrire l'adresse électronique de "
              "l'utilisateur, qui n'est transmise qu'à ces deux services. C'est facultatif, la commande continue.")
    try:
        if avert := a.controler_synchronisation(cfg):
            print(f'Attention. {avert}')
        b = a.lire_a_jour(cfg, ecriture.depuis_config(cfg), _progression)
        services = sources.depuis_config(cfg, args.rafraichir)
        client = ecriture.depuis_config(cfg)
        if sous_etape == m.TYPES:
            plan, rapport = m.types(b, cfg, services, client, lecture.lire_types(cfg.base), m.afficher_progression)
        else:
            fonction = m.identifiants if sous_etape == m.IDENTIFIANTS else m.completer
            plan, rapport = fonction(b, cfg, services, client, m.afficher_progression)
        for avert in services.avertissements():
            print(f'Attention. {avert}')
    except (Refus, ErreurAPI, FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 1
    a_juger = sum(1 for c in m.charger_suivi(cfg) if c.sous_etape == sous_etape and not c.decision)
    if a_juger:
        print(f'{a_juger} cas à juger dans {cfg.suivi / m.FICHIER}, à décider avec `zc metadonnees accepter` et '
              '`zc metadonnees refuser`.')
    if not plan.groupes:
        print('Aucune fiche à modifier pour le moment.')
        return 0
    chemin = plans.ecrire(plan, cfg.plans, rapport)
    print(f'{len(plan.groupes)} fiche(s) à modifier.\nPlan : {chemin}\nRapport : {chemin.with_suffix(".md")}')
    print(f'Relire le rapport, puis `zc appliquer {chemin} --essai`.')
    return 0


def metadonnees_identifiants(args) -> int:
    return _metadonnees(args, 'identifiants')


def metadonnees_types(args) -> int:
    return _metadonnees(args, 'types')


def metadonnees_completer(args) -> int:
    return _metadonnees(args, 'completer')



def _decision(texte: str) -> tuple[str, int | None]:
    cle, _, choix = texte.partition('=')
    if choix and not choix.isdigit():
        raise SystemExit(f'« {texte} » : écrire la clé seule, ou CLÉ=numéro de la proposition.')
    cle, _, probleme = cle.strip().partition(':')
    return cle.upper() + (f':{probleme}' if probleme else ''), int(choix) if choix else None


def metadonnees_decider(args) -> int:
    from zot_clean import config, metadonnees as m
    cfg = config.charger(args.dossier)
    cas = m.charger_suivi(cfg)
    refuser = args.action_suivi == 'refuser'
    if not refuser and not args.cles and not args.evidents:
        raise SystemExit('Donner des clés de fiches (CLÉ ou CLÉ=numéro), ou --evidents.')
    decisions = [_decision(t) for t in args.cles]
    if refuser:
        acceptes, refuses = m.decider(cas, refuser=[k for k, _ in decisions])
    else:
        acceptes, refuses = m.decider(cas, args.evidents, dict(decisions), sauf={k.upper() for k in args.sauf})
    m.ecrire_suivi(cfg, cas, _lire_a_jour(cfg))
    print(f'{acceptes} cas accepté(s), {refuses} refusé(s), dans {cfg.suivi / m.FICHIER}. Relancer la sous-étape '
          'pour obtenir le plan.')
    return 0

def fonds_inventaire(args) -> int:
    from zot_clean import config, fonds as f, lecture
    cfg = config.charger(args.dossier)
    if motif := f.refus(cfg):
        print(motif, file=sys.stderr)
        return 1
    try:
        b = lecture.lire(cfg.base)
    except (FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 2
    f.suivre_racines(cfg)
    rapport, suivi, nouvelles, disparues = f.inventaire(b, cfg)
    f.ecrire_suivi(cfg, suivi)
    cfg.rapports.mkdir(parents=True, exist_ok=True)
    sortie = cfg.rapports / f'fonds-inventaire-{date.today():%Y-%m-%d}.md'
    sortie.write_text(rapport, encoding='utf-8')
    sans_sort = sum(1 for c in suivi.collections if not c.sort)
    print(f'{len(suivi.collections)} ancienne(s) collection(s), dont {sans_sort} sans sort.')
    if disparues:
        print(f'{len(disparues)} collection(s) disparue(s) depuis le dernier inventaire, retirée(s) de '
              f'suivi/{f.FICHIER} : ' + ', '.join(c.chemin for c in disparues) + '.')
    print(f'Inventaire : {sortie}\nCorrespondance à remplir : {cfg.suivi / f.FICHIER}')
    print(f'Plan à écrire dans {cfg.dossier_travail / f.PLAN}, puis `zc fonds valider`.')
    return 0


def fonds_valider(args) -> int:
    from zot_clean import config, fonds as f
    cfg = config.charger(args.dossier)
    if motif := f.refus(cfg):
        print(motif, file=sys.stderr)
        return 1
    if n := f.suivre_racines(cfg):
        print(f'Nouveaux noms des racines reportés dans {cfg.suivi / f.FICHIER} ({n} collection(s)).')
    k = f.controler(cfg)
    for e in k.erreurs:
        print(f'Erreur. {e}')
    for a in k.avertissements:
        print(f'Attention. {a}')
    if k.changements:
        print('Changements depuis la dernière validation :')
        for c in k.changements:
            print(f'  {c}')
    if k.erreurs:
        print(f'{len(k.erreurs)} erreur(s) à corriger avant de valider le plan.')
        return 1
    if k.deja_valide:
        print('Plan valide, et déjà validé tel quel.')
        return 0
    if not args.enregistrer:
        print("Plan sans erreur. Une fois que l'utilisateur l'a approuvé, `zc fonds valider --enregistrer`.")
        return 0
    f.enregistrer(cfg, k)
    print(f'Plan validé, empreinte enregistrée dans {cfg.suivi / f.VALIDATION}.')
    return 0


def fonds_suivre(args) -> int:
    from zot_clean import config, controle as k, fonds as f, lecture
    cfg = config.charger(args.dossier)
    if motif := f.refus(cfg):
        print(motif, file=sys.stderr)
        return 1
    try:
        b = lecture.lire(cfg.base)
    except (FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 2
    s = k.suivre(b, cfg)
    if s is None:
        print(f"Rien à suivre, {f.PLAN} ou la racine « {cfg.methode.fonds} » manque.", file=sys.stderr)
        return 1
    for c in s.ignores:
        print(f'Laissé de côté (au-delà de {cfg.methode.profondeur_max} niveaux, ou parent introuvable) : {c}')
    if not s.lignes:
        print(f'{f.PLAN} suit déjà Zotero, aucun thème créé, renommé, déplacé ou supprimé à la main.')
        return 0
    print(f'Changements faits dans Zotero, à reporter dans {f.PLAN} :')
    for l in s.lignes:
        print(f'  {l}')
    if not args.enregistrer:
        print("Une fois que l'utilisateur les a approuvés, `zc fonds suivre --enregistrer`.")
        return 0
    for l in k.reporter(b, cfg, s):
        print(f'Retiré : {l}')
    controle = f.controler(cfg)
    for e in controle.erreurs:
        print(f'Erreur. {e}')
    if controle.erreurs:
        print(f'{f.PLAN} mis à jour, mais la validation a échoué. Corriger, puis `zc fonds valider --enregistrer`.')
        return 1
    f.enregistrer(cfg, controle)
    vu = k.examiner(b, cfg)
    if vu:
        k.ecrire_memoire(cfg, vu[2].memoire)
    print(f'{f.PLAN} et les fichiers de suivi mis à jour, plan validé.')
    if s.ajoutes:
        print(f'Définitions à écrire dans {f.PLAN} : ' + ', '.join(s.ajoutes) + '. Puis `zc fonds valider --enregistrer`.')
    return 0


def fonds_titres(args) -> int:
    from zot_clean import config, controle as k, fonds as f, lecture
    cfg = config.charger(args.dossier)
    if motif := f.refus(cfg):
        print(motif, file=sys.stderr)
        return 1
    try:
        b = lecture.lire(cfg.base)
    except (FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 2
    try:
        rapport, n = k.titres(b, cfg, args.chemin)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        return 1
    cfg.rapports.mkdir(parents=True, exist_ok=True)
    nom = re.sub(r'[^\w-]+', '-', args.chemin.lower()).strip('-')
    sortie = cfg.rapports / f'titres-{nom}-{date.today():%Y-%m-%d}.md'
    sortie.write_text(rapport, encoding='utf-8')
    print(f'{n} référence(s) dans « {args.chemin} » et ses sous-thèmes : {sortie}')
    return 0


def fonds_a_ranger(args) -> int:
    from zot_clean import config, fonds as f, lecture, rangement as r
    cfg = config.charger(args.dossier)
    if motif := f.refus(cfg):
        print(motif, file=sys.stderr)
        return 1
    try:
        b = lecture.lire(cfg.base)
    except (FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 2
    if args.resume:
        print(r.resume(b, cfg, args.resume))
        return 0
    if args.examinees:
        for chemin, n in r.marquer_examinees(b, cfg, args.examinees).items():
            print(f'{chemin} : {n} fiche(s) laissée(s) en place, notées dans {cfg.suivi / r.EXAMINEES}.')
    if args.laisser:
        cles = r.laisser(b, cfg, args.laisser)
        print(f'{len(cles)} fiche(s) laissée(s) hors du fonds par décision, notées dans {cfg.suivi / r.LAISSEES}. '
              'Elles reviendront si leurs collections changent.')
    nouveau = not (cfg.suivi / r.FICHIER).is_file()
    rapport, paquets, ajouts = r.a_ranger(b, cfg)
    cfg.rapports.mkdir(parents=True, exist_ok=True)
    sortie = cfg.rapports / f'fonds-a-ranger-{date.today():%Y-%m-%d}.md'
    sortie.write_text(rapport, encoding='utf-8')
    print(f'{sum(len(p.fiches) for p in paquets)} fiche(s) à juger en {len(paquets)} paquet(s).')
    if ajouts:
        print(f'{ajouts} proposition(s) tirée(s) des tags ajoutée(s) à {cfg.suivi / r.FICHIER}.')
    print(f'Fiches : {sortie}\nDécisions à écrire dans {cfg.suivi / r.FICHIER}'
          + (', créé avec son en-tête et un exemple' if nouveau else '') + ', puis `zc fonds planifier`.')
    return 0


def fonds_planifier(args) -> int:
    from zot_clean import appliquer as a, config, ecriture, fonds as f, lecture, plans, rangement as r
    from zot_clean.ecriture import ErreurAPI, Refus
    cfg = config.charger(args.dossier)
    if motif := f.refus(cfg):
        print(motif, file=sys.stderr)
        return 1
    try:
        if avert := a.controler_synchronisation(cfg):
            print(f'Attention. {avert}')
        client = ecriture.depuis_config(cfg)
        _progression('Lecture de la copie locale de Zotero et de la version du serveur.')
        b = a.lire_a_jour(cfg, client, _progression)
        plan, rapport = r.planifier(b, cfg, client, args.racines, _progression)
    except (Refus, ErreurAPI, FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 1
    if not plan.groupes:
        print('Rien à ranger : la bibliothèque est dans l\'état visé par le plan et par les décisions acceptées.')
        return 0
    chemin = plans.ecrire(plan, cfg.plans, rapport)
    print(f'{len(plan.groupes)} groupe(s), {plan.nb_operations} opération(s).')
    print(f"Plan : {chemin}\nRapport : {chemin.with_suffix('.md')}")
    print(f'Relire le rapport, puis `zc appliquer {chemin} --essai`.')
    if args.racines:
        print('Après l\'application complète, reporter les nouveaux noms des racines dans config.toml et plan.md.')
    return 0


def tags_inventaire(args) -> int:
    from zot_clean import config, lecture, tags as t
    cfg = config.charger(args.dossier)
    try:
        b = _lire_a_jour(cfg)
    except (FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 2
    rapport, suivi = t.inventaire(b, cfg)
    t.ecrire(cfg, suivi, b)
    cfg.rapports.mkdir(parents=True, exist_ok=True)
    sortie = cfg.rapports / f'tags-inventaire-{date.today():%Y-%m-%d}.md'
    sortie.write_text(rapport, encoding='utf-8')
    attente = [e for e in suivi.tags if not e.decision]
    groupes = [g for g in suivi.variantes if not g.decision]
    print(suivi.resume_automatiques + (f' Décision : {suivi.automatiques}.' if suivi.automatiques
                                       else ' Règle à approuver.'))
    if suivi.resume_importes:
        print(suivi.resume_importes)
    print(f'{len(attente)} tag(s) à juger (dont {sum(e.classe == t.EVIDENT for e in attente)} évident(s)), '
          f'{len(groupes)} groupe(s) de variantes (dont {sum(g.classe == t.EVIDENT for g in groupes)} évident(s)).')
    if suivi.a_ranger:
        print(f'{len(suivi.a_ranger)} proposition(s) de rangement ajoutée(s) à {cfg.suivi / "rangement.toml"}.')
    print(f'Inventaire : {sortie}\nRègles à juger : {cfg.suivi / t.FICHIER}, à décider avec `zc tags accepter` et '
          '`zc tags refuser`, puis `zc tags planifier`.')
    return 0


def _suivi_tags(args):
    from zot_clean import config, lecture, tags as t
    cfg = config.charger(args.dossier)
    if not (cfg.suivi / t.FICHIER).is_file():
        raise SystemExit(f'Pas encore de {cfg.suivi / t.FICHIER}. Lancer d\'abord `zc tags inventaire`.')
    return cfg, t.charger(cfg), lecture


def tags_decider(args) -> int:
    """`zc tags accepter` et `zc tags refuser` (D177)."""
    from zot_clean import tags as t
    cfg, suivi, lecture = _suivi_tags(args)
    refuser = args.action_suivi == 'refuser'
    evidents = getattr(args, 'evidents', False)
    regles = [r for r, oui in (('automatiques', args.regle_automatiques), ('importes', args.regle_importes)) if oui]
    if not (args.noms or args.variantes or regles or evidents):
        raise SystemExit('Donner des noms de tags, des groupes (--variantes), une règle globale (--regle-automatiques, '
                         '--regle-importes)' + ('.' if refuser else ', ou --evidents.'))
    n = t.decider(suivi, cfg, t.REFUSER if refuser else t.ACCEPTER, args.noms, args.variantes, evidents,
                  getattr(args, 'sauf', []), regles, getattr(args, 'sort', '') or '', getattr(args, 'cible', '') or '')
    try:
        b = lecture.lire(cfg.base)
    except (FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 2
    t.ecrire(cfg, suivi, b)
    print(f"{n} règle(s) {'refusée(s)' if refuser else 'acceptée(s)'} dans {cfg.suivi / t.FICHIER}. Lancer "
          '`zc tags planifier` pour obtenir le plan.')
    return 0


def tags_ajouter(args) -> int:
    from zot_clean import tags as t
    cfg, suivi, lecture = _suivi_tags(args)
    try:
        b = lecture.lire(cfg.base)
    except (FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 2
    n = t.ajouter(suivi, cfg, b, args.noms, args.sort, args.cible or '', args.utilisateur)
    t.ecrire(cfg, suivi, b)
    print(f'{n} règle(s) ajoutée(s) et acceptée(s) dans {cfg.suivi / t.FICHIER}. Lancer `zc tags planifier` pour '
          'obtenir le plan.')
    return 0


def tags_planifier(args) -> int:
    from zot_clean import appliquer as a, config, ecriture, lecture, plans, tags as t
    from zot_clean.ecriture import ErreurAPI, Refus
    cfg = config.charger(args.dossier)
    try:
        if avert := a.controler_synchronisation(cfg):
            print(f'Attention. {avert}')
        client = ecriture.depuis_config(cfg)
        b = a.lire_a_jour(cfg, client, _progression)
        plan, rapport = t.planifier(b, cfg, client)
    except (Refus, ErreurAPI, FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 1
    if not plan.groupes:
        print("Rien à faire : les tags sont dans l'état visé par les règles acceptées de suivi/tags.toml.")
        return 0
    chemin = plans.ecrire(plan, cfg.plans, rapport)
    print(f'{len(plan.groupes)} groupe(s), {plan.nb_operations} opération(s).')
    print(f"Plan : {chemin}\nRapport : {chemin.with_suffix('.md')}")
    print(f'Relire le rapport, puis `zc appliquer {chemin} --essai`.')
    return 0


def cles_planifier(args) -> int:
    from zot_clean import appliquer as a, bbt, cles as c, config, ecriture, lecture, plans
    from zot_clean.ecriture import ErreurAPI, Refus
    cfg = config.charger(args.dossier)
    try:
        if avert := a.controler_synchronisation(cfg):
            print(f'Attention. {avert}')
        client = ecriture.depuis_config(cfg)
        b = a.lire_a_jour(cfg, client, _progression)
        etat = bbt.detecter(cfg.dossier_zotero)
        plan, rapport = c.planifier(b, cfg, client, etat)
    except (Refus, ErreurAPI, FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 1
    for avert in c.avertissements(b, etat):
        print(f'Attention. {avert}')
    if not etat.present:
        print("Better BibTeX n'est pas actif : seules les clés en double sont départagées.")
    if a_juger := sum(1 for e in c.charger(cfg).extra if not e.decision):  # un double se départage seul
        print(f'{a_juger} cas qui demandent un avis : {cfg.suivi / c.FICHIER}, à décider avec `zc cles decider`.')
    if not plan.groupes:
        cfg.rapports.mkdir(parents=True, exist_ok=True)
        sortie = cfg.rapports / f'cles-{date.today():%Y-%m-%d}.md'
        sortie.write_text(rapport, encoding='utf-8')
        print(f"Rien à faire : aucune clé en double à départager ni ligne d'Extra à ranger. Rapport : {sortie}")
        return 0
    chemin = plans.ecrire(plan, cfg.plans, rapport)
    print(f'{len(plan.groupes)} groupe(s), {plan.nb_operations} opération(s).')
    print(f"Plan : {chemin}\nRapport : {chemin.with_suffix('.md')}")
    print(f'Relire le rapport, puis `zc appliquer {chemin} --essai`.')
    return 0


def cles_decider(args) -> int:
    """`zc cles decider FICHE=DÉCISION …` (D177)."""
    from zot_clean import bbt, cles as c, config, filtre
    cfg = config.charger(args.dossier)
    if not (cfg.suivi / c.FICHIER).is_file():
        raise SystemExit(f'Pas de {cfg.suivi / c.FICHIER} : aucun cas ne demande d\'avis. Lancer `zc cles planifier`.')
    decisions = {}
    for texte in args.decisions:
        fiche, _, decision = texte.partition('=')
        if not fiche.strip() or not decision.strip():
            raise SystemExit(f'« {texte} » : écrire FICHE=décision (garder, écarter, natif ou extra).')
        decisions[fiche.strip().upper()] = decision
    suivi = c.charger(cfg)
    n = c.decider(suivi, decisions, args.raison or '')
    b = _lire_a_jour(cfg)
    etat = bbt.detecter(cfg.dossier_zotero)
    c.ecrire(cfg, b, c.analyser(b, cfg, etat, suivi, avec_extra=etat.present), filtre.cles_masquees(b, cfg), suivi)
    print(f'{n} cas décidé(s) dans {cfg.suivi / c.FICHIER}. Lancer `zc cles planifier` pour obtenir le plan.')
    return 0


def noms_planifier(args) -> int:
    from zot_clean import appliquer as a, bbt, config, ecriture, lecture, noms as n, plans
    from zot_clean.ecriture import ErreurAPI, Refus
    cfg = config.charger(args.dossier)
    try:
        if avert := a.controler_synchronisation(cfg):
            print(f'Attention. {avert}')
        client = ecriture.depuis_config(cfg)
        b = a.lire_a_jour(cfg, client, _progression)
        stockage = bbt.stockage_fichiers(cfg.dossier_zotero)
        # Un fichier absent n'est renommé que s'il est stocké sur zotero.org et que Zotero y synchronise (D158).
        en_ligne, motif = (None, 'option --hors-ligne') if args.hors_ligne else (
            _fichiers_en_ligne(cfg, b, n.absents(b), client) if stockage == bbt.ZOTERO_ORG else ({}, ''))
        if motif:
            print(f'Fichiers absents du disque non cherchés sur zotero.org ({motif}), ils ne seront pas renommés.')
        plan, rapport = n.planifier(b, cfg, client, en_ligne, stockage)
    except n.ModeleNonPrisEnCharge as e:
        print(e, file=sys.stderr)
        return 1
    except (Refus, ErreurAPI, FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 1
    if not plan.groupes:
        cfg.rapports.mkdir(parents=True, exist_ok=True)
        sortie = cfg.rapports / f'noms-{date.today():%Y-%m-%d}.md'
        sortie.write_text(rapport, encoding='utf-8')
        print(f'Rien à renommer : les fichiers principaux portent le nom attendu, hors cas laissés de côté.\n'
              f'Rapport : {sortie}')
        return 0
    chemin = plans.ecrire(plan, cfg.plans, rapport)
    print(f'{len(plan.groupes)} fichier(s) à renommer.')
    print(f"Plan : {chemin}\nRapport : {chemin.with_suffix('.md')}")
    print(f'Relire le rapport, puis `zc appliquer {chemin} --essai`, synchroniser Zotero et vérifier avec `zc voir` '
          'que les fichiers de l\'essai portent leur nouveau nom avant `--tout`.')
    return 0


def voir(args) -> int:
    from zot_clean import config, lecture, voir as v
    if not args.cles and not args.tag:
        print('Donner des clés de fiches, ou un tag avec --tag.', file=sys.stderr)
        return 1
    cfg = config.charger(args.dossier)
    try:
        b = _lire_a_jour(cfg)
    except (FileNotFoundError, lecture.SchemaInconnu) as e:
        print(e, file=sys.stderr)
        return 2
    if args.tag:
        print(v.decrire_tag(b, cfg, args.tag))
    if args.cles:
        print(v.decrire(b, cfg, args.cles))
    return 0


def journal(args) -> int:
    from zot_clean import config, journal as jl
    cfg = config.charger(args.dossier)
    resumes = jl.tous(cfg.journal)
    if not resumes:
        print('Aucune écriture journalisée.')
        return 0
    annules = {n for r in resumes if r.termine for n in r.en_tete.get('annule', [])}
    for r in resumes:
        e = r.en_tete
        statuts = list(r.groupes.values())
        etat = 'annulé' if r.chemin.name in annules else ('terminé' if r.termine else 'interrompu')
        conflits = sum(s in ('conflit', 'erreur') for s in statuts)
        print(f"{r.chemin.name}  {e.get('mode', '?'):5}  {statuts.count('fait'):4} groupe(s) faits"
              f"{f', {conflits} en conflit' if conflits else ''}, {r.elements} élément(s), {etat}")
    return 0


def analyseur() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='zc', description="Mettre et garder de l'ordre dans sa bibliothèque Zotero.")
    p.add_argument('--version', action='version', version=f'zot-clean {__version__}')
    sous = p.add_subparsers(dest='commande', metavar='commande')
    s = sous.add_parser('init', help="Crée un dossier de travail (configuration, clé API, consignes de l'agent)")
    s.add_argument('dossier', nargs='?', type=chemin, default=Path('.'), help='dossier à créer (par défaut, le dossier courant)')
    s.add_argument('--dossier-zotero', type=chemin, help='dossier de données de Zotero (par défaut, ~/Zotero)')
    s.add_argument('--maj', action='store_true', help="met à jour les consignes de l'agent (AGENTS.md et skills) seulement")
    s.set_defaults(action=init)
    s = sous.add_parser('audit', help='Audit en lecture seule de la bibliothèque')
    s.add_argument('--dossier', type=chemin, help='dossier de travail (par défaut, celui qui contient config.toml)')
    s.add_argument('--sans-empreintes', action='store_true',
                   help='ne pas comparer le contenu des PDF (plus rapide sur une grande bibliothèque)')
    s.add_argument('--hors-ligne', action='store_true',
                   help='ne pas chercher sur zotero.org les fichiers absents du disque')
    s.set_defaults(action=audit)
    s = sous.add_parser('sauvegarder', help='Sauvegarde le dossier Zotero (Zotero fermé)')
    s.add_argument('--dossier', type=chemin, help='dossier de travail')
    s.set_defaults(action=sauvegarder)
    s = sous.add_parser('appliquer', help="Applique un plan préparé par une étape (essai d'abord)")
    s.add_argument('plan', type=chemin, help='fichier du plan (plans/…json)')
    mode = s.add_mutually_exclusive_group()
    mode.add_argument('--essai', action='store_true', help="applique les premiers groupes seulement")
    mode.add_argument('--tout', action='store_true', help="applique le reste (après l'essai et une sauvegarde)")
    s.add_argument('--dossier', type=chemin, help='dossier de travail')
    s.set_defaults(action=appliquer)
    s = sous.add_parser('annuler', help="Prépare l'annulation d'une écriture (journal ou plan)")
    s.add_argument('cible', type=chemin, help='journal (journal/…jsonl) ou plan (plans/…json) à annuler')
    s.add_argument('--dossier', type=chemin, help='dossier de travail')
    s.set_defaults(action=annuler)
    s = sous.add_parser('doublons', help='Étape 2 du nettoyage, doublons')
    ss = s.add_subparsers(dest='sous_commande', metavar='sous-commande', required=True)
    t = ss.add_parser('chercher', help='Repère les doublons et met à jour suivi/doublons.toml')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=doublons_chercher)
    t = ss.add_parser('planifier', help='Prépare le plan de fusion des groupes décidés')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=doublons_planifier)
    t = ss.add_parser('accepter', help='Décide de fusionner des groupes, ou tous les groupes sûrs (--surs)')
    t.add_argument('cles', nargs='*', metavar='CLÉ', help="clé d'une fiche de chaque groupe")
    t.add_argument('--surs', action='store_true', help='fusionne tous les groupes sûrs encore à juger')
    t.add_argument('--sauf', nargs='+', default=[], metavar='CLÉ', help='groupes à laisser de côté avec --surs')
    t.add_argument('--conserver', nargs='+', default=[], metavar='CLÉ',
                   help='fiche à garder dans son groupe, groupe accepté du même coup')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=doublons_decider, action_suivi='accepter')
    t = ss.add_parser('refuser', help="Juge des groupes distincts (pas des doublons), qui ne seront plus proposés")
    t.add_argument('cles', nargs='+', metavar='CLÉ', help="clé d'une fiche de chaque groupe")
    t.add_argument('--raison', help='raison, gardée dans le fichier (éditions différentes…)')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=doublons_decider, action_suivi='refuser')
    s = sous.add_parser('pieces', help='PDF identiques, copies en trop ou sur la mauvaise fiche (étape 2)')
    ss = s.add_subparsers(dest='sous_commande', metavar='sous-commande', required=True)
    t = ss.add_parser('chercher', help='Repère les PDF identiques et met à jour suivi/pieces.toml')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=pieces_chercher)
    t = ss.add_parser('planifier', help='Prépare le plan des groupes décidés')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=pieces_planifier)
    t = ss.add_parser('accepter', help='Décide quelles copies vont à la corbeille ou sur une autre fiche')
    t.add_argument('--corbeille', nargs='+', default=[], metavar='COPIE', help='copies à mettre à la corbeille')
    t.add_argument('--rattacher', nargs='+', default=[], metavar='COPIE=FICHE',
                   help='copies à rattacher à une autre fiche')
    t.add_argument('--raison', help='note libre, gardée dans le fichier')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=pieces_decider, action_suivi='accepter')
    t = ss.add_parser('refuser', help='Garde toutes les copies de ces groupes (copies voulues, à ne plus signaler)')
    t.add_argument('copies', nargs='+', metavar='COPIE', help="clé d'une copie de chaque groupe")
    t.add_argument('--raison', help='raison, gardée dans le fichier (chapitre et livre entier…)')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=pieces_decider, action_suivi='refuser')
    s = sous.add_parser('metadonnees', help='Étape 3 du nettoyage, métadonnées')
    ss = s.add_subparsers(dest='sous_commande', metavar='sous-commande', required=True)
    for nom, aide, action in (('identifiants', 'Corrige, vérifie et cherche les DOI', metadonnees_identifiants),
                              ('types', 'Corrige le type des fiches d\'après la source du DOI', metadonnees_types),
                              ('completer', 'Complète les champs vides depuis le DOI', metadonnees_completer)):
        t = ss.add_parser(nom, help=aide)
        t.add_argument('--rafraichir', action='store_true', help='vide le cache des sources avant de commencer')
        t.add_argument('--dossier', type=chemin, help='dossier de travail')
        t.set_defaults(action=action)
    t = ss.add_parser('accepter', help='Accepte des cas à juger, ou tous les évidents (--evidents)')
    t.add_argument('cles', nargs='*', metavar='CLÉ[=N]', help='fiche (CLÉ:problème pour un seul de ses cas), avec le numéro de la proposition retenue')
    t.add_argument('--evidents', action='store_true', help='accepte tous les cas évidents encore à juger')
    t.add_argument('--sauf', nargs='+', default=[], metavar='CLÉ', help='fiches à laisser de côté avec --evidents')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=metadonnees_decider, action_suivi='accepter')
    t = ss.add_parser('refuser', help='Refuse les cas à juger de ces fiches, qui ne seront plus proposés')
    t.add_argument('cles', nargs='+', metavar='CLÉ')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=metadonnees_decider, action_suivi='refuser')
    s = sous.add_parser('inbox', help="Gestion courante, tri des nouvelles références (Inbox et hors fonds)")
    ss = s.add_subparsers(dest='sous_commande', metavar='sous-commande', required=True)
    t = ss.add_parser('preparer', help='Doublons, métadonnées et thèmes voisins des références à trier')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=inbox_preparer)
    t = ss.add_parser('planifier', help='Un seul plan pour les références jugées (fusions, champs, rangement)')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=inbox_planifier)
    s = sous.add_parser('fonds', help='Étape 4 du nettoyage, plan du fonds (puis étape 5, rangement)')
    ss = s.add_subparsers(dest='sous_commande', metavar='sous-commande', required=True)
    t = ss.add_parser('inventaire', help="Inventaire du classement existant, prépare suivi/fonds.toml")
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=fonds_inventaire)
    t = ss.add_parser('valider', help='Contrôle plan.md et suivi/fonds.toml')
    t.add_argument('--enregistrer', action='store_true', help="enregistre la validation (après accord de l'utilisateur)")
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=fonds_valider)
    t = ss.add_parser('suivre', help='Reporte dans plan.md les thèmes créés, renommés, déplacés ou supprimés dans Zotero')
    t.add_argument('--enregistrer', action='store_true', help="écrit plan.md et le suivi (après accord de l'utilisateur)")
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=fonds_suivre)
    t = ss.add_parser('titres', help="Tous les titres d'un thème, pour proposer des sous-thèmes")
    t.add_argument('chemin', help='chemin du thème dans le fonds (« Psychologie/Perception »)')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=fonds_titres)
    t = ss.add_parser('a-ranger', help='Fiches à répartir ou à placer, par paquets (étape 5)')
    t.add_argument('--resume', metavar='CLE', help="donne le résumé d'une fiche douteuse")
    t.add_argument('--examinees', nargs='+', metavar='CLE',
                   help='marque ces collections à répartir comme entièrement jugées')
    t.add_argument('--laisser', nargs='+', metavar='CLE',
                   help='note ces fiches sans place comme vues et laissées hors du fonds')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=fonds_a_ranger)
    t = ss.add_parser('planifier', help='Prépare le plan de rangement (étape 5), relançable après chaque passe')
    t.add_argument('--racines', action='store_true', help='renomme aussi les racines d\'après [racines] de fonds.toml')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=fonds_planifier)
    s = sous.add_parser('tags', help='Étape 6 du nettoyage, tags (automatiques, variantes, concepts, états)')
    ss = s.add_subparsers(dest='sous_commande', metavar='sous-commande', required=True)
    t = ss.add_parser('inventaire', help='Inventaire des tags, prépare ou complète suivi/tags.toml')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=tags_inventaire)
    t = ss.add_parser('planifier', help='Prépare le plan des règles acceptées, relançable après chaque passe')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=tags_planifier)
    for verbe, aide in (('accepter', 'Accepte des règles de suivi/tags.toml, ou toutes les évidentes (--evidents)'),
                        ('refuser', 'Refuse des règles de suivi/tags.toml')):
        t = ss.add_parser(verbe, help=aide)
        t.add_argument('noms', nargs='*', metavar='NOM', help='entrées [[tag]], par leur nom entre guillemets')
        t.add_argument('--variantes', nargs='+', default=[], metavar='NOM',
                       help='groupes [[variantes]], par leur cible ou l\'un de leurs noms')
        t.add_argument('--regle-automatiques', action='store_true', help='règle qui retire les tags automatiques')
        t.add_argument('--regle-importes', action='store_true', help='règle qui retire les mots-clés importés')
        if verbe == 'accepter':
            t.add_argument('--evidents', action='store_true',
                           help='accepte toutes les entrées et tous les groupes évidents encore à juger')
            t.add_argument('--sauf', nargs='+', default=[], metavar='NOM', help='noms à laisser de côté avec --evidents')
            t.add_argument('--sort', help='autre sort pour les entrées données (supprimer, garder, concept, état, '
                                          'fusionner)')
            t.add_argument('--cible', help='autre cible pour les entrées et groupes donnés')
        t.add_argument('--dossier', type=chemin, help='dossier de travail')
        t.set_defaults(action=tags_decider, action_suivi=verbe)
    t = ss.add_parser('ajouter', help='Ajoute à suivi/tags.toml, acceptée, une règle pour des tags sans entrée')
    t.add_argument('noms', nargs='+', metavar='NOM', help='tags, par leur nom entre guillemets')
    t.add_argument('--sort', required=True, help='supprimer, garder, concept, état ou fusionner')
    t.add_argument('--cible', help='nom visé par un concept, un état ou une fusion')
    t.add_argument('--utilisateur', action='store_true',
                   help="demande explicite de l'utilisateur (source « utilisateur », seule à changer un tag protégé)")
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=tags_ajouter)
    s = sous.add_parser('cles', help='Étape 7 du nettoyage, clés de citation (doubles, restes dans Extra)')
    ss = s.add_subparsers(dest='sous_commande', metavar='sous-commande', required=True)
    t = ss.add_parser('planifier', help='Prépare le plan des clés en double et des lignes « Citation Key: » d\'Extra, '
                                        'relançable après chaque passe')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=cles_planifier)
    t = ss.add_parser('decider', help='Décide des cas de suivi/cles.toml (clé gardée, double ou ligne d\'Extra)')
    t.add_argument('decisions', nargs='+', metavar='FICHE=DÉCISION',
                   help='garder (la fiche garde la clé de son double), écarter, natif ou extra (ligne d\'Extra)')
    t.add_argument('--raison', help='note libre, gardée dans le fichier')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=cles_decider)
    s = sous.add_parser('noms', help='Étape 8 du nettoyage, noms des fichiers d\'après le modèle de Zotero')
    ss = s.add_subparsers(dest='sous_commande', metavar='sous-commande', required=True)
    t = ss.add_parser('planifier', help='Prépare le renommage des fichiers en retard, relançable après chaque passe')
    t.add_argument('--hors-ligne', action='store_true',
                   help='ne pas chercher sur zotero.org les fichiers absents du disque (ils ne sont pas renommés)')
    t.add_argument('--dossier', type=chemin, help='dossier de travail')
    t.set_defaults(action=noms_planifier)
    s = sous.add_parser('journal', help='Liste les écritures journalisées et leur état')
    s.add_argument('--dossier', type=chemin, help='dossier de travail')
    s.set_defaults(action=journal)
    s = sous.add_parser('voir', help="Montre des fiches en entier (champs, début du texte des PDF) pour juger un cas")
    s.add_argument('cles', nargs='*', metavar='clé', help='clés de fiches ou de pièces jointes')
    s.add_argument('--tag', metavar='NOM', help='montre les éléments qui portent ce tag (étape 6)')
    s.add_argument('--dossier', type=chemin, help='dossier de travail')
    s.set_defaults(action=voir)
    for nom, (aide, _) in A_VENIR.items():
        sous.add_parser(nom, help=aide)
    return p


def chemin(texte: str) -> Path:
    """Chemin donné en argument, `~` compris : Windows PowerShell 5.1 ne le développe pas pour un programme (D193)."""
    return Path(texte).expanduser()


def sortie_utf8() -> None:
    """Sous Windows, une sortie redirigée vers un tube (celle que lit un agent) s'écrit dans le jeu de caractères de
    la machine, et un titre grec ou une flèche y arrêtaient la commande. Elle passe en UTF-8 (D193)."""
    for flux in (sys.stdout, sys.stderr):
        if (getattr(flux, 'encoding', '') or '').lower().replace('-', '') != 'utf8' and hasattr(flux, 'reconfigure'):
            try:
                flux.reconfigure(encoding='utf-8', errors='replace')
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    sortie_utf8()
    p = analyseur()
    args = p.parse_args(argv)
    if args.commande is None:
        p.print_help()
        return 0
    if hasattr(args, 'action'):
        debut = time.monotonic()
        code = executer(args)
        _enregistrer_duree(args, argv if argv is not None else sys.argv[1:], debut, code)
        return code
    print(f'zc {args.commande} : pas encore disponible (prévu pour la {A_VENIR[args.commande][1]}).', file=sys.stderr)
    return 1


def _enregistrer_duree(args, argv: list[str], debut: float, code: int) -> None:
    """Une ligne par commande dans `journal/commandes.jsonl` du dossier de travail (D173), pour savoir où passe le
    temps d'une séance. Les intervalles entre deux commandes donnent le temps de l'agent et de l'utilisateur. Rien ne
    quitte l'ordinateur, et un échec d'écriture n'empêche jamais la commande."""
    from zot_clean import config
    try:
        dossier = args.dossier if args.commande == 'init' else getattr(args, 'dossier', None) or config.trouver_dossier()
        if not dossier or not (dossier / config.FICHIER).is_file():
            return
        commande = ' '.join(x for x in (args.commande, getattr(args, 'sous_commande', None)) if x)
        ligne = {'commande': commande, 'arguments': argv[len(commande.split()):],
                 'debut': datetime.now().astimezone().isoformat(timespec='seconds'),
                 'duree': round(time.monotonic() - debut, 1), 'code': code}
        (dossier / 'journal').mkdir(exist_ok=True)
        from zot_clean.journal import REGISTRE
        with open(dossier / 'journal' / REGISTRE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + '\n')
    except (OSError, SystemExit):
        pass


def executer(args) -> int:
    """Lance la commande. Tout refus ou échec sort avec un code non nul et son message sur la sortie d'erreur, pour
    qu'un agent qui teste le code de retour le voie (répétition du pilote). Les refus des modules passent par
    `SystemExit(message)`, ceux de l'écriture par `Refus` et `ErreurAPI`. Les lectures de la base faites par la
    commande se partagent une seule copie (`lecture.partager`)."""
    from zot_clean import lecture
    from zot_clean.ecriture import ErreurAPI, Refus
    try:
        with lecture.partager():
            code = args.action(args)
    except SystemExit as e:
        if e.code is None or isinstance(e.code, int):
            raise
        print(e.code, file=sys.stderr)
        return 1
    except (Refus, ErreurAPI) as e:
        print(e, file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f'Fichier introuvable : {e.filename or e}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Interrompu. Une commande interrompue se relance telle quelle.', file=sys.stderr)
        return 130
    return code or 0


if __name__ == '__main__':
    sys.exit(main())
