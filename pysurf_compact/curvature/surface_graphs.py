import graphs
import vtk
import numpy as np
import time
from graph_tool.all import *
from scipy import ndimage
import math


# Calculates curvatures for a vtkPolyData surface.
# Returns the vtkPolyData surface with '<type>_Curvature' property added for each point.
# How to get the curvatures later, e.g. for point with ID 0:
# point_data = surface_curvature.GetPointData()
# curvatures = point_data.GetArray(n), n=2 for Gaussian, 3 for Mean, 4 for Maximum or Minimum
# curvature_point0 = curvatures.GetTuple1(0)
def add_curvature_to_vtk_surface(surface, curvature_type):
    if isinstance(surface, vtk.vtkPolyData):
        curvature_filter = vtk.vtkCurvatures()
        curvature_filter.SetInputData(surface)
        if curvature_type == "Gaussian":
            print "Gaussian curvature"
            curvature_filter.SetCurvatureTypeToGaussian()
        elif curvature_type == "Mean":
            print "Mean curvature"
            curvature_filter.SetCurvatureTypeToMean()
        elif curvature_type == "Maximum":
            print "Maximum curvature"
            curvature_filter.SetCurvatureTypeToMaximum()
        elif curvature_type == "Minimum":
            print "Minimum curvature"
            curvature_filter.SetCurvatureTypeToMinimum()
        else:
            print 'Error: Wrong curvature type.'
            exit(1)
        curvature_filter.Update()
        surface_curvature = curvature_filter.GetOutput()
        return surface_curvature
    else:
        print 'Error: Wrong input data type, \'surface\' has to be a vtkPolyData object.'
        exit(1)


# Rescales the given surface with a given scaling factor "scale".
def rescale_surface(surface, scale):
    if isinstance(surface, vtk.vtkPolyData):
        transf = vtk.vtkTransform()
        transf.Scale(scale, scale, scale)
        tpd = vtk.vtkTransformPolyDataFilter()
        tpd.SetInputData(surface)
        tpd.SetTransform(transf)
        tpd.Update()
        scaled_surface = tpd.GetOutput()
        return scaled_surface
    else:
        print 'Error: Wrong input data type, \'surface\' has to be a vtkPolyData object.'
        exit(1)


# Class defining the SurfaceGraph object, its attributes and methods.
class SurfaceGraph(graphs.SegmentationGraph):
    # Builds the graph from a vtkPolyData surface.
    def build_graph_from_vtk_surface(self, surface, verbose):
        pass


# Class defining the PointGraph object, its attributes and methods.
class PointGraph(SurfaceGraph):
    # Builds the graph from a vtkPolyData surface.
    def build_graph_from_vtk_surface(self, surface, verbose):
        if isinstance(surface, vtk.vtkPolyData):
            surface = rescale_surface(surface, self.scale_factor_to_nm)  # rescale the surface to nm

            # 0. Check numbers of cells (polygons or triangles) and all points.
            print '%s cells' % surface.GetNumberOfCells()
            print '%s points' % surface.GetNumberOfPoints()

            # 1. Iterate over all cells, adding their points as vertices to the graph and connecting them by edges.
            for i in xrange(surface.GetNumberOfCells()):
                if verbose:
                    print 'Cell number %s:' % i

                # Get all points which made up the cell and check that they are 3.
                points_cell = surface.GetCell(i).GetPoints()
                if points_cell.GetNumberOfPoints() == 3:
                    # 1a) Add each of the 3 points as vertex to the graph, if it has not been added yet.
                    for j in range(0, 3):
                        x, y, z = points_cell.GetPoint(j)
                        p = (x, y, z)
                        if p not in self.coordinates_to_vertex_index:
                            vd = self.graph.add_vertex()  # vertex descriptor
                            self.graph.vp.xyz[vd] = [x, y, z]
                            self.coordinates_to_vertex_index[p] = self.graph.vertex_index[vd]
                            if verbose:
                                print '\tThe point (%s, %s, %s) has been added to the graph as a vertex.' % (x, y, z)

                    # 1b) Add an edge with a distance between all 3 pairs of vertices, if it has not been added yet.
                    for k in range(0, 2):
                        x1, y1, z1 = points_cell.GetPoint(k)
                        p1 = (x1, y1, z1)
                        vd1 = self.graph.vertex(self.coordinates_to_vertex_index[p1])  # vertex descriptor of the 1st point
                        for l in range(k + 1, 3):
                            x2, y2, z2 = points_cell.GetPoint(l)
                            p2 = (x2, y2, z2)
                            vd2 = self.graph.vertex(self.coordinates_to_vertex_index[p2])  # vertex descriptor of the 2nd point
                            if not (((p1, p2) in self.coordinates_pair_connected) or ((p2, p1) in self.coordinates_pair_connected)):
                                ed = self.graph.add_edge(vd1, vd2)  # edge descriptor
                                self.graph.ep.distance[ed] = self.distance_between_voxels(p1, p2)
                                self.coordinates_pair_connected[(p1, p2)] = True
                                if verbose:
                                    print '\tThe neighbor points (%s, %s, %s) and (%s, %s, %s) have been connected by an edge with a distance of %s pixels.' \
                                          % (x1, y1, z1, x2, y2, z2, self.graph.ep.distance[ed])
                else:
                    print 'Oops, there are %s points in cell number %s' % points_cell.GetNumberOfPoints(), i

            # 2. Check if the numbers of vertices and edges are as they should be:
            assert self.graph.num_vertices() == len(self.coordinates_to_vertex_index)  # surface.GetNumberOfPoints() is higher for some reason
            assert self.graph.num_edges() == len(self.coordinates_pair_connected)
            print '%s triangle vertices' % self.graph.num_vertices()
        else:
            print 'Error: Wrong input data type, \'surface\' has to be a vtkPolyData object.'
            exit(1)


