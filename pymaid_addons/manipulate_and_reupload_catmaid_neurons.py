#!/usr/bin/env python3
# Requires python 3.6+ for f-strings

# When this file is imported during package initialization (see __init__.py),
# the package connects to catmaid and grants this file access to that
# connection. If you want to use this code independently of the package, you'll
# need to give this file a source_project and target_project to use, either by
# adding explicit 'source_project = pymaid.CatmaidInstance(...' lines in this
# script, or by importing this file then assigning
# 'manipulate_and_reupload_catmaid_neurons.source_project = your_instance'

import os
import time
import json
import subprocess

import pandas as pd
import numpy as np

import pymaid
from pymaid import morpho
pymaid.set_loggers(40)
# Default logger level is 20, INFO. Changed to 40, ERROR, to suppress cached
# data notices and annotation-not-found warnings, which are handled explicitly
# here. See https://docs.python.org/3/library/logging.html#levels
import navis


# ---Constants--- #
PRIMARY_NEURITE_RADIUS = 500


# -------pymaid wrappers------- #
def get_skids_by_annotation(annotations, remote_instance=None):
    if remote_instance in [None, 'source']:
        remote_instance = source_project
    elif remote_instance == 'target':
        remote_instance = target_project

    return pymaid.get_skids_by_annotation(
        annotations,
        intersect=True,
        remote_instance=remote_instance
    )


def find_unlinked_connectors(remote_instance=None):
    if remote_instance is None:
        try:
            remote_instance = target_project
            print('Searching for unlinked connectors in target project.')
        except:
            remote_instance = source_project
            print('Searching for unlinked connectors in source project.')

    all_connectors = pymaid.get_connectors(None, remote_instance=remote_instance)
    # A connector's type being null seems to indicate it is unlinked.
    # I'm not confident this will always be true in future versions of pymaid
    # and catmaid. A more robust but slower approach would actually go check
    # there are no links.
    unlinked_connectors = all_connectors.connector_id[all_connectors.type.isnull()]
    return unlinked_connectors.to_list()


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


