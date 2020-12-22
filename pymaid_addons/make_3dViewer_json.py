#!/usr/bin/env python

import json
import datetime

import numpy as np
import pandas as pd
import pymaid


def write_catmaid_json(skids_to_colors, filename):
    """
    skids_to_colors must be a dict containing keys that are skeleton IDs and
    values that are either hex color strings or 2-tuples containing a hex color
    string as the 0th entry and an opacity value from 0 to 1 as the 1st entry
    """
    if filename[-5:] != '.json':
        filename += '.json'
    with open(filename, 'w') as f:
        f.write('[\n')
        first = True
        for skid in skids_to_colors:
            if first:
                first = False
            else:
                f.write(', \n')
            f.write(' {\n')
            f.write(f'  \"skeleton_id\": {skid},\n')
            if isinstance(skids_to_colors[skid], tuple):
                color = skids_to_colors[skid][0]
                opacity = skids_to_colors[skid][1]
            else:
                color = skids_to_colors[skid]
                opacity = 1
            f.write(f'  \"color\": \"{color}\",\n')
            f.write(f'  \"opacity\": {opacity}\n')
            f.write(' }')
        f.write('\n]')

    print(f'CATMAID json written to {filename}. Use this file at'
          f' {source_project.server}/?pid={source_project.project_id}')
    return filename


def make_json_by_annotations(annotations_to_colors, filename,
                             datestamp=False, addons=None):
    """
    annotations_to_colors must be a dictionary whose keys are color words
    (defined by the colorword_to_hex dictionary within this script) or hex
    colors (like #ffff00), and each value must be a list of annotations to
    search for (intersectionally).  To do multiple searches and assign them to
    the same color, use lists-of-lists as keys for a given color. Each list
    will be searched for independently, and the results of each search will get
    assigned the same color.
    If you want to put some additional neurons into the json by specifying the
    skids and colors yourself, provide that as a dictionary as the addons kwarg.

    Example: Make neurons annotated with 'sensory neuron' AND 'left soma' blue:
    >>> make_json_by_annotations({'blue': ['sensory neuron', 'left soma']}, 'some_filename')

    Example: Make neurons annotated with 'sensory neuron' OR 'left soma' blue:
    >>> make_json_by_annotations({'blue': [['sensory neuron'], ['left soma']]}, 'some_filename')

    See functions within make_3dViewer_json.py for more specific examples.
    """

    skids_to_colors = {}  # Changed to an argument so user can pass a custom starting list
    if addons is not None:
        skids_to_colors.update(addons)

    always_include = annotations_to_colors.pop('always include', [])
    for key in annotations_to_colors.keys():
        color = colorword_to_hex.get(key, key)
        annotation_lists = annotations_to_colors[key]
        # Convert any values that are either strings or lists-of-strings
        # into lists-of-lists-of-strings, so that downstream processing
        # can assume each dict value is a list of annotations
        if type(annotation_lists) is str:
            annotation_lists = [annotation_lists]
        if type(annotation_lists[0]) is str:
            annotation_lists = [annotation_lists]

        for annotation_list in annotation_lists:
            annotation_list.extend(always_include)
            print(annotation_list)
            skids = pymaid.get_skids_by_annotation(
                annotations=annotation_list,
                intersect=True,
                remote_instance=source_project
            )
            print('Found {} neurons'.format(len(skids)))
            for skid in skids:
                if skid not in skids_to_colors:
                    skids_to_colors[skid] = color
                else:
                    print(f'Skeleton ID {skid} was previously given'
                          f' a color, skipping coloring it {color} from'
                          f' search {annotation_list}')

    filename = expand_filename(filename, datestamp=datestamp)
    return write_catmaid_json(skids_to_colors, filename)


