# 🧹 DataCompiler

**DataCompiler** est un package Python modulaire conçu pour l'extraction, le diagnostic, la résolution et la reconstruction fidèle géométrique de documents PDF.

---

## 🚀 Structure du projet

L'architecture repose sur un *src-layout* moderne et modulaire :

```text
datacompiler/
├── src/
│   └── datacompiler/
│       ├── frontend/       # Extraction, OCR (Mistral/Tesseract), Diagnostic
│       ├── compile/        # Arbitrage native/OCR, résolution
│       ├── backend/        # Moteurs de rendu (PDF fidèle, DOCX, HTML, etc.)
│       ├── model/          # Modèles de données (Document, Word, BBox...)
│       └── pipeline.py     # Orchestrateur principal
├── tests/                  # Tests unitaires et fixtures (pytest)
├── pyproject.toml          # Configuration du package
└── requirements.txt        # Dépendances du projet

---

## ⚙️ Installation

1. Active ton environnement virtuel Python (Python >= 3.11 recommandé) :
   ```bash
   source venv/bin/activate
   ```

2. Installe le package en mode éditable :
   ```bash
   pip install -e .
   ```

---

## 🛠️ Utilisation

### 1. Via la commande CLI
Une fois le package installé en mode éditable, tu peux exécuter directement la commande `datacleaner` dans ton terminal :

```bash
datacleaner tests/fixtures/test1.pdf
```

### 2. Directement via l'orchestrateur Python
```bash
python src/datacleaner/pipeline.py tests/fixtures/test1.pdf
```

### 3. Utilisation en tant que bibliothèque
```python
from datacleaner.core.extract import extraire
from datacleaner.core.document import Document
from datacleaner.renderers.faithful_pdf import render_faithful_pdf

# 1. Extraction
donnees = extraire("chemin/vers/document.pdf")

# 2. Modélisation
doc = Document(donnees)

# 3. Reconstruction du PDF
render_faithful_pdf(doc, "sortie_propre.pdf")
```

---

## 🧪 Lancer les tests

Pour exécuter l'ensemble des tests automatisés avec `pytest` :

```bash
pytest
```