def upload_or_update_neurons(neurons,
                             linking_relation='',
                             annotate_source_neuron=False,
                             import_connectors=False,
                             reuse_existing_connectors=True,
                             refuse_to_update=True,
                             verbose=False,
                             fake=True):
    server_responses = []
    start_day = time.strftime('%Y-%m-%d')
    start_time = time.strftime('%Y-%m-%d %I:%M %p')

    if type(neurons) is pymaid.core.CatmaidNeuron:
        neurons = pymaid.core.CatmaidNeuronList(neurons)

    # There are some pesky corner cases where updates will unintentionally create unlinked
    # connectors. When that occurs, the user is warned and asked to investigate manually.
    unlinked_connectors_start = find_unlinked_connectors(remote_instance=target_project)

    for source_neuron in neurons:
        source_project.clear_cache()
        target_project.clear_cache()

        # Check if a neuron/skeleton with this neuron's name already exists in the target project
        # If so, replace that neuron/skeleton's data with this neuron's data.
        skid_to_update = None
        nid_to_update = None
        force_id = False

        if linking_relation is '':
            linking_annotation_template = 'LINKED NEURON - skeleton id {skid} in project id {pid} on server {server}'
        else:
            linking_annotation_template = 'LINKED NEURON - {relation} skeleton id {skid} in project id {pid} on server {server}'

        linking_annotation_target = linking_annotation_template.format(
            relation=linking_relation,
            skid=source_neuron.skeleton_id,
            name=source_neuron.neuron_name, #Not used currently
            pid=source_project.project_id,
            server=source_project.server
        )
        if verbose: print("Linking annotation is: '{linking_annotation_target}'")

        try:
            linked_neuron_skid = pymaid.get_skids_by_annotation(
                add_escapes(linking_annotation_target),
                raise_not_found=False,
                remote_instance=target_project
            )
        except Exception as e:
            # There appears to be a bug in get_skids_by_annotation where it still
            # raises exceptions sometimes even with raise_not_found=False, so
            # use this block to continue through any of those cases without raising.
            #print(e)
            linked_neuron_skid = []

        source_neuron.annotations = [annot for annot in
            source_neuron.annotations if 'LINKED NEURON' not in annot]

        if len(linked_neuron_skid) is 0:  # Prepare to upload neuron as new
            print(f'Uploading "{source_neuron.neuron_name}" to project'
                  f' {target_project.project_id} as a new skeleton.')
            source_neuron.annotations.append(linking_annotation_target)
            source_neuron.annotations.append(
                f'UPDATED FROM LINKED NEURON - {start_time}')
        elif len(linked_neuron_skid) is not 1:
            print('Found multiple neurons annotated with'
                  f' "{linking_annotation_target}" in target project.'
                  ' Go fix that! Skipping upload for this neuron.')
        else:  # Prepare to update the linked neuron
            linked_neuron = pymaid.get_neuron(linked_neuron_skid[0],
                                              remote_instance=target_project)
            m = ', connectors,' if import_connectors else ''
            print(f'{source_neuron.neuron_name}: Found linked neuron with '
                  f'skeleton ID {linked_neuron.skeleton_id} in target project.'
                  f' Updating its treenodes{m} and annotations to match the'
                  ' source neuron.')

            # Check whether names match
            if not source_neuron.neuron_name == linked_neuron.neuron_name:
                user_input = input(
                    'WARNING: The linked neuron\'s name is'
                    f' "{linked_neuron.neuron_name}" but was expected to be'
                    f' "{source_neuron.neuron_name}". Continuing will rename'
                    ' the linked neuron to the expected name. Proceed? [Y/n] ')
                if user_input not in ('y', 'Y'):
                    continue

            # TODO
            # Check whether there are any nodes or connectors in the source
            # neuron with edition dates after the previous upload date. If not,
            # skip the upload and tell the user.  

            # Check whether any edited nodes will be overwritten
            linked_node_details = pymaid.get_node_details(linked_neuron.nodes.node_id.values,
                                                          remote_instance=target_project)
            is_edited = linked_node_details.edition_time != min(linked_node_details.edition_time)
            if is_edited.any():
                edited_nodes = linked_node_details.loc[is_edited, ['node_id', 'edition_time', 'editor']]
                users = pymaid.get_user_list(remote_instance=target_project).set_index('id')
                edited_nodes.loc[:, 'editor'] = [users.loc[user_id, 'login'] for
                                                 user_id in edited_nodes.editor]
                print('WARNING: The linked neuron has been manually edited,'
                      f' with {len(edited_nodes)} nodes modified. Those'
                      ' changes will get thrown away if this update is allowed'
                      ' to continue.')
                print(edited_nodes)
                user_input = input('OK to proceed and throw away the above changes? [Y/n] ')
                if user_input not in ('y', 'Y'):
                    print(f'Skipping update for "{source_neuron.neuron_name}"')
                    continue

            if refuse_to_update:
                print('refuse_to_update set to true. Skipping.\n')
                continue

            # This does NOT annotate the source neuron on the server,
            # it only appends to the object in memory
            source_neuron.annotations.append(f'UPDATED FROM LINKED NEURON - {start_time}')
            # Make sure to preserve all annotations on the target neuron. This will not
            # be necessary once # https://github.com/catmaid/CATMAID/issues/2042 is resolved
            source_neuron.annotations.extend([a for a in linked_neuron.annotations
                                              if a not in source_neuron.annotations])

            skid_to_update = linked_neuron.skeleton_id
            nid_to_update = pymaid.get_neuron_id(
                linked_neuron.skeleton_id,
                remote_instance=target_project
            )[str(linked_neuron.skeleton_id)]
            force_id = True

        if not fake:
            # Actually do the upload/update:
            server_responses.append(pymaid.upload_neuron(
                source_neuron,
                skeleton_id=skid_to_update,
                neuron_id=nid_to_update,
                force_id=force_id,
                import_tags=True,
                import_annotations=True,
                import_connectors=import_connectors,
                reuse_existing_connectors=reuse_existing_connectors,
                remote_instance=target_project
            ))

            if annotate_source_neuron:
                try:
                    upload_skid = server_responses[-1]['skeleton_id']
                    source_annotation = linking_annotation_template.format(
                        relation=linking_relation,
                        skid=server_responses[-1]['skeleton_id'],
                        name=source_neuron.neuron_name, #Not used currently
                        pid=target_project.project_id,
                        server=target_project.server
                    )
                    try:
                        server_responses[-1]['source_annotation'] = pymaid.add_annotations(
                            source_neuron.skeleton_id,
                            source_annotation,
                            remote_instance=source_project
                        )
                    except:
                        m = ('WARNING: annotate_source_neuron was requested,'
                             ' but failed. You may not have permissions to'
                             ' annotate the source project through the API')
                        print(m)
                        input('(Press enter to acknowledge and continue.)')
                        server_responses[-1]['source_annotation'] = m
                except:
                    print('WARNING: upload was not successful,'
                          ' so could not annotate source neuron.')
                    input('(Press enter to acknowledge and continue.)')

            print(f'{source_neuron.neuron_name}: Done with upload or update.')
        print(' ')
    if fake:
        print('fake was set to True. Set fake=False to actually run'
              ' upload_or_update_neurons with settings:\n'
              f'annotate_source_neuron={annotate_source_neuron}\n'
              f'import_connectors={import_connectors},\n'
              f'reuse_existing_connectors={reuse_existing_connectors},\n'
              f'refuse_to_update={refuse_to_update}')
    else:
        # There are some pesky corner cases where updates will unintentionally
        # create unlinked connectors. When that occurs, the user is warned and
        # asked to investigate manually. Note that if a human tracer is
        # annotating in catmaid and happens to make an unlinked connector that
        # exists when the following lines are run, this will throw an warning
        # despite there being nothing to worry about. Not much I can do there.
        target_project.clear_cache()
        unlinked_connectors_end = find_unlinked_connectors(remote_instance=target_project)
        newly_unlinked_connectors = set(unlinked_connectors_end).difference(set(unlinked_connectors_start))
        if len(newly_unlinked_connectors) != 0:
            print("WARNING: This upload caused some connectors in the "
                  "target project to become unlinked from any skeleton. "
                  "(This can harmlessly result from deleting connectors from "
                  "the source project, or it may indicate a bug in the code.) "
                  "You may want to go clean up the new unlinked connectors:")
            print(newly_unlinked_connectors)
            input('(Press enter to acknowledge warning and continue.)')

    return server_responses