def make_rainbow_json_by_position(annotations,
                                  filename,
                                  extract_position=None,
                                  convert_values_to_rank=False,
                                  **kwargs):
    """
    extract_position can be either a lambda function that defines how to
    extract a position value from a CatmaidNeuron object, or can be one of the
    following strings:
        'root_x', 'root_y' (default), 'root_z', 'mean_x', 'mean_y', 'mean_z'

    colormap must be a Nx3 array specifying triplets of RGB values. The
    smallest extracted position will get mapped to the first element of the
    colormap, the largest extracted position will get mapped to the last
    element of the colormap, and intermediate positions will take on
    intermediate values.
    """
    colormap = kwargs.get('colormap', turbo_colormap_data)

    if extract_position == 'root_x':
        extract_position = lambda n: n.nodes.x[n.nodes.node_id == n.root[0]].values[0]
    elif extract_position in (None, 'root_y'):
        extract_position = lambda n: n.nodes.y[n.nodes.node_id == n.root[0]].values[0]
    elif extract_position == 'root_z':
        extract_position = lambda n: n.nodes.z[n.nodes.node_id == n.root[0]].values[0]
    elif extract_position  == 'mean_x':
        extract_position = lambda n: n.nodes.x.mean()
    elif extract_position  == 'mean_y':
        extract_position = lambda n: n.nodes.y.mean()
    elif extract_position  == 'mean_z':
        extract_position = lambda n: n.nodes.z.mean()
    elif extract_position in ['rand', 'random']:
        import random
        extract_position = lambda: random.random()


    if 'neurons' in kwargs:
        neurons = kwargs['neurons']
        skids = neurons.skeleton_id
    else:
        try:
            skids = pymaid.get_skids_by_annotation(
                        annotations,
                        intersect=True,
                        remote_instance=source_project
                    )
        except:
            skids = annotations  # Allows users to pass skids directly
        if extract_position.__code__.co_argcount > 0: # Neuron data needed
            # Can I avoid pulling all this neuron data if I only need the root
            # position? Is there a way to pull less data even if I need the nodes?
            neurons = pymaid.get_neuron(skids, remote_instance=source_project)

    if extract_position.__code__.co_argcount > 0:
        extracted_vals = pd.Series({n.skeleton_id: extract_position(n) for n in neurons})
    else:
        extracted_vals = pd.Series({skid: extract_position() for skid in skids})
    extracted_vals.sort_values(ascending=False, inplace=True)
    if convert_values_to_rank:
        extracted_vals.iloc[:] = np.arange(len(extracted_vals), 0, -1)
    #print(extracted_vals)

    max_pos = extracted_vals.iloc[0]
    min_pos = extracted_vals.iloc[-1]
    scaled_extracted_vals = (extracted_vals - min_pos) / (max_pos - min_pos)
    colors = [RGB_to_catmaidhex(colormap[int(p*(len(colormap)-1))]) for p in scaled_extracted_vals]
    #print(colors)
    skids_to_colors = dict(zip(extracted_vals.index, colors))

    filename = expand_filename(filename, datestamp=kwargs.get('datestamp', False))
    write_catmaid_json(skids_to_colors, filename)


def expand_filename(filename, project_id=-1, datestamp=False):
    if filename[-5:] == '.json':
        filename = filename[:-5]
    if project_id is not None:
        if project_id == -1:
            # source_project is defined by package __init__
            project_id = source_project.project_id
        filename = f'project{project_id}_{filename}'
    if datestamp:
        now = datetime.datetime.now()
        filename = f'{filename}_{now.strftime("%y%m%d")}'

    filename = filename + '.json'
    return filename


# --- Below here are functions that call the above functions to make specific
# --- jsons that I've needed to make frequently in the Full Adult Nerve Cord
# --- (FANC) EM dataset.
def makejson_T1mn_bundles(kind=None,
                          soma_side=None,
                          radius_pruned=None,
                          volume_pruned=None,
                          vol_num=109,
                          flipped=None):
    always_include = add_kind([], kind)

    if soma_side is 'left':
        always_include.append('left soma')
    elif soma_side is 'right':
        always_include.append('right soma')

    if radius_pruned is False:
        always_include.append('~pruned to nodes with radius 500')
    elif radius_pruned is True:
        always_include.append('pruned to nodes with radius 500')

    if volume_pruned is False:
        always_include.append(f'~pruned \(first entry, last exit\) by vol {vol_num}')
    elif volume_pruned is True:
        always_include.append(f'pruned \(first entry, last exit\) by vol {vol_num}')

    if flipped is False:
        always_include.append('~left-right flipped')
    elif flipped is True:
        always_include.append('left-right flipped')

    return make_json_by_annotations(
        {
            'always include': always_include,
            'blue':        ['T1 leg motor neuron L1 bundle'],
            'cyan':        ['T1 leg motor neuron L2 bundle'], #could update to darkcyan
            'lightblue':   ['T1 leg motor neuron L3 bundle'], #could update to lightazure
            'darkcyan':    ['T1 leg motor neuron L4 bundle'], #could update to azure
            'darkblue':    ['T1 leg motor neuron L5 bundle'], #could update to ggb
            'darkpurple':  ['T1 leg motor neuron A1 bundle'],
            'lightpurple': ['T1 leg motor neuron A2 bundle'],
            'purple':      ['T1 leg motor neuron A3 bundle'],
            'violet':      ['T1 leg motor neuron A4 bundle'],
            'lightviolet': ['T1 leg motor neuron A5 bundle'],
            'lightorange': ['T1 leg motor neuron V1 bundle'],
            'darkmagenta': ['T1 leg motor neuron V2 bundle'],
            'orange':      ['T1 leg motor neuron V3 bundle'],
            'lightmagenta':['T1 leg motor neuron V4 bundle'],
            'lightred':    ['T1 leg motor neuron V5 bundle'],
            'red':         ['T1 leg motor neuron V6 bundle'],
            'lightgrey':   ['T1 leg motor neuron D1 bundle'],
            'darkgrey':    ['T1 leg motor neuron D2 bundle']
        },
        add_kind('T1legMNs', kind)
    )


