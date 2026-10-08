"""Sonde du renommage des fichiers par l'API web (D147), sur le compte de test seulement.

Écrit par l'API un nouveau `filename` pour trois pièces jointes importées (PDF factices téléversés par la
sonde), puis vérifie après synchronisation ce que Zotero en fait sur le disque :
1. fichier présent sur le disque, nouveau nom avec espaces et accents ;
2. fichier présent, nom qui ne change que par la casse ;
3. fichier pas encore téléchargé (réglage « Télécharger les fichiers : au besoin » du profil de test).
Pour chacun, le fichier est-il renommé dans `storage/<clé>/`, `itemAttachments.path` vaut-il
`storage:<nouveau nom>`, Zotero n'a-t-il rien renvoyé au serveur, Zotero ouvre-t-il le fichier (question),
y a-t-il eu un conflit (question). Puis l'annulation remet les anciens noms, vérifiés de la même façon.

    ZC_COMPTE_TEST=<identifiant> uv run python tests/manual/probe_filenames.py --dossier ~/zc-test --preparer
    (régler « au besoin », synchroniser, ouvrir les PDF des deux premières fiches seulement)
    ... --ecrire
    (synchroniser)
    ... --verifier
    ... --annuler
    (synchroniser)
    ... --verifier
    ... --nettoyer

Les fiches de la sonde ont un titre qui commence par « zc-sonde noms ». --nettoyer les supprime pour de
bon, avec leurs PDF.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manual.probe_tools import Probe, arguments, visible_files, same_name  # noqa: E402

# role -> (item title, old name, new name, file present on the disk before the renaming)
CASES = {
    'present': ('zc-sonde noms, fichier présent', 'zc-sonde-present.pdf',
                'Sondeur - 2026 - Fichier présent renommé.pdf', True),
    'casse': ('zc-sonde noms, casse seule', 'zc-sonde-casse.pdf', 'ZC-Sonde-Casse.pdf', True),
    'absent': ('zc-sonde noms, fichier absent', 'zc-sonde-absent.pdf',
               'Sondeur - 2026 - Fichier absent renommé.pdf', False),
}
FILE_FIELDS = ('filename', 'md5', 'mtime')

PHASES = {
    'preparer': 'crée trois fiches avec un PDF chacune',
    'ecrire': 'écrit les nouveaux noms par l\'API (après synchronisation)',
    'verifier': 'compare la copie locale et le disque aux noms attendus (après synchronisation)',
    'annuler': 'remet les anciens noms par l\'API (après la première vérification)',
    'nettoyer': 'supprime les fiches de la sonde et leurs PDF',
}


def prepare(s: Probe) -> int:
    state = s.new_state()
    items = s.client.create([{'itemType': 'journalArticle', 'title': title, 'date': '2026',
                              'creators': [{'creatorType': 'author', 'lastName': 'Sondeur', 'firstName': 'Zc'}]}
                             for title, *_ in CASES.values()])
    state['fiches'] = dict(zip(CASES, items))
    s.save(state)  # right now, so that --nettoyer finds the items again if the rest fails
    state['pieces'] = {r: s.attach_pdf(state['fiches'][r], CASES[r][1]) for r in CASES}
    s.save(state)
    d = s.client.items(list(state['pieces'].values()))
    for r, k in state['pieces'].items():
        s.check(d[k].get('filename') == CASES[r][1] and d[k].get('linkMode') == 'imported_file'
                   and s.client.file_online(k), f'PDF « {CASES[r][1]} » téléversé',
                   f"{d[k].get('linkMode')}, {d[k].get('filename')!r}")
    state['version'] = s.client.server_version()
    s.save(state)
    return s.outcome(
        'dans le profil de test, Réglages › Synchronisation › Synchronisation des fichiers, régler « Télécharger '
        'les fichiers » sur « au besoin ». Synchroniser. Ouvrir (double-clic) le PDF de « zc-sonde noms, fichier '
        'présent » et celui de « zc-sonde noms, casse seule », pour qu\'ils soient téléchargés, puis fermer leurs '
        'onglets. Ne pas ouvrir celui de « zc-sonde noms, fichier absent ». Lancer ensuite la phase --ecrire.')


def rename(s: Probe, state: dict, to: int, step: str) -> None:
    """Writes the name of index `to` of CASES (1 old, 2 new) on the three attachments."""
    p = state['pieces']
    before = s.client.items(list(p.values()))
    res = s.write([{'key': p[r], 'filename': CASES[r][to]} for r in CASES])
    s.check(not res.failures, 'écriture des trois filename acceptée',
               json.dumps(res.failures, ensure_ascii=False) if res.failures else 'aucun refus')
    after = s.client.items(list(p.values()))
    for r in CASES:
        a, b = before[p[r]], after[p[r]]
        s.check(b.get('filename') == CASES[r][to], f'{r} : le serveur montre « {CASES[r][to]} »',
                   repr(b.get('filename')))
        s.check(all(a.get(c) == b.get(c) for c in ('md5', 'mtime')) and s.client.file_online(p[r]),
                   f'{r} : md5 et mtime inchangés, fichier toujours sur zotero.org', f"md5 {b.get('md5')}")
    state['apres_ecriture'] = {r: {c: after[p[r]].get(c) for c in FILE_FIELDS} | {'version': after[p[r]]['version']}
                              for r in CASES}
    state.update(etape=step, version=s.client.server_version())
    s.save(state)


def write(s: Probe) -> int:
    state = s.state()
    if state.get('etape'):
        raise SystemExit('La phase --ecrire a déjà été faite. Synchroniser, puis lancer --verifier.')
    p = state['pieces']
    lib = s.local_copy(state, list(state['fiches'].values()) + list(p.values()))
    attachments = {att.key: att for att in lib.attachments.values()}
    for r, (_, old, _, present) in CASES.items():
        on_disk = visible_files(s.storage(p[r]))
        s.check(attachments[p[r]].path == f'storage:{old}', f'{r} : Zotero a reçu la pièce jointe',
                   attachments[p[r]].path)
        if present and on_disk != [old]:
            raise SystemExit(f'Le PDF de « {CASES[r][0]} » n\'est pas sur le disque ({on_disk}). L\'ouvrir dans '
                             'Zotero pour le télécharger, puis relancer --ecrire.')
        if not present:
            s.check(not on_disk, f'{r} : le fichier n\'est pas encore téléchargé',
                       ', '.join(on_disk) or 'dossier vide ou absent')
    rename(s, state, 2, 'renomme')
    return s.outcome('synchroniser le profil de test dans Zotero, puis lancer la phase --verifier.')


def check(s: Probe) -> int:
    state = s.state()
    step = state.get('etape')
    if step not in ('renomme', 'annule'):
        raise SystemExit('Lancer d\'abord la phase --ecrire.')
    to = 2 if step == 'renomme' else 1
    print(f"Vérification après {'le renommage' if to == 2 else 'l’annulation'}.")
    p = state['pieces']
    lib = s.local_copy(state, list(p.values()), require_upload=False)
    attachments = {att.key: att for att in lib.attachments.values()}
    server = s.client.items(list(p.values()))
    waiting = [r for r in CASES if not lib.by_key()[p[r]].synced]
    s.check(not waiting, 'Zotero n\'a aucun changement local en attente d\'envoi sur ces pièces jointes',
               ', '.join(waiting) or 'rien en attente')
    for r, (title, old, new, _) in CASES.items():
        expected, other = (new, old) if to == 2 else (old, new)
        path = attachments[p[r]].path
        s.check(same_name(path, f'storage:{expected}'), f'{r} : itemAttachments.path vaut storage:{expected}',
                   path)
        on_disk = visible_files(s.storage(p[r]))
        if r == 'absent' and not on_disk:
            s.check(True, f'{r} : fichier toujours absent du disque, rien à renommer', 'dossier vide ou absent')
        else:
            s.check(len(on_disk) == 1 and same_name(on_disk[0], expected),
                       f'{r} : un seul fichier sur le disque, nommé « {expected} », casse comprise',
                       ', '.join(on_disk) or 'aucun fichier')
            s.check(not any(same_name(f, other) for f in on_disk), f'{r} : plus de fichier « {other} »',
                       ', '.join(on_disk))
        written, current = state['apres_ecriture'][r], server[p[r]]
        diff = {c: current.get(c) for c in FILE_FIELDS if current.get(c) != written.get(c)}
        s.check(current['version'] == written['version'] and not diff,
                   f'{r} : Zotero n\'a rien renvoyé au serveur sur cette pièce jointe',
                   f"version {written['version']} -> {current['version']}" + (f', {json.dumps(diff, ensure_ascii=False)}'
                                                                           if diff else ''))

    s.question('Double-cliquer sur le PDF de « zc-sonde noms, fichier présent », puis sur celui de « zc-sonde noms, '
               'casse seule » : chacun s\'ouvre-t-il dans le lecteur de Zotero, sans message d\'erreur ?')
    s.question('Double-cliquer sur le PDF de « zc-sonde noms, fichier absent » : Zotero le télécharge-t-il et '
               'l\'ouvre-t-il ? Relancer ensuite --verifier, qui contrôle alors le nom du fichier téléchargé.')
    s.question('Une erreur ou un conflit de synchronisation s\'est-il affiché (fenêtre de conflit, point '
               'd\'exclamation sur le bouton de synchronisation) ?')
    s.question('Dans le panneau de droite de chaque pièce jointe, le nom de fichier affiché est-il le nom '
               f'attendu (« {CASES["present"][to]} », « {CASES["casse"][to]} », « {CASES["absent"][to]} ») ?')
    follow_up = ('noter les réponses, puis lancer la phase --annuler.' if to == 2 else
             'noter les réponses, puis lancer la phase --nettoyer, et remettre « Télécharger les fichiers » '
             'sur « à la synchronisation » dans le profil de test.')
    return s.outcome(follow_up)


def undo_plan(s: Probe) -> int:
    state = s.state()
    if state.get('etape') != 'renomme':
        raise SystemExit('L\'annulation suit la phase --ecrire et sa vérification.')
    s.local_copy(state, list(state['pieces'].values()))
    rename(s, state, 1, 'annule')
    return s.outcome('synchroniser le profil de test dans Zotero, puis relancer la phase --verifier.')


def clean(s: Probe) -> int:
    state = s.state()
    keys = list(state.get('fiches', {}).values())
    s.delete(keys)
    leftovers = s.client.items(keys + list(state.get('pieces', {}).values()))
    s.check(not leftovers, 'fiches et PDF de la sonde supprimés du serveur', f'{len(leftovers)} reste(nt)')
    if not leftovers:
        s.state_file.unlink()
    return s.outcome('synchroniser le profil de test dans Zotero, et remettre « Télécharger les fichiers » sur '
                   '« à la synchronisation » si ce n\'est pas fait.')


def main() -> int:
    args = arguments(__doc__, PHASES)
    s = Probe('noms', args.folder)
    return {'preparer': prepare, 'ecrire': write, 'verifier': check, 'annuler': undo_plan,
            'nettoyer': clean}[args.phase](s)


if __name__ == '__main__':
    sys.exit(main())
