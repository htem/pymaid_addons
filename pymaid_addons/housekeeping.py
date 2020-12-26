#!/usr/bin/env python3

import numpy as np
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


def delete_unlinked_connectors(remote_instance=None, no_prompt=False, verbose=True):
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
    user_input= input(f'Found {len(connector_ids)} unlinked connectors. Continue?  [Y/n] ')
    if user_input not in ('Y', 'y'):
        return
    resp = []
    for i in tqdm(connector_ids):
        resp.append(
            pymaid.delete_nodes(i, 'CONNECTOR', no_prompt=no_prompt, remote_instance=remote_instance)
        )


def find_overlapping_connectors(remote_instance=None, verbose=True, tolerance=1):
    """Find pairs of connectors that are at exactly the same location"""
    if remote_instance in [None, 'source']:
        remote_instance = source_project
        if verbose: print('Searching for overlapping connectors in source project.')
    elif remote_instance == 'target':
        remote_instance = target_project
        if verbose: print('Searching for overlapping connectors in target project.')
    all_connectors = pymaid.get_connectors(None, remote_instance=remote_instance)
    all_connectors.sort_values(by=['x', 'y', 'z'], inplace=True, ignore_index=True)
    n_connectors = len(all_connectors)
    hits = []
    #d = lambda pt1, pt2: ((pt2 - pt1)**2).sum()**0.5  # euclidian distance
    #d = lambda pt1, pt2: np.abs(pt2 - pt1).max()  # Chebyshev distance
    d = lambda row1, row2: np.abs(all_connectors.loc[row2, ['x', 'y', 'z']].values - all_connectors.loc[row1, ['x', 'y', 'z']].values).max()  # Chebyshev distance
    for row1 in tqdm(range(n_connectors)):
        row2 = row1 + 1
        while (row2 < n_connectors and np.abs(all_connectors.at[row2, 'x'] - all_connectors.at[row1, 'x']) <= tolerance):
            if d(row2, row1) <= tolerance:
                hits.append([all_connectors.at[row1, 'connector_id'], all_connectors.at[row2, 'connector_id']])
            row2 += 1
    print(f'Found {len(hits)} pairs of overlapping connectors')
    return hits


def merge_overlapping_connectors(remote_instance=None, verbose=True, tolerance=1):
    """Merge pairs of connectors that are at exactly the same coordinate"""
    if remote_instance in [None, 'source']:
        remote_instance = source_project
        if verbose: print('Merging overlapping connectors in source project.')
    elif remote_instance == 'target':
        remote_instance = target_project
        if verbose: print('Merging overlapping connectors in target project.')
    overlapping_pairs_ids = find_overlapping_connectors(remote_instance=remote_instance,
                                                        verbose=False, tolerance=tolerance)
    user_input = input('Continue with merge? [Y/n] ')
    if user_input not in ('y', 'Y'):
        return
    resp = []
    for ids in overlapping_pairs_ids:
        print('ids', ids)
        details = pymaid.get_connector_details(ids, remote_instance=remote_instance)
        # Put the connector with presynaptic links first, if there is one
        details.sort_values(by='presynaptic_to', inplace=True, ignore_index=True)
        # Make sure it's not the case that both connectors have presynaptic links
        assert details.at[1, 'presynaptic_to'] is None, "Can't merge two presynaptic connectors"
        #Add postsynaptic connections between the winner and the loser's postsynaptic nodes
        print('linking')
        link_resp = pymaid.link_connector(
            [(postsyn_node_id, details.at[0, 'connector_id'], 'postsynaptic_to')
             for postsyn_node_id in details.at[1, 'postsynaptic_to_node']],
            remote_instance=remote_instance
        )
        #Delete the loser
        print('deleting')
        del_resp = pymaid.delete_nodes(details.at[1, 'connector_id'], 'CONNECTOR',
                                       no_prompt=True, remote_instance=remote_instance)
        resp.append((link_resp, del_resp))
        print('done')

    return resp


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