def replace_skeleton_from_swc(skid, swc_file, remote_instance=None,
                              fake=True):
    assert isinstance(skid, int)
    if remote_instance is None:
        try:
            remote_instance = target_project
            print('Performing skeleton replacement in TARGET project.')
        except:
            remote_instance = source_project
            print('Performing skeleton replacement in SOURCE project.')

    new_neuron = pymaid.from_swc(swc_file)
    old_neuron = pymaid.get_neuron(skid, remote_instance=remote_instance)

    dist = lambda old, new: sum(
        (new.nodes[['x', 'y', 'z']].mean()
         - old.nodes[['x', 'y', 'z']].mean())**2)**0.5

    print(f'Neuron to be replaced: {old_neuron.neuron_name}')
    print('Distance between mean coordinate of old neuron and mean'
          f' coordinate of new neuron: {dist(old_neuron, new_neuron):.0f}nm')

    nid = pymaid.get_neuron_id(skid, remote_instance=remote_instance)[str(skid)]
    if len(old_neuron.connectors) != 0:
        print('WARNING: connectors on old neuron will become unlinked'
              ' (i.e. they will not be linked to the new neuron).')
    if len(old_neuron.tags) != 0:
        print('WARNING: tags on old neuron will be deleted.')

    if fake: return False

    old_root_radius = old_neuron.nodes.radius[old_neuron.nodes.parent_id.isnull()].iloc[0]
    new_neuron.nodes.loc[new_neuron.nodes.parent_id.isnull(), 'radius'] = old_root_radius

    #new_neuron.annotations = old_neuron.annotations
    new_neuron.neuron_name = old_neuron.neuron_name
    pymaid.upload_neuron(
        new_neuron,
        skeleton_id=skid,
        neuron_id=nid,
        force_id=True,
        #import_tags=True,
        #import_annotations=True,
        #import_connectors=import_connectors,
        #reuse_existing_connectors=reuse_existing_connectors,
        remote_instance=remote_instance
    )


# -------Copy neurons with no modifications------- #
def copy_neurons_by_annotations(annotations, **kwargs):
    """
    See upload_or_update_neurons for all keyword argument options.
    """
    skids = get_skids_by_annotation(annotations)
    try:
        user_input = input(f'Duplicating {len(skids)} neurons.'
            ' Continue? [Y/n] ')
    except:
        skids = [skids]
        user_input = input('Duplicating 1 neuron. Continue? [Y/n] ')
    if user_input not in ('y', 'Y'):
        return

    return copy_neurons_by_skid(skids, **kwargs)


def copy_neurons_by_skid(skids, **kwargs):
    """
    See upload_or_update_neurons for all keyword argument options.
    """
    neurons=pymaid.get_neuron(skids, remote_instance=source_project)
    kwargs['linking_relation'] = 'copy of'
    return upload_or_update_neurons(neurons, **kwargs)


# -------Translate neurons by a specified vector------- #
def translate_neurons_by_annotations(annotations,
                                     translation,
                                     unit='nm',
                                     pixel_size=(4, 4, 40),
                                     **kwargs):
    """
    See upload_or_update_neurons for all keyword argument options.
    """
    skids = get_skids_by_annotation(annotations)
    try:
        user_input = input(f'Translating {len(skids)} neurons.'
            ' Continue? [Y/n] ')
    except:
        skids = [skids]
        user_input = input('Translating 1 neuron. Continue? [Y/n] ')
    if user_input not in ('y', 'Y'):
        return

    return translate_neurons_by_skid(
        skids, translation,
        unit=unit, pixel_size=pixel_size,
        **kwargs
    )


def translate_neurons_by_skid(skids,
                              translation,
                              unit='nm',
                              pixel_size=(4, 4, 40),
                              **kwargs):
    """
    See upload_or_update_neurons for all keyword argument options.
    """
    kwargs['linking_relation'] = 'translation of'
    return upload_or_update_neurons(
        get_translated_neurons_by_skid(
            skids,
            translation,
            unit=unit,
            pixel_size=pixel_size),
        **kwargs
    )


def get_translated_neurons_by_annotations(annotations,
                                          translation,
                                          unit='nm',
                                          pixel_size=(4, 4, 40)):

    return get_translated_neurons_by_skid(
        get_skids_by_annotation(annotations),
        translation,
        unit=unit,
        pixel_size=pixel_size
    )


def get_translated_neurons_by_skid(skids,
                                   translation,
                                   unit='nm',
                                   pixel_size=(4, 4, 40)):
    if len(translation) != 3:
        raise ValueError('Expected translation to look like [x, y, z]'
                         f' and have length 3 but got {translation}')

    if unit not in ('nm', 'pixel'):
        raise ValueError(f"Expected unit to be 'nm' or 'pixel' but got {unit}")

    if unit is 'pixel':
        print(f'Translation of ({translation[0]}, {translation[1]},'
              f' {translation[2]}) pixels requested. Using pixel size of'
              f' {pixel_size} nm to convert to nm. Resulting translation is'
              f' ({translation[0]*pixel_size[0]},'
              f' {translation[1]*pixel_size[1]},'
              f' {translation[2]*pixel_size[2]}) nm.')
        translation = (translation[0]*pixel_size[0],
                       translation[1]*pixel_size[1],
                       translation[2]*pixel_size[2])

    neurons = pymaid.get_neuron(skids, remote_instance=source_project)
    if type(neurons) is pymaid.core.CatmaidNeuron:
        neurons = pymaid.core.CatmaidNeuronList(neurons)

    for neuron in neurons:

        neuron.nodes.x += translation[0]
        neuron.nodes.y += translation[1]
        neuron.nodes.z += translation[2]

        neuron.connectors.x += translation[0]
        neuron.connectors.y += translation[1]
        neuron.connectors.z += translation[2]

        neuron.neuron_name += ' - translated'

    return neurons


