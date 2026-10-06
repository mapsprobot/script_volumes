# -*- coding: utf-8 -*-
"""
Volumes de stocks - script Python pour Agisoft Metashape Professional
=====================================================================

Calcule automatiquement le volume (m3) de chaque stock dessiné sous
forme de polygone dans Metashape, à partir d'un MNE (MNS) - sans classification
préalable des points sol.

Pour chaque polygone du groupe de formes « Stocks » (tracé au pied du stock) :

1. le MNE est échantillonné sur une grille régulière à l'intérieur du polygone ;
2. les zones parasites (groupe « Exclusions » : arbre, engin, bloc...) et les
   trous éventuels du MNE sont reconstruits par interpolation depuis leur pourtour ;
3. une surface de base est estimée à partir du pied du stock en écartant
   automatiquement les points aberrants (végétation, objets) et les tronçons
   de pied déclarés comme épaulement (groupe « Epaulements » : mur, blocs, talus) ;
4. volume = somme (MNE - base) x surface de cellule.

Compatibilité : Metashape Professional 2.x (Python 3.9+). Aucune dépendance
externe (pas de numpy). Voir README.md pour l'installation et le mode opératoire.
"""

from __future__ import division, print_function

import csv
import datetime
import math
import os
import re
import time
import traceback
import unicodedata

try:
    import Metashape
except ImportError:  # exécution hors de Metashape (tests unitaires)
    Metashape = None

try:
    from PySide2 import QtWidgets
except ImportError:
    try:
        from PySide6 import QtWidgets
    except ImportError:
        QtWidgets = None


VERSION = "1.1.0"
LIBELLE_MENU = "Scripts/Volumes de stocks..."
GROUPE_CONTROLE = "Controle volumes - pied ignore"

# =============================================================================
# CONFIGURATION PAR DÉFAUT (modifiable ici ou dans la fenêtre du script)
# =============================================================================
CONFIG = {
    # --- Formes ----------------------------------------------------------------
    # Groupe(s) de formes contenant les polygones des stocks (séparés par des
    # virgules). Si le groupe n'existe pas : polygones sélectionnés, sinon tous
    # les polygones hors groupes d'exclusions / d'épaulements.
    "groupe_stocks": "Stocks",
    # Polygones autour des éléments parasites (arbre, engin, bloc...) : le MNE y
    # est ignoré et reconstruit par interpolation. "" = aucun.
    "groupe_exclusions": "Exclusions",
    # Épaulements contre lesquels le stock s'appuie. "" = aucun.
    #  - LIGNE le long d'un mur vertical (blocs béton, front de roche vertical) :
    #    le pied est ignoré le long de la ligne, la base du sol est prolongée ;
    #  - POLYGONE sur la face VISIBLE d'un épaulement incliné (talus naturel ou
    #    artificiel, flanc de roche incliné) : la pente de la face est prolongée
    #    sous le stock jusqu'au sol (base = le plus haut des deux).
    "groupe_epaulements": "Epaulements",
    "tolerance_epaulement": 0.5,  # m : distance d'influence des lignes d'épaulement
    "distance_epaulement": 5.0,   # m : un polygone d'épaulement s'applique aux stocks à moins de cette distance
    "pente_min_epaulement": 10.0, # % : face moins pentue = non prolongée (alerte)

    # --- Surface du stock (MNE) -------------------------------------------------
    "mne": "",  # libellé du MNE à utiliser ; "" = MNE actif du chunk
    # Construire un nouveau MNE depuis le nuage dense en excluant les classes
    # ci-dessous (végétation, véhicules, bruit), avec interpolation des trous.
    "construire_mne_filtre": False,
    # Lancer d'abord la classification automatique des points de Metashape
    # (attention : remplace les classes existantes du nuage).
    "classer_points": False,
    "classes_exclues": ["LowVegetation", "MediumVegetation", "HighVegetation",
                        "Car", "LowPoint", "HighNoise"],
    "resolution_mne": 0.0,  # m ; 0 = résolution automatique de Metashape

    # --- Base du stock -----------------------------------------------------------
    # plan | horizontal | triangule | altitude | mne_reference
    "methode_base": "plan",
    "altitude_base": None,  # m : pour la méthode "altitude"
    "mne_reference": "",    # libellé du MNE de base (méthode "mne_reference")
    "rejet_points_hauts": True,  # rejet automatique des points aberrants du pied
    "rejet_k": 2.5,              # seuil = max(k x écart-type robuste, rejet_min)
    "rejet_min": 0.10,           # m
    "fenetre_pied": 1.0,   # m : demi-fenêtre le long du pied pour l'altitude d'un sommet (triangulé)
    "fenetre_rejet": 8.0,  # m : demi-fenêtre de la médiane glissante (triangulé)

    # --- Calcul -------------------------------------------------------------------
    "pas_grille": 0.0,        # m ; 0 = automatique (résolution du MNE, plafonnée)
    "max_cellules": 400000,   # nombre maximal de cellules par stock en mode automatique
    "densite": 0.0,           # t/m3 ; 0 = volumes seuls (colonnes tonnage masquées)

    # --- Sorties ------------------------------------------------------------------
    "fichier_csv": "",        # "" = à côté du projet .psx
    "separateur_csv": ";",
    "virgule_decimale": True,
    "ecrire_attributs": True,   # résultats écrits dans les attributs des polygones
    "formes_controle": True,    # tronçons de pied ignorés dessinés dans un groupe de contrôle
    "comparer_metashape": True, # ajoute le volume « plan ajusté » natif de Metashape (contrôle)
}

METHODES = ("plan", "horizontal", "triangule", "altitude", "mne_reference")

DESCRIPTION_METHODES = {
    "plan": "Plan ajusté robuste sur le pied (terrain plat ou en pente régulière)",
    "horizontal": "Plan horizontal à l'altitude moyenne robuste du pied",
    "triangule": "Base triangulée sur les sommets du polygone (terrain irrégulier, stock adossé à un talus)",
    "altitude": "Plan horizontal à une altitude imposée (dalle, fond d'alvéole connu)",
    "mne_reference": "Un autre MNE sert de base (levé à vide, MNT, levé précédent)",
}

ALIAS_METHODES = {
    "plan": "plan", "plan_ajuste": "plan", "bestfit": "plan", "best_fit": "plan",
    "incline": "plan", "plan_incline": "plan",
    "horizontal": "horizontal", "moyen": "horizontal", "mean": "horizontal",
    "niveau_moyen": "horizontal", "plan_horizontal": "horizontal",
    "triangule": "triangule", "tin": "triangule", "triangulation": "triangule",
    "triangulee": "triangule",
    "altitude": "altitude", "fixe": "altitude", "altitude_fixe": "altitude",
    "custom": "altitude", "cote": "altitude",
    "mne_reference": "mne_reference", "reference": "mne_reference",
    "mne": "mne_reference", "mnt": "mne_reference", "surface": "mne_reference",
}

RAISONS_PIED = {
    "exclusion": "zone d'exclusion",
    "epaulement": "epaulement",
    "sans_donnees": "sans donnees MNE",
    "rejet_auto": "rejet automatique",
}

# Noms des classes de points Metashape (Metashape.PointClass)
CLASSES_POINTS = ["Created", "Unclassified", "Ground", "LowVegetation", "MediumVegetation",
                  "HighVegetation", "Building", "LowPoint", "ModelKeyPoint", "Water", "Rail",
                  "RoadSurface", "OverlapPoints", "WireGuard", "WireConductor",
                  "TransmissionTower", "WireConnector", "BridgeDeck", "HighNoise", "Car",
                  "Manmade", "ManMade"]


class ErreurStock(Exception):
    """Erreur bloquante pour un stock (les autres stocks sont tout de même calculés)."""


class ErreurScript(Exception):
    """Erreur bloquante pour l'ensemble du traitement."""


# =============================================================================
# OUTILS GÉNÉRAUX
# =============================================================================

def normaliser(texte):
    """Minuscules, sans accents, espaces et tirets remplacés par '_'."""
    texte = unicodedata.normalize("NFKD", str(texte or ""))
    texte = texte.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[\s\-]+", "_", texte.strip().lower())


def methode_normalisee(nom):
    methode = ALIAS_METHODES.get(normaliser(nom))
    if methode is None:
        raise ErreurStock("méthode de base inconnue : '%s' (possibles : %s)"
                          % (nom, ", ".join(METHODES)))
    return methode


def nombre(valeur):
    """Convertit '1,6' / '1.6' / 1.6 en float ; None si impossible."""
    if valeur is None or isinstance(valeur, bool):
        return None
    if isinstance(valeur, (int, float)):
        return float(valeur)
    texte = str(valeur).strip().replace(" ", "").replace(",", ".")
    try:
        return float(texte)
    except ValueError:
        return None


def mediane(valeurs):
    s = sorted(valeurs)
    n = len(s)
    if n == 0:
        return None
    m = n // 2
    return s[m] if n % 2 else 0.5 * (s[m - 1] + s[m])


def ecart_robuste(valeurs, centre=None):
    """Écart-type robuste : 1,4826 x médiane des écarts absolus."""
    if not valeurs:
        return 0.0
    if centre is None:
        centre = mediane(valeurs)
    return 1.4826 * mediane([abs(v - centre) for v in valeurs])


# =============================================================================
# GÉOMÉTRIE PLANE (coordonnées locales métriques)
# =============================================================================

def nettoyer_anneau(points, tol=1e-9):
    """Supprime les doublons consécutifs et le point de fermeture."""
    out = []
    for p in points:
        x, y = float(p[0]), float(p[1])
        if out and abs(x - out[-1][0]) <= tol and abs(y - out[-1][1]) <= tol:
            continue
        out.append((x, y))
    while len(out) > 1 and abs(out[0][0] - out[-1][0]) <= tol and abs(out[0][1] - out[-1][1]) <= tol:
        out.pop()
    return out


def aire_signee(anneau):
    s = 0.0
    n = len(anneau)
    for k in range(n):
        x1, y1 = anneau[k]
        x2, y2 = anneau[(k + 1) % n]
        s += x1 * y2 - x2 * y1
    return 0.5 * s


def longueur_anneau(anneau):
    n = len(anneau)
    return sum(math.hypot(anneau[(k + 1) % n][0] - anneau[k][0],
                          anneau[(k + 1) % n][1] - anneau[k][1]) for k in range(n))


def emprise(anneaux):
    xs = [p[0] for a in anneaux for p in a]
    ys = [p[1] for a in anneaux for p in a]
    return min(xs), min(ys), max(xs), max(ys)


def emprises_recouvrent(e1, e2, marge=0.0):
    return not (e1[2] + marge < e2[0] or e2[2] + marge < e1[0] or
                e1[3] + marge < e2[1] or e2[3] + marge < e1[1])


def croisements(anneaux, y):
    """Abscisses (triées) des intersections de l'horizontale y avec les anneaux."""
    xs = []
    for anneau in anneaux:
        n = len(anneau)
        for k in range(n):
            x1, y1 = anneau[k]
            x2, y2 = anneau[(k + 1) % n]
            if (y1 <= y < y2) or (y2 <= y < y1):
                xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    xs.sort()
    return xs


def intervalles(anneaux, y):
    """Intervalles [xa, xb] intérieurs (règle pair-impair) sur l'horizontale y."""
    xs = croisements(anneaux, y)
    return [(xs[k], xs[k + 1]) for k in range(0, len(xs) - 1, 2)]


