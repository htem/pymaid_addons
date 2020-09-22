## pymaid_addons
A collection of python scripts that extend [Philipp Schlegel](https://github.com/schlegelp)'s wonderful [pymaid package](https://github.com/schlegelp/pymaid). Pymaid makes it easy to interact with neuron reconstructions on a [CATMAID](https://catmaid.readthedocs.io/en/stable/) server. pymaid_addons provides some additional functionality for easily opening connections to particular servers (like [VirtualFlyBrain's CATMAID server](https://fanc.catmaid.virtualflybrain.org/)) where the reconstructions from [this paper](https://www.lee.hms.harvard.edu/maniatesselvin-et-al-2020) are hosted), as well as some other utilities. See below for details.

This package was pulled out of the [GridTape_VNC_paper](https://github.com/htem/GridTape_VNC_paper/tree/master/pymaid_utils) repository. This repository is where development of the package will continue.

This package contains 3 modules:

#### `connections.py`
Opens a connection to a CATMAID server, reading the needed URL and account info from a config file stored in the `connection_configs` folder. Example credentials files are provided for connecting to Virtual Fly Brain's CATMAID servers for FAFB, FANC, and the L1 larva.

#### `make_3dViewer_json.py`
A collection of functions to create json configuration files for the CATMAID 3D viewer widget, by providing a mapping between colors and lists of annotations to search for. The workhorses here are `make_json_by_annotations` for converting annotation lists to skeleton ID lists, and `write_catmaid_json` for writing out a correctly formatted file.

    # Example:
    import pymaid_addons as pa
    > Connecting to catmaid...
    > Source project: 1 Adult Brain  # This means that the default connection file located at
                                     # connection_configs/default_connection.json is linked to point to
                                     # connection_configs/virtualflybrain_FAFB.json. The below example
                                     # only works when connected to that server.
    pa.make_json_by_annotations({'cyan': 'Paper: Kim et al 2020', 'magenta': 'FBbt:00110882'}, 'FAFB_example')
    > ['Paper: Kim et al 2020']
    > Found 95 neurons
    > ['FBbt:00110882']
    > Found 11 neurons
    > CATMAID json written to project1_FAFB_example.json. Use this file at https://fafb.catmaid.virtualflybrain.org/?pid=1

    pa.connect_to('larva')
    > Connecting to catmaid...
    > Source project: 1 L1 CNS  # Now connected to the L1 larva catmaid project
    pa.make_rainbow_json_by_position('A1 motorneurons', 'larva_a1_motor_neurons', extract_position='root_x')
    > CATMAID json written to project1_a1_motor_neurons.json. Use this file at https://l1em.catmaid.virtualflybrain.org/?pid=1



#### `manipulate_and_reupload_catmaid_neurons.py`
Pull neuron data from one CATMAID project, manipulate the neuron in some way, and reupload it to a target project. These functions require that you add credentials for a target project in the connections_config file for which you have API annotation privileges. This is only relevant for users that have their own CATMAID instances - users looking to just pull neuron data from VirtualFlyBrain for examining can ignore this module. **Be careful with these functions, as they directly modify data on your CATMAID server.**

Uploaded neurons are given a 'linking annotation' that allows uploaded neurons to know which source neuron they were generated from. This linking annotation enables the function `push_all_updates_by_annotations`/`push_all_updates_by_skid` to straightforwardly updated linked neurons in a target project if their source neuron has been modified somehow, for instance by adding annotations or tracing. This ensures that duplicate neurons are not made in the target project when such modifications are pushed, and also ensures that the skeleton ID of the target neuron never changes, which means code or .json files that identify neurons by their skeleton ID don't need to be updated after updating a linked neuron.
1. `copy_neurons`: No modifications to the neuron
2. `translate_neurons`: Apply a translation
3. `affinetransform_neurons`: Apply an affine transformation
4. `elastictransform_neurons`: Apply an elastic transformation. Uses the function [transformix](https://manpages.debian.org/testing/elastix/transformix.1.en.html) from the [elastix](https://elastix.lumc.nl/) package, which must be installed. Used in the [GridTape/VNC paper](https://www.lee.hms.harvard.edu/maniatesselvin-et-al-2020) to take [neurons reconstructed in the VNC EM dataset](https://catmaid3.hms.harvard.edu/catmaidvnc/?pid=2&zp=168300&yp=583144.5&xp=186030.9&tool=tracingtool&sid0=10&s0=7) and warp them them to the coordinate space of the VNC standard atlas (JRC2018_FEMALE_VNC), and upload those warped neurons to a [separate CATMAID project](https://catmaid3.hms.harvard.edu/catmaidvnc/?pid=59&zp=71200&yp=268000&xp=131600&tool=tracingtool&sid0=49&s0=1).
5. `volume_prune_neurons`: Prune a neuron to the parts that are within a CATMAID volume object. Used in the GridTape/VNC paper to prune neurons down to the regions within the VNC's neuropil.
6. `radius_prune_neurons`: Prune a neuron to only the nodes that have a certain radius. Used in the GridTape/VNC paper to prune motor neurons down to their primary neurites.

#### Additionally, `__init__.py`
Upon importing this package, `__init__.py` opens a connection to CATMAID using `connetions.connect_to_catmaid()`, which uses the default parameters at `connection_configs/default_connection.json`. Then, `__init__.py` shares access to that connection object with each of the 3 modules above, so that changes in the connection (like changing project ID) will be seen by each of the modules.

To use `pymaid_addons` to easily open a CATMAID connection for use by `pymaid` functions, you can do something like the following:

    import pymaid
    import pymaid_addons as pa
    pymaid.whatever_pymaid_function_you_want_to_use(args)  # https://pymaid.readthedocs.io/en/latest/index.html
    #OR
    pymaid.whatever_pymaid_function_you_want_to_use(args, remote_instance=pa.source_project)
    # If you have both a source and a target project, then the source project
    # won't be set to be a global connection, so you need to explicitly pass
    # either pa.source_project or pa.target_project project to pymaid functions.

    pa.connect_to('larva')  # Now connect to VFB's L1 larva data. Nicknames 'fafb', 'fanc', and 'larva' work.
    pa.now_call_functions_to_access_larva_reconstructions(args)
