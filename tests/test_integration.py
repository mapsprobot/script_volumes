# -*- coding: utf-8 -*-
"""Test de bout en bout de executer() avec un faux module Metashape."""

import csv
import math
import os
import shutil
import sys
import tempfile
import unittest

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ICI, ".."))
sys.path.insert(0, ICI)

import faux_metashape as fm  # noqa: E402
import volumes_stocks as vs  # noqa: E402

X0, Y0 = 700000.0, 6600000.0          # centre du chantier dans le SCR du MNE (« A »)
DECALAGE_FORMES = (1000.0, 2000.0)    # SCR des formes (« B ») = A + décalage
R, H = 10.0, 5.0
V_CONE = math.pi * R * R * H / 3.0
CENTRES = [(X0, Y0), (X0 + 40.0, Y0)]
ARBRE = (X0 + 5.0, Y0)


def mns(x, y, arbre=True):
    z = 100.0
    for cx, cy in CENTRES:
        z += max(0.0, H * (1.0 - math.hypot(x - cx, y - cy) / R))
    if arbre and math.hypot(x - ARBRE[0], y - ARBRE[1]) <= 1.5:
        z += 6.0
    angle = math.degrees(math.atan2(y - Y0, x - X0)) % 360
    if 11.8 <= math.hypot(x - X0, y - Y0) <= 13.0 and 60 <= angle <= 140:
        z += 1.5  # buissons au pied du stock A
    return z


def cercle_b(cx, cy, rayon, n=72):
    return [fm.Vector([cx + DECALAGE_FORMES[0] + rayon * math.cos(2 * math.pi * k / n),
                       cy + DECALAGE_FORMES[1] + rayon * math.sin(2 * math.pi * k / n), 0.0])
            for k in range(n)]


