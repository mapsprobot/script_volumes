# Volumes de stocks pour Agisoft Metashape

Script Python pour **Metashape Professional 2.x** (prévu pour la **2.3.2**). Il
calcule automatiquement le **volume en m³** de chaque stock de matériaux dessiné
sous forme de polygone, y compris pour les stocks :

- **épaulés** contre un mur, des blocs béton ou un front de roche ;
- **adossés à un talus**, naturel ou artificiel, ou à un flanc de roche incliné ;
- **partiellement masqués** par de la végétation, des engins ou d'autres éléments.

**Aucune classification des points sol n'est nécessaire** : le calcul se fait
directement sur le MNE (MNS) du projet.

Il fonctionne dans **tous les systèmes de coordonnées** : CC42 à CC50,
Lambert-93, UTM, WGS 84, systèmes locaux, avec ou sans système d'altitude
(NGF-IGN69…). Les résultats sont toujours en **m, m² et m³**, même si le système
est en pieds.

---

## 1. Installation

1. Copier `volumes_stocks.py` sur le poste.
2. Dans Metashape : **Outils > Exécuter un script…** (*Tools > Run Script*), puis
   choisir `volumes_stocks.py`. Cette étape **ne lance pas le calcul** : elle
   ajoute seulement le menu.
3. Lancer le calcul par le menu **Scripts > Volumes de stocks...** : une fenêtre
   de réglages s'ouvre, puis **OK** lance le calcul.

Pour que le menu soit présent à chaque démarrage de Metashape, copier le fichier
dans le dossier des scripts chargés automatiquement :

| Système | Dossier |
|---|---|
| Windows | `%LOCALAPPDATA%\Agisoft\Metashape Pro\scripts\` |
| macOS | `~/Library/Application Support/Agisoft/Metashape Pro/scripts/` |
| Linux | `~/.local/share/Agisoft/Metashape Pro/scripts/` |

Aucune bibliothèque externe n'est nécessaire (pas de numpy, pas de pip).

## 2. Préparer le projet

- Un **MNE** (*Workflow > Construire un MNE*), construit à partir du nuage dense
  ou du maillage. On peut aussi cocher l'option « Construire un MNE sans
  végétation », ce qui demande un nuage dense.
- Des **formes**, rangées dans des groupes (calques de formes) :

| Groupe | À dessiner | Obligatoire |
|---|---|---|
| `Stocks` | Un **polygone par stock**, tracé **au pied** du stock, de préférence 0,5 à 1 m à l'extérieur, sur le sol. Le nom du polygone devient le nom du stock. | oui (sinon : polygones sélectionnés, puis tous les polygones) |
| `Exclusions` | Des polygones autour des éléments parasites : arbre, buisson, engin, bloc isolé, personne… | non |
| `Epaulements` | Une **ligne** le long d'un mur vertical, ou un **polygone** sur la face visible d'un talus (voir §3). | non |

Les noms de groupes se changent dans la fenêtre du script. Les majuscules et les
accents ne comptent pas : « Épaulements » convient aussi.

## 3. Épaulements : comment les dessiner

Le pied d'un stock épaulé n'est pas visible côté épaulement. Le script doit donc
savoir ce qu'il y a sous le stock de ce côté.

### Mur vertical : blocs béton, front de roche vertical → une LIGNE

Tracer une **ligne** (polyligne) dans le groupe `Epaulements`, le long du pied du
mur, à l'endroit où le stock touche le mur. Le polygone du stock suit lui aussi le
mur de ce côté.

Le script ignore le pied du stock le long de cette ligne. Il prolonge la base du
sol, estimée sur les côtés dégagés, jusqu'au mur.

```
   vue en coupe         mur
                         █
          ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄█
       ▄▄▀   stock       █
  ▄▄▄▀▀..................█  ← base du sol prolongée jusqu'au mur
  sol                    █
                         ↑ ligne d'épaulement (pied du mur)
```

### Talus naturel ou artificiel, flanc de roche incliné → un POLYGONE

Tracer un **polygone** dans le groupe `Epaulements`, **sur la partie visible de
la face du talus**, au-dessus ou à côté du stock. Il ne faut pas déborder sur la
crête plate ni sur le stock. 1 à 3 m de large suffisent.

Le script calcule la pente de cette face et la **prolonge sous le stock** jusqu'au
sol. La base retenue est la plus haute des deux surfaces : le sol, ou la face du
talus prolongée. Le pied du talus, caché sous le stock, est ainsi reconstitué.

```
   vue en coupe                          ▄▄▄▄  crête
                                     ▄▄▀▀ ▓▓   ← polygone sur la face VISIBLE
             ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▀▀▀
          ▄▀▀       stock       .·'
     ▄▄▄▀▀.....................'   ← face du talus prolongée sous le stock
     sol                    ↑ pied du talus (caché) retrouvé automatiquement
