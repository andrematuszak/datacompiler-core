# ROADMAP — Priorités du projet

## 🚨 URGENT

### 1. Améliorer le rendu sur `rebuilt`
- Travailler la qualité du rendu du PDF reconstruit (`rebuilt_pdf.py`).
- Vérifier la fidélité visuelle et la cohérence du flux par rapport au document source.

### 2. Refaire ce ROADMAP.md
- Intégrer les nouveaux changements et refléter les priorités actuelles du projet.
- (Ce point est la tâche en cours — le document est mis à jour.)

### 3. Débogage : images non extraites
- Comprendre pourquoi certaines images ne sont pas extraites du PDF source.
- Isoler le cas (images encodées, formats, surfaces, etc.) et corriger l'extraction.

### 4. Diagnostic texte-dans-image + raffinement
- **Objectif :** "Liberté Égalité Fraternité" dans `test-impots-revenu.pdf` doit être détecté.
- Développer le diagnostic texte-dans-image (`image_text_probe.py`).
- Raffiner le diagnostic selon les résultats des tests.
- Étendre aux autres outils de diagnostic.
- Enchaîner sur la **reconnaissance OCR des images** une fois le diagnostic stable.

### 5. Comparaison d'OCR + merge
- Comparer les moteurs OCR entre eux (Tesseract, PaddleOCR, Mistral).
- Utiliser la fonction `merge.py` pour une correction croisée des résultats.
- Bénéfice direct pour l'article (section "comparaison" d'OCR).

### 6. Outil de niveau de confiance
- Développer l'outil de niveau de confiance (`confidence.py`).
- Réfléchir et implémenter l'UI associée pour présenter ce niveau à l'utilisateur.

### 7. Détection de tableaux
- Développer et consolider la détection de tableaux (`table_reconstruction.py`).

### 8. Axe JSON central
- Définir le **format entrant** et le **format sortant** du JSON.
- Organiser la structure du JSON.
- Intégrer le **diagnostic** dans le JSON.
- Définir la structure globale de l'axe JSON central.

---

## ✏️ TYPO

### 1. Refaire les `__init__.py`
- Nettoyer et harmoniser les fichiers `__init__.py` de tous les modules.

### 2. Zones "ombragées" inutilisées
- Regarder toutes les zones ombragées dans tous les fichiers et voir comment les utiliser :
  - `Polygon` dans `document.py`
  - `List` dans `mistral.py`
- (Ex-zone "P3" de l'ancien roadmap, remontée en priorité.)

### 3. Confidentialité des fonctions
- Ajouter un `_` devant les fonctions devant rester privées.
- Normaliser la visibilité des méthodes à travers le code.

---

## 🛡️ Garde-fous & points de vigilance (à ne pas perdre)

### Garde-fou Mistral / confidentialité client
- **Priorité haute** (risque asymétrique) : empêcher tout appel Mistral accidentel sur un document client réel.
- Test : vérifier qu'aucune requête réseau sortante n'est faite quand `MISTRAL_API_KEY` n'est pas définie.
- Ajouter un flag `--local-only` qui lève une erreur plutôt que basculer silencieusement sur Mistral si la clé traîne dans l'environnement.
- *Contexte : traduction pharma/médical/juridique — une fuite serait un vrai problème professionnel, pas un bug.*

### Test de non-régression (comptage) — à écrire
- Ouvrir `test-impots-revenu_propre.pdf`, extraire le texte (pdfplumber/PyMuPDF),
- Vérifier que le nombre de mots extraits du PDF de sortie == `len(page.resolved.words)`.
- Généraliser ensuite : check systématique "nb de mots dans `resolved.words`" vs "nb de mots extractibles du PDF rendu" sur tout le corpus.

### Test de séquence (suite logique)
- Le test de comptage ne détecte pas les bugs d'**ordre**.
- Comparer l'ordre relatif de mots-repères connus (ex. "CTIOI/DIRECTION" avant "particulier").
- À écrire une fois le comportement d'ordre stabilisé.

### Limite connue — `page.rotation`
- `render_zone_image` clippe en coordonnées brutes sans tenir compte de la rotation.
- Pas urgent tant qu'aucun fichier du corpus ne présente ce cas, mais à garder visible.

### Layout & reading order (`_colonnes_depuis_fragments`)
- Dernier bug de correction confirmé. À traiter en priorité car il fausse tous les tests suivants.
- À revérifier avec le script de diagnostic (affichage `colonne=X y0=Y "texte"`) avant toute modification.

---

## 📈 Pistes & observations (contexte)

### Perf OCR (Windows vs Mac)
- Piste : `ocralliser_zone` appelée une fois par zone, chaque appel spawn un sous-processus Tesseract.
- La création de processus est structurellement plus lente sur Windows (pas de fork) — peut expliquer un facteur x5.
- Avant d'investir dans un GPU : mesurer le nombre d'appels `ocralliser_zone` et le temps par appel isolément.
- Solution possible si confirmé : regrouper plusieurs zones en un seul appel Tesseract (image composite).

### Taille des PDF (232 Ko → 130 Ko)
- Les vecteurs ne sont pas le coupable (ils appartiennent au PDF source).
- Le surpoids vient probablement : (1) du contenu du flux de page pour chaque objet texte invisible inséré, (2) du sous-ensemble de police DejaVu Sans embarqué.
- Tester isolément : rendre un PDF avec la couche invisible désactivée, comparer la taille.

### Architecture backend
- Refactoriser `backend/__init__.py` seulement après l'intégration d'un deuxième moteur OCR réel (éviter la sur-ingénierie sur hypothèse).