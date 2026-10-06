# -*- coding: utf-8 -*-
"""Imitation minimale de l'API Python Metashape 2.x, pour tester le script hors logiciel.

Seuls les éléments utilisés par volumes_stocks.py sont simulés. Les noms et
signatures suivent l'API Metashape 2.x ; ils ne garantissent pas à eux seuls
la compatibilité avec le vrai logiciel.
"""


class Vector(object):
    def __init__(self, valeurs):
        self._v = [float(v) for v in valeurs]

    def __getitem__(self, i):
        return self._v[i]

    def __len__(self):
        return len(self._v)

    @property
    def x(self):
        return self._v[0]

    @property
    def y(self):
        return self._v[1]

    @property
    def z(self):
        if len(self._v) < 3:
            raise AttributeError("vecteur 2D")
        return self._v[2]


class CoordinateSystem(object):
    """SCR simulé : décalage (dx, dy) par rapport au SCR « A »."""

    def __init__(self, wkt, decalage=(0.0, 0.0)):
        self.wkt = wkt
        self.decalage = decalage

    @staticmethod
    def transform(point, source, cible):
        x = point[0] - source.decalage[0] + cible.decalage[0]
        y = point[1] - source.decalage[1] + cible.decalage[1]
        z = point[2] if len(point) > 2 else 0.0
        return Vector([x, y, z])


class _Type(object):
    def __init__(self, nom):
        self.nom = nom

    def __str__(self):
        return "Metashape.Geometry.Type." + self.nom


class Geometry(object):
    def __init__(self, nom, coordonnees):
        self.type = _Type(nom)
        self.coordinates = coordonnees

    @staticmethod
    def Polygon(exterieur, *trous):
        return Geometry("PolygonType", [list(exterieur)] + [list(t) for t in trous])

    @staticmethod
    def MultiPolygon(polygones):
        return Geometry("MultiPolygonType", polygones)

    @staticmethod
    def LineString(points):
        return Geometry("LineStringType", list(points))

    @staticmethod
    def Point(point):
        return Geometry("PointType", point)


class ShapeGroup(object):
    _cle = 0

    def __init__(self, label=""):
        ShapeGroup._cle += 1
        self.key = ShapeGroup._cle
        self.label = label
        self.color = (0, 0, 0)
        self.enabled = True


class Shape(object):
    def __init__(self):
        self.label = ""
        self.group = None
        self.geometry = None
        self.attributes = {}
        self.description = ""
        self.selected = False
        self.is_attached = False
        self.volume_natif = {"above": 10.0, "below": 1.0}

    def volume(self, level="bestfit"):
        return self.volume_natif


class Shapes(object):
    def __init__(self, crs):
        self.crs = crs
        self.groups = []
        self.shapes = []

    def __iter__(self):
        return iter(list(self.shapes))

    def addGroup(self):
        g = ShapeGroup()
        self.groups.append(g)
        return g

    def addShape(self):
        s = Shape()
        self.shapes.append(s)
        return s

    def remove(self, elements):
        if not isinstance(elements, (list, tuple)):
            elements = [elements]
        for e in elements:
            if e in self.shapes:
                self.shapes.remove(e)
            if e in self.groups:
                self.groups.remove(e)


class Elevation(object):
    _cle = 0

    def __init__(self, fonction, crs, resolution=0.05, label="DEM"):
        Elevation._cle += 1
        self.key = Elevation._cle
        self.fonction = fonction
        self.crs = crs
        self.resolution = resolution
        self.label = label

    def altitude(self, point):
        z = self.fonction(point[0], point[1])
        return -32767.0 if z is None else z


class _Enum(object):
    def __init__(self, **valeurs):
        self.__dict__.update(valeurs)


PointClass = _Enum(Created=0, Unclassified=1, Ground=2, LowVegetation=3, MediumVegetation=4,
                   HighVegetation=5, Building=6, LowPoint=7, Water=9, RoadSurface=11,
                   HighNoise=18, Car=19, Manmade=20)
Interpolation = _Enum(DisabledInterpolation=0, EnabledInterpolation=1, Extrapolated=2)
PointCloudData = "PointCloudData"


class PointCloud(object):
    def __init__(self):
        self.classifications = []

    def classifyPoints(self, target_classes=None, confidence=0.0):
        self.classifications.append(list(target_classes))


class Chunk(object):
    def __init__(self, label, crs, elevations, crs_formes):
        self.label = label
        self.crs = crs
        self.elevations = list(elevations)
        self.elevation = self.elevations[0] if self.elevations else None
        self.shapes = Shapes(crs_formes)
        self.markers = []
        self.point_cloud = None
        self.appels_build_dem = []
        self.surface_filtree = None

    def buildDem(self, **kwargs):
        self.appels_build_dem.append(kwargs)
        el = Elevation(self.surface_filtree, self.crs, 0.05, "nouveau")
        self.elevations.append(el)
        self.elevation = el


class Document(object):
    def __init__(self, chunks, path=""):
        self.chunks = chunks
        self.chunk = chunks[0] if chunks else None
        self.path = path


class Application(object):
    version = "2.3.0"

    def __init__(self):
        self.document = None
        self.menus = {}
        self.messages = []

    def update(self):
        pass

    def addMenuItem(self, libelle, fonction):
        self.menus[libelle] = fonction

    def messageBox(self, texte):
        self.messages.append(texte)

    def getSaveFileName(self, *args):
        return ""


app = Application()