# -------Transform neurons using an affine transformation matrix------- #
# Affine transformation matrix must be defined in a text file
# with 4 lines, 4 entries per line, e.g.
#   -1 0 0 0
#   0 1 0 0
#   0 0 1 0
#   320000 0 0 0
# These parameters transform new_x = -x + 320000, which is a
# reflection across the plane x = 160000. This transformation is
# provided as an example file, see affinetransform_reflect_x.txt.
def affinetransform_neurons_by_annotations(annotations,
                                           transform_file,
                                           **kwargs):
    """
    See upload_or_update_neurons for all keyword argument options.
    """
    skids = get_skids_by_annotation(annotations)
    try:
        user_input = input(f'Applying affine transformation to {len(skids)}'
            ' neurons. Continue? [Y/n] ')
    except:
        skids = [skids]
        user_input = input('Applying affine transformation to 1 neuron. Continue? [Y/n] ')
    if user_input not in ('y', 'Y'):
        return

    return affinetransform_neurons_by_skid(
        skids,
        transform_file,
        **kwargs
    )


def affinetransform_neurons_by_skid(skids,
                                    transform_file,
                                    **kwargs):
    """
    See upload_or_update_neurons for all keyword argument options.
    """
    kwargs['linking_relation'] = f'affine transformation using {transform_file} of'
    return upload_or_update_neurons(
        get_affinetransformed_neurons_by_skid(skids, transform_file),
        **kwargs
    )


def get_affinetransformed_neurons_by_annotations(annotations,
                                                 transform_file):
    return get_affinetransformed_neurons_by_skid(
        get_skids_by_annotation(annotations), transform_file
    )


def get_affinetransformed_neurons_by_skid(skids,
                                          transform_file):
    neurons = pymaid.get_neuron(skids, remote_instance=source_project)
    if type(neurons) is pymaid.core.CatmaidNeuron: 
        neurons = pymaid.core.CatmaidNeuronList(neurons)

    transformed_neurons = []
    for neuron in neurons:
        node_coords = neuron.nodes[['x', 'y', 'z']].copy()
        connector_coords = neuron.connectors[['x', 'y', 'z']].copy()
        #Append a column of 1s to enable affine transformation
        node_coords['c'] = 1
        connector_coords['c'] = 1

        T = np.loadtxt(transform_file)

        #Apply transformation matrix using matrix multiplication
        transformed_node_coords = node_coords.dot(T)
        transformed_connector_coords = connector_coords.dot(T)

        #Restore column names
        transformed_node_coords.columns = ['x', 'y', 'z', 'c' ]
        transformed_connector_coords.columns = ['x', 'y', 'z', 'c']

        neuron.nodes.loc[:, ['x', 'y', 'z']] = transformed_node_coords[['x', 'y', 'z']]
        neuron.connectors.loc[:, ['x', 'y', 'z']] = transformed_connector_coords[['x', 'y', 'z']]

        neuron.neuron_name += ' -  affine transform'
        transformed_neurons.append(neuron)

    return pymaid.CatmaidNeuronList(transformed_neurons)


# -------Transform neurons using an arbitrary transform function------- #
def elastictransform_neurons_by_annotations(annotations,
                                            transform=None,
                                            **kwargs):
    """
    Searches for skeleton_ids using the given annotations, then
    calls get_elastictransformed_neurons_by_skid and runs
    upload_or_update_neurons on the returned neurons.
    See those two functions for arg and kwarg descriptions.
    """
    skids = get_skids_by_annotation(annotations)
    try:
        user_input = input(f'Elastically transforming {len(skids)} neurons.'
                           ' Continue? [Y/n] ')
    except:
        skids = [skids]
        user_input = input('Elastically transforming 1 neuron. Continue? [Y/n] ')
    if user_input not in ('y', 'Y'):
        return

    return elastictransform_neurons_by_skid(
        skids,
        transform=transform,
        **kwargs
    )


def elastictransform_neurons_by_skid(skids,
                                     transform=None,
                                     **kwargs):
    """
    Calls get_elastictransformed_neurons_by_skid and runs
    upload_or_update_neurons on the returned neurons.
    See those two functions for argument descriptions.
    """
    left_right_flip = kwargs.pop('left_right_flip', False)
    if left_right_flip:
        kwargs['linking_relation'] = 'elastic transformation and flipped of'
    else:
        kwargs['linking_relation'] = 'elastic transformation of'
    include_connectors = kwargs.get('import_connectors', False)
    return upload_or_update_neurons(
        get_elastictransformed_neurons_by_skid(
            skids,
            transform=transform,
            left_right_flip=left_right_flip,
            include_connectors=include_connectors,
            **kwargs),
        **kwargs
    )