def point_dans(anneaux, x, y):
    """Point dans le polygone (anneau extérieur + trous), règle pair-impair."""
    dedans = False
    for anneau in anneaux:
        n = len(anneau)
        for k in range(n):
            x1, y1 = anneau[k]
            x2, y2 = anneau[(k + 1) % n]
            if (y1 <= y < y2) or (y2 <= y < y1):
                if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                    dedans = not dedans
    return dedans


def distance_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 <= 0.0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _segments(anneaux):
    segs = []
    for a in anneaux:
        n = len(a)
        for k in range(n):
            segs.append((a[k][0], a[k][1], a[(k + 1) % n][0], a[(k + 1) % n][1]))
    return segs


def distance_polygones(a, b):
    """Distance minimale entre deux polygones (listes d'anneaux) ; 0 s'ils se touchent."""
    if any(point_dans(b, p[0], p[1]) for p in a[0]) or any(point_dans(a, p[0], p[1]) for p in b[0]):
        return 0.0
    d = float("inf")
    for s in _segments(a):
        for t in _segments(b):
            p1, p2, p3, p4 = (s[0], s[1]), (s[2], s[3]), (t[0], t[1]), (t[2], t[3])
            if ((_orient(p1, p2, p3) > 0) != (_orient(p1, p2, p4) > 0)
                    and (_orient(p3, p4, p1) > 0) != (_orient(p3, p4, p2) > 0)):
                return 0.0
            d = min(d, distance_segment(s[0], s[1], *t), distance_segment(s[2], s[3], *t),
                    distance_segment(t[0], t[1], *s), distance_segment(t[2], t[3], *s))
    return d


def densifier_anneau(anneau, pas):
    """Échantillonne un anneau fermé tous les `pas` mètres.

    Retourne (échantillons, indices des sommets, longueur) ; échantillon =
    (x, y, abscisse curviligne, indice de l'arête, fraction sur l'arête).
    """
    echantillons = []
    sommets = []
    s = 0.0
    n = len(anneau)
    for k in range(n):
        x1, y1 = anneau[k]
        x2, y2 = anneau[(k + 1) % n]
        longueur = math.hypot(x2 - x1, y2 - y1)
        sommets.append(len(echantillons))
        m = max(1, int(math.ceil(longueur / pas)))
        for t in range(m):
            f = t / m
            echantillons.append((x1 + f * (x2 - x1), y1 + f * (y2 - y1), s + f * longueur, k, f))
        s += longueur
    return echantillons, sommets, s


def simplifier_anneau(anneau, max_sommets):
    """Douglas-Peucker sur un anneau fermé ; retourne les indices conservés."""
    n = len(anneau)
    if n <= max_sommets:
        return list(range(n))

    def dp(chaine, tol):
        garde = {chaine[0], chaine[-1]}
        pile = [(0, len(chaine) - 1)]
        while pile:
            a, b = pile.pop()
            pa, pb = anneau[chaine[a]], anneau[chaine[b]]
            dmax, imax = -1.0, None
            for i in range(a + 1, b):
                p = anneau[chaine[i]]
                d = distance_segment(p[0], p[1], pa[0], pa[1], pb[0], pb[1])
                if d > dmax:
                    dmax, imax = d, i
            if imax is not None and dmax > tol:
                garde.add(chaine[imax])
                pile.append((a, imax))
                pile.append((imax, b))
        return garde

    # Coupe de l'anneau au sommet le plus éloigné du sommet 0
    loin = max(range(n), key=lambda i: math.hypot(anneau[i][0] - anneau[0][0], anneau[i][1] - anneau[0][1]))
    chaine1 = list(range(0, loin + 1))
    chaine2 = list(range(loin, n)) + [0]
    xmin, ymin, xmax, ymax = emprise([anneau])
    tol = 1e-3 * max(xmax - xmin, ymax - ymin, 1e-6)
    garde = list(range(n))
    for _ in range(60):
        garde = sorted(dp(chaine1, tol) | dp(chaine2, tol))
        if len(garde) <= max_sommets:
            return garde
        tol *= 1.5
    return garde


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _dans_cercle(a, b, c, d):
    """> 0 si d est dans le cercle circonscrit au triangle direct (a, b, c)."""
    adx, ady = a[0] - d[0], a[1] - d[1]
    bdx, bdy = b[0] - d[0], b[1] - d[1]
    cdx, cdy = c[0] - d[0], c[1] - d[1]
    return ((adx * adx + ady * ady) * (bdx * cdy - cdx * bdy)
            - (bdx * bdx + bdy * bdy) * (adx * cdy - cdx * ady)
            + (cdx * cdx + cdy * cdy) * (adx * bdy - bdx * ady))


def trianguler(anneau):
    """Triangulation d'un polygone simple (oreilles + bascules de Delaunay).

    Retourne une liste de triplets d'indices (triangles orientés dans le sens
    direct) ou None si le polygone n'a pas pu être triangulé (auto-intersection).
    """
    n = len(anneau)
    if n < 3:
        return None
    xmin, ymin, xmax, ymax = emprise([anneau])
    echelle = max(xmax - xmin, ymax - ymin, 1e-9)
    eps = 1e-12 * echelle * echelle
    idx = list(range(n))
    if aire_signee(anneau) < 0:
        idx.reverse()

    # Les sommets alignés en plan sont conservés : leur altitude peut porter une
    # rupture de pente (pied de talus) ; ils ne sont simplement jamais des oreilles.
    triangles = []
    depart = 0
    while len(idx) > 3:
        m = len(idx)
        trouve = False
        for dt in range(m):
            t = (depart + dt) % m
            i0, i1, i2 = idx[(t - 1) % m], idx[t], idx[(t + 1) % m]
            a, b, c = anneau[i0], anneau[i1], anneau[i2]
            if _orient(a, b, c) <= eps:
                continue  # sommet rentrant
            libre = True
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                p = anneau[j]
                if p == a or p == b or p == c:
                    continue
                if _orient(a, b, p) >= -eps and _orient(b, c, p) >= -eps and _orient(c, a, p) >= -eps:
                    libre = False
                    break
            if libre:
                triangles.append((i0, i1, i2))
                del idx[t]
                depart = t % len(idx)
                trouve = True
                break
        if not trouve:
            return None
    if _orient(anneau[idx[0]], anneau[idx[1]], anneau[idx[2]]) <= eps:
        return None
    triangles.append((idx[0], idx[1], idx[2]))

    # Bascules d'arêtes (critère de Delaunay) pour éviter les triangles effilés
    tol_cercle = 1e-9 * echelle ** 4
    for _ in range(20 * n + 100):
        aretes = {}
        for it, (a, b, c) in enumerate(triangles):
            aretes[(a, b)] = it
            aretes[(b, c)] = it
            aretes[(c, a)] = it
        bascule = False
        for (u, v), t1 in aretes.items():
            t2 = aretes.get((v, u))
            if t2 is None or t2 < t1:
                continue
            c = [s for s in triangles[t1] if s != u and s != v][0]
            d = [s for s in triangles[t2] if s != u and s != v][0]
            pu, pv, pc, pd = anneau[u], anneau[v], anneau[c], anneau[d]
            if (_dans_cercle(pu, pv, pc, pd) > tol_cercle
                    and _orient(pu, pd, pc) > eps and _orient(pd, pv, pc) > eps):
                triangles[t1] = (u, d, c)
                triangles[t2] = (d, v, c)
                bascule = True
                break
        if not bascule:
            break
    return triangles


# =============================================================================
# AJUSTEMENTS ROBUSTES
# =============================================================================

def ajuster_modele(points, degre):
    """Moindres carrés : degré 0 -> z = a ; degré 1 -> z = a + b(x-xm) + c(y-ym).

    Retourne (a, b, c, xm, ym) ou None si le plan est indéterminé (points alignés).
    """
    n = len(points)
    if n == 0:
        return None
    xm = sum(p[0] for p in points) / n
    ym = sum(p[1] for p in points) / n
    zm = sum(p[2] for p in points) / n
    if degre == 0:
        return (zm, 0.0, 0.0, xm, ym)
    if n < 3:
        return None
    sxx = syy = sxy = sxz = syz = 0.0
    for x, y, z in points:
        dx, dy, dz = x - xm, y - ym, z - zm
        sxx += dx * dx
        syy += dy * dy
        sxy += dx * dy
        sxz += dx * dz
        syz += dy * dz
    det = sxx * syy - sxy * sxy
    if det <= 1e-6 * (sxx + syy) ** 2 or det <= 0.0:
        return None
    b = (sxz * syy - syz * sxy) / det
    c = (syz * sxx - sxz * sxy) / det
    return (zm, b, c, xm, ym)


def evaluer_modele(modele, x, y):
    a, b, c, xm, ym = modele
    return a + b * (x - xm) + c * (y - ym)


