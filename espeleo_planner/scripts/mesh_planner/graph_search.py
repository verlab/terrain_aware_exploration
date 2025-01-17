#!/usr/bin/env python

from heapq import heappush, heappop
from itertools import count
import networkx as nx
import numpy as np
from .graph_metrics import GraphMetricType
from . import mesh_helper
from prettytable import PrettyTable
import math
import time
from scipy import spatial


class MeshGraphSearch:
    """
    Mesh Graph Search given a graph it calculates the optimum paths for an specific metric
    """

    def __init__(self, G, metric, centroids, normals, c_short=0.25, c_energy=0.25, c_traversal=0.5,
                 pybullet_angle_client=None, optimization_angle_client=None):
        """MeshGraphSearch constructor

        :param G: initial undirected graph
        :param metric: edge metric to use
        :param centroids: centroids of the faces
        :param normals: normals of the faces
        :param c_short: the constant for the weight of the shortest path in the combined metric
        :param c_energy: the constant for the weight of the least energy consuming path in the combined metric
        :param c_traversal: the constant for the weight of the flattest path in the combined metric
        """
        self.G = G
        self.metric = metric

        self.centroids = centroids
        self.normals = normals
        self.c_short = c_short
        self.c_energy = c_energy
        self.c_traversal = c_traversal
        self.c_threshold_std_angle_terrain = 5

        self.path = None
        self.path_distance = None

        self.min_dist = 0
        self.max_dist = 0
        self.min_traversability = 0
        self.max_traversability = 0
        self.min_energy = 0
        self.max_energy = 0
        self.min_rotation = 0
        self.max_rotation = 0

        self.last_execution_time = 0

        # estimate the min man list only for the combined metric
        # since this is the only metric that normalize values
        # if self.metric == GraphMetricType.COMBINED:
        self.estimate_min_max()

        self.border_3d_points = []
        self.border_kdtree = None

        self.pybullet_angle_client = pybullet_angle_client
        self.optimization_angle_client = optimization_angle_client

        if (self.metric == GraphMetricType.FLATTEST_PYBULLET or
            self.metric == GraphMetricType.FLATTEST_PYBULLET_NORMAL) and self.pybullet_angle_client is None:
            raise ValueError("Pybullet client is None and the metric used Pybullet")

        if (self.metric == GraphMetricType.FLATTEST_OPTIMIZATION or
            self.metric == GraphMetricType.FLATTEST_OPTIMIZATION_NORMAL) and self.optimization_angle_client is None:
            raise ValueError("Optimization client is None and the metric used optimization")

    def get_path(self):
        """Return the list of nodes that generates the path

        :return: list of nodes forming the path
        """
        return self.path

    def get_path_distance(self):
        """Return the path distance estimated by the Dijkstra algorithm
        If called before the dijkstra algorithm return None

        :return: the estimated path distance
        """
        return self.path_distance

    def estimate_min_max(self):
        """Estimate the minimum and maximum values for every metric inside the graph
        this data is utilized for normalization when using the combined metrics
        """
        distances = []
        energy_consumptions = []
        traversabilities = []
        rotations = []

        for v in self.G.nodes():
            neighbors = self.G.neighbors(v)

            for u in neighbors:
                distances.append(self.weight_euclidean_distance(v, u))
                energy_consumptions.append(self.weight_energy(v, u))
                traversabilities.append(self.weight_traversability(u))
                rotations.append(self.weight_rotation(v, u))

        self.min_dist, self.max_dist = min(distances), max(distances)
        self.min_energy, self.max_energy = min(energy_consumptions), max(energy_consumptions)
        self.min_traversability, self.max_traversability = min(traversabilities), max(traversabilities)
        self.min_rotation, self.max_rotation = min(rotations), max(rotations)

    def dijkstra_search(self, sources, target, cutoff=None):
        """Find shortest weighted paths and lengths from a given set of
        source nodes.

        Uses Dijkstra's algorithm to compute the shortest paths and lengths
        between one of the source nodes and the given `target`, or all other
        reachable nodes if not specified, for a weighted graph.

        :param sources: source node
        :param target: destination node
        :param cutoff: integer or float, optional
            Depth to stop the search. Only return paths with length <= cutoff.
        :return:
        """

        start_time = time.clock()

        if not sources:
            raise ValueError('src must not be empty')

        if sources in sources:
            self.last_execution_time = 0
            return 0, [sources]

        pred = {source: [] for source in sources}
        paths = {source: [source] for source in sources}  # dictionary of paths
        dist = self._dijkstra_multisource(sources, pred=pred, paths=paths, cutoff=cutoff, target=target)
        self.last_execution_time = time.clock() - start_time

        if target is None:
            return dist, paths
        try:
            self.path = paths[target]
            self.path_distance = dist[target]
            return dist[target], paths[target]
        except KeyError:
            raise nx.NetworkXNoPath("No path to {}.".format(target))

    def _dijkstra_multisource(self, sources, pred=None, paths=None, cutoff=None, target=None):
        """Uses Dijkstra's algorithm to find shortest weighted paths

        Parameters
        ----------
        G : NetworkX graph

        sources : non-empty iterable of nodes
            Starting nodes for paths. If this is just an iterable containing
            a single node, then all paths computed by this function will
            start from that node. If there are two or more nodes in this
            iterable, the computed paths may begin from any one of the start
            nodes.

        weight: function
            Function with (u, v, data) input that returns that edges weight

        pred: dict of lists, optional(default=None)
            dict to store a list of predecessors keyed by that node
            If None, predecessors are not stored.

        paths: dict, optional (default=None)
            dict to store the path list from source to each node, keyed by node.
            If None, paths are not stored.

        target : node label, optional
            Ending node for path. Search is halted when target is found.

        cutoff : integer or float, optional
            Depth to stop the search. Only return paths with length <= cutoff.

        Returns
        -------
        distance : dictionary
            A mapping from node to shortest distance to that node from one
            of the source nodes.

        Raises
        ------
        NodeNotFound
            If any of `sources` is not in `G`.

        Notes
        -----
        The optional predecessor and path dictionaries can be accessed by
        the caller through the original pred and paths objects passed
        as arguments. No need to explicitly return pred or paths.

        """
        G_succ = self.G._succ if self.G.is_directed() else self.G._adj
        push = heappush
        pop = heappop
        dist = {}  # dictionary of final distances
        seen = {}
        # fringe is heapq with 3-tuples (distance,c,node)
        # use the count c to avoid comparing nodes (may not be able to)
        c = count()
        fringe = []

        for source in sources:
            if source not in self.G:
                raise nx.NodeNotFound("Source {} not in G".format(source))
            seen[source] = 0
            push(fringe, (0, next(c), source))

        while fringe:
            (d, _, v) = pop(fringe)  # this v is the next node to path

            if v in dist:
                continue  # already searched this node.
            dist[v] = d
            if v == target:
                break
            for u, e in list(G_succ[v].items()):
                # cost = weight(v, u, e)     # original cost function from v to u
                cost = self.edge_weight_by_metric(v, u, pred[v])

                if cost is None:
                    continue
                vu_dist = dist[v] + cost
                if cutoff is not None:
                    if vu_dist > cutoff:
                        continue
                if u in dist:
                    if vu_dist < dist[u]:
                        print("vu_dist:", vu_dist, "dist[v]:", dist[v], 'cost:', cost, "dist[u]:", dist[u], 'v', v, 'u', u, "pred[v]:", pred[v])
                        raise ValueError('Contradictory paths found:',
                                         'negative weights?')
                elif u not in seen or vu_dist < seen[u]:
                    seen[u] = vu_dist  # seen[u] = a weight
                    push(fringe, (vu_dist, next(c), u))
                    if paths is not None:
                        paths[u] = paths[v] + [u]
                    if pred is not None:
                        pred[u] = [v]
                elif vu_dist == seen[u]:
                    if pred is not None:
                        pred[u].append(v)

        # The optional predecessor and path dictionaries can be accessed
        # by the caller via the pred and paths objects passed as arguments.
        return dist

    def edge_weight_by_metric(self, v, u, pred):
        """Estimate the weight of an edge given a metric (self.metric)

        :param source: id of the source node
        :param target: if of the target node
        :return:
        """

        pred_node = None
        if len(pred) > 0:
            pred_node = pred[0]

        if self.metric == GraphMetricType.SHORTEST:
            d = self.weight_euclidean_distance(v, u)
            return d

        elif self.metric == GraphMetricType.FLATTEST or self.metric == GraphMetricType.FLATTEST_COMPARISON_TEST:
            # this metric also uses the euclidean distance to minimze
            # flipping around in zigzag motion
            # use traditional normal vector of the face
            d = self.weight_euclidean_distance(v, u)
            target_traversal_normal = self.weight_traversability(u)

            if self.metric == GraphMetricType.FLATTEST_COMPARISON_TEST:
                start_pos = (self.centroids[u][0], self.centroids[u][1], self.centroids[u][2])
                final_pos, final_vector = self.pybullet_angle_client.estimate_pose(start_pos)
                target_traversal_pybullet = self.calculate_traversal_angle(final_vector)

                final_vector = self.optimization_angle_client.estimate_pose(self.centroids[u])
                target_traversal_optimization = self.calculate_traversal_angle(final_vector)

                vector = self.optimization_angle_client.estimate_pose(self.centroids[u])
                target_traversal_optimization = self.calculate_traversal_angle(vector)

                #print "angles:", [target_traversal_pybullet, target_traversal_optimization, target_traversal_normal]

            return target_traversal_normal + d
        elif self.metric == GraphMetricType.FLATTEST_PYBULLET or \
                self.metric == GraphMetricType.FLATTEST_PYBULLET_NORMAL:
            # this metric also uses the euclidean distance to minimze
            # flipping around in zigzag motion
            # use the pybullet engine
            d = self.weight_euclidean_distance(v, u)

            if self.metric == GraphMetricType.FLATTEST_PYBULLET_NORMAL:
                mean, std = self.get_neighbours_angle_mean_std(u)
                # if std is bellow threshold use the quicker normal angle estimation
                if std <= self.c_threshold_std_angle_terrain:
                    return self.weight_traversability(u) + d

            start_pos = (self.centroids[u][0], self.centroids[u][1], self.centroids[u][2])
            final_pos, final_vector = self.pybullet_angle_client.estimate_pose(start_pos)
            target_traversal_pybullet = self.calculate_traversal_angle(final_vector)
            return target_traversal_pybullet + d

        elif self.metric == GraphMetricType.FLATTEST_OPTIMIZATION or \
                self.metric == GraphMetricType.FLATTEST_OPTIMIZATION_NORMAL:
            # this metric also uses the euclidean distance to minimze
            # flipping around in zigzag motion
            d = self.weight_euclidean_distance(v, u)

            if self.metric == GraphMetricType.FLATTEST_OPTIMIZATION_NORMAL:
                mean, std = self.get_neighbours_angle_mean_std(u)
                # if std is bellow threshold use the quicker normal angle estimation
                if std <= self.c_threshold_std_angle_terrain:
                    return self.weight_traversability(u) + d

            final_vector = self.optimization_angle_client.estimate_pose(self.centroids[u])
            target_traversal_optimization = self.calculate_traversal_angle(final_vector)
            return target_traversal_optimization + d

        elif self.metric == GraphMetricType.ENERGY:
            # todo check diferences between new code and old code
            energy = self.weight_energy(v, u, predecessor=pred_node)
            return energy

        elif self.metric == GraphMetricType.COMBINED:
            # todo: check if this combined metric uses weight_rotation too?
            dist = self.weight_euclidean_distance(v, u)
            short_weight = mesh_helper.normalize_from_minmax(dist, self.min_dist, self.max_dist)

            traversal = self.weight_traversability(u)
            #print "traversal:", traversal, self.min_traversability, self.max_traversability
            traversal_weight = mesh_helper.normalize_from_minmax(traversal, self.min_traversability, self.max_traversability)

            energy = self.weight_energy(v, u, predecessor=pred_node)
            energy_weight = mesh_helper.normalize_from_minmax(energy, self.min_energy, self.max_energy)

            total_weight = (short_weight * self.c_short) + \
                           (traversal_weight * self.c_traversal) + \
                           (energy_weight * self.c_energy)

            return total_weight

        elif self.metric == GraphMetricType.STRAIGHTEST:
            rot = self.weight_rotation(v, u, predecessor=pred_node)
            return rot

        else:
            raise TypeError("No valid Metric Type available to estimate edge weight {}".format(self.metric))

    def weight_euclidean_distance(self, v, u):
        """Calculate the 3D euclidean distance between a pair of nodes

        :param v: id of the source node
        :param u: id of the target node
        :return:
        """
        a = np.asarray(self.centroids[v])
        b = np.asarray(self.centroids[u])

        return np.linalg.norm(a-b)

    def weight_traversability(self, u):
        """Calculate the traversability of a node face
        Traversability is given by the inclination of the face with respect to the gravity vector (0, 0, -1)

        :param u: id of the target node
        :return: traversal angle in degrees
        """
        return MeshGraphSearch.calculate_traversal_angle(self.normals[u])

    @staticmethod
    def calculate_traversal_angle(face_normal, z_vector=(0, 0, -1)):
        """Public method Calculate the traversability of a node face
        Traversability is given by the inclination of the face with respect to the gravity vector (0, 0, -1)
        :param face_normal:
        :param z_vector:
        :return: traversal angle in degrees
        """
        theta = mesh_helper.angle_between_vectors(face_normal, z_vector)

        # overcome inverted normals by normalizing the opposite angle (90-180) to 0-90
        if theta > 90:
            theta = math.fabs(theta - 180)

        return theta

    def weight_energy(self, v, u, predecessor=None):
        """Calculate the energy cost between a pair of nodes

        :param v: id of the source node
        :param u: id of the target node
        :param predecessor: id of the predecessor nodes
        :return:
        """
        src = np.asarray(self.centroids[v])
        tgt = np.asarray(self.centroids[u])
        v_tgtsrc = tgt - src

        if not predecessor:
            rot = mesh_helper.angle_between_vectors(src, tgt)
            angle = mesh_helper.angle_between_vectors(v_tgtsrc, (0, 0, -1))
        else:
            pred = np.asarray(self.centroids[predecessor])
            v_srcpred = src - pred

            rot = mesh_helper.angle_between_vectors(v_srcpred, v_tgtsrc)
            angle = mesh_helper.angle_between_vectors(v_srcpred, (0, 0, -1))

        angle = 90 - angle
        dist = self.weight_euclidean_distance(v, u)

        if angle < 0:
            energy = (((37735.9 * rot) / 360) + ((-475.07 * angle) + 1089.3)) * dist
        else:
            energy = (((37735.9 * rot) / 360) + ((564.97 * angle) + 1364.9)) * dist

        return energy

    def weight_rotation(self, v, u, predecessor=None):
        """Calculate the horizontal rotation between a pair of nodes

        :param v: id of the source node
        :param u: id of the target node
        :param predecessor: id of the predecessor nodes
        :return:
        """
        src = np.asarray(self.centroids[v][:2])
        tgt = np.asarray(self.centroids[u][:2])
        v_tgtsrc = tgt - src

        if not predecessor:
            return 0

        pred = np.asarray(self.centroids[predecessor][:2])
        v_srcpred = src - pred

        res = mesh_helper.angle_between_vectors(v_srcpred, v_tgtsrc)
        return res

    def weight_border(self, u, d0=2.0, c1=3, min_dist=0.2):
        """Calculate the weight based on distance from border nodes
        This weight aims to penalize paths closer to dangerous areas such as map borders and obstacles
        Using repulsive potential fields https://youtu.be/MQjeqvbzhGQ?t=222
        http://people.csail.mit.edu/lpk/mars/temizer_2001/Potential_Field_Method/index.html
        d0 = mininum_distance to evaluate
        c1 = scale constant
        obstacle_d = distance to the closest obstacle

        if obstacle_d <= d0:
            c1 * (1/obstacle_d - 1/d0)^2
        else:
            0

        IMPORTANT: not actively used, this code serve as reference for future potential field functions

        :param u: id of the target node
        :param d0: minimum distance to evaluate
        :param c1: scale constant
        :param min_dist: minimum distance to use as treshold, any value < to min_dist is set to the min_dist value
        :return: repulsive weight
        """
        if not self.border_kdtree:
            # todo add warning
            return 0

        distances, nearest_idx = self.border_kdtree.query([self.centroids[u]])
        obstacle_d = distances[0]

        if obstacle_d <= min_dist:
            # treating very close distances to prevent exploding values
            obstacle_d = min_dist

        if obstacle_d <= d0:
            repulsive_w = 1/2.0 * c1 * (((1 / float(obstacle_d)) - (1 / float(d0))) ** 2)
        else:
            repulsive_w = 0

        return repulsive_w

    def get_neighbours_angle_mean_std(self, u):
        """
        Get the mean and standard deviation of the neighbours angles
        considering a weighted mean. The weights are estimated using a
        gaussian decay function.
        :param u:
        :return:
        """

        def second_neighbors(graph, node):
            """Yield second neighbors of node in graph.
            Neighbors are not not unique!
            """
            yield node
            for dn in graph.neighbors(node):
                for sn in graph.neighbors(dn):
                    yield sn

        def estimate_decay(x, mu=0, variance=0.3, height=1.0):
            """
            Estimate decay given the distance of the faces to the current node position
            :param x:
            :param mu:
            :param variance:
            :param height:
            :return:
            """
            return height * math.exp(-math.pow(x - mu, 2) / (2 * variance))

        def weighted_avg_and_std(values, weights):
            """
            Return the weighted average and standard deviation.

            values, weights -- Numpy ndarrays with the same shape.
            https://stackoverflow.com/questions/2413522/weighted-standard-deviation-in-numpy
            """
            average = np.average(values, weights=weights)
            var = np.average((values - average) ** 2, weights=weights)
            return average, math.sqrt(var)

        neighbours_ids = sorted(list(set(second_neighbors(self.G, u))))

        neighbours_data = []
        for neigh_idx in neighbours_ids:
            face_angle = self.calculate_traversal_angle(self.normals[neigh_idx])
            d = self.weight_euclidean_distance(neigh_idx, u)
            decay = estimate_decay(d)

            neighbours_data.append({
                'theta': face_angle,
                'decay': decay
            })

            #print 'theta:', face_angle, '\tdecay:', decay, '\td:', d

        theta_list = np.array([a['theta'] for a in neighbours_data])
        decay_list = np.array([a['decay'] for a in neighbours_data])
        decay_list[np.abs(decay_list) < 0.001] = 0

        avg, std = weighted_avg_and_std(theta_list, decay_list)
        #print [avg, std]
        return avg, std

    def get_last_execution_time(self):
        """
        Return last execution time in seconds
        :return:
        """
        return self.last_execution_time

    def print_path_metrics(self):
        """ Print this graph metrics in a tabular format
        distance, energy, rotation and traversability (min, max, mean, dev, and total)
        """

        path = self.get_path()
        if not path:
            raise AssertionError("there is no path to calculate properties (self.path == None)")

        distances = []
        energy_consumptions = []
        traversabilities = []
        rotations = []

        for i in range(len(path) - 1):
            node_source = path[i]
            node_target = path[i + 1]

            if node_source == path[0]:
                predecessor = None
            else:
                predecessor = path[i - 1]

            distances.append(self.weight_euclidean_distance(node_source, node_target))
            traversabilities.append(self.weight_traversability(node_target))
            energy_consumptions.append(self.weight_energy(node_source, node_target, predecessor))
            rotations.append(self.weight_rotation(node_source, node_target, predecessor))

        table = PrettyTable()

        table.field_names = ["{} PATH ({:.2f} sec)".format(self.metric.name, self.get_last_execution_time()),
                             "Distance", "Energy", "Rotation", "Traversality"]
        table.float_format = ".2"

        table.add_row(["min", self.min_dist, self.min_energy, self.min_rotation, self.min_traversability])
        table.add_row(["max", self.max_dist, self.max_energy, self.max_rotation, self.max_traversability])
        table.add_row(["mean", np.mean(distances), np.mean(energy_consumptions), np.mean(rotations), np.mean(traversabilities)])
        table.add_row(["std dev", np.std(distances), np.std(energy_consumptions), np.std(rotations), np.std(traversabilities)])
        table.add_row(["sum", sum(distances), sum(energy_consumptions), sum(rotations), sum(traversabilities)])

        print(table)