def get_elastictransformed_neurons_by_annotations(annotations, **kwargs):
    """
    See get_elastictransformed_neuron_by_skids for argument descriptions.
    """
    return get_elastictransformed_neurons_by_skid(
        get_skids_by_annotation(annotations),
        **kwargs
    )


def get_elastictransformed_neurons_by_skid(skids,
                                           transform=None,
                                           include_connectors=True,
                                           y_coordinate_cutoff=None,
                                           **kwargs):
    """
    Apply an arbitrary transformation to a neuron.
    skids: A skeleton ID or list of skeleton IDs to transform.
    transform: a function that takes in an Nx3 numpy array representing a list
        of treenodes' coordinates and returns an Nx3 numpy array representing
        the transformed coordinates. Defaults to using warp_points_FANC_to_template
        from coordinate_transforms.warp_points_between_FANC_and_template.
    include_connectors (bool): If True, connectors will be transformed,
        otherwise will not be transformed (which saves execution time).
    y_coordinate_cutoff (numerical): If not None, filter out treenodes and
        connectors with y coordinate < y_coordinate_cutoff before transforming.

    kwargs:
        left_right_flip (bool): Flips the neuron across the VNC template's
            midplane. Only relevant for the default transform function.
    """

    left_right_flip = kwargs.get('left_right_flip', False)

    if transform is None:
        try:
            from .coordinate_transforms.warp_points_between_FANC_and_template \
                    import warp_points_FANC_to_template as warp
        except:
            from coordinate_transforms.warp_points_between_FANC_and_template \
                    import warp_points_FANC_to_template as warp
        transform = lambda x: warp(x, reflect=left_right_flip)
        y_coordinate_cutoff = 322500  # 300000 * 4.3/4. In nm

    print('Pulling source neuron data from catmaid')
    source_project.clear_cache()
    neurons = pymaid.get_neuron(skids, remote_instance=source_project)
    if type(neurons) is pymaid.core.CatmaidNeuron:
        neurons = pymaid.core.CatmaidNeuronList(neurons)

    if y_coordinate_cutoff is not None:
        print(f'Applying y coordinate cutoff of {y_coordinate_cutoff}')
        for neuron in neurons:
            kept_rows = neuron.nodes.y >= y_coordinate_cutoff
            kept_node_ids = neuron.nodes[kept_rows].node_id.values
            # TODO double check whether this removes synapses as well. I think it does
            navis.subset_neuron(neuron, kept_node_ids, inplace=True)
            if neuron.n_skeletons > 1:
                print(f'{neuron.neuron_name} is fragmented. Healing before continuing.')
                navis.heal_fragmented_neuron(neuron, inplace=True)

    for neuron in neurons:
        print(f'Transforming {neuron.neuron_name}')
        neuron.neuron_name += ' - elastic transform'
        if left_right_flip:
            neuron.neuron_name += ' - flipped'
            neuron.annotations.append('left-right flipped')

        neuron.nodes[['x', 'y', 'z']] = transform(neuron.nodes[['x', 'y', 'z']])
        if include_connectors:
            neuron.connectors[['x', 'y', 'z']] = transform(neuron.connectors[['x', 'y', 'z']])

    return neurons



# -------Prune neuron by volume------- #
def volume_prune_neurons_by_annotations(annotations,
                                        volume_id,
                                        mode='fele',
                                        resample=0,
                                        only_keep_largest_fragment=False,
                                        **kwargs):
    """
    volume_id : Get this number from the catmaid volume manager
    mode : 'fele' -   Keep all parts of the neuron between its First Entry to
                      and Last Exit from the volume. So if a branch leaves and
                      then re-enters the volume, that path is not removed.
           'strict' - All nodes outside the volume are pruned.
    resample : If set to a positive value, the neuron will be resampled before
               pruning to have treenodes placed every `resample` nanometers. If
               left at 0, resampling is not performed.
    In both cases, if a branch point is encountered before the first entry or
    last exit, that branch point is used as the prune point.
    See upload_or_update_neurons for all keyword argument options.
    """
    skids = get_skids_by_annotation(annotations)
    try:
        len(skids)
        user_input = input(f'Volume pruning {len(skids)} neurons.'
                           ' Continue? [Y/n] ')
    except:
        skids = [skids]
        user_input = input('Volume pruning 1 neuron. Continue? [Y/n] ')
    if user_input not in ('y', 'Y'):
        return

    return volume_prune_neurons_by_skid(
        skids,
        volume_id,
        mode=mode,
        only_keep_largest_fragment=only_keep_largest_fragment,
        **kwargs
    )


def volume_prune_neurons_by_skid(skids,
                                 volume_id,
                                 mode='fele',
                                 resample=0,
                                 only_keep_largest_fragment=False,
                                 **kwargs):
    """
    volume_id : Get this number from the catmaid volume manager
    mode : 'fele' -   Keep all parts of the neuron between its First Entry to
                      and Last Exit from the volume. So if a branch leaves and
                      then re-enters the volume, that path is not removed.
           'strict' - All nodes outside the volume are pruned.
    resample : If set to a positive value, the neuron will be resampled before
               pruning to have treenodes placed every `resample` nanometers. If
               left at 0, resampling is not performed.
    In both cases, if a branch point is encountered before the first entry or
    last exit, that branch point is used as the prune point.
    See upload_or_update_neurons for all keyword argument options.
    """
    if mode == 'fele':
        linking_relation = f'pruned (first entry, last exit) by vol {volume_id} of'
    elif mode == 'strict':
        linking_relation = f'pruned (strict) by vol {volume_id} of'
    kwargs['linking_relation'] = linking_relation
    if 'verbose' in kwargs:
        get_nrn_kwargs = {'verbose': kwargs['verbose']}
    else:
        get_nrn_kwargs = {}

    return upload_or_update_neurons(
        get_volume_pruned_neurons_by_skid(
            skids,
            volume_id,
            mode=mode,
            only_keep_largest_fragment=only_keep_largest_fragment,
            **get_nrn_kwargs),
        **kwargs
    )


