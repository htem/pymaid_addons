#!/usr/bin/env python3

from tqdm import tqdm

import pymaid

def find_unlinked_connectors(remote_instance=None, verbose=True):
    if remote_instance in [None, 'source']:
        remote_instance = source_project
        if verbose: print('Searching for unlinked connectors in source project.')
    elif remote_instance == 'target':
        remote_instance = target_project
        if verbose: print('Searching for unlinked connectors in target project.')

    all_connectors = pymaid.get_connectors(None, remote_instance=remote_instance)
    # A connector's type being null seems to indicate it is unlinked.
    # I'm not confident this will always be true in future versions of pymaid
    # and catmaid. A more robust but slower approach would actually go check
    # there are no links.
    unlinked_connectors = all_connectors.connector_id[all_connectors.type.isnull()]
    return unlinked_connectors.to_list()


def delete_unlinked_connectors(remote_instance=None, verbose=True):
    if remote_instance in [None, 'source']:
        remote_instance = source_project
        if verbose: print('Deleting unlinked connectors in source project.')
    elif remote_instance == 'target':
        remote_instance = target_project
        if verbose: print('Deleting unlinked connectors in target project.')
    remote_instance.clear_cache()
    connector_ids = find_unlinked_connectors(remote_instance=remote_instance, verbose=False)
    if len(connector_ids) == 0:
        print('No unlinked connectors found to delete.')
        return
    print(connector_ids)
    resp = input(f'Found {len(connector_ids)} unlinked connectors. Continue?  [Y/n] ')
    if resp not in ('Y', 'y'):
        return
    for i in tqdm(connector_ids):
        pymaid.delete_nodes(i, 'CONNECTOR', no_prompt=True, remote_instance=remote_instance)


def find_overlapping_connectors(remote_instance=None, verbose=True):
    """Find pairs of connectors that are at exactly the same coordinate"""
    if remote_instance in [None, 'source']:
        remote_instance = source_project
        if verbose: print('Searching for overlapping connectors in source project.')
    elif remote_instance == 'target':
        remote_instance = target_project
        if verbose: print('Searching for overlapping connectors in target project.')
    all_connectors = pymaid.get_connectors(None, remote_instance=remote_instance)


def purge_unused_annotations(remote_instance=None, force=False, verbose=True):
    if remote_instance in [None, 'source']:
        remote_instance = source_project
        if verbose: print('Purging unused annotations from the source project.')
    elif remote_instance == 'target':
        remote_instance = target_project
        if verbose: print('Purging unused annotations from the target project.')
    pid = remote_instance.project_id


    tmp_neuron_skids = {
        2: 6401,
        13: 120221,
        38: 352154,
        59: 665257
    }
    if pid not in tmp_neuron_skids:
        raise ValueError(f'Need to specify a dummy neuron to use for project id {pid}')
    tmp_skid = tmp_neuron_skids[pid]

    all_annots = pymaid.get_annotation_list(remote_instance=remote_instance)

    def add_escapes(s, chars_to_escape='()[]?+'):
        for char in chars_to_escape:
            s = s.replace(char, '\\'+char)
        return s
    def remove_escapes(s):
        while '\\' in s:
            s = s.replace('\\', '')
        return s

    for name in tqdm(all_annots.name):
        name = add_escapes(name)
        try:
            count = len(pymaid.get_annotated(name, remote_instance=remote_instance))
            if count > 0:
                pass #print('{:04d}'.format(count), name)
            else:
                print(name)
                if not force and input('Purge me? [Y/n] ').lower() != 'y':
                    continue
                pymaid.add_annotations(tmp_skid, remove_escapes(name), remote_instance=remote_instance)
                pymaid.remove_annotations(tmp_skid, remove_escapes(name), remote_instance=remote_instance)
        except:
            print(name)
            raise
