#!/usr/bin/env python

import os
import sys
import rospy
import pymesh
import rospkg
import traceback
import mesh_planner
from visualization_msgs.msg import Marker
from mesh_planner import mesh_helper, graph_metrics, mesh_planner_base, mesh_planner_node


if __name__ == '__main__':
    rospy.init_node('test_mesh_planner_node')

    mplanner = mesh_planner_node.MeshPlannerNode()

    pub_mesh_marker = rospy.Publisher('/reconstructed_mesh_marker_normal', Marker, latch=True, queue_size=1)
    rate_slow = rospy.Rate(1.0)
    rate_fast = rospy.Rate(10.0)

    try:
        rospy.loginfo("Start planning...")
        src = (7.76, 1.16, -0.05)
        dst = (-8.37, 10.53, 0)
        test_stl_filename = "map_01_frontiers.stl"

        rospack = rospkg.RosPack()
        pkg_path = rospack.get_path('espeleo_planner')
        mesh_filepath = os.path.join(pkg_path, "test", "maps", test_stl_filename)
        rospy.loginfo("mesh_filepath: %s", mesh_filepath)

        mesh_marker = mesh_helper.create_marker((0, 0, 0),
                                               m_scale = 1.0,
                                               color=(0.0, 0.0, 1.0), duration=0, marker_id=2,
                                               mesh_resource="file://" + mesh_filepath)
        pub_mesh_marker.publish(mesh_marker)

        src_marker = mesh_helper.create_marker(src, color=(0.0, 1.0, 0.0), duration=0, marker_id=0)
        mplanner.pub_src_point.publish(src_marker)

        dst_marker = mesh_helper.create_marker(dst, color=(0.0, 0.0, 1.0), duration=0, marker_id=1)
        mplanner.pub_dst_point.publish(dst_marker)

        rate_fast.sleep()

        # load the mesh and locate the face closer to the src and dst points
        mesh_load = pymesh.load_mesh(mesh_filepath)
        mesh_load.add_attribute("face_centroid")
        centroids = mesh_load.get_face_attribute("face_centroid")

        vertices = mesh_load.vertices
        ver_face = mesh_load.faces

        source_face = mesh_helper.find_closer_centroid(centroids, src, force_return_closer=True)

        target_face = mesh_helper.find_closer_centroid(centroids, dst, force_return_closer=True)

        # check if src and dst faces are found
        if source_face == -1 or target_face == -1:
            rospy.loginfo("Cannot find the target or source face: src:%d dst:%d", source_face, target_face)
            rate_slow.sleep()
            sys.exit()

        # graph_metric_types = [graph_metrics.GraphMetricType.SHORTEST,
        #                       graph_metrics.GraphMetricType.FLATTEST,
        #                       graph_metrics.GraphMetricType.ENERGY,
        #                       graph_metrics.GraphMetricType.COMBINED,
        #                       graph_metrics.GraphMetricType.STRAIGHTEST]

        # graph_metric_types = [graph_metrics.GraphMetricType.STRAIGHTEST]
        # graph_metric_types = [graph_metrics.GraphMetricType.SHORTEST]
        graph_metric_types = [graph_metrics.GraphMetricType.COMBINED]

        planner = mesh_planner_base.MeshPlannerBase(mesh_filepath, graph_metric_types)
        return_dict = planner.run(source_face, target_face)
        mplanner.publish_paths(return_dict)

        rospy.signal_shutdown(0)
        sys.exit()
    except Exception as e:
        tb = traceback.format_exc()
        rospy.logerr("Main Exception: %s", str(tb))

    rospy.loginfo("MeshPlanner node stop")