class TestIntegration(unittest.TestCase):

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        crs_a = fm.CoordinateSystem('PROJCS["RGF93 / Lambert-93 (A)"]')
        crs_b = fm.CoordinateSystem('PROJCS["Formes (B)"]', DECALAGE_FORMES)
        self.mne = fm.Elevation(mns, crs_a, 0.05, "MNE drone")
        chunk = fm.Chunk("Chantier", crs_a, [self.mne], crs_b)
        chunk.surface_filtree = lambda x, y: mns(x, y, arbre=False)
        formes = chunk.shapes
        g_stocks, g_excl, g_divers = formes.addGroup(), formes.addGroup(), formes.addGroup()
        g_stocks.label, g_excl.label, g_divers.label = "Stocks", "Exclusions", "Divers"

        a = formes.addShape()
        a.label, a.group = "Stock A", g_stocks
        a.geometry = fm.Geometry.Polygon(cercle_b(X0, Y0, 12.0))
        b = formes.addShape()
        b.label, b.group = "Stock B", g_stocks
        b.geometry = fm.Geometry.Polygon(cercle_b(X0 + 40.0, Y0, 12.0))
        b.description = "methode=altitude; altitude=100; densite=1,6"
        e = formes.addShape()
        e.label, e.group = "Arbre", g_excl
        e.geometry = fm.Geometry.Polygon(cercle_b(ARBRE[0], ARBRE[1], 2.0, 24))
        d = formes.addShape()
        d.label, d.group = "Autre", g_divers
        d.geometry = fm.Geometry.Polygon(cercle_b(X0 + 80.0, Y0, 5.0))
        self.chunk, self.stock_a, self.stock_b = chunk, a, b
        fm.app.document = fm.Document([chunk], os.path.join(self.dossier, "projet.psx"))
        self.ancien = vs.Metashape
        vs.Metashape = fm

    def tearDown(self):
        vs.Metashape = self.ancien
        shutil.rmtree(self.dossier)

    def lire_csv(self, chemin):
        with open(chemin, encoding="utf-8-sig") as f:
            lignes = list(csv.reader(f, delimiter=";"))
        entete = next(i for i, l in enumerate(lignes) if l and l[0] == "Stock")
        colonnes = lignes[entete]
        return [dict(zip(colonnes, l)) for l in lignes[entete + 1:]]

    def test_executer(self):
        sortie = vs.executer({"fichier_csv": os.path.join(self.dossier, "volumes.csv")})
        res = {r["nom"]: r for r in sortie["resultats"]}
        self.assertEqual(sorted(res), ["Stock A", "Stock B"])
        a, b = res["Stock A"], res["Stock B"]
        # Stock A : base plan robuste (buissons au pied rejetés), arbre exclu
        self.assertEqual(a["methode"], "plan")
        bosse = 1.5 * (80.0 / 360.0) * math.pi * (12.0 ** 2 - 11.8 ** 2)
        self.assertAlmostEqual(a["volume_net"], V_CONE + bosse, delta=0.015 * V_CONE)
        self.assertTrue(any(t["raison"] == "rejet_auto" for t in a["pied_ignore"]))
        # Stock B : paramètres lus dans la description de la forme
        self.assertEqual(b["methode"], "altitude")
        self.assertAlmostEqual(b["volume_net"], V_CONE, delta=0.01 * V_CONE)
        self.assertAlmostEqual(b["tonnage"], 1.6 * b["volume_net"])
        self.assertAlmostEqual(a["volume_metashape"], 9.0)
        # Attributs écrits sur les formes
        self.assertAlmostEqual(float(self.stock_a.attributes["Vol_net_m3"]), a["volume_net"], places=2)
        self.assertEqual(self.stock_b.attributes["Vol_methode"], "altitude")
        # Formes de contrôle dans le SCR des formes (décalage B)
        groupes = [g for g in self.chunk.shapes.groups if g.label == vs.GROUPE_CONTROLE]
        self.assertEqual(len(groupes), 1)
        controle = [s for s in self.chunk.shapes if s.group is groupes[0]]
        self.assertTrue(controle)
        p = controle[0].geometry.coordinates[0]
        self.assertLess(abs(math.hypot(p.x - X0 - DECALAGE_FORMES[0], p.y - Y0 - DECALAGE_FORMES[1]) - 12.0), 0.2)
        # Une seconde exécution remplace le groupe de contrôle au lieu de l'empiler
        vs.executer({"fichier_csv": os.path.join(self.dossier, "volumes2.csv")})
        self.assertEqual(len([g for g in self.chunk.shapes.groups if g.label == vs.GROUPE_CONTROLE]), 1)
        # CSV au format français
        lignes = self.lire_csv(sortie["csv"])
        self.assertEqual([l["Stock"] for l in lignes], ["Stock A", "Stock B", "TOTAL"])
        total = float(lignes[-1]["Volume net (m3)"].replace(",", "."))
        self.assertAlmostEqual(total, a["volume_net"] + b["volume_net"], delta=0.1)
        self.assertIn(",", lignes[0]["Surface 2D (m2)"])

    def test_csv_par_defaut_a_cote_du_projet(self):
        sortie = vs.executer({"formes_controle": False})
        self.assertEqual(os.path.dirname(sortie["csv"]), self.dossier)
        self.assertTrue(os.path.basename(sortie["csv"]).startswith("projet_volumes_Chantier_"))

    def test_groupe_absent_utilise_la_selection(self):
        self.stock_b.selected = True
        sortie = vs.executer({"groupe_stocks": "Inexistant", "fichier_csv": os.path.join(self.dossier, "s.csv")})
        self.assertEqual([r["nom"] for r in sortie["resultats"]], ["Stock B"])

    def test_mne_filtre(self):
        with self.assertRaises(vs.ErreurScript):  # pas de nuage dense
            vs.executer({"construire_mne_filtre": True})
        self.chunk.point_cloud = fm.PointCloud()
        sortie = vs.executer({"construire_mne_filtre": True, "classer_points": True, "groupe_exclusions": "",
                              "fichier_csv": os.path.join(self.dossier, "f.csv")})
        appel = self.chunk.appels_build_dem[-1]
        self.assertNotIn(fm.PointClass.HighVegetation, appel["classes"])
        self.assertIn(fm.PointClass.Ground, appel["classes"])
        self.assertEqual(appel["interpolation"], fm.Interpolation.EnabledInterpolation)
        self.assertTrue(self.chunk.point_cloud.classifications)
        a = {r["nom"]: r for r in sortie["resultats"]}["Stock A"]
        bosse = 1.5 * (80.0 / 360.0) * math.pi * (12.0 ** 2 - 11.8 ** 2)
        self.assertAlmostEqual(a["volume_net"], V_CONE + bosse, delta=0.015 * V_CONE)

    def test_mne_reference_et_erreurs(self):
        self.chunk.elevations.append(fm.Elevation(lambda x, y: 100.0, self.chunk.crs, 0.1, "Sol a vide"))
        self.stock_b.description = "methode=mne_reference; reference=Sol a vide"
        self.stock_a.description = "methode=altitude"  # altitude manquante -> erreur sur ce stock seulement
        sortie = vs.executer({"fichier_csv": os.path.join(self.dossier, "r.csv")})
        res = {r["nom"]: r for r in sortie["resultats"]}
        self.assertIsNone(res["Stock A"].get("volume_net"))
        self.assertTrue(res["Stock A"]["alertes"][0].startswith("ERREUR"))
        self.assertAlmostEqual(res["Stock B"]["volume_net"], V_CONE, delta=0.01 * V_CONE)
        lignes = self.lire_csv(sortie["csv"])
        self.assertTrue(lignes[0]["Alertes / erreurs"].startswith("ERREUR"))

    def test_mne_geographique(self):
        wgs84 = fm.CoordinateSystem('GEOGCS["WGS 84"]')
        lon0, lat0 = 2.35, 48.85
        rep = vs.Repere(wgs84, lon0, lat0)

        def surface(lon, lat):
            u, v = rep.vers_local(lon, lat)
            return 100.0 + max(0.0, H * (1.0 - math.hypot(u, v) / R))
        chunk = fm.Chunk("Geo", wgs84, [fm.Elevation(surface, wgs84, 0.05 / rep.ky, "MNE")], wgs84)
        forme = chunk.shapes.addShape()
        forme.label = "Stock geo"
        forme.geometry = fm.Geometry.Polygon([fm.Vector(list(rep.vers_mne(12 * math.cos(t / 36.0 * math.pi),
                                                                         12 * math.sin(t / 36.0 * math.pi))))
                                              for t in range(72)])
        fm.app.document = fm.Document([chunk], os.path.join(self.dossier, "geo.psx"))
        sortie = vs.executer({"pas_grille": 0.1, "formes_controle": False})
        r = sortie["resultats"][0]
        self.assertAlmostEqual(r["volume_net"], V_CONE, delta=0.01 * V_CONE)
        self.assertAlmostEqual(r["surface_2d"], math.pi * 144, delta=0.01 * math.pi * 144)

    def test_menu_et_lancer_sans_qt(self):
        ancien_qt = vs.QtWidgets
        vs.QtWidgets = None
        try:
            vs.CONFIG["fichier_csv"] = os.path.join(self.dossier, "menu.csv")
            vs.lancer()
        finally:
            vs.CONFIG["fichier_csv"] = ""
            vs.QtWidgets = ancien_qt
        self.assertIn("TOTAL", fm.app.messages[-1])


if __name__ == "__main__":
    unittest.main()
