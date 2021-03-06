# Implementation with adaptation of the Normal Vector Voting algorithm of Page et al. from 2002.

import time
import numpy as np


# Runs the modified Vector Voting algorithm for the given triangle graph with the given parameters:
# integer k (multiple of the average length of the triangle edges), epsilon (default 2) and eta (default 2).
# Returns the surface of triangles with classified orientation and estimated normals / tangents and curvatures (vtkPolyData object) as well the underlying triangle-graph (TriangleGraph object).
def vector_voting(tg, k, epsilon=2, eta=2, all_vertices=True, exclude_borders=True):
    # Preparation (calculations & printouts that are the same for the whole graph)
    t_begin = time.time()
    print '\nPreparing for running modified Vector Voting...'

    # * k, integer multiple of the average length of the triangle edges *
    print "k = %s" % k

    # * Average length of the triangle edges *
    avg_weak_edge_length = tg.calculate_average_edge_length(prop_e="is_strong", value=0)  # weak edges of triangle graph are the most similar in length to the triangle edges
    try:
        assert(avg_weak_edge_length > 0)
    except AssertionError:
        print "Something wrong in the graph construction has happened: average weak edge length is 0."
        exit(1)

    # * Maximal geodesic distance g_max and sigma (depend on k but is also the same for the whole graph) *
    g_max = k * avg_weak_edge_length
    print "g_max = %s" % g_max
    sigma = g_max / 3.0

    # * Maximal triangle area *
    A, _ = tg.get_areas()
    A_max = np.max(A)
    print "Maximal triangle area = %s" % A_max

    # * Orientation classification parameters *
    print "epsilon = %s" % epsilon
    print "eta = %s" % eta

    # * Adding vertex properties to be filled in classifying_orientation *
    # vertex property storing the orientation class of the vertex: 1 if it belongs to a surface patch, 2 if it belongs to a crease junction or 3 if it doesn't have a preferred orientation:
    tg.graph.vp.orientation_class = tg.graph.new_vertex_property("int")
    # vertex property for storing the estimated normal of the corresponding triangle (if the vertex belongs to class 1; scaled in nm):
    tg.graph.vp.N_v = tg.graph.new_vertex_property("vector<float>")
    # vertex property for storing the estimated tangent of the corresponding triangle (if the vertex belongs to class 2; scaled in nm):
    tg.graph.vp.T_v = tg.graph.new_vertex_property("vector<float>")

    # * Adding vertex properties to be filled in estimate_curvature *
    # vertex property for storing the estimated principal directions of the maximal curvature of the corresponding triangle (if the vertex belongs to class 1; scaled in nm):
    tg.graph.vp.T_1 = tg.graph.new_vertex_property("vector<float>")
    # vertex property for storing the estimated principal directions of the minimal curvature of the corresponding triangle (if the vertex belongs to class 1; scaled in nm):
    tg.graph.vp.T_2 = tg.graph.new_vertex_property("vector<float>")
    # vertex property for storing the estimated maximal curvature of the corresponding triangle (if the vertex belongs to class 1; scaled in nm):
    tg.graph.vp.kappa_1 = tg.graph.new_vertex_property("float")
    # vertex property for storing the estimated minimal curvature of the corresponding triangle (if the vertex belongs to class 1; scaled in nm):
    tg.graph.vp.kappa_2 = tg.graph.new_vertex_property("float")
    # vertex property for storing the Gaussian curvature calculated from kappa_1 and kappa_2 at the corresponding triangle:
    tg.graph.vp.gauss_curvature_VV = tg.graph.new_vertex_property("float")
    # vertex property for storing the mean curvature calculated from kappa_1 and kappa_2 at the corresponding triangle:
    tg.graph.vp.mean_curvature_VV = tg.graph.new_vertex_property("float")
    # vertex property for storing the shape index calculated from kappa_1 and kappa_2 at the corresponding triangle:
    tg.graph.vp.shape_index_VV = tg.graph.new_vertex_property("float")
    # vertex property for storing the curvedness calculated from kappa_1 and kappa_2 at the corresponding triangle:
    tg.graph.vp.curvedness_VV = tg.graph.new_vertex_property("float")

    t_end = time.time()
    duration = t_end - t_begin
    print 'Preparation took: %s min %s s' % divmod(duration, 60)

    # # * Calculating average number of direct ("umbrella") neighbors for all vertices *
    # num_umbrella_neighbors_list = []
    # for v in tg.graph.vertices():
    #     num_umbrella_neighbors_of_v = sum(1 for _ in v.out_neighbours())
    #     num_umbrella_neighbors_list.append(num_umbrella_neighbors_of_v)
    #     #print "Vertex %s has %s direct neighbors." % (tg.graph.vertex_index[v], number_umbrella_neighbors_of_v)
    # avg_num_umbrella_neighbors = sum(x for x in num_umbrella_neighbors_list) / len(num_umbrella_neighbors_list)
    # print "Average number of umbrella neighbors for all vertices: %s" % avg_num_umbrella_neighbors  # 11 for k = 1

    # Main algorithm
    t_begin = time.time()

    # * For all vertices, collecting normal vector votes, while calculating average number of the geodesic neighbors, and classifying the orientation of each vertex *
    if all_vertices is True:
        print "\nRunning modified Vector Voting for all vertices..."

        print "\nFirst run: classifying orientation and estimating normals for surface patches and tangents for creases..."
        t_begin1 = time.time()

        collecting_votes = tg.collecting_votes
        all_num_neighbors = []
        all_neighbor_idx_to_dist = []
        classifying_orientation = tg.classifying_orientation
        classes_counts = {}
        for v in tg.graph.vertices():
            neighbor_idx_to_dist, V_v = collecting_votes(v, g_max, A_max, sigma, verbose=False)
            all_num_neighbors.append(len(neighbor_idx_to_dist))
            all_neighbor_idx_to_dist.append(neighbor_idx_to_dist)
            class_v = classifying_orientation(v, V_v, epsilon=epsilon, eta=eta, verbose=False)
            try:
                classes_counts[class_v] += 1
            except KeyError:
                classes_counts[class_v] = 1

        # Printing out some numbers concerning the first run:
        avg_num_geodesic_neighbors = sum(x for x in all_num_neighbors) / len(all_num_neighbors)
        print "Average number of geodesic neighbors for all vertices: %s" % avg_num_geodesic_neighbors
        print "%s surface patches" % classes_counts[1]
        if 2 in classes_counts:
            print "%s crease junctions" % classes_counts[2]
        if 3 in classes_counts:
            print "%s no preferred orientation" % classes_counts[3]

        t_end1 = time.time()
        duration1 = t_end1 - t_begin1
        print 'First run took: %s min %s s' % divmod(duration1, 60)

        print "\nSecond run: estimating principle curvatures and directions for surface patches..."
        t_begin2 = time.time()

        orientation_class = tg.graph.vp.orientation_class
        collecting_votes2 = tg.collecting_votes2
        estimate_curvature = tg.estimate_curvature
        if exclude_borders is False:
            for i, v in enumerate(tg.graph.vertices()):
                # Estimate principal curvatures and directions (and calculate the Gaussian and mean curvatures, shape index and curvedness) for vertices belonging to a surface patch
                B_v = None  # initialization
                if orientation_class[v] == 1:
                    B_v = collecting_votes2(v, all_neighbor_idx_to_dist[i], sigma, verbose=False)  # None is returned if v does not have any neighbor belonging to a surface patch
                if B_v is not None:
                    estimate_curvature(v, B_v, verbose=False)
                if orientation_class[v] != 1 or B_v is None: # For crease, no preferably oriented vertices or vertices lacking neighbors, add placeholders to the corresponding vertex properties
                    tg.graph.vp.T_1[v] = np.zeros(shape=3)
                    tg.graph.vp.T_2[v] = np.zeros(shape=3)
                    tg.graph.vp.kappa_1[v] = 0
                    tg.graph.vp.kappa_2[v] = 0
                    tg.graph.vp.gauss_curvature_VV[v] = 0
                    tg.graph.vp.mean_curvature_VV[v] = 0
                    tg.graph.vp.shape_index_VV[v] = 0
                    tg.graph.vp.curvedness_VV[v] = 0
        else:  # Exclude triangles at the borders from curvatures calculation and remove them in the end
            print '\nFinding triangles that are at surface borders and excluding them from curvatures calculation...'
            tg.find_graph_border(purge=False)  # Mark vertices at borders with vertex property 'is_on_border', do not delete
            is_on_border = tg.graph.vp.is_on_border
            for i, v in enumerate(tg.graph.vertices()):
                # Estimate principal curvatures and directions (and calculate the Gaussian and mean curvatures, shape index and curvedness) for vertices belonging to a surface patch and not on border
                B_v = None  # initialization
                if orientation_class[v] == 1 and is_on_border[v] == 0:
                    B_v = collecting_votes2(v, all_neighbor_idx_to_dist[i], sigma, verbose=False)  # None is returned if v does not have any neighbor belonging to a surface patch
                if B_v is not None:
                    estimate_curvature(v, B_v, verbose=False)
                if orientation_class[v] != 1 or is_on_border[v] == 1 or B_v is None: # For crease, no preferably oriented vertices, vertices on border or vertices lacking neighbors,
                    # add placeholders to the corresponding vertex properties
                    tg.graph.vp.T_1[v] = np.zeros(shape=3)
                    tg.graph.vp.T_2[v] = np.zeros(shape=3)
                    tg.graph.vp.kappa_1[v] = 0
                    tg.graph.vp.kappa_2[v] = 0
                    tg.graph.vp.gauss_curvature_VV[v] = 0
                    tg.graph.vp.mean_curvature_VV[v] = 0
                    tg.graph.vp.shape_index_VV[v] = 0
                    tg.graph.vp.curvedness_VV[v] = 0
            tg.find_graph_border(purge=True)

        # Transforming the resulting graph to a surface with triangles:
        surface_VV = tg.graph_to_triangle_poly()
        returnValue = surface_VV, tg

        t_end2 = time.time()
        duration2 = t_end2 - t_begin2
        print 'Second run took: %s min %s s' % divmod(duration2, 60)

    # * For testing, running the same for only the first vertex *  TODO remove this testing option
    else:
        print "Running modified Vector Voting for one vertex..."
        v = tg.graph.vertex(0)
        neighbor_idx_to_dist, V_v = tg.collecting_votes(v, g_max, A_max, sigma, verbose=True)
        class_v = tg.classifying_orientation(v, V_v, epsilon=epsilon, eta=eta, verbose=True)
        if class_v == 1:
            for v_i_idx in neighbor_idx_to_dist.keys():
                v_i = tg.graph.vertex(v_i_idx)
                _, V_v_i = tg.collecting_votes(v_i, g_max, A_max, sigma, verbose=False)
                tg.classifying_orientation(v_i, V_v_i, epsilon=epsilon, eta=eta, verbose=False)
            B_v = tg.collecting_votes2(v, neighbor_idx_to_dist, sigma, verbose=True)
            if B_v is not None:
                tg.estimate_curvature(v, B_v, verbose=True)

        returnValue = None, None

    t_end = time.time()
    duration = t_end - t_begin
    print 'Modified Vector Voting took: %s min %s s' % divmod(duration, 60)
    return returnValue

