#!/usr/bin/env python

from enum import Enum


class GraphMetricType(Enum):
    SHORTEST = (0, "Shortest metric", (1.0, 0.0, 0.0))
    FLATTEST = (1, "Flattest metric", (1.0, 1.0, 1.0))
    ENERGY = (2, "Most energy efficient metric", (1.0, 1.0, 0.0))
    COMBINED = (3, "Combined metric", (0.0, 1.0, 0.0))
    STRAIGHTEST = (4, "Straightest metric", (0.5, 1.0, 0.5))
    FLATTEST_SIM = (5, "Flattest metric", (0.5, 0.5, 0.5))
    FLATTEST_PYBULLET = (6, "Flattest metric using PyBullet for angle estimation", (0.5, 0.5, 0.5))
    FLATTEST_OPTIMIZATION = (7, "Flattest metric using Linear Programming Optimization for angle estimation",
                             (0.5, 0.5, 0.5))
    FLATTEST_PYBULLET_NORMAL = (8, "Flattest metric using PyBullet with selective pruning of neighbouring normals",
                                (0.5, 0.5, 0.5))
    FLATTEST_OPTIMIZATION_NORMAL = (9, "Flattest metric using Linear Programming Optimization with selective "
                                       "pruning of neighbouring normals", (0.5, 0.5, 0.5))
    FLATTEST_COMPARISON_TEST = (10, "Compare angle between all flattest", (0.5, 0.5, 0.5))
    GLOBAL = (11, "A global path", (0.5, 0.5, 0.5))
