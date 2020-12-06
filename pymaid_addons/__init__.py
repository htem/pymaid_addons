from .connections import *
from .manipulate_and_reupload_catmaid_neurons import *
from .make_3dViewer_json import *

def reset_connection(config_filename='default_connection.json'):
    # Open connections
    print('Connecting to catmaid...')
    projects = connect_to_catmaid(config_filename=config_filename)
    target_project = None
    if isinstance(projects, tuple):
        source_project, target_project = projects
    else:
        source_project = projects

    # Allow each script read/write access to these project objects
    connections.source_project = source_project
    manipulate_and_reupload_catmaid_neurons.source_project = source_project
    make_3dViewer_json.source_project = source_project
    connections.target_project = target_project
    manipulate_and_reupload_catmaid_neurons.target_project = target_project

connect_to = reset_connection  # Just an alias
 

def __getattr__(name):
    if name == 'source_project':
        # source_project points to connections.source_project
        return connections.source_project
    elif name == 'target_project':
        # target_project points to connections.target_project
        return connections.target_project

reset_connection()