# Class defining the TriangleGraph object, its attributes and methods.
class TriangleGraph(SurfaceGraph):
    def __init__(self, scale_factor_to_nm, scale_x, scale_y, scale_z):
        graphs.SegmentationGraph.__init__(self, scale_factor_to_nm, scale_x, scale_y, scale_z)

        # Add more "internal property maps" to the graph.
        # vertex property for storing the area of the corresponding triangle in nm squared:
        self.graph.vp.area = self.graph.new_vertex_property("float")
        # vertex property for storing the normal of the corresponding triangle scaled in nm:
        self.graph.vp.normal = self.graph.new_vertex_property("vector<float>")
        # vertex property for storing the VTK minimal curvature at the corresponding triangle:
        self.graph.vp.min_curvature = self.graph.new_vertex_property("float")
        # vertex property for storing the VTK maximal curvature at the corresponding triangle:
        self.graph.vp.max_curvature = self.graph.new_vertex_property("float")
        # vertex property for storing the VTK Gaussian curvature at the corresponding triangle:
        self.graph.vp.gauss_curvature = self.graph.new_vertex_property("float")
        # vertex property for storing the VTK mean curvature at the corresponding triangle:
        self.graph.vp.mean_curvature = self.graph.new_vertex_property("float")
        # vertex property for storing the coordinates scaled in nm of the 3 points of the corresponding triangle:
        self.graph.vp.points = self.graph.new_vertex_property("object")
        # edge property storing the "strength" property of the edge: 1 for a "strong" or 0 for a "weak" one:
        self.graph.ep.is_strong = self.graph.new_edge_property("int")

        # A dictionary mapping a point coordinates (x, y, z) scaled in nm to a list of cell indices sharing this point:
        self.point_in_cells = {}

    # Builds the graph from a vtkPolyData surface. Returns the rescaled surface to nm for writing into a file, if needed.
    def build_graph_from_vtk_surface(self, surface, verbose=False):
        if isinstance(surface, vtk.vtkPolyData):
            t_begin = time.time()

            print 'Adding curvatures to the vtkPolyData surface...'
            surface = add_curvature_to_vtk_surface(surface, "Minimum")
            surface = add_curvature_to_vtk_surface(surface, "Maximum")
            surface = rescale_surface(surface, self.scale_factor_to_nm)  # rescale the surface to nm

            # 0. Check numbers of cells (polygons or triangles) (and all points).
            print '%s cells' % surface.GetNumberOfCells()
            if verbose:
                print '%s points' % surface.GetNumberOfPoints()

            point_data = surface.GetPointData()
            n = point_data.GetNumberOfArrays()
            min_curvatures = None
            max_curvatures = None
            gauss_curvatures = None
            mean_curvatures = None
            for i in range(n):
                if point_data.GetArrayName(i) == "Minimum_Curvature":  # minimum curvatures have to be added before!
                    min_curvatures = point_data.GetArray(i)
                if point_data.GetArrayName(i) == "Maximum_Curvature":  # maximum curvatures have to be added before!
                    max_curvatures = point_data.GetArray(i)
                if point_data.GetArrayName(i) == "Gauss_Curvature":
                    gauss_curvatures = point_data.GetArray(i)
                if point_data.GetArrayName(i) == "Mean_Curvature":
                    mean_curvatures = point_data.GetArray(i)

            # 2. Add each triangle cell as a vertex to the graph. Ignore the non-triangle cells.
            # Get a list of all triangle cell indices first:
            triangle_cell_ids = []
            for cell_id in xrange(surface.GetNumberOfCells()):
                # Get the cell i and check if it's a triangle:
                cell = surface.GetCell(cell_id)
                if isinstance(cell, vtk.vtkTriangle):
                    triangle_cell_ids.append(cell_id)
                else:
                    print 'Oops, the cell number %s is not a vtkTriangle but a %s! It will be ignored.' % (cell_id, cell.__class__.__name__)

            for cell_id in triangle_cell_ids:
                cell = surface.GetCell(cell_id)
                if verbose:
                    print '(Triangle) cell number %s' % cell_id

                # Initialize a list for storing the points coordinates making out the cell
                points_xyz = []

                # Get the 3 points which made up the triangular cell:
                points_cell = cell.GetPoints()

                # Calculate the centroid of the triangle:
                x_center = 0
                y_center = 0
                z_center = 0
                for j in range(0, 3):
                    x, y, z = points_cell.GetPoint(j)
                    x_center += x
                    y_center += y
                    z_center += z

                    # Add each point j as a key in point_in_cells and cell index to the value list:
                    point_j = (x, y, z)
                    if point_j in self.point_in_cells:
                        self.point_in_cells[point_j].append(cell_id)
                    else:
                        self.point_in_cells[point_j] = [cell_id]

                    # Add each point j into the points coordinates list
                    points_xyz.append([x, y, z])
                x_center /= 3
                y_center /= 3
                z_center /= 3

                # Calculate the area of the triangle i;
                area = cell.TriangleArea(points_cell.GetPoint(0), points_cell.GetPoint(1), points_cell.GetPoint(2))
                try:
                    assert(area > 0)
                except AssertionError:
                    print '\tThe triangle centroid (%s, %s, %s) cannot be added to the graph as a vertex, because the triangle area is not positive, but is %s. Points = %s.' \
                          % (x_center, y_center, z_center, area, points_xyz)
                    continue

                # Calculate the normal of the triangle i;
                normal = np.zeros(shape=3)
                cell.ComputeNormal(points_cell.GetPoint(0), points_cell.GetPoint(1), points_cell.GetPoint(2), normal)

                # Get the min, max and Gaussian curvatures for each of 3 points of the triangle i and calculate the average curvatures:
                avg_min_curvature = 0
                avg_max_curvature = 0
                avg_gauss_curvature = 0
                avg_mean_curvature = 0
                for j in range(0, 3):
                    point_j_id = cell.GetPointId(j)

                    min_curvature_point_j = min_curvatures.GetTuple1(point_j_id)
                    avg_min_curvature += min_curvature_point_j

                    max_curvature_point_j = max_curvatures.GetTuple1(point_j_id)
                    avg_max_curvature += max_curvature_point_j

                    gauss_curvature_point_j = gauss_curvatures.GetTuple1(point_j_id)
                    avg_gauss_curvature += gauss_curvature_point_j

                    mean_curvature_point_j = mean_curvatures.GetTuple1(point_j_id)
                    avg_mean_curvature += mean_curvature_point_j

                avg_min_curvature /= 3
                avg_max_curvature /= 3
                avg_gauss_curvature /= 3
                avg_mean_curvature /= 3

                # Add the centroid as vertex to the graph, setting its properties:
                vd = self.graph.add_vertex()  # vertex descriptor, vertex index numbered from 0 and does not necessarily correspond to the (triangle) cell index!
                self.graph.vp.xyz[vd] = [x_center, y_center, z_center]
                self.coordinates_to_vertex_index[(x_center, y_center, z_center)] = self.graph.vertex_index[vd]
                self.graph.vp.area[vd] = area
                self.graph.vp.normal[vd] = normal
                self.graph.vp.min_curvature[vd] = avg_min_curvature
                self.graph.vp.max_curvature[vd] = avg_max_curvature
                self.graph.vp.gauss_curvature[vd] = avg_gauss_curvature
                self.graph.vp.mean_curvature[vd] = avg_mean_curvature
                self.graph.vp.points[vd] = points_xyz

                if verbose:
                    print '\tThe triangle centroid %s has been added to the graph as a vertex. Triangle area = %s, normal = %s,' \
                          '\naverage minimal curvature = %s, average maximal curvature = %s, points = %s.' \
                          % (self.graph.vp.xyz[vd], self.graph.vp.area[vd], self.graph.vp.normal[vd], self.graph.vp.min_curvature[vd],
                             self.graph.vp.max_curvature[vd], self.graph.vp.points[vd])

            # 3. Add edges for each cell / vertex.
            for i, cell_id in enumerate(triangle_cell_ids):  # i corresponds to the vertex number of each cell, because they were added in this order
                cell = surface.GetCell(cell_id)
                if verbose:
                    print '(Triangle) cell number %s:' % cell_id

                # Find the "neighbor cells" and how many points they share with cell i (1 or 2) as follows.
                # For each point j of cell i, iterate over the neighbor cells sharing that point (excluding the cell i).
                # Add each neighbor cell to the neighbor_cells list if it is not there yet and add 1 into the
                # shared_points list. Otherwise, find the index of the cell in neighbor_cells and increase the counter
                # of shared_points at the same index.
                points_cell = cell.GetPoints()
                neighbor_cells = []
                shared_points = []
                for j in range(points_cell.GetNumberOfPoints()):
                    point_j = points_cell.GetPoint(j)
                    for neighbor_cell_id in self.point_in_cells[point_j]:
                        if neighbor_cell_id != cell_id:
                            if neighbor_cell_id not in neighbor_cells:
                                neighbor_cells.append(neighbor_cell_id)
                                shared_points.append(1)
                            else:
                                idx = neighbor_cells.index(neighbor_cell_id)
                                shared_points[idx] += 1
                if verbose:
                    print "has %s neighbor cells" % len(neighbor_cells)

                # Get the vertex descriptor representing the cell i:
                vd_i = self.graph.vertex(i)  # vertex descriptor of the current cell, vertex i

                # Get the coordinates of the vertex i (as a list and convert into a tupel):
                p_i = self.graph.vp.xyz[vd_i]
                p_i = (p_i[0], p_i[1], p_i[2])

                # Iterate over the ready neighbor_cells and shared_points lists, connecting cell i with a neighbor cell
                # x with a "strong" edge if they share 2 edges and with a "weak" edge otherwise (= only 1 edge).
                for idx, neighbor_cell_id in enumerate(neighbor_cells):
                    # Get the vertex descriptor representing the cell x:
                    x = triangle_cell_ids.index(neighbor_cell_id)  # vertex index of the current neighbor cell
                    vd_x = self.graph.vertex(x)  # vertex descriptor of the current neighbor cell, vertex x

                    # Get the coordinates of the vertex x (as a list and convert into a tupel):
                    p_x = self.graph.vp.xyz[vd_x]
                    p_x = (p_x[0], p_x[1], p_x[2])

                    # Add an edge between the vertices i and x, if it has not been added yet:
                    if not (((p_i, p_x) in self.coordinates_pair_connected) or ((p_x, p_i) in self.coordinates_pair_connected)):
                        ed = self.graph.add_edge(vd_i, vd_x)  # edge descriptor
                        self.coordinates_pair_connected[(p_i, p_x)] = True

                        # Add the distance of the edge
                        self.graph.ep.distance[ed] = self.distance_between_voxels(p_i, p_x)

                        # Assign the "strength" property to the edge as explained above:
                        if shared_points[idx] == 2:
                            is_strong = 1
                            strength = 'strong'
                        else:
                            is_strong = 0
                            strength = 'weak'
                        self.graph.ep.is_strong[ed] = is_strong
                        if verbose:
                            print '\tThe neighbor vertices (%s, %s, %s) and (%s, %s, %s) have been connected by a %s edge with a distance of %s pixels.' \
                                  % (p_i[0], p_i[1], p_i[2], p_x[0], p_x[1], p_x[2], strength, self.graph.ep.distance[ed])

            # 4. Check if the numbers of vertices and edges are as they should be:
            assert self.graph.num_vertices() == len(triangle_cell_ids)
            assert self.graph.num_edges() == len(self.coordinates_pair_connected)
            if verbose:
                print 'Real number of unique points: %s' % len(self.point_in_cells)

            t_end = time.time()
            duration = t_end - t_begin
            print 'Surface graph generation took: %s min %s s' % divmod(duration, 60)

            return surface  # rescaled surface to nm for writing into a file
        else:
            print 'Error: Wrong input data type, \'surface\' has to be a vtkPolyData object.'
            exit(1)

    # Updates graph's dictionary coordinates_to_vertex_index, which has to be done after purging the graph, because vertices are renumbered.
    # Reminder: the dictionary maps the vertex coordinates (x, y, z) scaled in nm to the vertex index.
    def __update_coordinates_to_vertex_index(self):
        self.coordinates_to_vertex_index = {}
        for vd in self.graph.vertices():
            [x_center, y_center, z_center] = self.graph.vp.xyz[vd]
            self.coordinates_to_vertex_index[(x_center, y_center, z_center)] = self.graph.vertex_index[vd]

    # Finds and returns (as list of indices) vertices at the graph border (defined as such having less than 3 strong
    # edges) and adds corresponding vertex properties, 'num_strong_edges' and 'is_on_border'. If "purge" is set to True,
    # those vertices and their edges will be filtered out permanently, if it is False (default) no filtering will be done.
    def find_graph_border(self, purge=False):
        if "is_on_border" not in self.graph.vertex_properties:
            print 'Finding vertices at the graph border...'
            # Add a vertex property for storing the number of strong edges:
            self.graph.vp.num_strong_edges = self.graph.new_vertex_property("int")
            # Sum up the "strong" edges coming out of each vertex and add them to the new property:
            num_strong_edges = incident_edges_op(self.graph, "out", "sum", self.graph.ep.is_strong,
                                                 self.graph.vp.num_strong_edges)
            print 'number of strong edges: min = %s, max = %s' % (min(num_strong_edges.a), max(num_strong_edges.a))

            # Add a boolean vertex property telling whether a vertex is on border:
            self.graph.vp.is_on_border = self.graph.new_vertex_property("boolean")

            border_vertices_indices = np.where(self.graph.vp.num_strong_edges.a < 3)[0]  # indices of vertices with less than 3 strong edges (= vertices on border)
            self.graph.vp.is_on_border.a = np.zeros(shape=self.graph.num_vertices())
            self.graph.vp.is_on_border.a[border_vertices_indices] = 1
            print '%s vertices are at the graph border.' % len(border_vertices_indices)
            return border_vertices_indices

        if purge is True:
            print 'Filtering out the vertices at the graph borders and their edges...'
            # Set the filter to get only vertices NOT on border.
            self.graph.set_vertex_filter(self.graph.vp.is_on_border, inverted=True)
            # Purge the filtered out vertices and edges permanently from the graph:
            self.graph.purge_vertices()
            # Remove the properties used for the filtering that are no longer true:
            del self.graph.vertex_properties["num_strong_edges"]  # del self.graph.vp.num_strong_edges  # AttributeError: num_strong_edges
            del self.graph.vertex_properties["is_on_border"]
            # Update graph's dictionary coordinates_to_vertex_index:
            self.__update_coordinates_to_vertex_index()


    # Calculates for each vertex geodesics to each graph border vertex and stores the minimal one as a vertex property,
    # 'min_geodesics_to_border'. Also marks surface "islands" unreachable from the graph border in a vertex property.
    def __calculate_min_geodesics_to_border(self, verbose=False):
        border_vertices_indices = self.find_graph_border()

        print 'Calculating for each vertex geodesics to each graph border vertex...'
        t_begin = time.time()
        # Add a vertex property for storing the minimal geodesics to graph border:
        self.graph.vp.min_geodesics_to_border = self.graph.new_vertex_property("float")
        # Add a vertex property telling whether a vertex is unreachable from any graph border:
        self.graph.vp.unreachable_from_border = self.graph.new_vertex_property("boolean")
        num_vertices_unreachable_from_border = 0
        for v in self.graph.vertices():
            d = graph_tool.topology.shortest_distance(self.graph, source=v, target=border_vertices_indices,
                                                      weights=self.graph.ep.distance)
            self.graph.vp.min_geodesics_to_border[v] = min(d)
            if self.graph.vp.min_geodesics_to_border[v] == np.finfo(np.float64).max:  # == 1.7976931348623157e+308
                self.graph.vp.min_geodesics_to_border[v] = -1  # so ParaView doesn't run into problem showing the range
                self.graph.vp.unreachable_from_border[v] = 1
                num_vertices_unreachable_from_border += 1
                if verbose:
                    print 'Vertex %s is unreachable from border' % self.graph.vertex_index[v]
            else:
                self.graph.vp.unreachable_from_border[v] = 0
        t_end = time.time()
        duration = t_end - t_begin
        print '...took: %s min %s s' % divmod(duration, 60)
        print "%s vertices are unreachable from border." % num_vertices_unreachable_from_border

    # Finds vertices that are within distance b nm to the graph border. If "purge" is set to True, those vertices and
    # their edges will be filtered out permanently. If "filter_islands" is set to True, the islands unreachable from the
    # graph border will be filtered out permanently. If those parameters are set to False (default), no filtering will be done.
    def find_vertices_near_border(self, b, purge=False, filter_islands=False, verbose=False):
        self.__calculate_min_geodesics_to_border(verbose=verbose)  # this calls add one property and self.find_graph_border(), which adds two properties!

        print '\nFinding vertices within distance %s nm to the graph border...' % b
        # Add a boolean vertex property telling whether a vertex is within distance b to border:
        self.graph.vp.is_near_border = self.graph.new_vertex_property("boolean")
        num_vertices_near_border = 0
        for v in self.graph.vertices():
            if self.graph.vp.unreachable_from_border[v] == 0 and self.graph.vp.min_geodesics_to_border[v] <= b:
                self.graph.vp.is_near_border[v] = 1
                num_vertices_near_border += 1
            else:
                self.graph.vp.is_near_border[v] = 0
        print '%s vertices are within distance %s nm to the graph border.' % (num_vertices_near_border, b)

        if purge is True:
            print 'Filtering out those vertices and their edges...'
            # Set the filter to get only vertices NOT within distance b to border.
            self.graph.set_vertex_filter(self.graph.vp.is_near_border, inverted=True)
            # Purge the filtered out vertices and edges permanently from the graph:
            self.graph.purge_vertices()
            # Remove the properties used for the filtering that are no longer true:
            del self.graph.vertex_properties["num_strong_edges"]
            del self.graph.vertex_properties["is_on_border"]
            del self.graph.vertex_properties["min_geodesics_to_border"]
            del self.graph.vertex_properties["is_near_border"]

        if filter_islands is True:
            print 'Filtering out "islands" unreachable from the graph border...'
            # Set the filter to get only vertices NOT unreachable from border.
            self.graph.set_vertex_filter(self.graph.vp.unreachable_from_border, inverted=True)
            # Purge the filtered out vertices and edges permanently from the graph:
            self.graph.purge_vertices()
            # Remove the properties used for the filtering that are no longer true:
            del self.graph.vertex_properties["unreachable_from_border"]

        if purge is True or filter_islands is True:
            # Update graph's dictionary coordinates_to_vertex_index:
            self.__update_coordinates_to_vertex_index()

    # A faster version for find_vertices_near_border (Note: no option to filter islands - use a subgraphs filtering method).
    def find_vertices_near_border_fast(self, b, purge=False, verbose=False):
        t_very_begin = time.time()
        border_vertices_indices = self.find_graph_border()

        print 'For each graph border vertex, finding vertices within geodesic distance %s to it...' % b
        vertex_id_within_b_to_border = dict()
        for border_v_i in border_vertices_indices:
            border_v = self.graph.vertex(border_v_i)
            dist_border_v = graph_tool.topology.shortest_distance(self.graph, source=border_v, target=None, weights=self.graph.ep.distance, max_dist=b)
            dist_border_v = dist_border_v.get_array()

            idxs = np.where(dist_border_v <= b)[0]
            for idx in idxs:
                dist = dist_border_v[idx]
                try:
                    vertex_id_within_b_to_border[idx] = min(dist, vertex_id_within_b_to_border[idx])
                except KeyError:
                    vertex_id_within_b_to_border[idx] = dist
        print '%s vertices are within distance %s nm to the graph border.' % (len(vertex_id_within_b_to_border), b)

        # Add a boolean vertex property telling whether a vertex is within distance b to border:
        self.graph.vp.is_near_border = self.graph.new_vertex_property("boolean")
        for v in self.graph.vertices():
            v_i = self.graph.vertex_index[v]
            if v_i in vertex_id_within_b_to_border:
                self.graph.vp.is_near_border[v] = 1
            else:
                self.graph.vp.is_near_border[v] = 0

        if purge is True:
            print 'Filtering out those vertices and their edges...'
            # Set the filter to get only vertices NOT within distance b to border.
            self.graph.set_vertex_filter(self.graph.vp.is_near_border, inverted=True)
            # Purge the filtered out vertices and edges permanently from the graph:
            self.graph.purge_vertices()
            # Remove the properties used for the filtering that are no longer true:
            del self.graph.vertex_properties["num_strong_edges"]
            del self.graph.vertex_properties["is_on_border"]
            del self.graph.vertex_properties["is_near_border"]
            # Update graph's dictionary coordinates_to_vertex_index:
            self.__update_coordinates_to_vertex_index()

        t_very_end = time.time()
        duration = t_very_end - t_very_begin
        print 'Finding vertices near border took: %s min %s s' % divmod(duration, 60)

    # Finds vertices that are outside a mask, which means that their scaled back to pixels and rounded coordinates are further away than an allowed distance (in pixels)
    # to a mask voxel with the given label.
    def find_vertices_outside_mask(self, mask, label=1, allowed_dist=0):
        if isinstance(mask, np.ndarray):
            print '\nFinding vertices outside the membrane mask...'
            # Add a boolean vertex property telling whether a vertex is outside the mask:
            self.graph.vp.is_outside_mask = self.graph.new_vertex_property("boolean")
            maskd = ndimage.morphology.distance_transform_edt(np.invert(mask == label)) # Invert the boolean matrix,
            # because distance_transform_edt calculates distances from '0's, not from '1's!

            num_vertices_outside_mask = 0
            for v in self.graph.vertices():
                v_xyz = self.graph.vp.xyz[v]
                v_pixel_x = int(round(v_xyz[0] / self.scale_factor_to_nm))
                v_pixel_y = int(round(v_xyz[1] / self.scale_factor_to_nm))
                v_pixel_z = int(round(v_xyz[2] / self.scale_factor_to_nm))
                try:
                    if maskd[v_pixel_x, v_pixel_y, v_pixel_z] > allowed_dist:
                        self.graph.vp.is_outside_mask[v] = 1
                        num_vertices_outside_mask += 1
                    else:
                        self.graph.vp.is_outside_mask[v] = 0
                except IndexError:
                    print "IndexError happened. Vertex with coordinates in nm (%s, %s, %s)" % (v_xyz[0], v_xyz[1], v_xyz[2])
                    print "was transformed to pixel (%s, %s, %s)," % (v_pixel_x, v_pixel_y, v_pixel_z)
                    print "which is not inside the mask with shape (%s, %s, %s)" % (maskd.shape[0], maskd.shape[1], maskd.shape[2])
            print '%s vertices are further away than %s pixel to the mask.' % (num_vertices_outside_mask, allowed_dist)

        else:
            print 'Error: Wrong input data type, the mask has to be a numpy ndarray (3D).'
            exit(1)

    # Finds vertices that are within distance b nm to the graph border and outside a mask, i.e. further than the allowed distance (in pixels) from a mask voxel with the given label.
    # If "purge" is set to True, those vertices and their edges will be filtered out permanently.
    # If "filter_islands" is set to True, the islands unreachable from the graph border will be filtered out permanently.
    # If those parameters are set to False (default), no filtering will be done.
    def find_vertices_near_border_and_outside_mask(self, b, mask, label=1, allowed_dist=0, purge=False, filter_islands=False, verbose=False):
        self.find_vertices_near_border(b, purge=False, filter_islands=False, verbose=verbose)  # don't remove vertices near border, because have to intersect with the mask first!
        self.find_vertices_outside_mask(mask, label=label, allowed_dist=allowed_dist)

        # Add a boolean vertex property telling whether a vertex within distance b to border and outside mask:
        self.graph.vp.is_near_border_and_outside_mask = self.graph.new_vertex_property("boolean")
        num_vertices_near_border_and_outside_mask = 0
        for v in self.graph.vertices():
            if self.graph.vp.is_near_border[v] == 1 and self.graph.vp.is_outside_mask[v] == 1:
                self.graph.vp.is_near_border_and_outside_mask[v] = 1
                num_vertices_near_border_and_outside_mask += 1
            else:
                self.graph.vp.is_near_border_and_outside_mask[v] = 0
        print '%s vertices are within distance %s nm to the graph border and further than %s pixel from the mask.' % (num_vertices_near_border_and_outside_mask, b, allowed_dist)

        if purge is True:
            print 'Filtering out those vertices and their edges...'
            # Set the filter to get only vertices NOT (near border and outside mask).
            self.graph.set_vertex_filter(self.graph.vp.is_near_border_and_outside_mask, inverted=True)
            # Purge the filtered out vertices and edges permanently from the graph:
            self.graph.purge_vertices()
            # Remove the properties used for the filtering that are no longer true:
            del self.graph.vertex_properties["num_strong_edges"]
            del self.graph.vertex_properties["is_on_border"]
            del self.graph.vertex_properties["min_geodesics_to_border"]
            del self.graph.vertex_properties["is_near_border"]  # until here as in self.find_vertices_near_border(), because not purged
            del self.graph.vertex_properties["is_outside_mask"]
            del self.graph.vertex_properties["is_near_border_and_outside_mask"]

        if filter_islands is True:
            print 'Filtering out "islands" unreachable from the graph border...'
            # Set the filter to get only vertices NOT unreachable from border.
            self.graph.set_vertex_filter(self.graph.vp.unreachable_from_border, inverted=True)
            # Purge the filtered out vertices and edges permanently from the graph:
            self.graph.purge_vertices()
            # Remove the properties used for the filtering that are no longer true:
            del self.graph.vertex_properties["unreachable_from_border"]

        if purge is True or filter_islands is True:
            # Update graph's dictionary coordinates_to_vertex_index:
            self.__update_coordinates_to_vertex_index()

    # A faster version for find_vertices_near_border_and_outside_mask (Note: no option to filter islands - use a subgraphs filtering method).
    def find_vertices_near_border_and_outside_mask_fast(self, b, mask, label=1, allowed_dist=0, purge=False, verbose=False):
        self.find_vertices_near_border_fast(b, purge=False, verbose=verbose)  # don't remove vertices near border, because have to intersect with the mask first!
        self.find_vertices_outside_mask(mask, label=label, allowed_dist=allowed_dist)

        # Add a boolean vertex property telling whether a vertex within distance b to border and outside mask:
        self.graph.vp.is_near_border_and_outside_mask = self.graph.new_vertex_property("boolean")
        num_vertices_near_border_and_outside_mask = 0
        for v in self.graph.vertices():
            if self.graph.vp.is_near_border[v] == 1 and self.graph.vp.is_outside_mask[v] == 1:
                self.graph.vp.is_near_border_and_outside_mask[v] = 1
                num_vertices_near_border_and_outside_mask += 1
            else:
                self.graph.vp.is_near_border_and_outside_mask[v] = 0
        print '%s vertices are within distance %s nm to the graph border and further than %s pixel from the mask.' % (num_vertices_near_border_and_outside_mask, b, allowed_dist)

        if purge is True:
            print 'Filtering out those vertices and their edges...'
            # Set the filter to get only vertices NOT (near border and outside mask).
            self.graph.set_vertex_filter(self.graph.vp.is_near_border_and_outside_mask, inverted=True)
            # Purge the filtered out vertices and edges permanently from the graph:
            self.graph.purge_vertices()
            # Remove the properties used for the filtering that are no longer true:
            del self.graph.vertex_properties["num_strong_edges"]
            del self.graph.vertex_properties["is_on_border"]
            del self.graph.vertex_properties["is_near_border"]  # until here as in self.find_vertices_near_border(), because not purged
            del self.graph.vertex_properties["is_outside_mask"]
            del self.graph.vertex_properties["is_near_border_and_outside_mask"]
            # Update graph's dictionary coordinates_to_vertex_index:
            self.__update_coordinates_to_vertex_index()

    # Finds and returns the largest connected component (lcc) of the graph. If "replace" is True and the lcc has less vertices, the graph is replaced by its lcc.
    def find_largest_connected_component(self, replace=False):
        print 'Total number of vertices in the graph: %s' % self.graph.num_vertices()
        is_in_lcc = graph_tool.topology.label_largest_component(self.graph)
        lcc = graph_tool.GraphView(self.graph, vfilt=is_in_lcc)
        print 'Number of vertices in the largest connected component of the graph: %s' % lcc.num_vertices()

        if replace is True and lcc.num_vertices() < self.graph.num_vertices():
            print 'Filtering out those vertices and edges not belonging to the largest connected component...'
            # Set the filter to get only vertices belonging to the lcc.
            self.graph.set_vertex_filter(is_in_lcc, inverted=False)
            # Purge the filtered out vertices and edges permanently from the graph:
            self.graph.purge_vertices()
            # Remove the "unreachable_from_border" property, if it was not deleted yet (islands are always not lcc are are removed at the latest here):
            if "unreachable_from_border" in self.graph.vertex_properties:
                del self.graph.vertex_properties["unreachable_from_border"]
            # Update graph's dictionary coordinates_to_vertex_index:
            self.__update_coordinates_to_vertex_index()

        return lcc

    def find_small_connected_components(self, threshold=100, purge=False, verbose=False):
        t_begin = time.time()

        comp_labels_map, sizes = graph_tool.topology.label_components(self.graph)
        small_components = []
        for i, size in enumerate(sizes):
            comp_label = i
            if size < threshold:
                small_components.append(comp_label)
        print "The graph has %s components, %s of them have size < %s" % (len(sizes), len(small_components), threshold)
        if verbose:
            print "Sizes of components:"
            print sizes

        # Add a boolean vertex property telling whether a vertex belongs to a small component with size below the threshold:
        self.graph.vp.small_component = self.graph.new_vertex_property("boolean")
        num_vertices_in_small_components = 0
        for v in self.graph.vertices():
            if comp_labels_map[v] in small_components:
                self.graph.vp.small_component[v] = 1
                num_vertices_in_small_components += 1
            else:
                self.graph.vp.small_component[v] = 0
        print "%s vertices are in the small components." % num_vertices_in_small_components

        if len(small_components) > 0 and purge is True:
            print 'Filtering out those vertices and their edges belonging to the small components...'
            # Set the filter to get only vertices NOT belonging to a small component.
            self.graph.set_vertex_filter(self.graph.vp.small_component, inverted=True)
            # Purge the filtered out vertices and edges permanently from the graph:
            self.graph.purge_vertices()
            # Update graph's dictionary coordinates_to_vertex_index:
            self.__update_coordinates_to_vertex_index()
        # Remove the properties used for the filtering that are no longer true:
        del self.graph.vertex_properties["small_component"]

        t_end = time.time()
        duration = t_end - t_begin
        print 'Finding small components took: %s min %s s' % divmod(duration, 60)

    # Returns a list of all minimal geodesics to border from the vertex properties of the graph.
    def get_min_geodesics_to_border(self):
        if 'min_geodesics_to_border' not in self.graph.vp.keys():
            print 'min_geodesics_to_border property was not calculated. Please run ' \
                  '__calculate_min_geodesics_to_border or find_vertices_within_dist_b_to_border.'
            return None
        min_geodesics_to_border = []
        for v in self.graph.vertices():
            min_geodesics_to_border.append(self.graph.vp.min_geodesics_to_border[v])
        print '%s minimal geodesics to border values' % len(min_geodesics_to_border)
        print 'min = %s, max = %s' % (min(min_geodesics_to_border), max(min_geodesics_to_border))
        return min_geodesics_to_border

    # Returns numpy arrays of all triangle areas in nm squared from the vertex properties of the graph and the total area.
    def get_areas(self, verbose=False):
        triangle_areas = self.graph.vp.area.get_array()
        total_area = np.sum(triangle_areas)
        if verbose:
            print '%s triangle area values' % len(triangle_areas)
            print 'min = %s, max = %s' % (min(triangle_areas), max(triangle_areas))
            print 'total surface area = %s' % total_area
        return triangle_areas, total_area

    # Calculates and returns a numpy array of weighted curvatures by the relative triangle areas.
    # curvatures_key            property key of the curvature to be weighted
    # weighted_curvatures_key   if given (default None), the weighted curvature will be stored in a property with this key
    # triangle_areas            (optional) numpy array of all triangle areas in nm squared
    # total_area                (optional) the total area of the surface in nm squared
    # Last two options are for faster calculation if several weighted curvatures are calculated.
    def weight_curvatures_by_areas(self, curvatures_key, weighted_curvatures_key=None, triangle_areas=None, total_area=None):
        curvatures = self.graph.vertex_properties[curvatures_key].get_array()
        if triangle_areas is None or total_area is None:
            (triangle_areas, total_area) = self.get_areas()

        weighted_curvatures_prop = self.graph.new_vertex_property('float')
        for v in self.graph.vertices():
            weighted_curvatures_prop[v] = curvatures[int(v)] * triangle_areas[int(v)] / total_area

        weighted_curvatures = weighted_curvatures_prop.get_array()
        if weighted_curvatures_key is not None:
            # Storing the property
            self.graph.vertex_properties[weighted_curvatures_key] = weighted_curvatures_prop

        print '%s weighted %s values' % (len(weighted_curvatures), curvatures_key)
        print 'min = %s, max = %s' % (min(weighted_curvatures), max(weighted_curvatures))
        return weighted_curvatures

    # * The following TriangleGraph methods are implementing with adaptations the vector voting algorithm of Page et al. from 2002. *

    # For a vertex v, collects the normal votes of all triangles within its geodesic neighborhood and calculates the weighted covariance matrix sum V_v.
    # Implements equations (6), illustrated in figure 6(b), (7) and (8) from the paper.
    # More precisely, a normal vote N_i of each triangle i (whose centroid c_i is lying within the geodesic neighborhood of vertex v) is calculated using the normal N assigned to the triangle i.
    # Then, covariance matrix V_i is calculated from N_i and a weight depending of the area of triangle i and the geodesic distance of its centroid c_i from v.
    # In our case c_i and v are both centroids of triangles (v is a triangle vertex in Page's approach), which are vertices of TriangleGraph generated from the triangle surface.
    # Returns a dictionary of neighbors of vertex v, mapping index of each vertex c_i to its geodesic distance from the vertex v, and the 3x3 symmetric matrix V_v.
    def collecting_votes(self, vertex_v, g_max, A_max, sigma, verbose=False):
        # To spare function referencing every time in the following for loop:
        vertex = self.graph.vertex
        normal = self.graph.vp.normal
        array = np.array
        xyz = self.graph.vp.xyz
        vector_length = np.linalg.norm  # calculates the length of the vector, same as: np.sqrt(sum(vc_i**2))
        dot = np.dot
        outer = np.outer
        area = self.graph.vp.area
        exp = math.exp

        # Get the coordinates of vertex v (as numpy array):
        v = xyz[vertex_v]  # <class 'graph_tool.libgraph_tool_core.Vector_double'>
        v = array(v)  # <type 'numpy.ndarray'>

        # Find the neighboring vertices of vertex v to be returned:
        neighbor_idx_to_dist = self.find_geodesic_neighbors(vertex_v, g_max)
        try:
            assert len(neighbor_idx_to_dist) > 0
        except AssertionError:
            print "\nWarning: the vertex v = %s has 0 neighbors. It will be ignored later." % v
            return neighbor_idx_to_dist, np.zeros(shape=(3, 3))  # Return a placeholder instead of V_v, which would be returned anyway.

        if verbose:
            print "\nv = %s" % v
            print "%s neighbors" % len(neighbor_idx_to_dist)

        # Initialize the weighted matrix sum of all votes for vertex v to be calculated and returned:
        V_v = np.zeros(shape=(3, 3))

        # Let each of the neighboring vertices to cast a vote on vertex v:
        for idx_c_i in neighbor_idx_to_dist.keys():
            # Get the neighboring vertex c_i and its coordinates (as numpy array):
            vertex_c_i = vertex(idx_c_i)
            c_i = xyz[vertex_c_i]
            c_i = array(c_i)

            # Calculate the normal vote N_i of c_i on v:
            N = normal[vertex_c_i]
            N = array(N)

            vc_i = c_i - v
            vc_i_len = vector_length(vc_i)
            vc_i_norm = vc_i / vc_i_len

            cos_tetha_i = - (dot(N, vc_i)) / vc_i_len  # tetha_i is the angle between the vectors N and vc_i

            N_i = N + 2 * cos_tetha_i * vc_i_norm

            # Covariance matrix containing one vote of c_i on v:
            V_i = outer(N_i, N_i)

            # Calculate the weight depending on the area of the neighboring triangle i, A_i, and the geodesic distance to the neighboring vertex c_i from vertex v, g_i:
            A_i = area[vertex_c_i]
            g_i = neighbor_idx_to_dist[idx_c_i]
            w_i = A_i / A_max * exp(- g_i / sigma)

            if verbose:
                print "\nc_i = %s" % c_i
                print "N = %s" % N
                print "vc_i = %s" % vc_i
                print "||vc_i|| = %s" % vc_i_len
                print "cos(tetha_i) = %s" % cos_tetha_i
                print "N_i = %s" % N_i
                print "V_i = %s" % V_i
                print "A_i = %s" % A_i
                print "g_i = %s" % g_i
                print "w_i = %s" % w_i

            # Weigh V_i and add it to the weighted matrix sum:
            V_v += w_i * V_i

        if verbose:
            print "\nV_v: %s" % V_v
        return neighbor_idx_to_dist, V_v

    # For a vertex v, its calculated matrix V_v (output of collecting_votes) and the parameters epsilon and eta (default 2 each), classifies and returns its orientation:
    # 1 if it belongs to a surface patch, 2 if it belongs to a crease junction or 3 if it doesn't have a preferred orientation.
    # Adds the "orientation_class", the estimated normal "N_v" (if class is 1) and the estimated_tangent "T_v" (if class is 2) as vertex properties into the graph.
    # This is done using eigen-decomposition of V_v and equations (9) and (10). Also equations (11) and (12) may help to choose epsilon and eta.
    def classifying_orientation(self, vertex_v, V_v, epsilon=2, eta=2, verbose=False):
        # Decompose the symmetric semidefinite matrix V_v:
        eigenvalues, eigenvectors = np.linalg.eigh(V_v)  # eigenvalues are in increasing order and eigenvectors are in columns of the returned quadratic matrix
        # Eigenvalues from highest to lowest:
        lambda_1 = eigenvalues[2]
        lambda_2 = eigenvalues[1]
        lambda_3 = eigenvalues[0]
        # Eigenvectors, corresponding to the eigenvalues:
        E_1 = eigenvectors[:, 2]
        E_2 = eigenvectors[:, 1]
        E_3 = eigenvectors[:, 0]
        # Saliency maps:
        S_s = lambda_1 - lambda_2  # surface patch
        S_c = lambda_2 - lambda_3  # crease junction
        S_n = lambda_3  # no preferred orientation

        if verbose is True:
            print "\nlambda_1 = %s" % lambda_1
            print "lambda_2 = %s" % lambda_2
            print "lambda_3 = %s" % lambda_3
            print "E_1 = %s" % E_1
            print "E_2 = %s" % E_2
            print "E_3 = %s" % E_3
            print "S_s = %s" % S_s
            print "S_c = %s" % S_c
            print "epsilon * S_c = %s" % str(epsilon * S_c)
            print "S_n = %s" % S_n
            print "epsilon * eta * S_n = %s" % str(epsilon * eta * S_n)

        # Make decision and add the estimated normal or tangent as properties to the graph (add a placeholder [0, 0, 0] to each property, where it does not apply):
        max_saliency = max(S_s, epsilon * S_c, epsilon * eta * S_n)
        if max_saliency == S_s:
            # Eventually have to flip (negate) the estimated normal, because its direction is lost during the matrix generation!
            # Take the one for which the angle to the original normal is smaller (or cosine of the angle is higher):
            normal1 = E_1
            normal2 = -E_1
            orig_normal = self.graph.vp.normal[vertex_v]
            cos_angle1 = np.dot(orig_normal, normal1)
            cos_angle2 = np.dot(orig_normal, normal2)
            if cos_angle1 > cos_angle2:
                N_v = normal1
            else:
                N_v = normal2
            if verbose is True:
                print "surface patch with normal N_v = %s" % N_v
            self.graph.vp.orientation_class[vertex_v] = 1
            self.graph.vp.N_v[vertex_v] = N_v
            self.graph.vp.T_v[vertex_v] = np.zeros(shape=3)
            return 1
        elif max_saliency == (epsilon * S_c):
            if verbose is True:
                print "crease junction with tangent T_v = %s" % E_3
            self.graph.vp.orientation_class[vertex_v] = 2
            self.graph.vp.T_v[vertex_v] = E_3
            self.graph.vp.N_v[vertex_v] = np.zeros(shape=3)
            return 2
        else:
            if verbose is True:
                print "no preferred orientation"
            self.graph.vp.orientation_class[vertex_v] = 3
            self.graph.vp.N_v[vertex_v] = np.zeros(shape=3)
            self.graph.vp.T_v[vertex_v] = np.zeros(shape=3)
            return 3

    # For a vertex v, collects the curvature and tangent votes of all triangles within its geodesic neighborhood belonging to a surface patch and calculates the matrix B_v.
    # Implements equations (13) and (15) also illustrated in figure 6(c), (16), (17), (14), and (5) from the paper.
    # In short, three components are calculated for each neighboring vertex (representing triangle centroid) v_i:
    # 1) Weight w_i depending on the geodesic distance between v_i and v (so that all weight sum up to 2 * pi).
    # 2) Tangent T_i from v in the direction of the arc connecting v and v_i (using the estimated normal N_v at v).
    # 3) Normal curvature kappa_i, which is the turning angle between N_v and the projection of the estimated normal of v_i (N_v_i) onto the arc plane (formed by v, N_v and v_i) divided by the arc length.
    # Those components are incorporated into the 3x3 symmetric matrix B_v (Eq. 5), which is returned.
    def collecting_votes2(self, vertex_v, neighbor_idx_to_dist, sigma, verbose=False):
        # To spare function referencing every time in the following for loop:
        vertex = self.graph.vertex
        vp_N_v = self.graph.vp.N_v
        orientation_class = self.graph.vp.orientation_class
        exp = math.exp
        xyz = self.graph.vp.xyz
        array = np.array
        dot = np.dot
        vector_length = np.linalg.norm
        pi = math.pi
        cross = np.cross
        acos = math.acos
        outer = np.outer

        # Get the coordinates of vertex v and its estimated normal N_v (as numpy array):
        v = xyz[vertex_v]
        v = array(v)
        N_v = array(vp_N_v[vertex_v])

        # First, calculate the weights w_i of the neighboring triangles belonging to a surface patch, because they have to be normalized to sum up to 2 * pi:
        surface_neighbors_idx = []
        all_w_i = []
        for idx_v_i in neighbor_idx_to_dist.keys():
            # Get the neighboring vertex v_i:
            vertex_v_i = vertex(idx_v_i)

            # Check if the neighboring vertex v_i belongs to a surface patch (otherwise don't consider it):
            if orientation_class[vertex_v_i] == 1:
                surface_neighbors_idx.append(idx_v_i)
                # Weight depending on the geodesic distance to the neighboring vertex v_i from the vertex v, g_i:
                g_i = neighbor_idx_to_dist[idx_v_i]
                w_i = exp(- g_i / sigma)
                all_w_i.append(w_i)

        all_w_i = array(all_w_i)
        sum_w_i = np.sum(all_w_i)

        try:
            assert(sum_w_i > 0)
        except AssertionError:  # the sum can be 0 if no surface patch neighbors exist
            print "\nWarning: sum of the weights is not positive, but %s, for the vertex v = %s" % (sum_w_i, v)
            if len(surface_neighbors_idx) == 0:
                print "No neighbors in a surface patch."
            else:
                print "%s neighbors in a surface patch with weights w_i:" % len(surface_neighbors_idx)
                print all_w_i
            print "The vertex will be ignored."
            return None

        wanted_sum_w_i = 2 * pi
        factor = wanted_sum_w_i / sum_w_i
        all_w_i = factor * all_w_i  # normalized weights!

        if verbose:
            print "\nv = %s" % v
            print "N_v = %s" % N_v
            print "%s neighbors in a surface patch with normalized weights w_i:" % len(surface_neighbors_idx)
            print all_w_i

        # Initialize the weighted matrix sum of all votes for vertex v to be calculated:
        B_v = np.zeros(shape=(3, 3))

        # Let each of the neighboring triangles belonging to a surface patch (as checked before) to cast a vote on vertex v:
        for i, idx_v_i in enumerate(surface_neighbors_idx):
            # Get the neighboring vertex v_i:
            vertex_v_i = vertex(idx_v_i)

            # Second, calculate tangent directions T_i of each vote:
            v_i = xyz[vertex_v_i]
            v_i = array(v_i)
            vv_i = v_i - v
            t_i = vv_i - dot(N_v, vv_i) * N_v
            t_i_len = vector_length(t_i)
            T_i = t_i / t_i_len

            # Third, calculate the normal curvature kappa_i:
            P_i = cross(N_v, T_i)  # vector perpendicular to the plane that contains both N_v and T_i as well as the normal curve (between v and v_i),
            N_v_i = array(vp_N_v[vertex_v_i])  # estimated normal of vertex v_i
            n_i = N_v_i - dot(P_i, N_v_i) * P_i  # projection of N_v_i on the plane containing  N_v - rooted at v - and v_i
            n_i_len = vector_length(n_i)
            cos_tetha = dot(N_v, n_i) / n_i_len  # y is the turning angle between n_i and N_v
            try:
                tetha = acos(cos_tetha)
            except ValueError:
                if cos_tetha > 1:
                    cos_tetha = 1.0
                elif cos_tetha < 0:
                    cos_tetha = 0.0
                tetha = acos(cos_tetha)
            s = neighbor_idx_to_dist[idx_v_i]  # arc length s = g_i
            kappa_i = tetha / s

            w_i = all_w_i[i]  # recover the corresponding weight, which was calculated and normalized before

            if verbose:
                print "\nv_i = %s" % v_i
                print "vv_i = %s" % vv_i
                print "t_i = %s" % t_i
                print "||t_i|| = %s" % t_i_len
                print "T_i = %s" % T_i
                print "P_i = %s" % P_i
                print "N_v_i = %s" % N_v_i
                print "n_i = %s" % n_i
                print "||n_i|| = %s" % n_i_len
                print "tetha = %s" % tetha
                print "s = g_i = %s" % s
                print "kappa_i = %s" % kappa_i
                print "w_i = %s" % w_i

            # Finally, sum up the components of B_v:
            B_v += w_i * kappa_i * outer(T_i, T_i)
        # and normalize it by 2 * pi:
        B_v /= (2 * pi)

        if verbose:
            print "\nB_v = %s" % B_v
        return B_v

    # For a vertex v and its calculated matrix B_v, calculates the principal directions (T_1 and T_2) and curvatures (kappa_1 and kappa_2) at this vertex and adds them as vertex properties into the graph.
    # This is done using eigen-decomposition of B_v: the eigenvectors corresponding to the two largest eigenvalues are the principal directions and the principal curvatures are found with the linear transformations of
    # those eigenvalues in equation (4).
    def estimate_curvature(self, vertex_v, B_v, verbose=False):
        # Decompose the symmetric matrix B_v:
        eigenvalues, eigenvectors = np.linalg.eigh(B_v)  # eigenvalues are in increasing order and eigenvectors are in columns of the returned quadratic matrix
        # Eigenvalues from highest to lowest:
        b_1 = eigenvalues[2]
        b_2 = eigenvalues[1]
        # Eigenvectors that correspond to the highest two eigenvalues are the estimated principal directions:
        T_1 = eigenvectors[:, 2]
        T_2 = eigenvectors[:, 1]
        # Estimated principal curvatures:
        kappa_1 = 3 * b_1 - b_2
        kappa_2 = 3 * b_2 - b_1

        if verbose:
            print "\nb_1 = %s" % b_1
            print "b_2 = %s" % b_2
            print "T_1 = %s" % T_1
            print "T_2 = %s" % T_2
            print "kappa_1 = %s" % kappa_1
            print "kappa_2 = %s" % kappa_2

        # Add T_1, T_2, kappa_1, kappa_2, derived Gaussian and mean curvatures as well as shape index and curvedness as properties to the graph:
        self.graph.vp.T_1[vertex_v] = T_1
        self.graph.vp.T_2[vertex_v] = T_2
        self.graph.vp.kappa_1[vertex_v] = kappa_1
        self.graph.vp.kappa_2[vertex_v] = kappa_2
        self.graph.vp.gauss_curvature_VV[vertex_v] = kappa_1 * kappa_2
        self.graph.vp.mean_curvature_VV[vertex_v] = (kappa_1 + kappa_2) / 2
        self.graph.vp.shape_index_VV[vertex_v] = 2 / math.pi * math.atan((kappa_1 + kappa_2) / (kappa_1 - kappa_2))
        self.graph.vp.curvedness_VV[vertex_v] = math.sqrt((kappa_1 ** 2 + kappa_2 ** 2) / 2)
