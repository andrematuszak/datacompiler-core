# 📊 DataCompiler

**DataCompiler** est un pipeline complet de compilation, de traitement et de reconstruction de documents PDF. Il combine une extraction multi-moteurs, un diagnostic de la qualité native du texte, des étapes d'OCR intelligentes (globales ou ciblées) ainsi qu'un moteur d'arbitrage et de rendu dynamique multi-format.

🌐 **Site web officiel :** [https://datacompiler.org](https://datacompiler.org) *(en cours de construction)*

---

## ⚠️ Prérequis : version de Python

DataCompiler requiert **Python 3.11 ou supérieur** (testé en **Python 3.12**, macOS).
PaddleOCR / PaddlePaddle sont installés automatiquement comme dépendances ; le premier
lancement de l'OCR ciblé peut télécharger les modèles Paddle (connexion Internet requise).

---

### Installation du package Python

#### 1. Création de l'environnement virtuel (Python 3.11+)

**Sur macOS :**
```bash
python3.12 -m venv .venv   # ou python3.11
source .venv/bin/activate
```

**Sur Windows (PowerShell) :**
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### 2. Installation de DataCompiler

```bash
pip install --upgrade pip
pip install -e .
```

#### 3. Vérifier l'installation

```bash
python --version        # Python 3.11+ attendu
datacompiler --help
pip install -e ".[dev]" # outils de développement (pytest, ruff, black, mypy)
pytest
```

---

## 🚀 Quickstart (Démarrage Rapide)

### En ligne de commande

```bash
datacompiler tests/fixtures/impots-revenu/impots-revenu.pdf --strategy overlay
```

Les fichiers de sortie sont écrits **à côté du PDF source** (voir « Formats de sortie »).

> **Note v0.1.0 :** le format de sortie est choisi par `--strategy` (`overlay`, `clean_overlay`,
> `rasterized`, `flow`, `rebuilt`, `markdown`, `html`, `docx`). L'option `--format` est
> actuellement acceptée mais **n'est pas prise en compte**.

### En Python

```python
from datacompiler.pipeline import executer_pipeline

# Un appel = un format de sortie, choisi par `strategy`
doc = executer_pipeline(
    "tests/fixtures/impots-revenu/impots-revenu.pdf",
    strategy="overlay",      # overlay | clean_overlay | rasterized | flow | rebuilt | markdown | html | docx
    ocr_mode="auto",         # auto | force | skip | vector
)

print(f"Document traité avec succès ! Nombre de pages : {len(doc.pages)}")
```

Pour produire plusieurs formats, appelez `executer_pipeline` une fois par `strategy`.
Un exemple exécutable est fourni dans [`examples/basic_usage.py`](examples/basic_usage.py).

---

## ⚙️ Architecture & Pipeline de Fonctionnement

Le pipeline se déroule en **6 étapes** (les logs affichent `[1/6]` … `[6/6]`) :

```
📄 PDF Source ➔ [1. Extraction] ➔ [2. Diagnostic] ➔ [3. OCR Global] ➔ [4. OCR Ciblé] ➔ [5. Arbitrage] ➔ [6. Rendu] ➔ 📁 Fichiers Sortie
```

### 🔍 1. Extraction (`frontend/extract`)
Ouverture parallèle du PDF via **PyMuPDF** et **pdfplumber**. Extraction native du texte, des polices, des images, des éléments vectoriels et reconstruction des tableaux dans le modèle standardisé `Document`.

### 🩺 2. Diagnostic (`frontend/diagnostic`)
Analyse de l'intégrité du texte nativement extrait (score de qualité, symboles corrompus, couverture visuelle, détection de texte vectorisé/dessiné). Décide automatiquement si un OCR est nécessaire (`recommend_ocr = True`).

### 🤖 3. OCR Page Entière (`frontend/ocr`)
Backend **Mistral OCR** (clé `MISTRAL_API_KEY`). ⚠️ **Désactivé dans le flux actif en v0.1.0** :
l'alignement global OCR ↔ texte natif n'est pas encore validé sans régression (duplication de mots).
Seul l'OCR ciblé (étape 4) est actif.

### 🎯 4. OCR Ciblé — Zones Vectorisées (`frontend/ocr/vector_zones`)
Cible spécifiquement les zones de texte vectorisées ou masquées et comble les trous géométriques à l'aide de **PaddleOCR**.

### ⚙️ 5. Compilation & Arbitrage (`compile/`)
* Reconstitution de l'ordre de lecture et de l'arbre de mise en page (`LayoutBox`).
* Normalisation typographique (ligatures, césures).
* Alignement géométrique natif ↔ OCR.
* Résolution des conflits et évaluation de confiance QA.

### 📦 6. Backend de Rendu (`backend/`)
Génération des fichiers de sortie nettoyés dans les formats demandés.

---

## 📁 Formats de Sortie Générés

Un fichier par exécution, selon `--strategy`, écrit à côté du PDF source :

| `--strategy` | Fichier produit |
|---|---|
| `overlay`, `clean_overlay`, `rasterized` | `<nom>_propre.pdf` |
| `flow` | `<nom>_flow.pdf` |
| `rebuilt` | `<nom>_rebuilt.pdf` |
| `markdown` | `<nom>_propre.md` |
| `html` | `<nom>_propre.html` |
| `docx` | `<nom>_propre.docx` |

Sauf avec `--no-json`, un `<nom>.document.json` (arbre de données et métadonnées) est aussi écrit.

---

## 🧪 Tests

Pour exécuter la suite de tests :

```bash
pip install -e ".[dev]"
pytest
```

`tests/test_regression_word_count.py` est ignoré (skip) tant que les sorties de `impots-revenu.pdf` n'ont pas été générées : lancez d'abord la commande du Quickstart.

---

## 📜 Licence

Projet sous licence propriétaire — tous droits réservés. Voir le fichier [LICENSE](LICENSE).