def get_volume_pruned_neurons_by_annotations(annotations,
                                             volume_id,
                                             mode='fele',
                                             resample=0,
                                             only_keep_largest_fragment=False):
    """
    volume_id : Get this number from the catmaid volume manager
    mode : 'fele' -   Keep all parts of the neuron between its First Entry to
                      and Last Exit from the volume. So if a branch leaves and
                      then re-enters the volume, that path is not removed.
           'strict' - All nodes outside the volume are pruned.
    resample : If set to a positive value, the neuron will be resampled before
               pruning to have treenodes placed every `resample` nanometers. If
               left at 0, resampling is not performed.
    In both cases, if a branch point is encountered before the first entry or
    last exit, that branch point is used as the prune point.
    """
    return get_volume_pruned_neurons_by_skid(
        get_skids_by_annotation(annotations),
        volume_id,
        mode=mode,
        only_keep_largest_fragment=only_keep_largest_fragment
    )


volumes = {}  # For caching volumes
def get_volume_pruned_neurons_by_skid(skids,
                                      volume_id,
                                      mode='fele',
                                      resample=0,
                                      only_keep_largest_fragment=False,
                                      verbose=False,
                                      remote_instance=None):
    """
    mode : 'fele' -   Keep all parts of the neuron between its primary
                      neurite's First Entry to and Last Exit from the volume.
                      So if a segment of the primary neurite leaves and then
                      re-enters the volume, that segment is not removed.
           'strict' - All nodes outside the volume are pruned.
    resample : If set to a positive value, the neuron will be resampled before
               pruning to have treenodes placed every `resample` nanometers. If
               left at 0, resampling is not performed.
    In both cases, if a branch point is encountered before the first entry or
    last exit, that branch point is used as the prune point.
    """
    if remote_instance is None:
        remote_instance = source_project

    #if exit_volume_id is None:
    #    exit_volume_id = entry_volume_id

    neurons = pymaid.get_neuron(skids, remote_instance=source_project)
    if volume_id not in volumes:
        try:
            print(f'Pulling volume {volume_id} from project'
                  f' {remote_instance.project_id}.')
            volumes[volume_id] = pymaid.get_volume(volume_id, remote_instance=remote_instance)
        except:
            print(f"Couldn't find volume {volume_id} in project_id"
                  f" {remote_instance.project_id}! Exiting.")
            raise
    else:
        print(f'Loading volume {volume_id} from cache.')
    volume = volumes[volume_id]

    if type(neurons) is pymaid.core.CatmaidNeuron: 
        neurons = pymaid.core.CatmaidNeuronList(neurons)

    if resample > 0:
        #TODO find the last node on the primary neurite and store its position
        neurons.resample(resample)  # This throws out radius info except for root
        #TODO find the new node closest to the stored node and set all nodes
        #between that node and root to have radius 500

    for neuron in neurons:
        if 'pruned by vol' in neuron.neuron_name:
            raise Exception('Volume pruning was requested for '
                  f' "{neuron.neuron_name}". You probably didn\'t mean to do'
                  ' this since it was already pruned. Exiting.')
            continue
        print(f'Pruning neuron {neuron.neuron_name}')
        if mode == 'fele':
            """
            First, find the most distal primary neurite node. Then, walk
            backward until either finding a node within the volume or a branch
            point. Prune distal to one distal to that point (so it only gets
            the primary neurite and not the offshoot).
            Then, start from the primary neurite node that's a child of the
            soma node, and walk forward (how?) until finding a node within the
            volume or a branch point. Prune proximal to that.
            """
            nodes = neuron.nodes.set_index('node_id')
            # Find end of the primary neurite
            nodes['has_fat_child'] = False
            for tid in nodes.index:
                if nodes.at[tid, 'radius'] == PRIMARY_NEURITE_RADIUS:
                    parent = nodes.at[tid, 'parent_id']
                    nodes.at[parent, 'has_fat_child'] = True
            is_prim_neurite_end = (~nodes['has_fat_child']) & (nodes['radius']
                    == PRIMARY_NEURITE_RADIUS)
            prim_neurite_end = nodes.index[is_prim_neurite_end]
            if len(prim_neurite_end) is 0:
                raise ValueError(f"{neuron.neuron_name} doesn't look like a"
                                 "  motor neuron. Exiting.")
            elif len(prim_neurite_end) is not 1:
                raise ValueError('Multiple primary neurite ends for'
                                 f' {neuron.neuron_name}: {prim_neurite_end}.'
                                 '\nExiting.')
            
            nodes['is_in_vol'] = navis.in_volume(nodes, volume)

            # Walk backwards until at a point inside the volume, or at a branch
            # point
            current_node = prim_neurite_end[0]
            parent_node = nodes.at[current_node, 'parent_id']
            while (nodes.at[parent_node, 'type'] != 'branch'
                    and not nodes.at[parent_node, 'is_in_vol']):
                current_node = parent_node
                if verbose: print(f'Walk back to {current_node}')
                parent_node = nodes.at[parent_node, 'parent_id']
            if verbose: print(f'Pruning distal to {current_node}')
            neuron.prune_distal_to(current_node, inplace=True)

            # Start at the first primary neurite node downstream of root
            current_node = nodes.index[(nodes.parent_id == neuron.root[0])
                    #& (nodes.radius == PRIMARY_NEURITE_RADIUS)][0]
                    & (nodes.radius > 0)][0]
            #Walking downstream is a bit slow, but probably acceptable
            while (not nodes.at[current_node, 'is_in_vol'] and
                    nodes.at[current_node, 'type'] == 'slab'):
                current_node = nodes.index[nodes.parent_id == current_node][0]
                if verbose: print(f'Walk forward to {current_node}')
            if not nodes.at[current_node, 'is_in_vol']:
                input('WARNING: Hit a branch before hitting the volume for'
                      f' neuron {neuron.neuron_name}. This is unusual.'
                      ' Press enter to acknowledge.')

            if verbose: print(f'Pruning proximal to {current_node}')
            neuron.prune_proximal_to(current_node, inplace=True)

        elif mode == 'strict':
            neuron.prune_by_volume(volume) #This does in-place pruning

        if neuron.n_skeletons > 1:
            if only_keep_largest_fragment:
                print('Neuron has multiple disconnected fragments after'
                      ' pruning. Will only keep the largest fragment.')
                frags = morpho.break_fragments(neuron)
                neuron.nodes = frags[frags.n_nodes == max(frags.n_nodes)][0].nodes
                #print(neuron)
            #else, the neuron will get healed and print a message about being
            #healed during upload_neuron, so nothing needs to be done here.

        if mode == 'fele':
            neuron.annotations.append(f'pruned (first entry, last exit) by vol {volume_id}')
        elif mode == 'strict':
            neuron.annotations.append(f'pruned (strict) by vol {volume_id}')

        neuron.neuron_name = neuron.neuron_name + f' - pruned by vol {volume_id}'

        if verbose: print('\n')

    return neurons

