#!/usr/bin/env python3

import pymaid

from .manipulate_and_reupload_catmaid_neurons import *


paper_base_annots = ['Paper: Phelps, Hildebrand, Graham et al. 2020', 'tracing from electron microscopy', '~left-right flipped', '~pruned \(first entry, last exit\) by vol 109', '~pruned to nodes with radius 500']

def find_desyncs(annots=[]):
    target_skids = pymaid.get_skids_by_annotation(paper_base_annots + annots, intersect=True, remote_instance=target_project)
    target_neurons = pymaid.get_neuron(target_skids, remote_instance=target_project)
    for target_neuron in tqdm(target_neurons):
        linked_skid = [a.split('skeleton id ')[1].split(' ')[0] for a in target_neuron.annotations if a.startswith('LINKED NEURON')]
        assert len(linked_skid) is 1
        linked_skid = linked_skid[0]
        source_neuron = pymaid.get_neuron(linked_skid, remote_instance=source_project)

        #TODO change this from counting things to looking at timestamps, which
        #is actually guaranteed to find desyncs whereas counts aren't
        if source_neuron.n_nodes - target_neuron.n_nodes is not 0:
            print('Node number mismatch for:', source_neuron.neuron_name)
        if source_neuron.n_connectors - target_neuron.n_connectors is not 0:
            print('Connector number mismatch for:', source_neuron.neuron_name)


def push_all_updates_by_annotations(annotations, fake=True, **kwargs):
    """
    For each neuron in the source project with all the given
    annotations, search in the target project for neurons that
    are linked to it, and update the target neuron(s) using the
    appropriate manipulate_and_reupload_catmaid_neuron function
    as specified by the linking relation in the "LINKED NEURON"
    annotation.
    """
    kwargs['fake'] = fake
    skids = get_skids_by_annotation(annotations)
    try:
        user_input = input(f'Found {len(skids)} source project neurons.'
            ' Continue? [Y/n] ')
    except:
        skids = [skids]
        user_input = input('Found 1 source project neuron. Continue? [Y/n] ')
    if user_input not in ('y', 'Y'):
        return
    push_all_updates_by_skid(skids, **kwargs)


def push_all_updates_by_skid(skids, recurse=False, fake=True, **kwargs):
    """
    For each neuron in the source project with one of the given skids,
    search in the target project for neurons that are linked to it, and
    update the target neuron(s) using the appropriate
    manipulate_and_reupload_catmaid_neuron function as specified by the
    linking relation in the "LINKED NEURON" annotation.

    If recurse=True and this function succeeds in performing an update, it
    will then push_all_updates on that updated neuron to try to
    propagate changes through any chains of linked neurons. This
    recursion only happens within the target project. If you need to
    push the updated neuron to a different project, do that manually.
    """
    kwargs['fake'] = fake
    kwargs['refuse_to_update'] = False  # Since this function only does
                                        # updates, refusing to update is
                                        # redundant with 'fake'
    link_types = {
        'copy of': lambda skids: copy_neurons_by_skid(skids, **kwargs),
        'translation of': lambda skids: translate_neurons_by_skid(skids, **kwargs),
        'elastic transformation of':
            lambda skids: elastictransform_neurons_by_skid(skids, **kwargs),
        'elastic transformation and flipped of':
            lambda skids: elastictransform_neurons_by_skid(skids, left_right_flip=True, **kwargs),
        'pruned \(first entry, last exit\) by vol 109 of':  # Note that the \ MUST be included
            lambda skids: volume_prune_neurons_by_skid(skids, 109, **kwargs),
        'radius pruned of':
            lambda skids: radius_prune_neurons_by_skid(skids, **kwargs)
    }

    try:
        iter(skids)
    except:
        skids = [skids]

    if 'skip_dates' in kwargs:
        skip_dates = kwargs.pop('skip_dates')
    else:
        skip_dates = []

    all_target_annots = pymaid.get_annotation_list(remote_instance=target_project)

    original_source_project_id = source_project.project_id
    server_responses = []
    new_skids = skids
    while len(new_skids) > 0:
        new_skids = []
        for source_skid in skids:  # For each skeleton that needs to be pushed
            target_annots = [add_escapes(annot) for annot in all_target_annots.name
                             if 'skeleton id '+str(source_skid)+' ' in annot
                             and 'project id '+str(source_project.project_id)+' 'in annot]
            #print(target_annots)
            # For each annotation that indicates a link to the source skid
            for target_annot in target_annots:
                target_skids = get_skids_by_annotation(target_annot, remote_instance='target')
                if len(target_skids) == 0:
                    continue
                elif len(target_skids) != 1:
                    input('WARNING: Multiple neurons in the target project'
                          ' with the same linking annotation??? Skipping this'
                          f' push: {target_annot}')
                    continue
                if len(skip_dates) > 0:
                    this_target_skid_annots = pymaid.get_annotations(
                            target_skids, remote_instance=target_project)
                # Check what type of link is indicated by this linking annotation
                for linking_relation in link_types:
                    if linking_relation in target_annot:
                        resp = [f'Skipped: {target_annot}']
                        print('Found in project id '
                              f"{target_project.project_id}: '{target_annot}'")
                        if (len(skip_dates) == 0 or not any([any([date in annot for date in skip_dates]) for
                            annot in list(this_target_skid_annots.values())[0]])):
                                resp = link_types[linking_relation](source_skid)
                        else:
                            print(f'Skipping upload because was already updated recently')
                        if recurse and not fake:
                            #new_skids.append(resp[0]['skeleton_id']) # old
                            new_skids.append(target_skids[0])
                        server_responses.extend(resp)
        if recurse and not fake:
            source_project.project_id = target_project.project_id
            skids = new_skids
            print(f'Recursing - now pushing updates to skids {new_skids}')
    if recurse and not fake:
        source_project.project_id = original_source_project_id

    return server_responses


def pull_all_updates_by_annotations(annotations, fake=True):
    """
    For each neuron IN THE TARGET PROJECT that has the given annotations and a
    "LINKED NEURON" annotation that points to a neuron IN THE SOURCE PROJECT,
    pull updates from the source neuron.
    """
    skids = get_skids_by_annotation(annotations, remote_instance=target_project)
    pull_all_updates_by_skid(skids, **kwargs)


def pull_all_updates_by_skid(skids, **kwargs):
    annots = pymaid.get_annotations(skids, remote_instance=target_project)
    link_types = {
        'copy of': lambda skids: copy_neurons_by_skid(skids, **kwargs),
        'translation of': lambda skids: translate_neurons_by_skid(skids, **kwargs),
        'elastic transformation of':
            lambda skids: elastictransform_neurons_by_skid(skids, **kwargs),
        'elastic transformation and flipped of':
            lambda skids: elastictransform_neurons_by_skid(skids, left_right_flip=True, **kwargs),
        'pruned \(first entry, last exit\) by vol 109 of':  # Note that the \ MUST be included
            lambda skids: volume_prune_neurons_by_skid(skids, 109, **kwargs),
        'radius pruned of':
            lambda skids: radius_prune_neurons_by_skid(skids, **kwargs)
    }
    for skid in annots:
        link_annots = [annot for annot in annots[skid]
                       if 'LINKED NEURON' in annot
                       and 'UPDATED FROM LINKED NEURON' not in annot][0]
    # TODO finish implementing


def pull_annotation_updates_by_annotations():
    #TODO
    pass


def pull_annotation_updates_by_skid():
    #TODO
    pass