def makejson_motorneurons(kind=None,
                          pallete='matlab',
                          soma_side=None,
                          radius_pruned=None,
                          volume_pruned=None,
                          vol_num=109,
                          flipped=None):
    always_include = add_kind([], kind)

    if soma_side is 'left':
        always_include.append('left soma')
    elif soma_side is 'right':
        always_include.append('right soma')

    if radius_pruned is False:
        always_include.append('~pruned to nodes with radius 500')
    elif radius_pruned is True:
        always_include.append('pruned to nodes with radius 500')

    if volume_pruned is False:
        always_include.append(f'~pruned \(first entry, last exit\) by vol {vol_num}')
    elif volume_pruned is True:
        always_include.append(f'pruned \(first entry, last exit\) by vol {vol_num}')

    if flipped is False:
        always_include.append('~left-right flipped')
    elif flipped is True:
        always_include.append('left-right flipped')

    if pallete == 'matlab':
        colors = {
            'always include': always_include,
            'matlab1': ['neck motor neuron'],
            'matlab7': ['T1 leg motor neuron'],
            'matlab6': ['wing motor neuron'],
            'matlab3': ['T2 leg motor neuron'],
            'matlab4': ['haltere motor neuron'],
            'matlab5': ['T3 leg motor neuron']
        }
    elif pallete == 'jet':
        colors = {
            'always include': always_include,
            'white': ['neck motor neuron'],
            'red': ['T1 leg motor neuron'],
            'orange': ['wing motor neuron'],
            'yellow': ['T2 leg motor neuron'],
            'magenta': ['haltere motor neuron'],
            'green': ['T3 leg motor neuron']
        }

    return make_json_by_annotations(
        colors,
        add_kind('motorNeurons_byTargetOrgan', kind)
    )


def makejson_sensoryneurons(kind=None, flipped=None):
    always_include = add_kind(['sensory neuron'], kind) #'Paper: Maniates-Selvin, Hildebrand, Graham et al. 2020', 
    if flipped is False:
        always_include.append('~left-right flipped')
    elif flipped is True:
        always_include.append('left-right flipped')

    return make_json_by_annotations(
        {
            'always include': always_include,
            'matlab1': [['left cervical nerve'],
                        ['right cervical nerve'],
                        ['left prosternal nerve'],
                        ['right prosternal nerve'],
                        ['left T1 chordotonal nerve'],
                        ['right T1 chordotonal nerve']],
            'matlab7': [['left T1 leg nerve'],
                        ['left T1 ventral nerve'],
                        ['left T1 accessory nerve'],
                        ['right T1 leg nerve'],
                        ['right T1 ventral nerve'],
                        ['right T1 accessory nerve'],
                        ['left T1 dorsal nerve'],
                        ['right T1 dorsal nerve']],
            'matlab6': [['left anterior dorsal mesothoracic nerve'],
                        ['right anterior dorsal mesothoracic nerve'],
                        ['left posterior dorsal mesothoracic nerve'],
                        ['right posterior dorsal mesothoracic nerve']],
            'matlab3': [['left T2 accessory nerve'],
                        ['right T2 accessory nerve'],
                        ['left T2 leg nerve'],
                        ['right T2 leg nerve'],
                        ['left dorsal-3 branch of T2 leg nerve'],
                        ['right dorsal-3 branch of T2 leg nerve'],
                        ['left dorsal-5 branch of T2 leg nerve'],
                        ['right dorsal-5 branch of T2 leg nerve'],
                        ['left ventral-2 branch of T2 leg nerve'],
                        ['right ventral-2 branch of T2 leg nerve'],
                        ['left ventral-3 branch of T2 leg nerve'],
                        ['right ventral-3 branch of T2 leg nerve']],
            'matlab4': [['left haltere nerve'],
                        ['right haltere nerve']],
            'matlab5': [['left T3 leg nerve'],
                        ['right T3 leg nerve']]
        },
        add_kind('sensoryNeurons_byTargetOrgan', kind)
    )


