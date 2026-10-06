# -*- coding: utf-8 -*-
"""Tests du noyau de calcul sur des stocks synthétiques au volume connu.

Lancement : python -m unittest discover -s tests -v
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import volumes_stocks as vs  # noqa: E402

R, H, Z0 = 10.0, 5.0, 100.0
V_CONE = math.pi * R * R * H / 3.0


def cercle(rayon, n=72, cx=0.0, cy=0.0):
    return [(cx + rayon * math.cos(2 * math.pi * k / n), cy + rayon * math.sin(2 * math.pi * k / n))
            for k in range(n)]


def cone(x, y, sol=lambda x, y: Z0):
    return sol(x, y) + max(0.0, H * (1.0 - math.hypot(x, y) / R))


def integrer(f, x0, y0, x1, y1, pas=0.05):
    """Intégrale numérique de f sur un rectangle (référence)."""
    total = 0.0
    nx, ny = int(round((x1 - x0) / pas)), int(round((y1 - y0) / pas))
    for j in range(ny):
        y = y0 + (j + 0.5) * pas
        for i in range(nx):
            total += f(x0 + (i + 0.5) * pas, y)
    return total * pas * pas


def params(**kw):
    p = dict(vs.CONFIG)
    p.update({"pas_grille": 0.1, "resolution_mne_m": 0.05})
    p.update(kw)
    return p


class TestGeometrie(unittest.TestCase):

    def test_aire_et_point_dans(self):
        carre = [(0, 0), (10, 0), (10, 10), (0, 10)]
        trou = [(4, 4), (6, 4), (6, 6), (4, 6)]
        self.assertAlmostEqual(vs.aire_signee(carre), 100.0)
        self.assertTrue(vs.point_dans([carre, trou], 1, 1))
        self.assertFalse(vs.point_dans([carre, trou], 5, 5))
        self.assertFalse(vs.point_dans([carre], 11, 5))

    def _verifier_triangulation(self, anneau):
        tris = vs.trianguler(anneau)
        self.assertIsNotNone(tris)
        self.assertEqual(len(tris), len(anneau) - 2)
        aire = sum(abs(vs._orient(anneau[a], anneau[b], anneau[c])) / 2.0 for a, b, c in tris)
        self.assertAlmostEqual(aire, abs(vs.aire_signee(anneau)), places=6)
        for a, b, c in tris:
            self.assertGreater(vs._orient(anneau[a], anneau[b], anneau[c]), 0)

    def test_triangulation_concave(self):
        en_l = [(0, 0), (20, 0), (20, 5), (5, 5), (5, 20), (0, 20)]
        self._verifier_triangulation(en_l)
        self._verifier_triangulation(list(reversed(en_l)))
        etoile = [((10 if k % 2 == 0 else 4) * math.cos(math.pi * k / 7),
                   (10 if k % 2 == 0 else 4) * math.sin(math.pi * k / 7)) for k in range(14)]
        self._verifier_triangulation(etoile)

    def test_triangulation_cocirculaire(self):
        self._verifier_triangulation(cercle(12.0, 64))

    def test_simplification(self):
        anneau = cercle(50.0, 2000)
        garde = vs.simplifier_anneau(anneau, 400)
        self.assertLessEqual(len(garde), 400)
        self.assertGreater(abs(vs.aire_signee([anneau[i] for i in garde])), 0.99 * math.pi * 2500)

    def test_ajustement_robuste_rejette_les_points_hauts(self):
        pts = [(x, y, 100.0 + 0.05 * x) for x in range(-20, 21, 2) for y in (-20, 20)]
        pts += [(x, 0.0, 103.0) for x in range(-20, 0, 2)]  # 1/3 de points aberrants
        modele, garde = vs.ajustement_robuste(pts, 1, True, 2.5, 0.1)
        self.assertAlmostEqual(vs.evaluer_modele(modele, 0, 0), 100.0, places=3)
        self.assertAlmostEqual(modele[1], 0.05, places=4)
        self.assertEqual(sum(1 for g in garde if not g), 10)

    def test_repere_geographique(self):
        wgs84 = type("CRS", (), {"wkt": 'GEOGCS["WGS 84",DATUM["WGS_1984"]]'})()
        lambert = type("CRS", (), {"wkt": 'PROJCS["RGF93 / Lambert-93",GEOGCS["RGF93"]]'})()
        self.assertFalse(vs.Repere(lambert, 0, 0).geographique)
        rep = vs.Repere(wgs84, 2.35, 48.85)
        self.assertTrue(rep.geographique)
        self.assertAlmostEqual(rep.ky, 111200, delta=200)
        self.assertAlmostEqual(rep.kx, 73400, delta=300)
        u, v = rep.vers_local(2.36, 48.86)
        x, y = rep.vers_mne(u, v)
        self.assertAlmostEqual(x, 2.36, places=9)
        self.assertAlmostEqual(y, 48.86, places=9)


class TestVolumes(unittest.TestCase):

    def test_cone_sol_plat(self):
        for methode in ("plan", "horizontal", "triangule"):
            r = vs.calculer_stock([[cercle(12.0)]], cone, params(methode_base=methode))
            self.assertAlmostEqual(r["volume_net"], V_CONE, delta=0.01 * V_CONE, msg=methode)
            self.assertLess(r["volume_dessous"], 0.5)
            self.assertAlmostEqual(r["hauteur_max"], H, delta=0.1)
            self.assertEqual(r["alertes"], [], msg=methode)
        r = vs.calculer_stock([[cercle(12.0)]], cone, params(methode_base="altitude", altitude_base=Z0))
        self.assertAlmostEqual(r["volume_net"], V_CONE, delta=0.01 * V_CONE)

    def test_cone_sur_pente(self):
        def sol(x, y):
            return Z0 + 0.05 * x + 0.03 * y

        def f(x, y):
            return cone(x, y, sol)
        for methode in ("plan", "triangule"):
            r = vs.calculer_stock([[cercle(12.0)]], f, params(methode_base=methode))
            self.assertAlmostEqual(r["volume_net"], V_CONE, delta=0.01 * V_CONE, msg=methode)
            self.assertLess(r["volume_dessous"], 0.5, msg=methode)
        r = vs.calculer_stock([[cercle(12.0)]], f, params(methode_base="plan"))
        self.assertAlmostEqual(r["pente_base_pct"], 100 * math.hypot(0.05, 0.03), delta=0.05)
        r = vs.calculer_stock([[cercle(12.0)]], f, params(methode_base="horizontal"))
        self.assertGreater(r["volume_dessous"], 20.0)  # un plan horizontal ne convient pas

    def test_vegetation_au_pied(self):
        def buisson(x, y):
            a = math.degrees(math.atan2(y, x)) % 360
            return 1.5 if (11.8 <= math.hypot(x, y) <= 13.0 and a <= 100) else 0.0

        def f(x, y):
            return cone(x, y) + buisson(x, y)
        attendu = integrer(lambda x, y: (f(x, y) - Z0) if math.hypot(x, y) <= 12.0 else 0.0,
                           -12, -12, 12, 12)
        # Buisson continu sur 28 % du pied : géré par le plan robuste
        for methode in ("plan", "horizontal"):
            r = vs.calculer_stock([[cercle(12.0)]], f, params(methode_base=methode))
            self.assertAlmostEqual(r["volume_net"], attendu, delta=0.015 * attendu, msg=methode)
            self.assertLess(r["pied_retenu_pct"], 80.0)
            self.assertTrue(any(t["raison"] == "rejet_auto" for t in r["pied_ignore"]))
        sans_rejet = vs.calculer_stock([[cercle(12.0)]], f, params(rejet_points_hauts=False))
        self.assertLess(sans_rejet["volume_net"], attendu - 100.0)

    def test_buissons_isoles_base_triangulee(self):
        centres = [(12.0 * math.cos(math.radians(a)), 12.0 * math.sin(math.radians(a))) for a in (20, 140, 260)]

        def f(x, y):
            bosse = 1.5 if any(math.hypot(x - cx, y - cy) <= 1.5 for cx, cy in centres) else 0.0
            return cone(x, y) + bosse
        attendu = integrer(lambda x, y: (f(x, y) - Z0) if math.hypot(x, y) <= 12.0 else 0.0,
                           -12, -12, 12, 12)
        r = vs.calculer_stock([[cercle(12.0)]], f, params(methode_base="triangule"))
        self.assertAlmostEqual(r["volume_net"], attendu, delta=0.015 * attendu)
        self.assertTrue(any(t["raison"] == "rejet_auto" for t in r["pied_ignore"]))
        sans_rejet = vs.calculer_stock([[cercle(12.0)]], f, params(methode_base="triangule",
                                                                   rejet_points_hauts=False))
        self.assertLess(sans_rejet["volume_net"], attendu - 15.0)

    def test_stock_contre_mur_avec_epaulement(self):
        def h(x, y):
            taper = max(0.0, min(1.0, min(y, 20.0 - y) / 4.0))
            return max(0.0, 4.0 - 0.5 * x) * taper

        def f(x, y):
            return Z0 + h(x, y) if x >= 0 else Z0 + 6.0  # mur en x < 0
        rectangle = [(0, 0), (12, 0), (12, 20), (0, 20)]
        attendu = integrer(h, 0, 0, 12, 20)
        ligne_mur = [(0.0, -1.0), (0.0, 21.0)]
        for methode in ("plan", "horizontal", "triangule"):
            r = vs.calculer_stock([[rectangle]], f, params(methode_base=methode),
                                  epaulements_lignes=[ligne_mur])
            self.assertAlmostEqual(r["volume_net"], attendu, delta=0.015 * attendu, msg=methode)
            self.assertTrue(any(t["raison"] == "epaulement" for t in r["pied_ignore"]))
        # Sans déclarer l'épaulement ni rejet automatique, la base est faussée
        r = vs.calculer_stock([[rectangle]], f, params(rejet_points_hauts=False))
        self.assertLess(r["volume_net"], 0.8 * attendu)

    def test_stock_adosse_a_un_talus(self):
        def sol(x, y):
            return Z0 + 0.6 * max(0.0, x - 8.0)  # talus qui monte à partir de x = 8

        def f(x, y):
            taper = max(0.0, min(1.0, min(y, 30.0 - y) / 5.0))
            dessus = Z0 + (4.0 - 0.7 * max(0.0, 6.0 - x)) * taper
            return max(sol(x, y), dessus)
        attendu = integrer(lambda x, y: f(x, y) - sol(x, y), 0, 0, 15, 30)
        # Sommets ajoutés au pied du talus (x = 8) : la base triangulée suit le terrain
        polygone = [(0, 0), (8, 0), (15, 0), (15, 30), (8, 30), (0, 30)]
        r = vs.calculer_stock([[polygone]], f, params(methode_base="triangule"))
        self.assertAlmostEqual(r["volume_net"], attendu, delta=0.01 * attendu)
        # Le plan passe sous le talus : surestimation, signalée par une alerte
        r = vs.calculer_stock([[polygone]], f, params(methode_base="plan"))
        self.assertGreater(r["volume_net"], 1.3 * attendu)
        self.assertTrue(any("adossé" in a for a in r["alertes"]))

    def test_exclusion_arbre(self):
        def f(x, y):
            arbre = 6.0 if math.hypot(x - 5.0, y) <= 1.5 else 0.0
            return cone(x, y) + arbre
        brut = vs.calculer_stock([[cercle(12.0)]], f, params())
        self.assertGreater(brut["volume_net"], V_CONE + 30.0)
        r = vs.calculer_stock([[cercle(12.0)]], f, params(), exclusions=[[cercle(2.0, 24, 5.0, 0.0)]])
        self.assertAlmostEqual(r["volume_net"], V_CONE, delta=0.015 * V_CONE)
        self.assertGreater(r["interpole_pct"], 2.0)

    def test_exclusion_sur_le_pied(self):
        def f(x, y):
            arbre = 4.0 if math.hypot(x - 12.0, y) <= 2.0 else 0.0
            return cone(x, y) + arbre
        r = vs.calculer_stock([[cercle(12.0)]], f, params(rejet_points_hauts=False),
                              exclusions=[[cercle(2.5, 24, 12.0, 0.0)]])
        self.assertAlmostEqual(r["volume_net"], V_CONE, delta=0.015 * V_CONE)
        self.assertTrue(any(t["raison"] == "exclusion" for t in r["pied_ignore"]))

    def test_trous_du_mne(self):
        def f(x, y):
            if -3 <= x <= -1 and -1 <= y <= 1:
                return None
            return cone(x, y)
        r = vs.calculer_stock([[cercle(12.0)]], f, params())
        self.assertAlmostEqual(r["volume_net"], V_CONE, delta=0.01 * V_CONE)
        self.assertGreater(r["interpole_pct"], 0.5)

    def test_mne_reference(self):
        def sol(x, y):
            return Z0 + 0.3 * math.sin(x / 4.0) + 0.002 * y * y

        def f(x, y):
            return cone(x, y, sol)
        r = vs.calculer_stock([[cercle(12.0)]], f, params(methode_base="mne_reference"), reference=sol)
        self.assertAlmostEqual(r["volume_net"], V_CONE, delta=0.01 * V_CONE)

    def test_multipolygone_et_trou(self):
        def f(x, y):
            return cone(x, y) + cone(x - 40.0, y) - Z0
        r = vs.calculer_stock([[cercle(12.0)], [cercle(12.0, 72, 40.0, 0.0)]], f, params())
        self.assertAlmostEqual(r["volume_net"], 2 * V_CONE, delta=0.02 * V_CONE)
        carre = [(-12, -12), (12, -12), (12, 12), (-12, 12)]
        trou = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        r = vs.calculer_stock([[carre, trou]], cone, params())
        sommet = integrer(lambda x, y: cone(x, y) - Z0, -1, -1, 1, 1)
        self.assertAlmostEqual(r["volume_net"], V_CONE - sommet, delta=0.01 * V_CONE)
        self.assertAlmostEqual(r["surface_2d"], 24 * 24 - 4)

    def test_tonnage_et_parametres(self):
        r = vs.calculer_stock([[cercle(12.0)]], cone, params(densite="1,6"))
        self.assertAlmostEqual(r["tonnage"], 1.6 * r["volume_net"])
        with self.assertRaises(vs.ErreurStock):
            vs.calculer_stock([[cercle(12.0)]], cone, params(methode_base="altitude", altitude_base=None))
        with self.assertRaises(vs.ErreurStock):
            vs.calculer_stock([[cercle(12.0)]], cone, params(methode_base="inconnue"))
        with self.assertRaises(vs.ErreurStock):
            vs.calculer_stock([[[(0, 0), (1, 1)]]], cone, params())

    def test_pas_automatique(self):
        p = params(pas_grille=0, max_cellules=20000)
        r = vs.calculer_stock([[cercle(12.0)]], cone, p)
        self.assertLessEqual(r["nb_cellules"], 21000)
        self.assertAlmostEqual(r["volume_net"], V_CONE, delta=0.01 * V_CONE)


if __name__ == "__main__":
    unittest.main()