```

- **Alvéole** ou angle entre plusieurs talus : un polygone par face. Chaque face
  est prolongée, et la base suit le sol, puis chacune des faces.
- Un polygone d'épaulement s'applique aux stocks situés à **moins de 5 m**.
- Si la face tracée est presque horizontale (pente < 10 %, par exemple le dessus
  des blocs), elle n'est pas prolongée et une alerte le signale. Pour un mur
  vertical, tracer une ligne.
- La colonne « Épaulements inclinés » du CSV donne la pente mesurée de chaque
  face. C'est un contrôle simple : un talus de remblai fait en général 60 à 70 %.

**Pourquoi c'est important** (cas test, talus à 80 % dont le pied est caché) :
sans polygone d'épaulement, l'erreur atteint −80 % avec la base plane et +45 %
avec la base horizontale. Avec le polygone, le volume est exact.

## 4. Choisir la base du stock

La **base** est la surface sous le stock, qu'on ne voit pas. C'est le choix le
plus important pour le résultat.

| Situation | Méthode | Remarque |
|---|---|---|
| Stock sur un sol plat ou en pente régulière | `plan` (par défaut) | Plan ajusté sur le pied, en écartant automatiquement les points aberrants |
| Stock contre un mur, des blocs ou un talus | `plan` + épaulements (§3) | Méthode conseillée dans la plupart des cas |
| Stock sur une dalle ou une plateforme horizontale | `horizontal` | Plan horizontal à l'altitude moyenne du pied |
| Sol irrégulier tout autour du stock | `triangule` | Base triangulée sur les sommets du polygone : ajouter des sommets aux changements de pente |
| Cote du fond connue | `altitude` | Cote saisie dans la fenêtre, ou dans la description du polygone |
| Levé de la plateforme vide disponible (ou MNT) | `mne_reference` | Le MNE de référence peut être dans un autre chunk : `NomDuChunk/NomDuMNE` |

Les épaulements (lignes et polygones) fonctionnent avec toutes les méthodes,
sauf `mne_reference` : le MNE de référence contient déjà le terrain.

### Réglages propres à un stock

Dans la **description** du polygone, ou dans ses attributs, on peut donner des
réglages qui ne valent que pour ce stock, séparés par des `;` :

```
methode=triangule
methode=altitude; altitude=312,45
methode=mne_reference; reference=Plateforme vide
```

## 5. Végétation, engins et autres éléments

| Où | Ce que fait le script | Si ça ne suffit pas |
|---|---|---|
| **Au pied** du stock (buissons, herbes hautes, blocs) | Rejet automatique des points du pied aberrants. Méthode `plan` : efficace tant qu'environ la moitié du pied reste visible. Méthode `triangule` : écarte les objets de moins de ~8 m le long du pied. | Un polygone dans `Exclusions` |
| **Sur** le stock (arbre, buisson, engin) | Rien d'automatique sur le MNE brut | Un polygone dans `Exclusions` (le plus simple), ou l'option **MNE sans végétation** |
| **Sur la face d'un talus** (polygone d'épaulement) | Rejet automatique des points aberrants (buissons, blocs) | Un polygone dans `Exclusions` sur la végétation |
| Trous du MNE | Comblés par interpolation | Construire le MNE avec l'interpolation activée |

Dans une zone d'exclusion, le MNE est ignoré puis reconstruit par interpolation à
partir du pourtour. Les points du pied qui s'y trouvent sont aussi ignorés.

L'option **MNE sans végétation** construit un nouveau MNE à partir du nuage dense
en retirant les classes végétation, véhicules et bruit, puis en comblant les
trous. Elle s'appuie sur les classes déjà présentes dans le nuage. Si l'on coche
« Classer d'abord automatiquement », elle utilise la classification automatique
de Metashape, qui **remplace les classes existantes du nuage**. Le MNE existant
est conservé.

## 6. Où voir les résultats

1. **Une fenêtre récapitulative** à la fin du calcul : volume de chaque stock,
   total, stocks à vérifier, emplacement du CSV.
2. **Le fichier CSV**, enregistré **dans le dossier du projet `.psx`** sous le nom
   `<projet>_volumes_<chunk>_<date_heure>.csv`. Il utilise le séparateur `;` et la
   virgule décimale, et s'ouvre directement dans Excel. On peut choisir un autre
   emplacement dans la fenêtre du script.
3. **La console de Metashape** (*Affichage > Console*) : déroulé du calcul,
   système de coordonnées utilisé, et messages d'erreur éventuels.
4. **Les attributs des polygones** : `Vol_net_m3`, `Vol_surface_m2`,
   `Vol_hauteur_max_m`, `Vol_methode`, `Vol_date`. Ils sont enregistrés avec le
   projet et exportés avec les formes (SHP, DXF…).
5. **Le calque `Controle volumes - pied ignore`** : les tronçons de pied écartés
   par le script (rejet automatique, épaulement, exclusion, absence de données).
   Ils doivent correspondre à de la végétation, un mur, un talus ou un engin, pas
   à du sol propre. Le calque est recréé à chaque calcul.

Colonnes principales du CSV :

| Colonne | Signification |
|---|---|
| Volume net (m3) | **Volume du stock** = volume au-dessus de la base − volume sous la base |
| Volume au-dessus / sous base | Le volume sous la base doit rester proche de 0. Sinon, la base est trop haute ou le polygone mal placé. |
| Épaulements inclinés (pente) | Faces de talus prolongées sous le stock, avec leur pente mesurée |
| Base sur épaulement (%) | Part de la surface du stock où la base suit une face de talus |
| Pied utilisé (%) | Part du pied ayant servi à calculer la base du sol |
| Écart-type pied (m) | Régularité du sol au pied du stock |
| Incertitude base (± m3) | Ordre de grandeur de l'incertitude due à la base seule (hors erreur du MNE) |
| Sensibilité (m3 par cm) | Variation du volume pour 1 cm d'erreur sur la base (= surface / 100) |
| Surface interpolée (%) | Part de la surface reconstruite (exclusions et trous du MNE) |
| Vol. Metashape plan ajusté | Volume calculé par Metashape lui-même, pour comparaison. Il ne rejette pas les points aberrants et ne tient pas compte des épaulements. |
| Alertes / erreurs | Points à vérifier (voir ci-dessous) |

Alertes possibles :

- *x % du pied rejeté, en moyenne y m au-dessus de la base* : stock adossé ou
  végétation au pied. Vérifier le calque de contrôle et déclarer l'épaulement.
- *base très inclinée* : la pente de la base dépasse 15 %, souvent à cause d'un
  épaulement non déclaré.
- *épaulement « … » presque horizontal* : le polygone est sur une surface plate,
  par exemple le dessus des blocs. Pour un mur, tracer une ligne.
- *la base suit l'épaulement incliné sur x % de la surface* : au-delà de 60 %,
  vérifier que le polygone est bien sur la face du talus.
- *volume sous la base important* : base trop haute, ou polygone tracé sur le
  flanc du stock au lieu du sol.
- *seulement x % du pied utilisé*, *x % de la surface interpolée*,
  *pied irrégulier* : résultat à vérifier.

## 7. Bonnes pratiques

- Tracer le polygone du stock **sur le sol, juste à l'extérieur du pied**. S'il
  est tracé sur le flanc, la base est trop haute et le volume sous-estimé.
- Côté épaulement, faire passer le polygone **au contact** du mur ou du talus.
- La précision dépend d'abord du **géoréférencement** (points d'appui) : sur
  1 000 m², une erreur de 2 cm en altitude représente 20 m³.
- Le pas de calcul est automatique : résolution du MNE, plafonnée à 400 000
  cellules par stock. À 5–10 cm, l'erreur due au pas est négligeable.

## 8. Systèmes de coordonnées

Le script lit la définition du système de coordonnées du MNE (WKT) :

- **projeté** (CC47, Lambert-93, UTM…) : calcul direct ; une unité en pieds est
  convertie en mètres ;
- **composé** avec un système d'altitude (ex. CC47 + NGF-IGN69) : l'unité des
  altitudes est lue dans le système d'altitude ;
- **géographique** (WGS 84, RGF93 en degrés) : conversion locale en mètres
  (erreur négligeable à l'échelle d'un site) ; un système projeté reste
  préférable ;
- **local** : unités du système local (mètres si le projet est mis à l'échelle).

Les polygones peuvent être dans un autre système que le MNE : ils sont convertis
automatiquement. La console indique le système détecté et les conversions
appliquées.

## 9. Paramètres avancés

Tous les réglages par défaut se trouvent dans le dictionnaire `CONFIG`, en tête de
`volumes_stocks.py`. La plupart sont aussi modifiables dans la fenêtre :

| Paramètre | Défaut | Rôle |
|---|---|---|
| `groupe_stocks` | `Stocks` | Groupe(s) des polygones de stocks, séparés par des virgules |
| `groupe_exclusions` / `groupe_epaulements` | `Exclusions` / `Epaulements` | Groupes optionnels |
| `tolerance_epaulement` | 0,5 m | Distance d'influence des lignes de mur |
| `distance_epaulement` | 5 m | Un polygone de talus s'applique aux stocks situés à moins de cette distance |
| `pente_min_epaulement` | 10 % | En dessous, la face n'est pas prolongée |
| `mne` | MNE actif | Libellé du MNE à utiliser |
| `methode_base` | `plan` | `plan`, `horizontal`, `triangule`, `altitude`, `mne_reference` |
| `rejet_points_hauts` | oui | Rejet automatique des points aberrants |
| `rejet_k`, `rejet_min` | 2,5 ; 0,10 m | Seuil de rejet = max(k × écart-type robuste, minimum) |
| `fenetre_pied`, `fenetre_rejet` | 1 m ; 8 m | Méthode triangulée : fenêtres le long du pied |
| `pas_grille` | auto | Pas de calcul en mètres |
| `classes_exclues` | végétation, véhicules, bruit | Classes retirées du MNE sans végétation |
| `densite` | 0 | Optionnel : si une densité est renseignée, des colonnes de tonnage s'ajoutent |
| `separateur_csv`, `virgule_decimale` | `;`, oui | Format du CSV |

## 10. Fonctionnement

Pour chaque polygone de stock :

1. Le MNE est lu sur une grille régulière à l'intérieur du polygone. Les
   coordonnées et les altitudes sont converties en mètres.
2. Les cellules situées dans une exclusion, ou sans donnée, sont reconstruites par
   interpolation (inverse du carré de la distance) à partir de leur pourtour.
3. Le pied est échantillonné tous les 20 cm environ. Les points situés dans une
   exclusion, près d'un mur, sur un talus déclaré ou sans donnée sont écartés.
4. La base du sol est calculée :
   - `plan` / `horizontal` : estimation de départ insensible aux points aberrants
     (moindre médiane), puis moindres carrés itérés avec rejet ;
   - `triangule` : altitude robuste du sol à chaque sommet, puis triangulation du
     polygone (oreilles + critère de Delaunay) ;
   - `altitude` / `mne_reference` : cote fixe ou autre MNE.
5. Pour chaque polygone de talus proche, un plan robuste est ajusté sur la face
   visible (hors stock et hors exclusions). La base devient le maximum entre la
   base du sol et les faces prolongées.
6. Volume = Σ (MNE − base) × surface d'une cellule.

## 11. Tests

Le noyau de calcul est testé sur des stocks synthétiques dont le volume est
connu : cône sur sol plat ou en pente, végétation au pied, stock contre un mur,
stock adossé à un talus au pied caché, alvéole à deux faces, arbre sur le stock,
trous du MNE, multipolygones, MNE de référence. La lecture des systèmes de
coordonnées est testée sur CC47, CC47 + NGF-IGN69, WKT2, pieds US, WGS 84 et un
système local.

Un faux module `Metashape` permet de tester toute la chaîne : formes dans un autre
système que le MNE, groupes, réglages par stock, CSV, attributs, formes de
contrôle, MNE sans végétation, talus et système en pieds.

```
python -m unittest discover -s tests -v
```

## 12. Limites connues

- Le script n'a **pas encore été exécuté dans Metashape lui-même**. Il suit l'API
  Python 2.x (`Elevation.altitude`, `Shape.geometry`, `buildDem`,
  `classifyPoints`…) et a été validé avec une imitation de cette API. Un premier
  essai sur un projet réel en 2.3.2 est nécessaire.
- Une face de talus est représentée par **un plan**. Pour un talus courbe ou
  irrégulier, découper la face en plusieurs polygones.
- Un mur doit être **vertical** pour être traité par une ligne. Une face inclinée
  se traite avec un polygone.
- La base `triangule` relie les sommets du polygone par des triangles : entre deux
  sommets, le terrain est supposé linéaire.
- Un polygone qui se recoupe lui-même ne peut pas être triangulé. Le script
  utilise alors un plan et le signale.