def makejson_leftT1SN_types(kind=None,
                            show_unclassified=True,
                            show_neck_neurons=False):
    always_include = add_kind([], kind)
    leftT1nerves = ['left T1 leg nerve',
                    'left T1 accessory nerve',
                    'left T1 ventral nerve',
                    'left T1 dorsal nerve']
    if show_neck_neurons:
        leftT1nerves.append('left T1 chordotonal nerve')
        leftT1nerves.append('left prosternal nerve')
    colors = {
        'always include': always_include,
        'matlab3': [['hair plate', nerve] for nerve in leftT1nerves],
        'matlab4': [['campaniform sensillum', nerve] for nerve in leftT1nerves],
        'matlab2': [['chordotonal neuron', nerve] for nerve in leftT1nerves],
        'matlab6': [['bristle', nerve] for nerve in leftT1nerves]
    }
    if show_unclassified:
        if show_neck_neurons:
            colors['black'] = [['sensory neuron', nerve] for nerve in leftT1nerves]
        else:
            colors['black'] = [['T1 leg sensory neuron unclassified subtype', nerve] for nerve in leftT1nerves]

    return make_json_by_annotations(
        colors,
        add_kind('leftT1sensoryNeurons_majorSubtypes', kind)
    )


def makejson_chordotonal_subtypes(only_leftT1=True,
                                  show_unclassified=True,
                                  show_ascending=True,
                                  use_claw_subbundles=False,
                                  kind=None):
    always_include = add_kind([], kind)
    if only_leftT1:
        always_include.append('left T1 leg nerve')
    colors = {
        'always include': always_include,
        'green'  : 'T1 leg club chordotonal neuron',
        '#7e2f8e': 'T1 leg hook chordotonal neuron'
    }
    if use_claw_subbundles:
        colors.update({'red'    : 'T1 leg claw chordotonal neuron A bundle',
                       'matlab7': 'T1 leg claw chordotonal neuron B bundle'})
    else:
        colors.update({'red'    : 'T1 leg claw chordotonal neuron'})
    if show_unclassified:
        colors['black'] = 'T1 leg chordotonal neuron unclassified subtype'
    if show_ascending:
        colors['matlab6'] = 'T1 leg ascending chordotonal neuron'

    return make_json_by_annotations(
        colors,
        add_kind('leftT1chordotonal_subtypes', kind)
    )


def makejson_leftT1hairplates(kind=None):
    return make_json_by_annotations(
        {
            'always include': add_kind([], kind),
            'black': ['hair plate', 'left T1 leg nerve'],  # 'matlab4'
            'matlab7': ['hair plate', 'left T1 accessory nerve'],
            'matlab6': ['hair plate', 'left T1 ventral nerve'],
            'matlab3': ['hair plate', 'left T1 dorsal nerve']
        },
        add_kind('leftT1hairPlates_byNerve', kind)
    )


def makejson_bCS(kind=None, flipped=None):
    always_include = add_kind(['bCS'], kind)
    if flipped is False:
        always_include.append('~left-right flipped')
    elif flipped is True:
        always_include.append('left-right flipped')
    return make_json_by_annotations(
        {
            'always include': always_include,
            'matlab7': [['left T1 leg nerve'], ['right T1 leg nerve']],
            'matlab3': [['left T2 leg nerve'], ['right T2 leg nerve']],
            'matlab5': [['left T3 leg nerve'], ['right T3 leg nerve']]
        },
        add_kind('bCS_byT1T2T3', kind)
    )


def makejson_T1bCS_near_lProLN_MNs(kind=None,
                                   radius_pruned=None,
                                   volume_pruned=None,
                                   vol_num=109,
                                   flipped=None):
    always_include = add_kind([], kind)
    if radius_pruned is False:
        always_include.append('~pruned to nodes with radius 500')
    elif radius_pruned is True:
        always_include.append('pruned to nodes with radius 500')

    if volume_pruned is False:
        always_include.append(f'~pruned \(first entry, last exit\) by vol {vol_num}')
    elif volume_pruned is True:
        always_include.append(f'pruned \(first entry, last exit\) by vol {vol_num}')

    if flipped is False:
        always_include.append('~left-right flipped')
    elif flipped is True:
        always_include.append('left-right flipped')

    lT1mn_skids = pymaid.get_skids_by_annotation(
        ['left T1 leg nerve', 'motor neuron'] + always_include,
        intersect=True,
        remote_instance=source_project
    )
    addons = {skid: ('#b7b7b7', 0.6) for skid in lT1mn_skids}
    return make_json_by_annotations(
        {
            'always include': ['tracing from electron microscopy',
                               '~left-right flipped'],
            'matlab7': ['left T1 leg nerve', 'bCS'],
            'red': ['right T1 leg nerve', 'bCS']
        },
        add_kind('bCS_near_MNs', kind),
        addons=addons
    )