# -------Prune neuron by radius------- #
#Keep only nodes with radius == (or optionally >=) a given value
def radius_prune_neurons_by_annotations(annotations,
                                        radius_to_keep=PRIMARY_NEURITE_RADIUS,
                                        keep_larger_radii=True,
                                        **kwargs):
    """
    See upload_or_update_neurons for all keyword argument options.
    """
    skids = get_skids_by_annotation(annotations)
    try:
        len(skids)
        user_input = input(f'Radius pruning {len(skids)} neurons. Continue? [Y/n] ')
    except:
        skids = [skids]
        user_input = input('Radius pruning 1 neuron. Continue? [Y/n] ')
    if user_input not in ('y', 'Y'):
        return

    return radius_prune_neurons_by_skid(
        skids,
        radius_to_keep=radius_to_keep,
        keep_larger_radii=keep_larger_radii,
        **kwargs
    )


def radius_prune_neurons_by_skid(skids,
                                 radius_to_keep=PRIMARY_NEURITE_RADIUS,
                                 keep_larger_radii=True,
                                 **kwargs):
    """
    See upload_or_update_neurons for all keyword argument options.
    """

    linking_relation = 'radius pruned of'
    kwargs['linking_relation'] = linking_relation

    return upload_or_update_neurons(
        get_radius_pruned_neurons_by_skid(skids,
            radius_to_keep=radius_to_keep,
            keep_larger_radii=True),
        **kwargs
    )


def get_radius_pruned_neurons_by_annotations(annotations,
                                             radius_to_keep=PRIMARY_NEURITE_RADIUS,
                                             keep_larger_radii=True):

    return get_radius_pruned_neurons_by_skid(
        get_skids_by_annotation(annotations),
        radius_to_keep=radius_to_keep,
        keep_larger_radii=keep_larger_radii
    )


def get_radius_pruned_neurons_by_skid(skids,
                                      radius_to_keep=PRIMARY_NEURITE_RADIUS,
                                      keep_larger_radii=True):

    neurons = pymaid.get_neuron(skids, remote_instance=source_project)
    if type(neurons) is pymaid.core.CatmaidNeuron: 
        neurons = pymaid.core.CatmaidNeuronList(neurons)

    for neuron in neurons:
        if 'radius' in neuron.neuron_name:
            raise Exception('Radius pruning was requested for'
                            f' "{neuron.neuron_name}". You probably didn\'t'
                            ' mean to do this since it was already pruned.'
                            ' Abort!')
        if keep_larger_radii:
            navis.subset_neuron(
                neuron,
                neuron.nodes.node_id.values[neuron.nodes.radius >= radius_to_keep],
                inplace=True)
        else:
            navis.subset_neuron(
                neuron,
                neuron.nodes.node_id.values[neuron.nodes.radius == radius_to_keep],
                inplace=True)

        if neuron.n_skeletons > 1:
            navis.plot2d(neuron)
            raise Exception(f'You cut {neuron.neuron_name} into two fragments.'
                            " That's not supposed to happen.")

        neuron.annotations.append('pruned to nodes with radius 500')
        neuron.neuron_name = neuron.neuron_name + f' - radius {radius_to_keep}'

    return neurons


