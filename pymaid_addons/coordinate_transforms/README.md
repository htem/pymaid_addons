A set of functions that transform skeleton nodes in different ways. Each function must take an Nx3 numpy array (representing the x, y, z coordinates in nanometers of N skeleton nodes) and return an Nx3 numpy array (representing the transformed coordinates in nanometers).

### `warp_points_between_FANC_and_template.py`
Performs an elastix transformation to warp points between the Full Adult Nerve Cord GridTape-TEM dataset and the VNC atlas `JRC2018_VNC_FEMALE`. This script is a slight adaptation of the script originally released [here](https://github.com/htem/GridTape_VNC_paper/blob/master/template_registration_pipeline/register_EM_dataset_to_template/warp_points_between_FANC_and_template.py)

### `affine_transforms.py`
Implements affine transformations.