def modele_moindre_mediane(points, degre, tirages=250, graine=20240611):
    """Estimation initiale insensible à ~50 % de points aberrants (LMedS).

    Degré 0 : milieu de la « plus courte moitié » des altitudes.
    Degré 1 : parmi des plans passant par 3 points tirés au hasard (tirage
    reproductible), celui qui minimise la médiane des résidus absolus.
    Retourne (modèle, médiane des résidus absolus) ou (None, None).
    """
    import random
    n = len(points)
    if n == 0:
        return None, None
    xm = sum(p[0] for p in points) / n
    ym = sum(p[1] for p in points) / n
    if degre == 0:
        zs = sorted(p[2] for p in points)
        h = n // 2 + 1
        i = min(range(n - h + 1), key=lambda t: zs[t + h - 1] - zs[t])
        centre = mediane(zs[i:i + h])
        return (centre, 0.0, 0.0, xm, ym), mediane([abs(z - centre) for z in zs])
    if n < 3:
        return None, None
    tirage = random.Random(graine)
    pas = max(1, n // 1500)
    controle = points[::pas]
    xmin, ymin, xmax, ymax = emprise([[(p[0], p[1]) for p in points]])
    aire_min = 1e-3 * max(xmax - xmin, ymax - ymin) ** 2
    meilleur, score = None, None
    for _ in range(tirages):
        p1, p2, p3 = tirage.sample(points, 3)
        det = (p2[0] - p1[0]) * (p3[1] - p1[1]) - (p3[0] - p1[0]) * (p2[1] - p1[1])
        if abs(det) <= 2.0 * aire_min:
            continue
        b = ((p2[2] - p1[2]) * (p3[1] - p1[1]) - (p3[2] - p1[2]) * (p2[1] - p1[1])) / det
        c = ((p3[2] - p1[2]) * (p2[0] - p1[0]) - (p2[2] - p1[2]) * (p3[0] - p1[0])) / det
        modele = (p1[2] + b * (xm - p1[0]) + c * (ym - p1[1]), b, c, xm, ym)
        s = mediane([abs(p[2] - evaluer_modele(modele, p[0], p[1])) for p in controle])
        if score is None or s < score:
            meilleur, score = modele, s
    return meilleur, score


def ajustement_robuste(points, degre, rejet=True, k=2.5, seuil_min=0.10, max_iter=30):
    """Ajustement avec rejet des résidus aberrants.

    Départ par moindre médiane (insensible aux buissons, blocs, épaulement non
    déclaré), puis moindres carrés itérés : les points trop hauts sont rejetés
    au-delà de max(k x écart robuste, seuil_min), les points trop bas au-delà
    du double. Retourne (modèle, liste booléenne des points gardés).
    """
    n = len(points)
    garde = [True] * n
    modele = ajuster_modele(points, degre)
    if modele is None or not rejet:
        return modele, garde
    minimum = max(3 if degre else 1, int(math.ceil(0.2 * n)))
    depart, med_abs = modele_moindre_mediane(points, degre)
    if depart is not None:
        seuil = max(k * 1.4826 * med_abs, seuil_min)
        initial = [abs(p[2] - evaluer_modele(depart, p[0], p[1])) <= seuil for p in points]
        m0 = ajuster_modele([points[i] for i in range(n) if initial[i]], degre) \
            if sum(initial) >= minimum else None
        if m0 is not None:
            garde, modele = initial, m0
    for _ in range(max_iter):
        residus = [p[2] - evaluer_modele(modele, p[0], p[1]) for p in points]
        gardes = [residus[i] for i in range(n) if garde[i]]
        centre = mediane(gardes)
        seuil = max(k * ecart_robuste(gardes, centre), seuil_min)
        nouveau = [-2.0 * seuil <= residus[i] - centre <= seuil for i in range(n)]
        if nouveau == garde or sum(nouveau) < minimum:
            break
        m2 = ajuster_modele([points[i] for i in range(n) if nouveau[i]], degre)
        if m2 is None:
            break
        garde, modele = nouveau, m2
    return modele, garde


def rejet_glissant(z, valides, demi_fenetre, k=2.5, seuil_min=0.10):
    """Rejet par médiane glissante le long d'un anneau fermé (méthode triangulée)."""
    n = len(z)
    demi_fenetre = max(1, min(demi_fenetre, (n - 1) // 2))
    residus = [None] * n
    for i in range(n):
        if not valides[i]:
            continue
        voisins = [z[(i + d) % n] for d in range(-demi_fenetre, demi_fenetre + 1) if valides[(i + d) % n]]
        residus[i] = z[i] - mediane(voisins)
    connus = [r for r in residus if r is not None]
    if len(connus) < 5:
        return [False] * n
    centre = mediane(connus)
    seuil = max(k * ecart_robuste(connus, centre), seuil_min)
    return [r is not None and not (-2.0 * seuil <= r - centre <= seuil) for r in residus]


def interpoler_circulaire(valeurs, positions, longueur):
    """Complète les valeurs manquantes (None) par interpolation linéaire le long d'un anneau."""
    n = len(valeurs)
    connus = [i for i in range(n) if valeurs[i] is not None]
    if not connus:
        return None
    if len(connus) == 1:
        return [valeurs[connus[0]]] * n
    out = list(valeurs)
    for i in range(n):
        if valeurs[i] is not None:
            continue
        p = i
        while valeurs[p] is None:
            p = (p - 1) % n
        q = i
        while valeurs[q] is None:
            q = (q + 1) % n
        dp = (positions[i] - positions[p]) % longueur
        dq = (positions[q] - positions[i]) % longueur
        out[i] = valeurs[p] if dp + dq <= 0 else (valeurs[p] * dq + valeurs[q] * dp) / (dp + dq)
    return out


# =============================================================================
# CALCUL D'UN STOCK (indépendant de Metashape)
# =============================================================================

class _Echantillon(object):
    __slots__ = ("x", "y", "s", "partie", "arete", "frac", "z", "raison")

    def __init__(self, x, y, s, partie, arete, frac):
        self.x, self.y, self.s = x, y, s
        self.partie, self.arete, self.frac = partie, arete, frac
        self.z = None
        self.raison = None  # None = échantillon retenu pour la base


def calculer_stock(parties, surface, params, exclusions=(), epaulements_lignes=(),
                   epaulements_polygones=(), reference=None, progression=None,
                   noms_epaulements=None):
    """Calcule le volume d'un stock.

    parties    : liste de polygones ; polygone = [anneau extérieur, trou, ...] ;
                 anneau = [(x, y), ...] en coordonnées locales métriques.
    surface    : fonction (x, y) -> altitude du MNE en mètres, ou None (pas de donnée).
    params     : dictionnaire (clés de CONFIG + "resolution_mne_m").
    exclusions : polygones (même format) où le MNE est ignoré puis interpolé.
    epaulements_lignes : murs verticaux (blocs, front de roche) : pied ignoré le long.
    epaulements_polygones : faces visibles d'épaulements inclinés (talus, flanc de
                 roche) : pied ignoré et plan de la face prolongé sous le stock.
    reference  : fonction (x, y) -> altitude de la base (méthode mne_reference).
    progression: fonction(fraction) appelée régulièrement (rafraîchissement IHM).
    noms_epaulements : libellés des polygones d'épaulement (pour les alertes).
    """
    alertes = []
    methode = methode_normalisee(params.get("methode_base", "plan"))
    rejet = bool(params.get("rejet_points_hauts", True))
    k_rejet = float(params.get("rejet_k", 2.5))
    seuil_rejet = float(params.get("rejet_min", 0.10))

    # --- 1. Polygones -----------------------------------------------------------
    polys = []
    for poly in parties:
        anneaux = [nettoyer_anneau(a) for a in poly]
        anneaux = [a for a in anneaux if len(a) >= 3 and abs(aire_signee(a)) > 1e-9]
        if anneaux:
            polys.append(anneaux)
    if not polys:
        raise ErreurStock("polygone invalide (moins de 3 sommets ou surface nulle)")
    tous_anneaux = [a for p in polys for a in p]
    surface_2d = sum(abs(aire_signee(p[0])) - sum(abs(aire_signee(t)) for t in p[1:]) for p in polys)
    perimetre = sum(longueur_anneau(p[0]) for p in polys)
    if surface_2d <= 0:
        raise ErreurStock("surface du polygone nulle")

    # --- 2. Grille --------------------------------------------------------------
    pas = nombre(params.get("pas_grille")) or 0.0
    if pas <= 0:
        max_cellules = max(1000, int(params.get("max_cellules", 400000)))
        pas = max(nombre(params.get("resolution_mne_m")) or 0.0,
                  math.sqrt(surface_2d / max_cellules), 0.01)
    xmin, ymin, xmax, ymax = emprise([p[0] for p in polys])
    nx = max(1, int(math.ceil((xmax - xmin) / pas)))
    ny = max(1, int(math.ceil((ymax - ymin) / pas)))
    if surface_2d / (pas * pas) > 3e6:
        alertes.append("grille très fine (%d cellules) : calcul long" % int(surface_2d / (pas * pas)))
    zone = (xmin, ymin, xmax, ymax)

    excl = [p for p in ([nettoyer_anneau(a) for a in poly] for poly in exclusions)
            if p and len(p[0]) >= 3]
    excl = [(p, emprise(p)) for p in excl if emprises_recouvrent(emprise(p), zone, 10 * pas + 100.0)]

    def exclu(x, y):
        for p, e in excl:
            if e[0] <= x <= e[2] and e[1] <= y <= e[3] and point_dans(p, x, y):
                return True
        return False

    # Cellules intérieures (centre dans le polygone) et cellules exclues
    lignes = []  # (j, [clés])
    z = {}
    exclues = set()
    for j in range(ny):
        y = ymin + (j + 0.5) * pas
        cles = []
        for xa, xb in intervalles(tous_anneaux, y):
            i0 = max(0, int(math.ceil((xa - xmin) / pas - 0.5)))
            i1 = min(nx - 1, int(math.ceil((xb - xmin) / pas - 0.5)) - 1)
            cles.extend(j * nx + i for i in range(i0, i1 + 1))
        for p, e in excl:
            if e[1] <= y <= e[3]:
                for xa, xb in intervalles(p, y):
                    i0 = max(0, int(math.ceil((xa - xmin) / pas - 0.5)))
                    i1 = min(nx - 1, int(math.ceil((xb - xmin) / pas - 0.5)) - 1)
                    exclues.update(j * nx + i for i in range(i0, i1 + 1))
        if cles:
            lignes.append((j, cles))
    nb_cellules = sum(len(c) for _, c in lignes)
    if nb_cellules == 0:
        raise ErreurStock("polygone trop petit pour le pas de grille (%.3f m)" % pas)

    # --- 3. Échantillonnage du MNE ----------------------------------------------
    manquantes = []
    n_exclues = n_sans_donnees = 0
    for numero, (j, cles) in enumerate(lignes):
        y = ymin + (j + 0.5) * pas
        for cle in cles:
            if cle in exclues:
                z[cle] = None
                manquantes.append(cle)
                n_exclues += 1
                continue
            v = surface(xmin + (cle - j * nx + 0.5) * pas, y)
            z[cle] = v
            if v is None:
                manquantes.append(cle)
                n_sans_donnees += 1
        if progression is not None and numero % 25 == 0:
            progression(0.8 * numero / len(lignes))

    # --- 4. Comblement des zones exclues / sans données -------------------------
    non_comblees = 0
    if manquantes:
        non_comblees = _combler(z, manquantes, nx, ny, pas, xmin, ymin, surface, exclu)
    if non_comblees:
        alertes.append("%d cellules sans données non interpolables (hauteur nulle)" % non_comblees)

    # --- 5. Pied du stock --------------------------------------------------------
    ds = max(pas, 0.2, perimetre / 4000.0)
    echantillons = []
    infos_parties = []
    for ip, poly in enumerate(polys):
        pts, sommets, longueur = densifier_anneau(poly[0], ds)
        debut = len(echantillons)
        echantillons.extend(_Echantillon(x, y, s, ip, k, f) for (x, y, s, k, f) in pts)
        infos_parties.append({"debut": debut, "fin": len(echantillons), "sommets": sommets,
                              "longueur": longueur, "anneau": poly[0]})

    tol_ep = float(params.get("tolerance_epaulement", 0.5))
    segments_ep = []

    def ajouter_segments(ligne, ferme):
        pts = [(float(p[0]), float(p[1])) for p in ligne]
        n_l = len(pts)
        for k in range(n_l if ferme else n_l - 1):
            a, b = pts[k], pts[(k + 1) % n_l]
            segments_ep.append((a[0], a[1], b[0], b[1]))

    for ligne in epaulements_lignes:
        ajouter_segments(ligne, False)
    for poly in epaulements_polygones:
        for anneau in poly:
            ajouter_segments(anneau, True)
    segments_ep = [s for s in segments_ep if emprises_recouvrent(
        (min(s[0], s[2]), min(s[1], s[3]), max(s[0], s[2]), max(s[1], s[3])), zone, tol_ep + ds)]
    polys_ep = []
    for ie, poly in enumerate(epaulements_polygones):
        anneaux = [nettoyer_anneau(a) for a in poly]
        anneaux = [a for a in anneaux if len(a) >= 3]
        if anneaux:
            nom = (noms_epaulements[ie] if noms_epaulements and ie < len(noms_epaulements)
                   else "n°%d" % (ie + 1))
            polys_ep.append((anneaux, emprise([anneaux[0]]), nom))
    polys_ep_pied = [(p, e) for p, e, _ in polys_ep if emprises_recouvrent(e, zone, tol_ep + ds)]

    for e in echantillons:
        e.z = surface(e.x, e.y)
        if exclu(e.x, e.y):
            e.raison = "exclusion"
        elif any(distance_segment(e.x, e.y, *s) <= tol_ep for s in segments_ep) or \
                any(em[0] <= e.x <= em[2] and em[1] <= e.y <= em[3] and point_dans(p, e.x, e.y)
                    for p, em in polys_ep_pied):
            e.raison = "epaulement"
        elif e.z is None:
            e.raison = "sans_donnees"

    retenus = [e for e in echantillons if e.raison is None]
    points_ret = [(e.x, e.y, e.z) for e in retenus]

    # Plan robuste (base des méthodes plan / horizontal, secours des autres)
    modele = None
    if points_ret:
        degre = 0 if methode == "horizontal" else 1
        modele, garde = ajustement_robuste(points_ret, degre, rejet, k_rejet, seuil_rejet)
        if modele is None:
            modele, garde = ajustement_robuste(points_ret, 0, rejet, k_rejet, seuil_rejet)
            if methode == "plan":
                alertes.append("pied exploitable sur un seul alignement : base horizontale utilisée")
        if methode in ("plan", "horizontal"):
            for e, g in zip(retenus, garde):
                if not g:
                    e.raison = "rejet_auto"

    base_tin = {}
    sommets_z = None
    if methode in ("plan", "horizontal"):
        if modele is None:
            raise ErreurStock("pied du stock inexploitable (tout est exclu, épaulement ou sans données)")

        def base(cle, x, y):
            return evaluer_modele(modele, x, y)

    elif methode == "altitude":
        altitude = nombre(params.get("altitude_base"))
        if altitude is None:
            raise ErreurStock("méthode 'altitude' : altitude de base non renseignée")

        def base(cle, x, y):
            return altitude

    elif methode == "mne_reference":
        if reference is None:
            raise ErreurStock("méthode 'mne_reference' : MNE de référence introuvable")
        compteur = {"secours": 0, "vide": 0}

        def base(cle, x, y):
            v = reference(x, y)
            if v is None:
                if modele is None:
                    compteur["vide"] += 1
                    return None
                compteur["secours"] += 1
                return evaluer_modele(modele, x, y)
            return v

    else:  # triangule
        sommets_z = _altitudes_sommets(echantillons, infos_parties, rejet, k_rejet, seuil_rejet,
                                       float(params.get("fenetre_pied", 1.0)),
                                       float(params.get("fenetre_rejet", 8.0)), ds)
        if sommets_z is None:
            raise ErreurStock("pied du stock inexploitable (tout est exclu, épaulement ou sans données)")
        for ip, info in enumerate(infos_parties):
            anneau = info["anneau"]
            zs = sommets_z[ip]
            indices = simplifier_anneau(anneau, 400)
            if len(indices) < len(anneau):
                alertes.append("polygone simplifié à %d sommets pour la triangulation" % len(indices))
            sous_anneau = [anneau[i] for i in indices]
            triangles = trianguler(sous_anneau)
            if triangles is None:
                alertes.append("triangulation impossible (polygone auto-intersecté ?) : plan utilisé")
                continue
            _rasteriser(triangles, sous_anneau, [zs[i] for i in indices], z, base_tin,
                        nx, ny, pas, xmin, ymin)
        if modele is None and len(base_tin) < nb_cellules:
            raise ErreurStock("base triangulée incomplète et pied inexploitable")

        def base(cle, x, y):
            v = base_tin.get(cle)
            return v if v is not None else evaluer_modele(modele, x, y)

    # --- 5 bis. Épaulements inclinés : la face visible est prolongée sous le stock --
    plans_talus, pentes_talus = [], []
    suivi_talus = {"n": 0}
    if methode != "mne_reference" and polys_ep:
        distance_max = float(params.get("distance_epaulement", 5.0))
        pente_min = float(params.get("pente_min_epaulement", 10.0))
        for anneaux_ep, emprise_ep, nom in polys_ep:
            if not emprises_recouvrent(emprise_ep, zone, distance_max):
                continue
            if min(distance_polygones(anneaux_ep, p) for p in polys) > distance_max:
                continue
            modele_t = _plan_face(anneaux_ep, tous_anneaux, zone, surface, exclu, rejet, k_rejet, seuil_rejet)
            if modele_t is None:
                alertes.append("épaulement « %s » : pas assez de données MNE sur la face visible" % nom)
                continue
            pente_t = 100.0 * math.hypot(modele_t[1], modele_t[2])
            if pente_t < pente_min:
                alertes.append("épaulement « %s » presque horizontal (%.0f %%) : non prolongé sous le stock "
                               "(pour un mur vertical, tracer une ligne)" % (nom, pente_t))
                continue
            plans_talus.append(modele_t)
            pentes_talus.append("%s : %.0f %%" % (nom, pente_t))
    if plans_talus:
        base_sol = base

        def base(cle, x, y):
            zb = base_sol(cle, x, y)
            if zb is None:
                return None
            zt = max(evaluer_modele(m, x, y) for m in plans_talus)
            if zt > zb:
                suivi_talus["n"] += 1
                return zt
            return zb

    # --- 6. Volumes -----------------------------------------------------------------
    aire_cellule = pas * pas
    v_dessus = v_dessous = 0.0
    h_max = 0.0
    somme_base = 0.0
    n_calc = 0
    for numero, (j, cles) in enumerate(lignes):
        y = ymin + (j + 0.5) * pas
        for cle in cles:
            zs = z[cle]
            if zs is None:
                continue
            x = xmin + (cle - j * nx + 0.5) * pas
            zb = base(cle, x, y)
            if zb is None:
                continue
            dz = zs - zb
            if dz > 0:
                v_dessus += dz
                if dz > h_max:
                    h_max = dz
            else:
                v_dessous -= dz
            somme_base += zb
            n_calc += 1
        if progression is not None and numero % 50 == 0:
            progression(0.8 + 0.2 * numero / len(lignes))
    v_dessus *= aire_cellule
    v_dessous *= aire_cellule
    volume_net = v_dessus - v_dessous
    base_talus_pct = 100.0 * suivi_talus["n"] / nb_cellules if plans_talus else None
    if base_talus_pct is not None and base_talus_pct > 60.0:
        alertes.append("la base suit l'épaulement incliné sur %.0f %% de la surface : vérifier le "
                       "polygone d'épaulement (face visible du talus uniquement)" % base_talus_pct)

    if methode == "mne_reference":
        if compteur["secours"] > 0.05 * nb_cellules:
            alertes.append("MNE de référence absent sur %.0f %% de la surface (plan du pied utilisé)"
                           % (100.0 * compteur["secours"] / nb_cellules))
        if compteur["vide"]:
            alertes.append("%d cellules sans base (MNE de référence vide)" % compteur["vide"])
    if methode == "triangule":
        hors_tin = sum(1 for _, cles in lignes for c in cles if c not in base_tin)
        if hors_tin > 0.01 * nb_cellules:
            alertes.append("%.0f %% de la surface hors triangulation (plan utilisé)" % (100.0 * hors_tin / nb_cellules))

    # --- 7. Statistiques du pied ----------------------------------------------------
    residus = []
    for e in echantillons:
        if e.raison is not None:
            continue
        if methode == "triangule":
            zs = sommets_z[e.partie]
            nk = len(zs)
            zb = (1.0 - e.frac) * zs[e.arete] + e.frac * zs[(e.arete + 1) % nk]
        else:
            zb = base(None, e.x, e.y)
        if zb is not None:
            residus.append(e.z - zb)
    n_ech = len(echantillons)
    n_ret = len(residus)
    pied_pct = 100.0 * n_ret / n_ech if n_ech else 0.0
    ecart_type = math.sqrt(sum(r * r for r in residus) / n_ret) if n_ret else None
    ecart_moyen = sum(residus) / n_ret if n_ret else None
    incertitude = None
    if ecart_type is not None and methode in ("plan", "horizontal", "triangule"):
        n_independants = max(1.0, n_ret * ds / 2.0)  # corrélation ~2 m le long du pied
        incertitude = surface_2d * ecart_type / math.sqrt(n_independants)

    pente = None
    if methode == "plan" and modele is not None:
        pente = 100.0 * math.hypot(modele[1], modele[2])
        if pente > 15.0:
            alertes.append("base très inclinée (%.0f %%) : épaulement non déclaré ?" % pente)

    if methode in ("plan", "horizontal") and n_ech:
        hauts = [e.z - base(None, e.x, e.y) for e in echantillons
                 if e.raison == "rejet_auto" and e.z is not None]
        if len(hauts) > 0.15 * n_ech and sum(hauts) / len(hauts) > 0.5:
            alertes.append("%.0f %% du pied rejeté, en moyenne %.1f m au-dessus de la base : stock adossé "
                           "(mur, talus) ou végétation ? Vérifier (épaulement ou méthode triangule)"
                           % (100.0 * len(hauts) / n_ech, sum(hauts) / len(hauts)))

    interpole_pct = 100.0 * (n_exclues + n_sans_donnees) / nb_cellules
    if interpole_pct > 15.0:
        alertes.append("%.0f %% de la surface interpolée (exclusions / trous du MNE)" % interpole_pct)
    if methode not in ("altitude", "mne_reference") and pied_pct < 50.0:
        alertes.append("seulement %.0f %% du pied utilisé pour la base" % pied_pct)
    if v_dessous > max(1.0, 0.03 * v_dessus):
        alertes.append("volume sous la base important : base trop haute ou polygone mal placé ?")
    if ecart_type is not None and ecart_type > 0.30 and methode not in ("altitude", "mne_reference"):
        alertes.append("pied irrégulier (écart-type %.2f m)" % ecart_type)

    densite = nombre(params.get("densite")) or 0.0
    if progression is not None:
        progression(1.0)

    return {
        "methode": methode,
        "surface_2d": surface_2d,
        "perimetre": perimetre,
        "pas": pas,
        "nb_cellules": nb_cellules,
        "volume_net": volume_net,
        "volume_dessus": v_dessus,
        "volume_dessous": v_dessous,
        "densite": densite if densite > 0 else None,
        "tonnage": volume_net * densite if densite > 0 else None,
        "hauteur_max": h_max,
        "hauteur_moy": volume_net / surface_2d,
        "altitude_base_moy": somme_base / n_calc if n_calc else None,
        "pente_base_pct": pente,
        "epaulements_inclines": pentes_talus or None,
        "base_epaulement_pct": base_talus_pct,
        "pied_retenu_pct": pied_pct,
        "ecart_type_pied": ecart_type,
        "ecart_moyen_pied": ecart_moyen,
        "incertitude_base": incertitude,
        "sensibilite_cm": surface_2d * 0.01,
        "interpole_pct": interpole_pct,
        "alertes": alertes,
        "pied_ignore": _troncons_ignores(echantillons, infos_parties, base),
    }


def _combler(z, manquantes, nx, ny, pas, xmin, ymin, surface, exclu):
    """Interpolation (inverse du carré de la distance) des zones sans valeur,
    depuis les cellules valides qui les bordent (y compris hors polygone)."""
    a_combler = set(manquantes)
    vues = set()
    externes = {}
    non_comblees = 0
    for depart in manquantes:
        if depart in vues:
            continue
        composante = []
        pile = [depart]
        vues.add(depart)
        bord = {}
        while pile:
            cle = pile.pop()
            composante.append(cle)
            i, j = cle % nx, cle // nx
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ii, jj = i + di, j + dj
                kk = jj * nx + ii if (0 <= ii < nx and 0 <= jj < ny) else None
                if kk is not None and kk in z:
                    if kk in a_combler:
                        if kk not in vues:
                            vues.add(kk)
                            pile.append(kk)
                    elif z[kk] is not None:
                        bord[(ii, jj)] = z[kk]
                else:
                    if (ii, jj) not in externes:
                        x, y = xmin + (ii + 0.5) * pas, ymin + (jj + 0.5) * pas
                        externes[(ii, jj)] = None if exclu(x, y) else surface(x, y)
                    if externes[(ii, jj)] is not None:
                        bord[(ii, jj)] = externes[(ii, jj)]
        points = list(bord.items())
        if not points:
            non_comblees += len(composante)
            continue
        maximum = 400 if len(composante) < 5000 else 150
        if len(points) > maximum:
            saut = len(points) / float(maximum)
            points = [points[int(t * saut)] for t in range(maximum)]
        for cle in composante:
            i, j = cle % nx, cle // nx
            sw = swz = 0.0
            for (ii, jj), v in points:
                w = 1.0 / ((ii - i) ** 2 + (jj - j) ** 2)
                sw += w
                swz += w * v
            z[cle] = swz / sw
    return non_comblees


def _altitudes_sommets(echantillons, infos_parties, rejet, k, seuil_min, fenetre_pied,
                       fenetre_rejet, ds):
    """Altitude robuste du sol à chaque sommet du polygone (méthode triangulée)."""
    resultat = []
    total_connus = 0
    for info in infos_parties:
        echs = echantillons[info["debut"]:info["fin"]]
        n = len(echs)
        if rejet and n >= 5:
            valides = [e.raison is None for e in echs]
            rejets = rejet_glissant([e.z for e in echs], valides,
                                    int(round(fenetre_rejet / ds)), k, seuil_min)
            for e, r in zip(echs, rejets):
                if r:
                    e.raison = "rejet_auto"
        demi = max(1, min(int(round(fenetre_pied / ds)), (n - 1) // 2))
        valeurs, positions = [], []
        for idx in info["sommets"]:
            voisins = [echs[(idx + d) % n].z for d in range(-demi, demi + 1)
                       if echs[(idx + d) % n].raison is None]
            valeurs.append(mediane(voisins) if voisins else None)
            positions.append(echs[idx].s)
        total_connus += sum(1 for v in valeurs if v is not None)
        resultat.append((valeurs, positions, info["longueur"]))
    if total_connus == 0:
        return None
    # Une partie sans sommet connu reçoit la médiane des autres parties
    tous = [v for valeurs, _, _ in resultat for v in valeurs if v is not None]
    defaut = mediane(tous)
    sortie = []
    for valeurs, positions, longueur in resultat:
        complete = interpoler_circulaire(valeurs, positions, longueur)
        sortie.append(complete if complete is not None else [defaut] * len(valeurs))
    return sortie


def _rasteriser(triangles, anneau, zs, z, base_tin, nx, ny, pas, xmin, ymin):
    """Altitude de la base triangulée au centre de chaque cellule intérieure."""
    for a, b, c in triangles:
        pa, pb, pc = anneau[a], anneau[b], anneau[c]
        det = _orient(pa, pb, pc)
        if det <= 0:
            continue
        i0 = max(0, int(math.floor((min(pa[0], pb[0], pc[0]) - xmin) / pas - 0.5)))
        i1 = min(nx - 1, int(math.ceil((max(pa[0], pb[0], pc[0]) - xmin) / pas - 0.5)))
        j0 = max(0, int(math.floor((min(pa[1], pb[1], pc[1]) - ymin) / pas - 0.5)))
        j1 = min(ny - 1, int(math.ceil((max(pa[1], pb[1], pc[1]) - ymin) / pas - 0.5)))
        tol = -1e-9
        for j in range(j0, j1 + 1):
            y = ymin + (j + 0.5) * pas
            for i in range(i0, i1 + 1):
                cle = j * nx + i
                if cle not in z or cle in base_tin:
                    continue
                p = (xmin + (i + 0.5) * pas, y)
                w1 = _orient(pb, pc, p) / det
                w2 = _orient(pc, pa, p) / det
                w3 = 1.0 - w1 - w2
                if w1 >= tol and w2 >= tol and w3 >= tol:
                    base_tin[cle] = w1 * zs[a] + w2 * zs[b] + w3 * zs[c]


def _plan_face(anneaux, anneaux_stock, zone_stock, surface, exclu, rejet, k, seuil_min,
               max_points=20000):
    """Plan robuste ajusté sur la face visible d'un épaulement incliné.

    Le MNE est lu dans le polygone d'épaulement, hors du stock et hors des
    exclusions ; la végétation ou les blocs isolés sur la face sont rejetés.
    """
    xmin, ymin, xmax, ymax = emprise([anneaux[0]])
    aire = abs(aire_signee(anneaux[0])) - sum(abs(aire_signee(t)) for t in anneaux[1:])
    if aire <= 0:
        return None
    pas = max(0.1, math.sqrt(aire / max_points))
    points = []
    y = ymin + 0.5 * pas
    while y < ymax:
        for xa, xb in intervalles(anneaux, y):
            x = xa + 0.5 * pas
            while x < xb:
                dans_stock = (zone_stock[0] <= x <= zone_stock[2] and zone_stock[1] <= y <= zone_stock[3]
                              and point_dans(anneaux_stock, x, y))
                if not dans_stock and not exclu(x, y):
                    h = surface(x, y)
                    if h is not None:
                        points.append((x, y, h))
                x += pas
        y += pas
    if len(points) < 10:
        return None
    modele, _ = ajustement_robuste(points, 1, rejet, k, seuil_min)
    return modele


def _troncons_ignores(echantillons, infos_parties, base):
    """Regroupe les échantillons de pied non retenus en tronçons (formes de contrôle)."""
    troncons = []
    for info in infos_parties:
        echs = echantillons[info["debut"]:info["fin"]]
        n = len(echs)
        if n == 0:
            continue
        retenus = [i for i in range(n) if echs[i].raison is None]
        depart = (retenus[0] + 1) % n if retenus else 0
        courant = None
        for t in range(n):
            e = echs[(depart + t) % n]
            if e.raison is None:
                courant = None
                continue
            zz = e.z
            if zz is None:
                try:
                    zz = base(None, e.x, e.y)
                except Exception:
                    zz = None
            if courant is None or courant["raison"] != e.raison:
                courant = {"raison": e.raison, "points": []}
                troncons.append(courant)
            courant["points"].append((e.x, e.y, zz if zz is not None else 0.0))
    return troncons


# =============================================================================
# INTÉGRATION METASHAPE
# =============================================================================

def _log(message):
    print("[Volumes] " + message)


def _xyz(v):
    try:
        x, y = float(v.x), float(v.y)
    except AttributeError:
        x, y = float(v[0]), float(v[1])
    try:
        z = float(v.z)
    except Exception:
        try:
            z = float(v[2])
        except Exception:
            z = 0.0
    return x, y, z


def _wkt(crs):
    try:
        return crs.wkt if crs is not None else ""
    except Exception:
        return ""


def _meme_crs(a, b):
    if a is None or b is None:
        return True
    return _wkt(a) == _wkt(b)


_WKT_PROJETE = ("PROJCS", "PROJCRS", "PROJECTEDCRS")
_WKT_GEOGRAPHIQUE = ("GEOGCS", "GEOGCRS", "GEODCRS", "GEOGRAPHICCRS", "GEODETICCRS")
_WKT_LOCAL = ("LOCAL_CS", "ENGCRS", "ENGINEERINGCRS")
_WKT_VERTICAL = ("VERT_CS", "VERTCRS", "VERTICALCRS")
_WKT_COMPOSE = ("COMPD_CS", "COMPOUNDCRS")
_WKT_UNITE = ("UNIT", "LENGTHUNIT")


def arbre_wkt(texte):
    """Découpe un WKT (1 ou 2) en nœuds (MOT-CLÉ, [enfants])."""
    racine = ("", [])
    pile = [racine]
    jeton = ""
    i, n = 0, len(texte)
    while i < n:
        c = texte[i]
        if c == '"':
            fin = texte.find('"', i + 1)
            while fin != -1 and fin + 1 < n and texte[fin + 1] == '"':  # guillemet doublé
                fin = texte.find('"', fin + 2)
            if fin == -1:
                break
            pile[-1][1].append(texte[i + 1:fin].replace('""', '"'))
            jeton = ""
            i = fin + 1
            continue
        if c in "[(":
            noeud = (jeton.strip().upper(), [])
            pile[-1][1].append(noeud)
            pile.append(noeud)
            jeton = ""
        elif c in "])":
            if jeton.strip():
                pile[-1][1].append(jeton.strip())
            jeton = ""
            if len(pile) > 1:
                pile.pop()
        elif c == ",":
            if jeton.strip():
                pile[-1][1].append(jeton.strip())
            jeton = ""
        else:
            jeton += c
        i += 1
    return racine[1]


def _composantes_crs(noeuds):
    sortie = []
    for noeud in noeuds:
        if isinstance(noeud, tuple):
            if noeud[0] in _WKT_COMPOSE:
                sortie.extend(_composantes_crs(noeud[1]))
            else:
                sortie.append(noeud)
    return sortie


def _facteur_unite(noeud):
    """Facteur de conversion en mètres de l'unité de longueur d'un nœud de SCR."""
    unites = [e for e in noeud[1] if isinstance(e, tuple) and e[0] in _WKT_UNITE]
    if not unites:  # WKT2 : unité portée par le système d'axes
        for e in noeud[1]:
            if isinstance(e, tuple) and e[0] in ("CS", "AXIS"):
                unites += [u for u in e[1] if isinstance(u, tuple) and u[0] in _WKT_UNITE]
    for u in unites:
        valeurs = [v for v in u[1] if not isinstance(v, tuple)]
        if len(valeurs) >= 2:
            f = nombre(valeurs[1])
            if f and f > 0:
                return f
    return None


def infos_crs(crs):
    """(type, facteur plan -> m, facteur altitude -> m) d'un système de coordonnées.

    type : « projete », « geographique » ou « local ». Fonctionne pour tout SCR
    décrit en WKT : projeté (Lambert-93, CC42 à CC50, UTM...), géographique
    (WGS 84, RGF93...), local, composé avec un système d'altitude (NGF-IGN69...).
    """
    w = _wkt(crs)
    if not w:
        return "local", 1.0, 1.0
    try:
        composantes = _composantes_crs(arbre_wkt(w))
    except Exception:
        composantes = []
    genre, fh, fv = None, 1.0, None
    for noeud in composantes:
        if noeud[0] in _WKT_PROJETE and genre is None:
            genre, fh = "projete", _facteur_unite(noeud) or 1.0
        elif noeud[0] in _WKT_GEOGRAPHIQUE and genre is None:
            genre = "geographique"
        elif noeud[0] in _WKT_LOCAL and genre is None:
            genre, fh = "local", _facteur_unite(noeud) or 1.0
        elif noeud[0] in _WKT_VERTICAL:
            fv = _facteur_unite(noeud)
    if genre is None:  # WKT non reconnu : recherche simple
        haut = w.upper()
        genre = ("projete" if "PROJ" in haut else "geographique" if "GEOG" in haut else "local")
    if fv is None:
        fv = 1.0 if genre == "geographique" else fh
    return genre, fh, fv


def _type_crs(crs):
    return infos_crs(crs)[0]


def _nom_crs(crs):
    try:
        nom = crs.name
        if nom:
            return nom
    except Exception:
        pass
    noeuds = [n for n in arbre_wkt(_wkt(crs)) if isinstance(n, tuple)] if _wkt(crs) else []
    if noeuds and noeuds[0][1] and not isinstance(noeuds[0][1][0], tuple):
        return noeuds[0][1][0]
    return "inconnu"


class _Transfo(object):
    """Changement de système de coordonnées (identité si même SCR)."""

    def __init__(self, source, cible):
        self.source, self.cible = source, cible
        self.identite = _meme_crs(source, cible)

    def __call__(self, x, y, z=0.0):
        if self.identite:
            return x, y, z
        p = Metashape.CoordinateSystem.transform(Metashape.Vector([x, y, z]), self.source, self.cible)
        return _xyz(p)


class Repere(object):
    """Repère local en mètres centré sur la zone de travail (SCR du MNE).

    SCR projeté ou local : les unités (pied US, etc.) sont converties en mètres.
    SCR géographique (degrés) : projection équirectangulaire locale (erreur
    négligeable à l'échelle d'un site). fz convertit les altitudes en mètres.
    """

    def __init__(self, crs_mne, x0, y0):
        self.x0, self.y0 = x0, y0
        genre, fh, fv = infos_crs(crs_mne)
        self.geographique = genre == "geographique"
        self.fz = fv
        if self.geographique:
            a, e2 = 6378137.0, 0.00669437999014
            phi = math.radians(y0)
            w = math.sqrt(1.0 - e2 * math.sin(phi) ** 2)
            self.kx = math.radians(1.0) * a / w * math.cos(phi)
            self.ky = math.radians(1.0) * a * (1.0 - e2) / w ** 3
        else:
            self.kx = self.ky = fh

    def vers_local(self, x, y):
        return (x - self.x0) * self.kx, (y - self.y0) * self.ky

    def vers_mne(self, u, v):
        return self.x0 + u / self.kx, self.y0 + v / self.ky


def _crs_mne(elevation):
    crs = getattr(elevation, "crs", None)
    if crs is None:
        projection = getattr(elevation, "projection", None)
        crs = getattr(projection, "crs", None)
    return crs


def _fonction_mne(elevation, repere, transfo=None, facteur_z=1.0):
    """Fonction (x, y) locales -> altitude du MNE en mètres (None si pas de donnée)."""
    altitude = elevation.altitude
    vecteur = Metashape.Vector

    def f(u, v):
        x, y = repere.vers_mne(u, v)
        if transfo is not None and not transfo.identite:
            x, y, _ = transfo(x, y, 0.0)
        try:
            h = altitude(vecteur([x, y]))
        except Exception:
            return None
        if h is None:
            return None
        h = float(h)
        if h != h or h <= -32000.0 or h >= 1e9:
            return None
        return h * facteur_z
    return f


def _resolution_m(elevation, repere):
    try:
        r = float(elevation.resolution)
    except Exception:
        return 0.0
    return r * repere.ky


def _mnes(chunk):
    liste = list(getattr(chunk, "elevations", None) or [])
    if not liste and getattr(chunk, "elevation", None) is not None:
        liste = [chunk.elevation]
    return liste


def _label(objet, defaut=""):
    return (getattr(objet, "label", "") or defaut).strip()


def _trouver_mne(doc, chunk, libelle):
    """MNE par libellé : 'libellé' (chunk courant puis autres) ou 'chunk/libellé'."""
    if not libelle:
        return chunk.elevation, chunk
    cible = normaliser(libelle)
    chunks = [chunk] + [c for c in doc.chunks if c is not chunk]
    for c in chunks:
        for el in _mnes(c):
            if normaliser(_label(el)) == cible:
                return el, c
    if "/" in libelle:
        nom_chunk, nom_mne = libelle.split("/", 1)
        for c in chunks:
            if normaliser(_label(c)) == normaliser(nom_chunk):
                for el in _mnes(c):
                    if normaliser(_label(el)) == normaliser(nom_mne):
                        return el, c
    return None, None


def _geometrie(shape, chunk, marqueurs):
    """('polygone' | 'ligne' | 'autre', parties) dans le SCR des formes.

    polygone : parties = [[anneau, trou, ...], ...] ; ligne : parties = [[pts], ...].
    """
    def conv(c):
        if isinstance(c, int):  # forme attachée : clé de marqueur
            return marqueurs.get(c)
        return _xyz(c)

    def liste(points):
        out = [conv(c) for c in points]
        return [p for p in out if p is not None]

    geom = getattr(shape, "geometry", None)
    if geom is not None:
        nom = str(getattr(geom, "type", ""))
        coords = geom.coordinates
        if "MultiPolygon" in nom:
            return "polygone", [[liste(a) for a in poly] for poly in coords]
        if "Polygon" in nom:
            return "polygone", [[liste(a) for a in coords]]
        if "MultiLineString" in nom:
            return "ligne", [liste(l) for l in coords]
        if "LineString" in nom:
            return "ligne", [liste(coords)]
        return "autre", []
    nom = str(getattr(shape, "type", ""))  # API 1.x
    sommets = liste(shape.vertices)
    if "Polygon" in nom:
        return "polygone", [[sommets]]
    if "Polyline" in nom or "Line" in nom:
        return "ligne", [sommets]
    return "autre", []


def _positions_marqueurs(chunk):
    positions = {}
    try:
        crs_formes = chunk.shapes.crs
        monde = getattr(chunk, "world_crs", None)
        if monde is None and chunk.crs is not None:
            monde = chunk.crs.geoccs
        T = chunk.transform.matrix
        for m in chunk.markers:
            if m.position is None:
                continue
            p = T.mulp(m.position)
            if monde is not None and crs_formes is not None:
                p = Metashape.CoordinateSystem.transform(p, monde, crs_formes)
            positions[m.key] = _xyz(p)
    except Exception:
        pass
    return positions


def _groupe(shape):
    g = getattr(shape, "group", None)
    return normaliser(_label(g)) if g is not None else ""


def _parametres_forme(shape):
    """Paramètres propres à un stock : attributs de la forme ou description
    du type « methode=triangule; densite=1,6; altitude=123.45 »."""
    brut = {}
    try:
        attributs = shape.attributes
        for cle in list(attributs.keys()):
            brut[normaliser(cle)] = str(attributs[cle])
    except Exception:
        pass
    description = getattr(shape, "description", "") or ""
    for morceau in re.split(r"[;\n]", description):
        if "=" in morceau:
            cle, valeur = morceau.split("=", 1)
            brut[normaliser(cle)] = valeur.strip()
    params = {}
    for cle, valeur in brut.items():
        if not str(valeur).strip():
            continue
        if cle in ("methode", "methode_base", "base"):
            params["methode_base"] = valeur.strip()
        elif cle in ("altitude", "altitude_base", "z_base", "zbase", "cote_base"):
            params["altitude_base"] = nombre(valeur)
        elif cle in ("densite", "density", "masse_volumique"):
            params["densite"] = nombre(valeur)
        elif cle in ("mne_reference", "reference"):
            params["mne_reference"] = valeur.strip()
    return params


def _construire_mne_filtre(chunk, cfg):
    nuage = getattr(chunk, "point_cloud", None) or getattr(chunk, "dense_cloud", None)
    if nuage is None:
        raise ErreurScript("Pas de nuage de points dense dans le chunk : impossible de construire "
                           "le MNE filtré (décochez l'option ou construisez le nuage dense).")
    PC = Metashape.PointClass
    if cfg.get("classer_points"):
        cibles = [getattr(PC, n) for n in ("Ground", "HighVegetation", "Building", "RoadSurface",
                                            "Car", "Manmade", "ManMade") if hasattr(PC, n)]
        _log("Classification automatique du nuage de points (peut être long)...")
        try:
            nuage.classifyPoints(target_classes=cibles, confidence=0.0)
        except TypeError:
            nuage.classifyPoints(target=cibles, confidence=0.0)
        except AttributeError:
            chunk.classifyPoints(target_classes=cibles, confidence=0.0)
    exclues = set(cfg.get("classes_exclues") or [])
    classes = [getattr(PC, n) for n in CLASSES_POINTS if hasattr(PC, n) and n not in exclues]
    source = getattr(Metashape, "PointCloudData", None) or getattr(Metashape, "DenseCloudData")
    kwargs = {"source_data": source, "classes": classes,
              "interpolation": Metashape.Interpolation.EnabledInterpolation}
    resolution = nombre(cfg.get("resolution_mne")) or 0.0
    if resolution > 0:
        genre, fh, _ = infos_crs(chunk.crs)
        kwargs["resolution"] = resolution / (111320.0 if genre == "geographique" else fh)
    _log("Construction du MNE filtré (classes exclues : %s)..." % ", ".join(sorted(exclues)))
    if not hasattr(chunk, "elevations"):
        _log("ATTENTION : Metashape 1.x, le MNE existant du chunk est remplacé.")
    chunk.buildDem(**kwargs)
    elevation = chunk.elevation
    try:
        elevation.label = "MNE stocks filtre " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return elevation


def _volume_metashape(shape):
    """Volume natif Metashape (plan ajusté, MNE actif) pour contrôle ; None si indisponible."""
    try:
        r = shape.volume(level="bestfit")
    except Exception:
        return None
    try:
        if isinstance(r, dict):
            dessus, dessous = r.get("above"), r.get("below")
        else:
            dessus, dessous = r["above"], r["below"]
        return float(dessus) - float(dessous or 0.0)
    except Exception:
        try:
            return float(r)
        except Exception:
            return None


def _ecrire_attributs(shape, nom, r):
    valeurs = {
        "Vol_net_m3": r.get("volume_net"),
        "Vol_dessus_m3": r.get("volume_dessus"),
        "Vol_dessous_m3": r.get("volume_dessous"),
        "Vol_surface_m2": r.get("surface_2d"),
        "Vol_tonnage_t": r.get("tonnage"),
        "Vol_hauteur_max_m": r.get("hauteur_max"),
        "Vol_methode": r.get("methode"),
        "Vol_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    try:
        for cle, v in valeurs.items():
            if v is None:
                continue
            shape.attributes[cle] = ("%.3f" % v) if isinstance(v, float) else str(v)
        return True
    except Exception as e:
        _log("attributs non écrits pour %s (%s)" % (nom, e))
        return False


def _creer_formes_controle(chunk, troncons_par_stock, repere, vers_formes):
    formes = chunk.shapes
    for g in list(formes.groups):
        if normaliser(_label(g)) == normaliser(GROUPE_CONTROLE):
            try:
                anciennes = [s for s in formes if s.group is not None and s.group.key == g.key]
                if anciennes:
                    formes.remove(anciennes)
            except Exception:
                pass
            try:
                formes.remove(g)
            except Exception:
                pass
    if not any(troncons for _, troncons in troncons_par_stock):
        return 0
    if not hasattr(Metashape, "Geometry"):
        _log("formes de contrôle non disponibles avec cette version de Metashape")
        return 0
    groupe = formes.addGroup()
    groupe.label = GROUPE_CONTROLE
    try:
        groupe.color = (255, 40, 40)
    except Exception:
        pass
    nombre_formes = 0
    for nom, troncons in troncons_par_stock:
        for t in troncons:
            pts = []
            for (u, v, h) in t["points"]:
                x, y = repere.vers_mne(u, v)
                pts.append(Metashape.Vector(list(vers_formes(x, y, h / repere.fz))))
            forme = formes.addShape()
            forme.group = groupe
            forme.label = "%s - %s" % (nom, RAISONS_PIED.get(t["raison"], t["raison"]))
            if len(pts) >= 2:
                forme.geometry = Metashape.Geometry.LineString(pts)
            else:
                forme.geometry = Metashape.Geometry.Point(pts[0])
            nombre_formes += 1
    return nombre_formes


COLONNES_CSV = [
    ("Stock", "nom", None),
    ("Méthode base", "methode", None),
    ("Surface 2D (m2)", "surface_2d", 1),
    ("Volume net (m3)", "volume_net", 1),
    ("Volume au-dessus base (m3)", "volume_dessus", 1),
    ("Volume sous base (m3)", "volume_dessous", 1),
    ("Densité (t/m3)", "densite", 3),
    ("Tonnage (t)", "tonnage", 1),
    ("Hauteur max (m)", "hauteur_max", 2),
    ("Hauteur moy (m)", "hauteur_moy", 2),
    ("Altitude base moy (m)", "altitude_base_moy", 3),
    ("Pente base (%)", "pente_base_pct", 1),
    ("Épaulements inclinés (pente)", "epaulements_inclines", None),
    ("Base sur épaulement (%)", "base_epaulement_pct", 0),
    ("Pied utilisé (%)", "pied_retenu_pct", 0),
    ("Écart-type pied (m)", "ecart_type_pied", 3),
    ("Écart moyen pied/base (m)", "ecart_moyen_pied", 3),
    ("Incertitude base (± m3)", "incertitude_base", 1),
    ("Sensibilité (m3 par cm de base)", "sensibilite_cm", 1),
    ("Surface interpolée (%)", "interpole_pct", 1),
    ("Vol. Metashape plan ajusté (m3)", "volume_metashape", 1),
    ("Pas grille (m)", "pas", 3),
    ("Cellules", "nb_cellules", 0),
    ("Alertes / erreurs", "alertes", None),
]


def _format(valeur, decimales, virgule):
    if valeur is None:
        return ""
    if isinstance(valeur, (list, tuple)):
        return " | ".join(str(v) for v in valeur)
    if decimales is None:
        return str(valeur)
    texte = ("%." + str(decimales) + "f") % valeur
    return texte.replace(".", ",") if virgule else texte


def ecrire_csv(chemin, resultats, separateur=";", virgule=True, entete=None):
    with open(chemin, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=separateur)
        if entete:
            for ligne in entete:
                w.writerow([ligne])
            w.writerow([])
        # Colonnes de tonnage seulement si une densité a été renseignée
        colonnes = [c for c in COLONNES_CSV if c[1] not in ("densite", "tonnage")
                    or any(r.get(c[1]) is not None for r in resultats)]
        w.writerow([c[0] for c in colonnes])
        for r in resultats:
            w.writerow([_format(r.get(cle), dec, virgule) for _, cle, dec in colonnes])
        valides = [r for r in resultats if r.get("volume_net") is not None]
        total = {"nom": "TOTAL"}
        for cle in ("surface_2d", "volume_net", "volume_dessus", "volume_dessous"):
            total[cle] = sum(r[cle] for r in valides)
        tonnages = [r["tonnage"] for r in valides if r.get("tonnage") is not None]
        total["tonnage"] = sum(tonnages) if tonnages else None
        w.writerow([_format(total.get(cle), dec, virgule) for _, cle, dec in colonnes])


def _chemin_csv(doc, chunk, cfg):
    chemin = (cfg.get("fichier_csv") or "").strip()
    if chemin:
        return chemin
    horodatage = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    nom_chunk = re.sub(r"[^\w\-]+", "_", _label(chunk, "chunk"))
    projet = getattr(doc, "path", "") or ""
    if projet:
        base = os.path.splitext(os.path.basename(projet))[0]
        return os.path.join(os.path.dirname(projet), "%s_volumes_%s_%s.csv" % (base, nom_chunk, horodatage))
    nom = "volumes_%s_%s.csv" % (nom_chunk, horodatage)
    try:
        choix = Metashape.app.getSaveFileName("Enregistrer les volumes (CSV)", nom, "CSV (*.csv)")
        if choix:
            return choix
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), nom)


def _selection_stocks(formes, cfg, geometrie):
    """Polygones des stocks selon le(s) groupe(s) demandé(s) : [(forme, géométrie)]."""
    groupes = [normaliser(g) for g in str(cfg.get("groupe_stocks") or "").split(",") if g.strip()]
    autres = {normaliser(cfg.get("groupe_exclusions") or ""), normaliser(cfg.get("groupe_epaulements") or ""),
              normaliser(GROUPE_CONTROLE)} - {""}

    def polygones(filtre):
        choix = []
        for s in formes:
            if filtre(s):
                g = geometrie(s)
                if g[0] == "polygone":
                    choix.append((s, g))
        return choix

    if groupes:
        choix = polygones(lambda s: _groupe(s) in groupes)
        if choix:
            return choix, "groupe(s) « %s »" % cfg.get("groupe_stocks")
        _log("Groupe « %s » introuvable ou vide." % cfg.get("groupe_stocks"))
    choix = polygones(lambda s: getattr(s, "selected", False) and _groupe(s) not in autres)
    if choix:
        return choix, "polygones sélectionnés"
    return polygones(lambda s: _groupe(s) not in autres), "tous les polygones"


def executer(cfg=None, chunk=None):
    """Lance le calcul sur le chunk actif ; retourne la liste des résultats."""
    if Metashape is None:
        raise ErreurScript("Ce script doit être exécuté dans Agisoft Metashape Professional.")
    cfg = dict(CONFIG, **(cfg or {}))
    doc = Metashape.app.document
    chunk = chunk or doc.chunk
    if chunk is None:
        raise ErreurScript("Aucun chunk actif.")
    if chunk.shapes is None or not list(chunk.shapes):
        raise ErreurScript("Aucune forme dans le chunk : dessinez un polygone par stock "
                           "(de préférence dans un groupe « %s »)." % cfg["groupe_stocks"])
    debut = time.time()
    _log("Volumes de stocks v%s - Metashape %s - chunk « %s »"
         % (VERSION, getattr(Metashape.app, "version", "?"), _label(chunk, "chunk")))
    try:
        methode_normalisee(cfg["methode_base"])
    except ErreurStock as e:
        raise ErreurScript(str(e))

    # --- MNE ----------------------------------------------------------------------
    if cfg.get("construire_mne_filtre"):
        elevation = _construire_mne_filtre(chunk, cfg)
    else:
        elevation, _ = _trouver_mne(doc, chunk, cfg.get("mne"))
    if elevation is None:
        raise ErreurScript("Aucun MNE trouvé%s. Construisez un MNE (Workflow > Construire un MNE) "
                           "ou cochez « construire un MNE filtré »."
                           % ((" (« %s »)" % cfg["mne"]) if cfg.get("mne") else ""))
    crs_mne = _crs_mne(elevation) or chunk.crs
    crs_formes = chunk.shapes.crs or crs_mne
    genre, fh, fv = infos_crs(crs_mne)
    _log("SCR du MNE : %s (%s)" % (_nom_crs(crs_mne), genre))
    if genre == "geographique":
        _log("MNE en coordonnées géographiques : conversion locale en mètres (un SCR projeté est conseillé).")
    if abs(fh - 1.0) > 1e-9 or abs(fv - 1.0) > 1e-9:
        _log("Unités du SCR converties en mètres (plan x %.10g, altitude x %.10g) : résultats en m3."
             % (fh if genre != "geographique" else 1.0, fv))
    vers_mne = _Transfo(crs_formes, crs_mne)
    vers_formes = _Transfo(crs_mne, crs_formes)

    # --- Formes ---------------------------------------------------------------------
    formes = list(chunk.shapes)
    marqueurs = _positions_marqueurs(chunk) if any(getattr(s, "is_attached", False) for s in formes) else {}
    cache = {}

    def geometrie(s):
        if id(s) not in cache:
            try:
                cache[id(s)] = _geometrie(s, chunk, marqueurs)
            except Exception as e:
                _log("forme « %s » ignorée (%s)" % (_label(s), e))
                cache[id(s)] = ("autre", [])
        return cache[id(s)]

    stocks, origine = _selection_stocks(formes, cfg, geometrie)
    if not stocks:
        raise ErreurScript("Aucun polygone de stock trouvé.")
    _log("%d stock(s) : %s" % (len(stocks), origine))

    def en_mne(parties, polygone):
        if polygone:
            return [[[vers_mne(*p)[:2] for p in a] for a in poly] for poly in parties]
        return [[vers_mne(*p)[:2] for p in l] for l in parties]

    g_excl = normaliser(cfg.get("groupe_exclusions") or "")
    g_ep = normaliser(cfg.get("groupe_epaulements") or "")
    excl_mne, ep_lignes_mne, ep_polys_mne, noms_ep = [], [], [], []
    for s in formes:
        grp = _groupe(s)
        if not grp or grp not in (g_excl, g_ep):
            continue
        genre, parties = geometrie(s)
        if g_excl and grp == g_excl and genre == "polygone":
            excl_mne.extend(en_mne(parties, True))
        elif g_ep and grp == g_ep:
            if genre == "polygone":
                ep_polys_mne.extend(en_mne(parties, True))
                noms_ep.extend([_label(s) or "épaulement %d" % (len(noms_ep) + 1)] * len(parties))
            elif genre == "ligne":
                ep_lignes_mne.extend(en_mne(parties, False))
    stocks_mne = [(s, en_mne(parties, True)) for s, (genre, parties) in stocks]

    pts = [p for _, parties in stocks_mne for poly in parties for a in poly for p in a]
    if not pts:
        raise ErreurScript("Les polygones de stock n'ont pas de sommets exploitables.")
    x0 = 0.5 * (min(p[0] for p in pts) + max(p[0] for p in pts))
    y0 = 0.5 * (min(p[1] for p in pts) + max(p[1] for p in pts))
    repere = Repere(crs_mne, x0, y0)

    def local(parties, polygone=True):
        if polygone:
            return [[[repere.vers_local(*p) for p in a] for a in poly] for poly in parties]
        return [[repere.vers_local(*p) for p in l] for l in parties]

    exclusions = local(excl_mne)
    ep_lignes = local(ep_lignes_mne, False)
    ep_polys = local(ep_polys_mne)
    surface = _fonction_mne(elevation, repere, None, repere.fz)
    resolution = _resolution_m(elevation, repere)
    _log("MNE « %s » (résolution %.3f m), %d exclusion(s), %d mur(s), %d talus / face(s) inclinée(s)"
         % (_label(elevation, "actif"), resolution, len(exclusions), len(ep_lignes), len(ep_polys)))

    references = {}

    def fonction_reference(libelle):
        if libelle not in references:
            el_ref, _ = _trouver_mne(doc, chunk, libelle)
            if el_ref is None:
                references[libelle] = None
            else:
                crs_ref = _crs_mne(el_ref) or crs_mne
                references[libelle] = _fonction_mne(el_ref, repere, _Transfo(crs_mne, crs_ref),
                                                    infos_crs(crs_ref)[2])
        return references[libelle]

    # MNE actif = MNE de calcul, pour le contrôle par le volume natif Metashape
    actif = getattr(chunk, "elevation", None)
    restaurer = None
    if cfg.get("comparer_metashape") and actif is not None and \
            getattr(actif, "key", None) != getattr(elevation, "key", None):
        try:
            chunk.elevation = elevation
            restaurer = actif
        except Exception:
            pass

    resultats, controles = [], []
    try:
        for numero, (shape, parties) in enumerate(stocks_mne):
            nom = _label(shape) or "Stock_%d" % (numero + 1)
            params = dict(cfg)
            params.update(_parametres_forme(shape))
            params["resolution_mne_m"] = resolution
            altitude = nombre(params.get("altitude_base"))
            params["altitude_base"] = None if altitude is None else altitude * repere.fz
            t0 = time.time()
            try:
                methode = methode_normalisee(params["methode_base"])
                reference = None
                if methode == "mne_reference":
                    if not params.get("mne_reference"):
                        raise ErreurStock("méthode 'mne_reference' : aucun MNE de référence indiqué")
                    reference = fonction_reference(params["mne_reference"])
                    if reference is None:
                        raise ErreurStock("MNE de référence « %s » introuvable" % params["mne_reference"])
                r = calculer_stock(local(parties), surface, params, exclusions, ep_lignes, ep_polys,
                                   reference, progression=lambda f: Metashape.app.update(),
                                   noms_epaulements=noms_ep)
            except ErreurStock as e:
                r = {"methode": params.get("methode_base"), "alertes": ["ERREUR : %s" % e]}
                _log("%s : ERREUR - %s" % (nom, e))
            r["nom"] = nom
            if cfg.get("comparer_metashape") and r.get("volume_net") is not None:
                r["volume_metashape"] = _volume_metashape(shape)
            if r.get("volume_net") is not None:
                _log("%-25s %12.1f m3  (base %s, surface %.1f m2, %.1f s)%s"
                     % (nom, r["volume_net"], r["methode"], r["surface_2d"], time.time() - t0,
                        ("  ! " + " ; ".join(r["alertes"])) if r["alertes"] else ""))
                if cfg.get("ecrire_attributs"):
                    _ecrire_attributs(shape, nom, r)
                controles.append((nom, r.get("pied_ignore") or []))
            resultats.append(r)
            Metashape.app.update()
    finally:
        if restaurer is not None:
            try:
                chunk.elevation = restaurer
            except Exception:
                pass

    if cfg.get("formes_controle"):
        try:
            n = _creer_formes_controle(chunk, controles, repere, vers_formes)
            if n:
                _log("%d tronçon(s) de pied ignoré(s) dessiné(s) dans le groupe « %s »" % (n, GROUPE_CONTROLE))
        except Exception as e:
            _log("formes de contrôle non créées (%s)" % e)

    chemin = _chemin_csv(doc, chunk, cfg)
    entete = ["Volumes de stocks v%s - %s" % (VERSION, datetime.datetime.now().strftime("%d/%m/%Y %H:%M")),
              "Projet : %s - chunk : %s - MNE : %s" % (getattr(doc, "path", "") or "(non enregistré)",
                                                      _label(chunk, "chunk"), _label(elevation, "actif"))]
    try:
        ecrire_csv(chemin, resultats, cfg.get("separateur_csv", ";"), cfg.get("virgule_decimale", True), entete)
        _log("Résultats enregistrés : " + chemin)
    except Exception as e:
        _log("CSV non enregistré (%s)" % e)
        chemin = None

    valides = [r for r in resultats if r.get("volume_net") is not None]
    total = sum(r["volume_net"] for r in valides)
    _log("TOTAL : %.1f m3 sur %d stock(s) - %.1f s" % (total, len(valides), time.time() - debut))
    try:
        Metashape.app.update()
    except Exception:
        pass
    return {"resultats": resultats, "csv": chemin, "total": total}


# =============================================================================
# INTERFACE
# =============================================================================

if QtWidgets is not None:

    class DialogueVolumes(QtWidgets.QDialog):
        """Fenêtre de paramétrage du calcul."""

        AUCUN = "(aucun)"
        ACTIF = "(MNE actif)"

        def __init__(self, parent, cfg, chunk, doc):
            QtWidgets.QDialog.__init__(self, parent)
            self.setWindowTitle("Volumes de stocks v%s" % VERSION)
            self.cfg = dict(cfg)
            groupes = []
            try:
                groupes = [_label(g) for g in chunk.shapes.groups if _label(g)]
            except Exception:
                pass
            mnes = [_label(e) for e in _mnes(chunk) if _label(e)]
            refs = list(mnes)
            for c in doc.chunks:
                if c is not chunk:
                    refs.extend("%s/%s" % (_label(c), _label(e)) for e in _mnes(c) if _label(e))

            form = QtWidgets.QFormLayout()
            self.stocks = self._combo(groupes, cfg["groupe_stocks"], editable=True)
            form.addRow("Groupe des stocks :", self.stocks)
            self.exclusions = self._combo([self.AUCUN] + groupes, cfg["groupe_exclusions"] or self.AUCUN, True)
            form.addRow("Groupe exclusions :", self.exclusions)
            self.epaulements = self._combo([self.AUCUN] + groupes, cfg["groupe_epaulements"] or self.AUCUN, True)
            form.addRow("Groupe épaulements :", self.epaulements)
            aide = QtWidgets.QLabel("   murs / blocs / roche verticale : LIGNES au pied du mur\n"
                                    "   talus / roche inclinée : POLYGONE sur la face visible")
            form.addRow("", aide)

            self.mne = self._combo([self.ACTIF] + mnes, cfg["mne"] or self.ACTIF)
            form.addRow("MNE du stock :", self.mne)
            self.filtre = QtWidgets.QCheckBox("Construire un MNE sans végétation / véhicules / bruit (nuage dense)")
            self.filtre.setChecked(bool(cfg["construire_mne_filtre"]))
            form.addRow("", self.filtre)
            self.classer = QtWidgets.QCheckBox("Classer d'abord automatiquement le nuage (remplace les classes)")
            self.classer.setChecked(bool(cfg["classer_points"]))
            form.addRow("", self.classer)

            self.methode = QtWidgets.QComboBox()
            for m in METHODES:
                self.methode.addItem("%s - %s" % (m, DESCRIPTION_METHODES[m]), m)
            self.methode.setCurrentIndex(METHODES.index(methode_normalisee(cfg["methode_base"])))
            form.addRow("Base :", self.methode)
            self.altitude = QtWidgets.QLineEdit("" if cfg["altitude_base"] is None else str(cfg["altitude_base"]))
            form.addRow("Altitude de base (m) :", self.altitude)
            self.reference = self._combo([self.AUCUN] + refs, cfg["mne_reference"] or self.AUCUN, True)
            form.addRow("MNE de référence :", self.reference)
            self.rejet = QtWidgets.QCheckBox("Rejet automatique des points aberrants du pied")
            self.rejet.setChecked(bool(cfg["rejet_points_hauts"]))
            form.addRow("", self.rejet)

            self.pas = self._spin(cfg["pas_grille"], 0.0, 10.0, 3, " m  (0 = auto)")
            form.addRow("Pas de grille :", self.pas)

            ligne_csv = QtWidgets.QHBoxLayout()
            self.csv = QtWidgets.QLineEdit(cfg["fichier_csv"])
            self.csv.setPlaceholderText("(à côté du projet)")
            bouton = QtWidgets.QPushButton("...")
            bouton.clicked.connect(self._choisir_csv)
            ligne_csv.addWidget(self.csv)
            ligne_csv.addWidget(bouton)
            form.addRow("Fichier CSV :", ligne_csv)
            self.attributs = QtWidgets.QCheckBox("Écrire les résultats dans les attributs des polygones")
            self.attributs.setChecked(bool(cfg["ecrire_attributs"]))
            form.addRow("", self.attributs)
            self.controle = QtWidgets.QCheckBox("Dessiner les tronçons de pied ignorés (contrôle)")
            self.controle.setChecked(bool(cfg["formes_controle"]))
            form.addRow("", self.controle)

            boutons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            boutons.accepted.connect(self.accept)
            boutons.rejected.connect(self.reject)
            layout = QtWidgets.QVBoxLayout()
            layout.addLayout(form)
            layout.addWidget(boutons)
            self.setLayout(layout)

        @staticmethod
        def _combo(valeurs, courant, editable=False):
            combo = QtWidgets.QComboBox()
            combo.setEditable(editable)
            for v in valeurs:
                combo.addItem(v)
            if courant and courant not in valeurs:
                combo.addItem(courant)
            if courant:
                combo.setCurrentIndex(combo.findText(courant))
            return combo

        @staticmethod
        def _spin(valeur, mini, maxi, decimales, suffixe):
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(mini, maxi)
            spin.setDecimals(decimales)
            spin.setSuffix(suffixe)
            spin.setValue(float(valeur or 0.0))
            return spin

        def _choisir_csv(self):
            chemin = QtWidgets.QFileDialog.getSaveFileName(self, "Fichier CSV", self.csv.text(), "CSV (*.csv)")
            if isinstance(chemin, tuple):
                chemin = chemin[0]
            if chemin:
                self.csv.setText(chemin)

        def config(self):
            def texte(combo, vide):
                t = combo.currentText().strip()
                return "" if t == vide else t
            cfg = dict(self.cfg)
            cfg.update({
                "groupe_stocks": self.stocks.currentText().strip(),
                "groupe_exclusions": texte(self.exclusions, self.AUCUN),
                "groupe_epaulements": texte(self.epaulements, self.AUCUN),
                "mne": texte(self.mne, self.ACTIF),
                "construire_mne_filtre": self.filtre.isChecked(),
                "classer_points": self.classer.isChecked(),
                "methode_base": self.methode.currentData(),
                "altitude_base": nombre(self.altitude.text()),
                "mne_reference": texte(self.reference, self.AUCUN),
                "rejet_points_hauts": self.rejet.isChecked(),
                "pas_grille": self.pas.value(),
                "fichier_csv": self.csv.text().strip(),
                "ecrire_attributs": self.attributs.isChecked(),
                "formes_controle": self.controle.isChecked(),
            })
            return cfg


def lancer():
    """Point d'entrée du menu : fenêtre de paramétrage puis calcul."""
    try:
        doc = Metashape.app.document
        chunk = doc.chunk
        if chunk is None:
            raise ErreurScript("Aucun chunk actif.")
        cfg = dict(CONFIG)
        if QtWidgets is not None:
            parent = QtWidgets.QApplication.instance().activeWindow()
            dialogue = DialogueVolumes(parent, cfg, chunk, doc)
            ouvrir = getattr(dialogue, "exec_", None) or dialogue.exec
            if not ouvrir():
                return
            cfg = dialogue.config()
        sortie = executer(cfg, chunk)
        valides = [r for r in sortie["resultats"] if r.get("volume_net") is not None]
        lignes = ["%s : %.1f m³%s" % (r["nom"], r["volume_net"],
                                      (" (%.1f t)" % r["tonnage"]) if r.get("tonnage") else "")
                  for r in valides]
        erreurs = [r["nom"] for r in sortie["resultats"] if r.get("volume_net") is None]
        alertes = [r["nom"] for r in valides if r.get("alertes")]
        message = "\n".join(lignes[:30]) + ("\n..." if len(lignes) > 30 else "")
        message += "\n\nTOTAL : %.1f m³" % sortie["total"]
        if alertes:
            message += "\nAlertes à vérifier : " + ", ".join(alertes)
        if erreurs:
            message += "\nErreurs : " + ", ".join(erreurs)
        if sortie["csv"]:
            message += "\n\nDétail : " + sortie["csv"]
        Metashape.app.messageBox(message)
    except ErreurScript as e:
        Metashape.app.messageBox("Volumes de stocks :\n" + str(e))
    except Exception as e:
        traceback.print_exc()
        Metashape.app.messageBox("Volumes de stocks - erreur inattendue :\n%s\n(détail dans la console)" % e)


if Metashape is not None and hasattr(Metashape, "app"):
    try:
        Metashape.app.addMenuItem(LIBELLE_MENU, lancer)
        print("Volumes de stocks v%s : menu « %s »" % (VERSION, LIBELLE_MENU.replace("/", " > ")))
    except Exception:
        pass