# -------Helpers------- #
def add_escapes(s, chars_to_escape='()'):
    for char in chars_to_escape:
        s = s.replace(char, '\\'+char)
    return s


# ------Hardcoded pruning------- #
#Currently hardcoded for a 1-time use. Not wise to use as is!
default_prune_params = {
    #161745: {'new root': 4704225, 'prune points': [4704226]},
    #161481: {'prune points': [4782192]},
    #161331: {'new root': 4759676, 'prune points': [4759675]},
    #169059: {'prune points': [4850625], 'final root': 4850625}
    #161548: {'prune points': [4792830]},
    }
#TODO test this function's behavior with import_connectors=True. What happens if I cut off a branch that had a synapse on it?
def get_pruned_by_hardcoded_dict(prune_params=default_prune_params,
                                 **kwargs):
    neurons = []
    for skid in prune_params:
        neuron = pymaid.get_neuron(skid)
        if 'new root' in prune_params[skid]:
            neuron.reroot(prune_params[skid]['new root'], inplace=True)
        for prune_point in prune_params[skid]['prune points']:
            neuron.prune_distal_to(prune_point, inplace=True)
        if 'final root' in prune_params[skid]:
            neuron.reroot(prune_params[skid]['final root'], inplace=True)
        neuron.plot3d(color=None)
        neurons.append(neuron)
    upload_or_update_neurons(neurons, **kwargs)
    return neurons 


# ---Dummy nodes--- #
#Add dummy node to single-node neurons to get around pymaid's inability
#to deal with single-node neurons. These functions need to be called
#manually, as they're not (yet) integrated into the functions above.
def add_dummy_nodes_by_annotations(annotations, fake=True, remote_instance=None):
    return add_dummy_nodes_by_skid(
        pymaid.get_skids_by_annotation(
            annotations,
            intersect=True,
            remote_instance=remote_instance),
        fake=fake,
        remote_instance=remote_instance
    )


def add_dummy_nodes_by_skid(skids, fake=True, remote_instance=None):
    assert remote_instance is not None, 'Must pass a remote_instance. Exiting.'
    remote_instance.clear_cache()
    neurons = pymaid.get_neuron(skids, remote_instance=remote_instance)
    server_responses = []
    #TODO can I do this in one API call instead of one call per neuron?
    for neuron in neurons:
        if len(neuron.nodes) is not 1:
            print(f'Dummy node requested for a neuron with >1 node. Skipping "{neuron.neuron_name}".')
            continue
    
        if not fake:
            server_responses.append(
                pymaid.add_node((-1, -1, neuron.nodes.iloc[0].z),
                                    neuron.nodes.iloc[0].node_id,
                                    confidence=1,
                                    remote_instance=remote_instance)
            )
        else:
            print(f'pymaid.add_node((-1, -1, {neuron.nodes.iloc[0].z}),'
                  f' {neuron.nodes.iloc[0].node_id}, confidence=1,'
                  ' remote_instance=remote_instance)')
                  
    return server_responses


def delete_dummy_nodes_by_annotations(annotations,
                                      dummy_coords=(-1, -1),
                                      fake=True,
                                      remote_instance=None):
    return delete_dummy_nodes_by_skid(
        pymaid.get_skids_by_annotation(
            annotations,
            intersect=True,
            remote_instance=remote_instance),
        dummy_coords=dummy_coords,
        fake=fake,
        remote_instance=remote_instance
    )


def delete_dummy_nodes_by_skid(skids,
                               dummy_coords=(-1, -1),
                               fake=True,
                               remote_instance=None):
    assert remote_instance is not None, 'Must pass a remote_instance. Exiting.'
    remote_instance.clear_cache()
    neurons = pymaid.get_neuron(skids, remote_instance=remote_instance)
    neurons_with_dummy_nodes = []
    for neuron in neurons:
        if len(neuron.nodes) is not 2:
            print(f'"{neuron.neuron_name}" doesn\'t have exactly 2 nodes. Skipping.')
            continue
        # TODO checking for equality between floats is bad.
        # Change it to difference < 0.1 or something.
        if not (neuron.nodes[['x', 'y']] == dummy_coords).all(axis=1).any():
            print(f'"{neuron.neuron_name}" has no nodes at (x, y) = {dummy_coords}. Skipping.')
            continue
        neurons_with_dummy_nodes.append(neuron)

    neurons = pymaid.core.CatmaidNeuronList(neurons_with_dummy_nodes)

    if len(neurons) is 0:
        raise ValueError('No neurons appear to have dummy nodes.')

    server_responses = []
    # TODO checking for equality between floats is bad.
    # Change it to difference < 0.1 or something
    is_at_dummy_coords = (neurons.nodes[['x', 'y']] == dummy_coords).all(axis=1)
    nodes_to_delete = neurons.nodes.node_id[is_at_dummy_coords].to_list()

    if not fake:
        server_responses.append(pymaid.delete_nodes(
            nodes_to_delete,
            'TREENODE',
            remote_instance=remote_instance))
    else:
        print(f"pymaid.delete_nodes({nodes_to_delete},"
              " 'TREENODE', remote_instance=remote_instance)")

    return server_responses

