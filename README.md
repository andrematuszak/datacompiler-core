# 📊 DataCompiler

**DataCompiler** est un pipeline complet de compilation, de traitement et de reconstruction de documents PDF. Il combine une extraction multi-moteurs, un diagnostic de la qualité native du texte, des étapes d'OCR intelligentes (globales ou ciblées) ainsi qu'un moteur d'arbitrage et de rendu dynamique multi-format.

🌐 **Site web officiel :** [https://datacompiler.org](https://datacompiler.org) *(en cours de construction)*

---

## ⚠️ PRÉREQUIS IMPORTANT : Version de Python
 
> **Important :** Le moteur OCR **PaddleOCR** / **PaddlePaddle** n'est pas encore compatible de manière stable avec Python 3.12+.
> Veuillez utiliser **Python 3.10** ou **Python 3.11** pour installer et exécuter DataCompiler.

---

### Installation du package Python

#### 1. Création de l'environnement virtuel (Python 3.10 ou 3.11)

**Sur macOS :**
```bash
python3.11 -m venv .venv
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

---

## 🚀 Quickstart (Démarrage Rapide)

Voici l'utilisation la plus courante pour traiter un PDF, exécuter le diagnostic / OCR et générer un PDF nettoyé ainsi qu'un fichier Markdown :

```python
import os
from datacompiler.pipeline import run_pipeline

# (Optionnel) Définir la clé API Mistral pour l'OCR de haut niveau sur documents scannés
os.environ["MISTRAL_API_KEY"] = "votre_cle_api_mistral"

# Chemin vers votre fichier PDF source
pdf_path = "examples/test-impots-revenu.pdf"

# Exécution du pipeline complet
document = run_pipeline(
    pdf_path=pdf_path,
    output_dir="output/",
    export_formats=["pdf_faithful", "pdf_flow", "markdown", "docx"]
)

print(f"Document traité avec succès ! Nombre de pages : {len(document.pages)}")
```

---

## ⚙️ Architecture & Pipeline de Fonctionnement

Le pipeline se déroule en **6 étapes séquentielles** :

```
📄 PDF Source ➔ [1. Extraction] ➔ [2. Diagnostic] ➔ [3. OCR Global] ➔ [4. OCR Ciblé] ➔ [5. Arbitrage] ➔ [6. Rendu] ➔ 📁 Fichiers Sortie
```

### 🔍 1. Extraction (`frontend/extract`)
Ouverture parallèle du PDF via **PyMuPDF** et **pdfplumber**. Extraction native du texte, des polices, des images, des éléments vectoriels et reconstruction des tableaux dans le modèle standardisé `Document`.

### 🩺 2. Diagnostic (`frontend/diagnostic`)
Analyse de l'intégrité du texte nativement extrait (score de qualité, symboles corrompus, couverture visuelle, détection de texte vectorisé/dessiné). Décide automatiquement si un OCR est nécessaire (`recommend_ocr = True`).

### 🤖 3. OCR Page Entière (`frontend/ocr`)
Si recommandé par le diagnostic et qu'une clé API Mistral est renseignée, appel au backend **Mistral OCR** pour numériser l'intégralité de la page.

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

Après passage dans le pipeline, les fichiers suivants peuvent être produits dans le dossier de destination :

* `*_propre.pdf` *(Overlay fidèle avec couche texte propre)*
* `*_flow.pdf` *(PDF reflowable / réordonné)*
* `*_rebuilt.pdf` *(PDF entièrement reconstruit)*
* `*_propre.md` *(Document Markdown enrichi)*
* `*_propre.html` *(Export HTML structuré)*
* `*_propre.docx` *(Document Word modifiable)*
* `.document.json` *(Arbre de données et métadonnées complètes)*

---

## 🧪 Tests

Pour exécuter la suite de tests :

```bash
pytest
```

---

## 📜 Licence

Projet sous licence propriétaire / tous droits réservés.