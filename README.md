# Volumes de stocks pour Agisoft Metashape

Script Python pour **Metashape Professional 2.x**. Il calcule automatiquement le
volume (et, si on le souhaite, le tonnage) de chaque stock de matériaux dessiné
sous forme de polygone. Il gère les stocks **épaulés** (contre un mur ou des
blocs), **adossés à un talus**, et **partiellement masqués** par de la végétation
ou des engins.

**Aucune classification des points sol n'est nécessaire** : le calcul se fait
directement sur le MNE (MNS) du projet. La classification automatique de
Metashape reste disponible en option pour retirer la végétation présente *sur*
les stocks.

---

## 1. Installation

1. Copier `volumes_stocks.py` sur le poste.
2. Dans Metashape : **Outils > Exécuter un script…** (*Tools > Run Script*), puis
   choisir `volumes_stocks.py`.
3. Un menu **Scripts > Volumes de stocks...** apparaît : c'est lui qui lance le calcul.

Pour que le menu soit présent à chaque démarrage, copier le fichier dans le
dossier des scripts chargés automatiquement :

| Système | Dossier |
|---|---|
| Windows | `%LOCALAPPDATA%\Agisoft\Metashape Pro\scripts\` |
| macOS | `~/Library/Application Support/Agisoft/Metashape Pro/scripts/` |
| Linux | `~/.local/share/Agisoft/Metashape Pro/scripts/` |

Aucune bibliothèque externe n'est nécessaire (pas de numpy, pas de pip).

## 2. Ce qu'il faut dans le projet

- Un **MNE** (*Workflow > Construire un MNE*), à partir du nuage dense ou du
  maillage. Sinon, cocher l'option « Construire un MNE filtré » (il faut alors
  un nuage dense).
- Un **système de coordonnées projeté** en mètres (Lambert-93, CC, UTM…). Un
  MNE en WGS 84 (degrés) fonctionne aussi : il est converti localement en mètres.
- Des **formes**, rangées dans des groupes (calques de formes) :

| Groupe | Contenu | Obligatoire |
|---|---|---|
| `Stocks` | un **polygone par stock**, tracé **au pied** du stock, de préférence 0,5 à 1 m à l'extérieur, sur le sol. Le nom du polygone devient le nom du stock. | oui (sinon : polygones sélectionnés, puis tous les polygones) |
| `Exclusions` | polygones autour des éléments parasites : arbre, buisson, engin, bloc, personne… Le MNE y est ignoré et reconstruit par interpolation à partir de leur pourtour. Les points du pied situés dedans sont ignorés. | non |
| `Epaulements` | **lignes** tracées le long des murs, blocs ou épaulements contre lesquels le stock s'appuie (ou polygones couvrant ces zones). Les tronçons de pied à moins de 0,5 m sont ignorés pour estimer la base. | non |

Les noms de groupes se changent dans la fenêtre du script (ou dans `CONFIG`, en
tête du fichier). Les majuscules et les accents ne comptent pas.

### Réglages propres à un stock

Dans la **description** du polygone (ou dans ses attributs), on peut indiquer
des réglages qui ne valent que pour ce stock, séparés par des `;` :

```
methode=triangule; densite=1,6
methode=altitude; altitude=123,45
methode=mne_reference; reference=Sol avant stockage
```

## 3. Choisir la base du stock

La **base** est la surface sous le stock, qu'on ne voit pas. C'est le choix le
plus important pour le résultat.

| Situation sur le terrain | Méthode | Remarque |
|---|---|---|
| Stock sur un sol plat ou en pente régulière | `plan` (par défaut) | Plan ajusté sur le pied, en écartant automatiquement les points aberrants |
| Stock sur une dalle ou une plateforme horizontale | `horizontal` | Plan horizontal à l'altitude moyenne du pied |
| Stock en alvéole, contre un mur ou des blocs | `plan` + une **ligne** dans `Epaulements` le long du mur | Ou `altitude` si la cote du fond est connue |
| Stock adossé à un talus ou sur un terrain irrégulier | `triangule` | **Ajouter des sommets au polygone aux ruptures de pente** (pied du talus, haut du talus) |
| Fond connu à une cote précise | `altitude` | Cote donnée dans la fenêtre ou dans la description du polygone |
| Levé de la plateforme vide disponible (ou un MNT) | `mne_reference` | Le MNE de référence peut être dans un autre chunk : `NomDuChunk/NomDuMNE` |

**Stock adossé à un talus** : avec `plan`, la base passe *sous* le talus et le
volume est surestimé (le script le signale par une alerte « stock adossé… »).
Utiliser `triangule` et placer des sommets du polygone à la ligne de contact
stock/talus et au pied du talus : la base suit alors le terrain.

## 4. Végétation, engins et autres éléments

| Où | Ce que fait le script | Si ça ne suffit pas |
|---|---|---|
| **Au pied** du stock (buissons, herbes hautes, blocs) | Rejet automatique des points du pied trop hauts ou trop bas. Méthode `plan` : fonctionne tant que la moitié du pied environ reste visible. Méthode `triangule` : écarte les objets plus courts que ~8 m le long du pied. | Polygone dans `Exclusions` ou ligne dans `Epaulements` sur la portion masquée |
| **Sur** le stock (arbre, buisson, engin) | Rien d'automatique avec le MNE brut | Polygone dans `Exclusions` (le plus simple), ou option **« Construire un MNE sans végétation / véhicules / bruit »** |
| Trous du MNE | Comblés par interpolation | Construire le MNE avec interpolation activée |

L'option **MNE filtré** construit un nouveau MNE à partir du nuage dense en
excluant les classes végétation, véhicules et bruit, puis comble les trous par
interpolation. Elle s'appuie sur les classes déjà présentes dans le nuage, ou,
si l'on coche « Classer d'abord automatiquement », sur la classification
automatique de Metashape (**attention : elle remplace les classes existantes du
nuage**). Le MNE existant n'est pas supprimé, sauf sous Metashape 1.x qui ne
gère qu'un MNE par chunk.

## 5. Résultats

- **Fichier CSV** (séparateur `;`, virgule décimale : il s'ouvre directement dans
  Excel), enregistré à côté du projet `.psx`, avec une ligne par stock et une
  ligne TOTAL.
- **Attributs des polygones** : `Vol_net_m3`, `Vol_tonnage_t`, `Vol_surface_m2`,
  `Vol_methode`, `Vol_date`… Ils restent dans le projet et s'exportent avec les
  formes (SHP, GeoPackage, DXF).
- **Groupe `Controle volumes - pied ignore`** : les tronçons de pied que le script
  a écartés (rejet automatique, épaulement, exclusion, absence de données). C'est
  le contrôle visuel à faire : les tronçons rouges doivent correspondre à de la
  végétation, un mur, un engin… et pas à du sol propre. Ce groupe est recréé à
  chaque calcul.
- Un récapitulatif dans une fenêtre et dans la **console** de Metashape.

Colonnes principales du CSV :

| Colonne | Signification |
|---|---|
| Volume net (m3) | **Volume du stock** = volume au-dessus de la base − volume sous la base |
| Volume au-dessus / sous base | Le volume « sous la base » doit rester proche de 0 ; sinon, la base est trop haute ou le polygone mal placé |
| Tonnage (t) | Volume net × densité (si une densité est renseignée) |
| Pied utilisé (%) | Part du pied ayant servi à calculer la base |
| Écart-type pied (m) | Régularité du sol au pied du stock |
| Incertitude base (± m3) | Ordre de grandeur de l'incertitude due à la base seule (hors erreur du MNE) |
| Sensibilité (m3 par cm) | Variation du volume pour une erreur de 1 cm sur la base (= surface / 100) |
| Surface interpolée (%) | Part de la surface reconstruite (exclusions et trous du MNE) |
| Vol. Metashape plan ajusté | Volume calculé par Metashape lui-même (« Mesurer surface et volume », plan ajusté) pour comparaison ; il ne rejette pas les points aberrants |
| Alertes / erreurs | Points à vérifier (voir ci-dessous) |

Alertes possibles :

- *x % du pied rejeté, en moyenne y m au-dessus de la base* : stock adossé (mur,
  talus) ou végétation au pied. Vérifier le groupe de contrôle ; déclarer un
  épaulement ou passer en `triangule`.
- *base très inclinée* : pente de la base supérieure à 15 %, souvent un
  épaulement non déclaré.
- *volume sous la base important* : base trop haute ou polygone tracé sur le
  flanc du stock au lieu du sol.
- *seulement x % du pied utilisé* : base estimée sur peu de points.
- *x % de la surface interpolée* : exclusions ou trous importants.
- *pied irrégulier* : écart-type du pied supérieur à 30 cm.

## 6. Bonnes pratiques

- Tracer le polygone **sur le sol, juste à l'extérieur du pied**. S'il est tracé
  sur le flanc, la base est trop haute et le volume est sous-estimé.
- Pour les stocks en pente ou adossés, ajouter des **sommets aux changements de
  pente**.
- La précision dépend d'abord du **géoréférencement** (points d'appui) : sur
  1 000 m², une erreur de 2 cm en altitude fait 20 m³.
- Le pas de calcul est automatique (résolution du MNE, plafonné à 400 000
  cellules par stock) ; à 5–10 cm, l'erreur due au pas est négligeable.

## 7. Paramètres avancés

Tous les réglages par défaut sont dans le dictionnaire `CONFIG`, en tête de
`volumes_stocks.py`, et la plupart sont modifiables dans la fenêtre :

| Paramètre | Défaut | Rôle |
|---|---|---|
| `groupe_stocks` | `Stocks` | Groupe(s) des polygones de stocks (séparés par des virgules) |
| `groupe_exclusions` / `groupe_epaulements` | `Exclusions` / `Epaulements` | Groupes optionnels |
| `tolerance_epaulement` | 0,5 m | Distance d'influence des lignes d'épaulement |
| `mne` | MNE actif | Libellé du MNE à utiliser |
| `methode_base` | `plan` | `plan`, `horizontal`, `triangule`, `altitude`, `mne_reference` |
| `rejet_points_hauts` | oui | Rejet automatique des points aberrants du pied |
| `rejet_k`, `rejet_min` | 2,5 ; 0,10 m | Seuil de rejet = max(k × écart-type robuste, minimum) |
| `fenetre_pied` | 1 m | Méthode triangulée : demi-fenêtre pour l'altitude d'un sommet |
| `fenetre_rejet` | 8 m | Méthode triangulée : demi-fenêtre de la médiane glissante |
| `pas_grille` | auto | Pas de calcul en mètres |
| `densite` | 0 | Densité en t/m³ (0 = pas de tonnage) |
| `classes_exclues` | végétation, véhicules, bruit | Classes retirées du MNE filtré |
| `separateur_csv`, `virgule_decimale` | `;`, oui | Format du CSV |

## 8. Fonctionnement

Pour chaque polygone de stock :

1. Le MNE est lu sur une grille régulière à l'intérieur du polygone.
2. Les cellules situées dans une exclusion, ou sans donnée, sont reconstruites
   par interpolation (inverse du carré de la distance) à partir des cellules qui
   les bordent.
3. Le pied est échantillonné tous les 20 cm environ. Les points situés dans une
   exclusion, près d'un épaulement ou sans donnée sont écartés.
4. La base est calculée :
   - `plan` / `horizontal` : estimation de départ insensible aux points
     aberrants (moindre médiane), puis moindres carrés itérés avec rejet des
     points hors seuil ;
   - `triangule` : altitude robuste du sol à chaque sommet (médiane locale le
     long du pied, après rejet par médiane glissante), puis triangulation du
     polygone (oreilles + critère de Delaunay). Les sommets sans donnée valable
     sont interpolés le long du pied ;
   - `altitude` / `mne_reference` : cote fixe ou autre MNE.
5. Volume = Σ (MNE − base) × surface d'une cellule.

## 9. Tests

Le noyau de calcul est testé sur des stocks synthétiques dont le volume est
connu : cône sur sol plat ou en pente, végétation au pied, stock contre un mur,
stock adossé à un talus, arbre sur le stock, trous du MNE, multipolygones,
MNE de référence, MNE en WGS 84. Un faux module `Metashape` permet aussi de
tester toute la chaîne : formes dans un autre système de coordonnées, groupes,
réglages par stock, CSV, attributs, formes de contrôle et MNE filtré.

```
python -m unittest discover -s tests -v
```

## 10. Limites connues

- Le script n'a **pas encore été exécuté dans Metashape lui-même** : il suit
  l'API Python 2.x (`Elevation.altitude`, `Shape.geometry`, `buildDem`,
  `classifyPoints`…) et a été validé avec une imitation de cette API. Un premier
  essai sur un projet réel est nécessaire.
- La base `triangule` relie les sommets du polygone par des triangles : entre
  deux sommets, le terrain est supposé linéaire.
- Un SCR projeté en pieds donnerait des volumes en pieds cubes.
- Les polygones qui se recoupent eux-mêmes ne peuvent pas être triangulés ; le
  script utilise alors un plan et le signale.
