#!/usr/bin/env python
#Requires python 3.6+ for f-strings

import os
import json

import pymaid


connection_nicknames = {
    'fafb': 'virtualflybrain_FAFB.json',
    'brain': 'virtualflybrain_FAFB.json',
    'fanc': 'virtualflybrain_FANC.json',
    'vnc': 'virtualflybrain_FANC.json',
    'larva': 'virtualflybrain_L1larva.json',
    'l1': 'virtualflybrain_L1larva.json'
}
package_dir = os.path.dirname(__file__)
config_dir = os.path.join(package_dir, 'connection_configs')

nicknames_fn = os.path.join(config_dir, 'custom_nicknames.json')
if os.path.exists(nicknames_fn):
    with open(nicknames_fn, 'r') as f:
        connection_nicknames.update(json.load(f))
del f


def connect_to_catmaid(config_filename='default_connection.json'):
    if config_filename.lower() in connection_nicknames:
        config_filename = connection_nicknames[config_filename.lower()]

    if not os.path.exists(config_filename):
        config_filename = os.path.join(config_dir, config_filename)
    try:
        with open(config_filename, 'r') as f:
            configs = json.load(f)
    except:
        print(f'ERROR: No {config_filename} file found, or file improperly'
              ' formatted. See catmaid_configs_virtualflybrain_FAFB.json for'
              ' an example config file that works.')
        raise

    catmaid_http_username = configs.get('catmaid_http_username', None)
    catmaid_http_password = configs.get('catmaid_http_password', None)


    # --Source project-- #
    if all([configs.get('source_catmaid_url', None),
            configs.get('source_catmaid_account_to_use', None),
            configs.get('source_project_id', None)]):
        source_project = pymaid.CatmaidInstance(
            configs['source_catmaid_url'],
            configs['catmaid_account_api_keys'][
                configs['source_catmaid_account_to_use']
            ],
            http_user=catmaid_http_username,
            http_password=catmaid_http_password,
            make_global=True
        )
        source_project.project_id = configs['source_project_id']
        try:
            print_project_name(source_project, 'Source project: ' +
                               configs['source_catmaid_url'])
        except:
            raise Exception(f'The API key provided in {config_filename}'
                            ' does not appear to have access to project'
                            f' {source_project.project_id}. Please provide'
                            ' a different API key or project ID.')
    else:
        raise ValueError('The following fields must appear in'
                         f' {config_filename} and not be null:'
                         " 'source_catmaid_url',"
                         " 'source_catmaid_account_to_use',"
                         " and 'source_project_id'")


    # --Target project-- #
    # target_project is only used by upload_or_update_neurons, and may be
    # ommitted from the config file when you only want to do read-only
    # operations.
    if all([configs.get('target_catmaid_url', None),
            configs.get('target_catmaid_account_to_use', None),
            configs.get('target_project_id', None)]):
        target_project = pymaid.CatmaidInstance(
            configs['target_catmaid_url'],
            configs['catmaid_account_api_keys'][
                configs['target_catmaid_account_to_use']
            ],
            http_user=catmaid_http_username,
            http_password=catmaid_http_password,
            make_global=False
        )
        target_project.project_id = configs['target_project_id']
        print_project_name(target_project, 'Target project: '+
                           configs['target_catmaid_url'])

    elif any([configs.get('target_catmaid_url', None),
              configs.get('target_catmaid_account_to_use', None),
              configs.get('target_project_id', None)]):
        print('WARNING: You have configured some target project variables but'
              ' not all. The following fields must appear in'
              f" {config_filename} and not be null: 'target_catmaid_url',"
              " 'target_catmaid_account_to_use', and 'target_project_id'."
              ' Continuing without a target project.')

    try:
        return source_project, target_project
    except:
        return source_project


def print_project_name(project, title=None):
    print(
        title,
        project.project_id,
        project.available_projects[
            project.available_projects.id == project.project_id
        ].title.to_string().split('    ')[1]
    )


def get_source_project_id(verbose=True):
    if verbose:
        print_project_name(source_project, 'Source project:')
    return source_project.project_id


def set_source_project_id(project_id, verbose=True):
    source_project.project_id = project_id
    return get_source_project_id(verbose)


def get_target_project_id(verbose=True):
    if target_project is None:
        print('Target project not defined.')
        return None
    if verbose:
        print_project_name(target_project, 'Target project:')
    return target_project.project_id


def set_target_project_id(project_id, verbose=True):
    if target_project is None:
        print('Target project not defined.')
        return None
    target_project.project_id = project_id
    return get_target_project_id(verbose)


def set_project_ids(source_id, target_id=None, verbose=True):
    if target_id is None:
        target_id = source_id
    return set_source_project_id(source_id, verbose), set_target_project_id(target_id, verbose)


def get_project_ids(verbose=True):
    return get_source_project_id(verbose), get_target_project_id(verbose)


def clear_cache():
    # I had a few instances where this didn't seem to work. (Namely, I pulled data,
    # modified a neuron on catmaid, cleared cache, then re-pulled data,
    # but the old neuron seemed to still be present in memory.)
    # Maybe this doesn't work reliably, so try not to trust it.
    # Calling reconnect_to_catmaid is a more reliable way to clear cached data.
    source_project.clear_cache()
    try:
        target_project.clear_cache()
    except NameError:
        pass

