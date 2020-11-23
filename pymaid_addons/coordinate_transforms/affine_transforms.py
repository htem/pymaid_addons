#!/usr/bin/env python3

import numpy as np

arr = lambda x: np.array(x)

transform_matrices = {
    'reflect_x': {
        'A': arr([[-1, 0, 0],
                  [ 0, 1, 0],
                  [ 0, 0, 1]]), 
        'b': arr([320000, 0, 0])
    }
}


def affine_transform(points, A, b):
    """
    Implements
    transformed_points = (A*points' + b)'
    where
    A (3x3 numpy array) = transformation matrix
    points (Nx3 numpy array) = input points
    ' = transpose
    b (3x1 numpy array) = offset

    """
    return (np.matmul(A, points.T) + b).T