def makejson_DUMs(kind=None, include_ag=False, flipped=None):
    always_include = add_kind([], kind) 
    if flipped is False:
        always_include.append('~left-right flipped')
    elif flipped is True:
        always_include.append('left-right flipped')
    colors = {
        'always include': always_include,
        'matlab1': 'neck DUM neuron',
        'matlab7': 'T1 leg DUM neuron',
        'matlab6': 'wing DUM neuron',
        #'matlab6': [['T2 DUM neuron', 'right anterior dorsal mesothoracic nerve'],
        #    ['T2 DUM neuron', 'right posterior dorsal mesothoracic nerve']],
        'matlab3': 'T2 leg DUM neuron', # 'right T2 leg nerve'],
        'matlab4': 'haltere DUM neuron', # 'right haltere nerve'],
        'matlab5': 'T3 leg DUM neuron',  #'right T3 leg nerve'],
    }
    if include_ag:
        colors['matlab2'] = ['abdominal ganglion DUM neuron']
    return make_json_by_annotations(
        colors,
        add_kind('DUMs', kind)
    )


def add_kind(obj, kind):
    if kind is None:
        return obj

    if isinstance(obj, list):
        obj = obj.copy()
        if kind == 'EM':
            obj.append('tracing from electron microscopy')
        elif kind == 'LM':
            obj.append('tracing from light microscopy')
        else:
            raise ValueError(f"kind must be 'EM' or 'LM' but was {kind}")
        return obj

    elif isinstance(obj, str):
        return kind + '_' + obj


def RGB_to_catmaidhex(rgb, given_scaling=1):
    """
    If your RGB values range from 0 to 1, leave given_scaling at 1.
    If your RGB values range from 0 to 255, set given_scaling to 255.
    """
    def rescale_to_255(i):
        return int(i*255/given_scaling)
    r = rescale_to_255(rgb[0])
    g = rescale_to_255(rgb[1])
    b = rescale_to_255(rgb[2])
    return f'#{r:02x}{g:02x}{b:02x}'


#Dict of color -> hex mappings. I made this manually. There's probably a package for this.
colorword_to_hex = {
'white'  : '#ffffff',
    'grey'   : '#808080', 'darkgrey'   : '#404040', 'lightgrey'  : '#c0c0c0',
'black'  : '#000000',

'red'    : '#ff0000', 'darkred'    : '#800000', 'lightred'   : '#ff8080',
    'orange' : '#ff8000', 'darkorange' : '#804000', 'lightorange': '#ffc080', 'orange_': '#ed4617',
    'yellow' : '#ffff00', 'darkyellow' : '#808000', 'lightyellow': '#ffff80',
    'lime'   : '#80ff00', 'darklime'   : '#408000', 'lightlime'  : '#c0ff80',
'green'  : '#00ff00', 'darkgreen'  : '#008000', 'lightgreen' : '#80ff80',
    'ggb'    : '#00ff80', 'darkggb'    : '#008040', 'lightggb'   : '#80ffc0',
    'cyan'   : '#00ffff', 'darkcyan'   : '#008080', 'lightcyan'  : '#80ffff',
    'azure'  : '#0080ff', 'darkazure'  : '#004080', 'lightazure' : '#80c0ff',
'blue'   : '#0000ff', 'darkblue'   : '#000080', 'lightblue'  : '#8080ff',
    'violet' : '#8000ff', 'darkviolet' : '#400080', 'lightviolet': '#c080ff',
    'purple' : '#ff00ff', 'darkpurple' : '#800080', 'lightpurple': '#ff80ff',
    'magenta': '#ff0080', 'darkmagenta': '#800040', 'lightmagenta': '#ff80c0',

'matlab1'    : '#0072bd',
'matlab2'    : '#d95319',
'matlab3'    : '#edb120',
'matlab4'    : '#7e2f8e',
'matlab5'    : '#77ac30',
'matlab6'    : '#4dbeee',
'matlab7'    : '#a2142f',

'matlab1pre2014b' : '#0000ff',
'matlab2pre2014b' : '#008000',
'matlab3pre2014b' : '#ff0000',
'matlab4pre2014b' : '#00bfbf',
'matlab5pre2014b' : '#bf00bf',
'matlab6pre2014b' : '#bfbf00',
'matlab7pre2014b' : '#404040',
'note1' : 'Note that the matlab#pre2014b colors are just blue, darkgreen, red, cyan-darkcyan, purple-darkpurple, yellow-darkyellow, and darkgrey',

'baektrblue'   : '#7f93ff',
'baektrred'    : '#fb7f85'
}


