# Récapitulatif des tests — DataCompiler

*État au 04/08/2026. Tous les tests OCR/langue ci-dessous utilisent le modèle Tesseract anglais uniquement (aucun paquet `fra`/`deu`/`lit` disponible dans l'environnement de test) — à revalider avec les vrais paquets de langue en prod.*

---

## 1. Fichiers testés, par caractéristique

### test1 / test-impots-revenu.pdf — feuille d'impôts (DGFP)
Le fichier de référence de toute la session en cours.
- `native_text_quality` = 0.978, `reading_order_score` = 0.996 — chiffres stables, reproduits à l'identique sur ta nouvelle architecture.
- **Texte vectorisé confirmé** : "Numéro fiscal" (17 courbes, x=21.2→79.5, y=182.4→189.1), ~41 zones détectées sur la page 1 — vérifié visuellement (overlay sur rendu réel), aucun faux positif observé sur 3 zones inspectées (labels "Vos références"/"Vos contacts"), aucune fausse alerte sur le bloc adresse destinataire (natif).
- `native_text_coverage` calculé = **0.748** (pas 0.978, pas 50% — entre les deux).
- Logo Marianne = vraie image avec texte réel dedans ("RÉPUBLIQUE FRANÇAISE", "Liberté Égalité Fraternité") — confirmé non-sélectionnable, confirmé positif par `image_text_probe.py`.
- Catégorie recalculée : `natif_mixte` (nouvelle catégorie), pas `natif_propre`.
- Boucle crop-render + OCR ciblé validée de bout en bout sur la zone "Numéro fiscal" : `'Numero'` (0.83), `'fiscal'` (0.93), `'(C'` (0.91).

### test2.pdf — Bordereau de situation (DGFP, taxes locales)
Qualité native élevée. Un seul détail non-sélectionnable : le bandeau Marianne/RF (logo, normal). Tout le reste du tableau de montants est bien natif (correction d'une première lecture erronée de ma part).

### test3-extrait.pdf — Facture Free Mobile
Texte natif globalement propre (accents intacts) MAIS **`€` systématiquement mappé sur `e`** dans la couche native elle-même (bug source, pas d'extraction). `symboles_corrompus()` : `{'e': 3}`, zéro faux positif sur 9 autres documents testés.

### test4.pdf — RIB Crédit Mutuel
Propre, deux petites images (logo + icône), rien de notable.

### test5.pdf — Export Excel (relevé locataire)
Pas d'image. **Pas** un cas de tableau sans bordure malgré les apparences (28 rects agissent comme lignes, `find_tables()` détecte 5 tables correctement). Découverte annexe : `"GéranLtoyer"` — un token natif unique où Excel a entrelacé deux cellules superposées ("Gérant"+"Loyer") **à la génération du PDF**, pas à l'extraction — bug différent et plus dur qu'un problème d'ordre de lecture.

### test6.pdf — ATTESTATION (export Google Docs)
Qualité parfaite (1.0), une image de signature (8.4% de couverture).

### test7-extrait-1 à 4.pdf — Contrat allemand (Gröner)
Fichier de référence pour l'OCR embarqué corrompu : substitution systématique l→t (`Vergteichsvereinbarung` pour `Vergleichsvereinbarung`). `embedded_ocr_detected` confirmé (image pleine page + texte natif). **Angle mort confirmé** : `native_text_quality` sur ces extraits = 0.83–0.97 (ne détecte RIEN), motive `mots_suspects_ngrammes()` — vrais positifs trouvés (`Abtauf`/Ablauf, `Famity`/Family, `Kötn`/Köln, `Civite`/Civile) mais ~50% de faux positifs sans dictionnaire réel. Décision : signal informationnel seulement (`pages_a_verifier()`), pas dans `recommend_ocr`.

### test8.pdf — Compte de copropriété (Cabinet Jourdan)
Scan complet (Canon, ~200dpi), texte natif garbled (`"3'!jôühDAN"`). **Vrai test Tesseract** : excellent sur prose/adresses/en-têtes de tableau (`RESIDENCE`, `ADMINISTRATEUR DE BIENS`, `01-CHARGES COMMUNES`, confiances 0.83–0.96) mais **PSM 3 par défaut rate systématiquement les montants chiffrés du tableau** (33 294,56 etc.) — confirmé visuellement lisibles dans le scan, pas un problème de qualité d'image. Corrigé par fusion PSM3+PSM6 (stratégie à deux passes) + filtre anti-bruit ciblé (les `|` de grille de tableau ont une confiance élevée malgré tout, jusqu'à 96% — la confiance seule ne suffit pas à les filtrer). Confiance OCR moyenne finale : 0.87.

### test9.pdf — Facture lituanienne (Centro Poliklinika)
Scan complet, 0 texte natif confirmé. **Vrai test Tesseract (modèle anglais sur lituanien)** : confiance moyenne 0.80, médiane 0.90 — bon dans l'ensemble. `€` correctement reconnu (glyphe réellement imprimé, contrairement à test3). Échecs concentrés sur les diacritiques lituaniens spécifiques (`Pirkėjas`→`"Pirkeéjas"` 0.45, `ĮSTAIGA`→`"[STAIGA"`) et une section "copie carbone" en plus petit. `pages_ocr_peu_fiable()` ne se déclenche pas ici (0.80 > seuil 0.5) — correct.

### test10.pdf — Note manuscrite (photo de téléphone, polonais)
Scan (photo, pas scanner à plat), 0 texte natif, manuscrit. **Vrai test Tesseract** : charabia total (`gohike`, `matevial`) mais confiance uniformément basse (moyenne 0.45, médiane 0.38) — échec propre, pas de fausse confiance. Exception : `"4635."` à 0.87 (chiffres isolés plus reconnaissables que la cursive, correspond au vrai montant manuscrit). A motivé `pages_ocr_peu_fiable()`, testé positif ici (0.45 < 0.5) — correct.

### test11-extrait.pdf — Livre Hegel (vieux scan/OCR)
Polices CID Type0C, texte natif déjà corrompu (`nOU8`=nous, `contesu`=conteste, `�` de remplacement). `native_text_quality` existant = 0.881, se déclenche déjà correctement (via `SUSPECT_PATTERN` sur le `�`, pas via les nouveaux ajouts). `mots_suspects_ngrammes` peu exploitable ici (199 mots, échantillon trop petit) — a servi de déclencheur pour `qualite_avec_confiance()`, validé sur des cas synthétiques inspirés de ce fichier (même caractère suspect isolé : 0.17 sur un titre court vs 0.99 sur une page normale).

### test.pdf — Papier IEEE 2 colonnes (arXiv)
Fichier de référence pour `reading_order.py`. Bug initial total (colonnes entrelacées) corrigé après plusieurs itérations : seuil de gouttière adaptatif (détection bimodale par saut, pas médiane simple), exclusion des lignes pleine largeur du calcul de colonnes, scission des lignes fusionnées par coïncidence de hauteur. Validé : 655/655 mots conservés, ordre colonne-majeur correct, note de bas de page (colonne gauche uniquement) placée correctement sans logique dédiée. **Texte pivoté** (filigrane arXiv) trouvé inversé via `pdfplumber.extract_words()` — mais `page.chars` brut (ordre du flux) est correct ; bug probablement spécifique à `pdfplumber`, jamais confirmé avec le vrai `pymupdf`.

### test-sans-bordures.pdf — Rapport NREL (économies carburant)
Pensé sans bordures, en fait 168 rects fins (0.48pt) agissant comme filets. `find_tables()` extrait correctement le tableau en entier, en-tête fusionné inclus. Pas un cas de perte.

### test-sans-bordures-2-extrait.pdf — RFC 9110 (IETF)
**Le vrai cas de tableau perdu.** Zéro verticale interne confirmée (recherche exhaustive), seulement des filets horizontaux segmentés aux bonnes frontières. `find_tables()` fusionnait Title/Reference/See en une seule colonne. Corrigé par `table_reconstruction.py` (points de rupture récurrents des segments horizontaux) : 10/10 lignes correctes, cellule wrappée bien fusionnée. Testé sans régression sur test-sans-bordures.pdf, test5.pdf, test2.pdf, test3.pdf.

---

## 2. Signaux de diagnostic construits (transverses, pas liés à un seul fichier)

| Signal | Fichier | Statut |
|---|---|---|
| `symboles_corrompus()` | `diagnostic_angle_mort.py` | Haute précision, prêt à intégrer |
| `mots_suspects_ngrammes()` | `diagnostic_angle_mort.py` | ~50% précision sans dictionnaire, informationnel seulement |
| `qualite_avec_confiance()` | `diagnostic_angle_mort.py` | Garde-fou taille d'échantillon, validé |
| `pages_a_verifier()` | `diagnostic.py` | Signale les candidats non corrigés automatiquement |
| `pages_ocr_peu_fiable()` | `resolve/confidence.py` | Confiance OCR moyenne par page, validé (test8/9/10) |
| `vector_text.py` | nouveau | Validé sur un vrai fichier complexe (test-impots-revenu) |
| `image_text_probe.py` | nouveau | Validé (logo réel + 2 icônes réelles) |
| `native_text_coverage` | proposé, pas encore intégré côté schéma | Calculé manuellement, à ajouter au `Diagnostic` |
| `diagnostic_categorie.py` (+ `natif_mixte`) | mis à jour | Testé sur les vraies valeurs |

---

## 3. Backends OCR — état des lieux

- **Mistral** : un seul appel API pour tout le document, bbox au niveau bloc seulement (pas de bbox par mot — limite structurelle pour un futur alignement géométrique).
- **Tesseract** : bbox réelle par mot (avantage structurel), mais PSM par défaut rate les tableaux denses (corrigé par fusion à deux passes). Testé uniquement avec le modèle anglais — **jamais testé avec de vrais paquets de langue** (fra/deu/lit).

---

## 4. Tests manquants / à compléter

### A. Déjà commencés, jamais finis avec les vrais outils
- **Tesseract avec les vrais paquets de langue** (`tesseract-ocr-fra`, `-deu`, `-lit`) — tous les résultats de langue de cette session utilisent le modèle anglais par défaut.
- **Texte pivoté avec le vrai `pymupdf`** — bug trouvé côté `pdfplumber` uniquement, jamais confirmé/infirmé avec PyMuPDF.
- **`reading_order.py` avec le vrai `pymupdf`** — construit et validé uniquement via `pdfplumber` en substitut.
- **Décision sur test7** (dictionnaire réel vs seuil assoupli pour `mots_suspects_ngrammes`) — jamais tranchée.

### B. Jamais testés du tout (pas de fichier, ou fichier jamais essayé)
- **Texte non-latin dense** (CJK, cyrillique) — le lituanien testé reste en alphabet latin avec diacritiques, pas un vrai test non-latin. Toujours en attente de ton fichier.
- **Tableau qui continue sur 2 pages** (rupture au milieu d'un tableau).
- **PDF chiffré/protégé par mot de passe** — comportement de l'extraction non vérifié.
- **Formulaire AcroForm** (champs remplissables).
- **Page pivotée/paysage insérée dans un document portrait** (différent du texte pivoté — ici c'est la page entière).
- **Document multi-langues** (plusieurs langues dans un même PDF).
- **Pages mixtes dans un même PDF** (certaines natives propres, certaines scannées — jamais testé en conditions réelles, seulement en synthétique).
- **`image_quality`** — toujours `None`, jamais implémenté (flou, contraste, inclinaison).
- **Document très volumineux** (performance/mémoire sur des centaines de pages).
- **PDF/A archivistique**.

### C. Volontairement mis de côté (scope trop large, pas de recentrage)
Structure logique (hiérarchie de titres), score de qualité de tableau au-delà de la détection binaire, association image/légende, déduplication en-têtes/pieds de page, cohérence de métadonnées — chacun serait un chantier à part entière, pas repris pour l'instant.

### D. Ouvert par cette session, pas encore construit
- Fonction réutilisable **crop + OCR ciblé + insertion texte invisible** pour les zones vectorisées (validé manuellement une fois, pas encore encapsulé en fonction).
- Distinction `recommend_ocr` (page entière) vs `zones_a_extraire` (ciblé) — proposée, pas implémentée.
- Câblage réel de `image_text_probe.py` côté extraction (pixels disponibles à ce moment, pas en diagnostic).

### E. Signaux ajoutés de ton côté, jamais vérifiés ensemble
Visibles dans ta sortie terminal mais dont je ne connais pas la logique de calcul — à documenter/tester quand on y reviendra :
- **"Densité textuelle anormalement basse"** (déclenché sur les pages 2 et 3 de test-impots-revenu, celles avec le plus de tableaux chiffrés) — risque à vérifier : confond-elle "peu de prose" avec "page suspecte" ?
- **"Images basse résolution"** — recoupe potentiellement `visual_integrity.images_basse_resolution()` qu'on a déjà, ou une implémentation séparée de ton côté ?
- **"Chevauchement de texte"**, **"Coordonnées hors-limites"**, **"Chiffré"** — jamais construits de mon côté, logique et fiabilité inconnues.
