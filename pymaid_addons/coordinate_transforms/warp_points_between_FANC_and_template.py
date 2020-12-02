#!/usr/bin/env python3

# Wrappers for the program transformix, part of the library elastix

# This file is a slight adaptation of
# https://github.com/htem/GridTape_VNC_paper/blob/master/template_registration_pipeline/register_EM_dataset_to_template/warp_points_between_FANC_and_template.py

import os
import os.path
import subprocess
import numpy as np

template_plane_of_symmetry_x_voxel = 329
template_plane_of_symmetry_x_microns = 329 * 0.400

def warp_points_FANC_to_template(points,
                                 input_units='nm',
                                 output_units='nm',
                                 reflect=False):
    points = np.array(points, dtype=np.float64)
    if len(points.shape) == 1:
        return warp_points_FANC_to_template(np.expand_dims(points, 0),
                                            input_units, output_units)[0]
    if input_units == 'nm' and (points < 1000).all():
        resp = input('Your points appear to be in microns, not nm. Want to'
                     ' change input_units from nm to microns? [y/n] ')
        if resp.lower() == 'y':
            input_units = 'microns'
    if input_units in ['um', 'microns']:
        points *= 1000  # Convert microns to nm

    points -= (533.2, 533.2, 945)  # (1.24, 1.24, 2.1) vox at (430, 430, 450)nm/vox
    points /= (430, 430, 450)
    points *= (300, 300, 400)
    points[:, 2] = 435*400 - points[:, 2]  # z flipping a stack with 436 slices
    points /= 1000  # Convert nm to microns

    transform_params = os.path.join(
        os.path.dirname(__file__),
        'TransformParameters.FixedFANC.txt'
    )
    points = transformix(points, transform_params)

    if not reflect:
        points[:, 0] = template_plane_of_symmetry_x_microns * 2 - points[:, 0]
    if output_units == 'nm':
        points *= 1000  # Convert microns to nm

    return points


def warp_points_template_to_FANC(points,
                                 input_units='nm',
                                 output_units='nm',
                                 reflect=False):
    points = np.array(points)
    if len(points.shape) == 1:
        return warp_points_template_to_FANC(np.expand_dims(points, 0),
                                            input_units, output_units)[0]
    if input_units == 'nm' and (points < 1000).all():
        resp = input('Your points appear to be in microns, not nm. Want to'
                     ' change input_units from nm to microns? [y/n] ')
        if resp.lower() == 'y':
            input_units = 'microns'
    if input_units == 'nm':
        points /= 1000  # Convert nm to microns

    if not reflect:
        points[:, 0] = template_plane_of_symmetry_x_microns * 2 - points[:, 0]
    transform_params = os.path.join(
        os.path.dirname(__file__),
        'TransformParameters.FixedTemplate.Bspline.txt'
    )
    points = transformix(points, transform_params)

    points *= 1000  # Convert microns to nm
    points[:, 2] = 435*400- points[:, 2]  # z flipping a stack with 436 slices
    points /= (300, 300, 400)
    points *= (430, 430, 450)
    points += (533.2, 533.2, 945)  # (1.24, 1.24, 2.1) vox at (430, 430, 450)nm/vox

    if output_units in ['um', 'microns']:
        points /= 1000  # Convert nm to microns
    return points


def transformix(points, transformation_file):
    def write_points_as_transformix_input_file(points, fn):
        with open(fn, 'w') as f:
            f.write('point\n{}\n'.format(len(points)))
            for x, y, z in points:
                f.write('%f %f %f\n'%(x, y, z))

    starting_dir = os.getcwd()
    if '/' in transformation_file:
        os.chdir(os.path.dirname(transformation_file))

    for fn in ['transformix_input.txt', 'outputpoints.txt', 'transformix.log']:
        if os.path.exists(fn):
            m = ('Temporary file '+fn+' already exists in '+os.getcwd()+'. '
                 'Continuing will delete it. Continue? [Y/n] ')
            if input(m).lower() != 'y':
                wd = os.getcwd()
                os.chdir(starting_dir)
                raise FileExistsError(wd+'/'+fn+' must be removed.')
            else:
                os.remove(fn)

    try:
        fn = 'transformix_input.txt'
        write_points_as_transformix_input_file(points, fn)
        transformix_cmd = 'transformix -out ./ -tp {} -def {}'.format(
            transformation_file,
            fn
        )
        subprocess.run(transformix_cmd.split(' '), stdout=subprocess.DEVNULL)
        if not os.path.exists('outputpoints.txt'):
            # Run again but this time let the error message print
            subprocess.run(transformix_cmd.split(' '))
            raise Exception('transformix failed, see output above for details')

        new_pts = []
        with open('outputpoints.txt', 'r') as transformix_out:
            for line in transformix_out.readlines():
                output = line.split('OutputPoint = [ ')[1].split(' ]')[0]
                new_pts.append([float(i) for i in output.split(' ')])
    finally:
        try: os.remove('transformix_input.txt')
        except: pass
        try: os.remove('outputpoints.txt')
        except: pass
        try: os.remove('transformix.log')
        except: pass
        os.chdir(starting_dir)

    return np.array(new_pts)