#Source for interpolate and interpolate_or_clip: https://gist.github.com/mikhailov-work/ee72ba4191942acecc03fe6da94fc73f
# Copyright 2019 Google LLC.
# SPDX-License-Identifier: Apache-2.0
def interpolate(colormap, x):
    x = max(0.0, min(1.0, x))
    a = int(x*255.0)
    b = min(255, a + 1)
    f = x*255.0 - a
    return [colormap[a][0] + (colormap[b][0] - colormap[a][0]) * f,
            colormap[a][1] + (colormap[b][1] - colormap[a][1]) * f,
            colormap[a][2] + (colormap[b][2] - colormap[a][2]) * f]

def interpolate_or_clip(colormap, x):
    if   x < 0.0: return [0.0, 0.0, 0.0]
    elif x > 1.0: return [1.0, 1.0, 1.0]
    else: return interpolate(colormap, x)

#Source: https://gist.github.com/FedeMiorelli/640bbc66b2038a14802729e609abfe89
#Info: https://ai.googleblog.com/2019/08/turbo-improved-rainbow-colormap-for.html
turbo_colormap_data = np.array(
    [[0.18995, 0.07176, 0.23217],
    [0.19483, 0.08339, 0.26149],
    [0.19956, 0.09498, 0.29024],
    [0.20415, 0.10652, 0.31844],
    [0.20860, 0.11802, 0.34607],
    [0.21291, 0.12947, 0.37314],
    [0.21708, 0.14087, 0.39964],
    [0.22111, 0.15223, 0.42558],
    [0.22500, 0.16354, 0.45096],
    [0.22875, 0.17481, 0.47578],
    [0.23236, 0.18603, 0.50004],
    [0.23582, 0.19720, 0.52373],
    [0.23915, 0.20833, 0.54686],
    [0.24234, 0.21941, 0.56942],
    [0.24539, 0.23044, 0.59142],
    [0.24830, 0.24143, 0.61286],
    [0.25107, 0.25237, 0.63374],
    [0.25369, 0.26327, 0.65406],
    [0.25618, 0.27412, 0.67381],
    [0.25853, 0.28492, 0.69300],
    [0.26074, 0.29568, 0.71162],
    [0.26280, 0.30639, 0.72968],
    [0.26473, 0.31706, 0.74718],
    [0.26652, 0.32768, 0.76412],
    [0.26816, 0.33825, 0.78050],
    [0.26967, 0.34878, 0.79631],
    [0.27103, 0.35926, 0.81156],
    [0.27226, 0.36970, 0.82624],
    [0.27334, 0.38008, 0.84037],
    [0.27429, 0.39043, 0.85393],
    [0.27509, 0.40072, 0.86692],
    [0.27576, 0.41097, 0.87936],
    [0.27628, 0.42118, 0.89123],
    [0.27667, 0.43134, 0.90254],
    [0.27691, 0.44145, 0.91328],
    [0.27701, 0.45152, 0.92347],
    [0.27698, 0.46153, 0.93309],
    [0.27680, 0.47151, 0.94214],
    [0.27648, 0.48144, 0.95064],
    [0.27603, 0.49132, 0.95857],
    [0.27543, 0.50115, 0.96594],
    [0.27469, 0.51094, 0.97275],
    [0.27381, 0.52069, 0.97899],
    [0.27273, 0.53040, 0.98461],
    [0.27106, 0.54015, 0.98930],
    [0.26878, 0.54995, 0.99303],
    [0.26592, 0.55979, 0.99583],
    [0.26252, 0.56967, 0.99773],
    [0.25862, 0.57958, 0.99876],
    [0.25425, 0.58950, 0.99896],
    [0.24946, 0.59943, 0.99835],
    [0.24427, 0.60937, 0.99697],
    [0.23874, 0.61931, 0.99485],
    [0.23288, 0.62923, 0.99202],
    [0.22676, 0.63913, 0.98851],
    [0.22039, 0.64901, 0.98436],
    [0.21382, 0.65886, 0.97959],
    [0.20708, 0.66866, 0.97423],
    [0.20021, 0.67842, 0.96833],
    [0.19326, 0.68812, 0.96190],
    [0.18625, 0.69775, 0.95498],
    [0.17923, 0.70732, 0.94761],
    [0.17223, 0.71680, 0.93981],
    [0.16529, 0.72620, 0.93161],
    [0.15844, 0.73551, 0.92305],
    [0.15173, 0.74472, 0.91416],
    [0.14519, 0.75381, 0.90496],
    [0.13886, 0.76279, 0.89550],
    [0.13278, 0.77165, 0.88580],
    [0.12698, 0.78037, 0.87590],
    [0.12151, 0.78896, 0.86581],
    [0.11639, 0.79740, 0.85559],
    [0.11167, 0.80569, 0.84525],
    [0.10738, 0.81381, 0.83484],
    [0.10357, 0.82177, 0.82437],
    [0.10026, 0.82955, 0.81389],
    [0.09750, 0.83714, 0.80342],
    [0.09532, 0.84455, 0.79299],
    [0.09377, 0.85175, 0.78264],
    [0.09287, 0.85875, 0.77240],
    [0.09267, 0.86554, 0.76230],
    [0.09320, 0.87211, 0.75237],
    [0.09451, 0.87844, 0.74265],
    [0.09662, 0.88454, 0.73316],
    [0.09958, 0.89040, 0.72393],
    [0.10342, 0.89600, 0.71500],
    [0.10815, 0.90142, 0.70599],
    [0.11374, 0.90673, 0.69651],
    [0.12014, 0.91193, 0.68660],
    [0.12733, 0.91701, 0.67627],
    [0.13526, 0.92197, 0.66556],
    [0.14391, 0.92680, 0.65448],
    [0.15323, 0.93151, 0.64308],
    [0.16319, 0.93609, 0.63137],
    [0.17377, 0.94053, 0.61938],
    [0.18491, 0.94484, 0.60713],
    [0.19659, 0.94901, 0.59466],
    [0.20877, 0.95304, 0.58199],
    [0.22142, 0.95692, 0.56914],
    [0.23449, 0.96065, 0.55614],
    [0.24797, 0.96423, 0.54303],
    [0.26180, 0.96765, 0.52981],
    [0.27597, 0.97092, 0.51653],
    [0.29042, 0.97403, 0.50321],
    [0.30513, 0.97697, 0.48987],
    [0.32006, 0.97974, 0.47654],
    [0.33517, 0.98234, 0.46325],
    [0.35043, 0.98477, 0.45002],
    [0.36581, 0.98702, 0.43688],
    [0.38127, 0.98909, 0.42386],
    [0.39678, 0.99098, 0.41098],
    [0.41229, 0.99268, 0.39826],
    [0.42778, 0.99419, 0.38575],
    [0.44321, 0.99551, 0.37345],
    [0.45854, 0.99663, 0.36140],
    [0.47375, 0.99755, 0.34963],
    [0.48879, 0.99828, 0.33816],
    [0.50362, 0.99879, 0.32701],
    [0.51822, 0.99910, 0.31622],
    [0.53255, 0.99919, 0.30581],
    [0.54658, 0.99907, 0.29581],
    [0.56026, 0.99873, 0.28623],
    [0.57357, 0.99817, 0.27712],
    [0.58646, 0.99739, 0.26849],
    [0.59891, 0.99638, 0.26038],
    [0.61088, 0.99514, 0.25280],
    [0.62233, 0.99366, 0.24579],
    [0.63323, 0.99195, 0.23937],
    [0.64362, 0.98999, 0.23356],
    [0.65394, 0.98775, 0.22835],
    [0.66428, 0.98524, 0.22370],
    [0.67462, 0.98246, 0.21960],
    [0.68494, 0.97941, 0.21602],
    [0.69525, 0.97610, 0.21294],
    [0.70553, 0.97255, 0.21032],
    [0.71577, 0.96875, 0.20815],
    [0.72596, 0.96470, 0.20640],
    [0.73610, 0.96043, 0.20504],
    [0.74617, 0.95593, 0.20406],
    [0.75617, 0.95121, 0.20343],
    [0.76608, 0.94627, 0.20311],
    [0.77591, 0.94113, 0.20310],
    [0.78563, 0.93579, 0.20336],
    [0.79524, 0.93025, 0.20386],
    [0.80473, 0.92452, 0.20459],
    [0.81410, 0.91861, 0.20552],
    [0.82333, 0.91253, 0.20663],
    [0.83241, 0.90627, 0.20788],
    [0.84133, 0.89986, 0.20926],
    [0.85010, 0.89328, 0.21074],
    [0.85868, 0.88655, 0.21230],
    [0.86709, 0.87968, 0.21391],
    [0.87530, 0.87267, 0.21555],
    [0.88331, 0.86553, 0.21719],
    [0.89112, 0.85826, 0.21880],
    [0.89870, 0.85087, 0.22038],
    [0.90605, 0.84337, 0.22188],
    [0.91317, 0.83576, 0.22328],
    [0.92004, 0.82806, 0.22456],
    [0.92666, 0.82025, 0.22570],
    [0.93301, 0.81236, 0.22667],
    [0.93909, 0.80439, 0.22744],
    [0.94489, 0.79634, 0.22800],
    [0.95039, 0.78823, 0.22831],
    [0.95560, 0.78005, 0.22836],
    [0.96049, 0.77181, 0.22811],
    [0.96507, 0.76352, 0.22754],
    [0.96931, 0.75519, 0.22663],
    [0.97323, 0.74682, 0.22536],
    [0.97679, 0.73842, 0.22369],
    [0.98000, 0.73000, 0.22161],
    [0.98289, 0.72140, 0.21918],
    [0.98549, 0.71250, 0.21650],
    [0.98781, 0.70330, 0.21358],
    [0.98986, 0.69382, 0.21043],
    [0.99163, 0.68408, 0.20706],
    [0.99314, 0.67408, 0.20348],
    [0.99438, 0.66386, 0.19971],
    [0.99535, 0.65341, 0.19577],
    [0.99607, 0.64277, 0.19165],
    [0.99654, 0.63193, 0.18738],
    [0.99675, 0.62093, 0.18297],
    [0.99672, 0.60977, 0.17842],
    [0.99644, 0.59846, 0.17376],
    [0.99593, 0.58703, 0.16899],
    [0.99517, 0.57549, 0.16412],
    [0.99419, 0.56386, 0.15918],
    [0.99297, 0.55214, 0.15417],
    [0.99153, 0.54036, 0.14910],
    [0.98987, 0.52854, 0.14398],
    [0.98799, 0.51667, 0.13883],
    [0.98590, 0.50479, 0.13367],
    [0.98360, 0.49291, 0.12849],
    [0.98108, 0.48104, 0.12332],
    [0.97837, 0.46920, 0.11817],
    [0.97545, 0.45740, 0.11305],
    [0.97234, 0.44565, 0.10797],
    [0.96904, 0.43399, 0.10294],
    [0.96555, 0.42241, 0.09798],
    [0.96187, 0.41093, 0.09310],
    [0.95801, 0.39958, 0.08831],
    [0.95398, 0.38836, 0.08362],
    [0.94977, 0.37729, 0.07905],
    [0.94538, 0.36638, 0.07461],
    [0.94084, 0.35566, 0.07031],
    [0.93612, 0.34513, 0.06616],
    [0.93125, 0.33482, 0.06218],
    [0.92623, 0.32473, 0.05837],
    [0.92105, 0.31489, 0.05475],
    [0.91572, 0.30530, 0.05134],
    [0.91024, 0.29599, 0.04814],
    [0.90463, 0.28696, 0.04516],
    [0.89888, 0.27824, 0.04243],
    [0.89298, 0.26981, 0.03993],
    [0.88691, 0.26152, 0.03753],
    [0.88066, 0.25334, 0.03521],
    [0.87422, 0.24526, 0.03297],
    [0.86760, 0.23730, 0.03082],
    [0.86079, 0.22945, 0.02875],
    [0.85380, 0.22170, 0.02677],
    [0.84662, 0.21407, 0.02487],
    [0.83926, 0.20654, 0.02305],
    [0.83172, 0.19912, 0.02131],
    [0.82399, 0.19182, 0.01966],
    [0.81608, 0.18462, 0.01809],
    [0.80799, 0.17753, 0.01660],
    [0.79971, 0.17055, 0.01520],
    [0.79125, 0.16368, 0.01387],
    [0.78260, 0.15693, 0.01264],
    [0.77377, 0.15028, 0.01148],
    [0.76476, 0.14374, 0.01041],
    [0.75556, 0.13731, 0.00942],
    [0.74617, 0.13098, 0.00851],
    [0.73661, 0.12477, 0.00769],
    [0.72686, 0.11867, 0.00695],
    [0.71692, 0.11268, 0.00629],
    [0.70680, 0.10680, 0.00571],
    [0.69650, 0.10102, 0.00522],
    [0.68602, 0.09536, 0.00481],
    [0.67535, 0.08980, 0.00449],
    [0.66449, 0.08436, 0.00424],
    [0.65345, 0.07902, 0.00408],
    [0.64223, 0.07380, 0.00401],
    [0.63082, 0.06868, 0.00401],
    [0.61923, 0.06367, 0.00410],
    [0.60746, 0.05878, 0.00427],
    [0.59550, 0.05399, 0.00453],
    [0.58336, 0.04931, 0.00486],
    [0.57103, 0.04474, 0.00529],
    [0.55852, 0.04028, 0.00579],
    [0.54583, 0.03593, 0.00638],
    [0.53295, 0.03169, 0.00705],
    [0.51989, 0.02756, 0.00780],
    [0.50664, 0.02354, 0.00863],
    [0.49321, 0.01963, 0.00955],
    [0.47960, 0.01583, 0.01055]]
)
