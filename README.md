# 🧹 DataCompiler

**DataCompiler** est un package Python modulaire conçu pour l'extraction, le diagnostic, la résolution et la reconstruction fidèle géométrique de documents PDF.

---

## 🚀 Structure du projet

L'architecture repose sur un *src-layout* moderne et modulaire :

```text
datacompiler/
├── src/
│   └── datacompiler/
│       ├── frontend/       # Extraction, OCR (PaddleOCR/Mistral), Diagnostic
│       ├── compile/        # Arbitrage native/OCR, résolution
│       ├── backend/        # Moteurs de rendu (PDF fidèle, DOCX, HTML, etc.)
│       ├── model/          # Modèles de données (Document, Word, BBox...)
│       └── pipeline.py     # Orchestrateur principal
├── tests/                  # Tests unitaires et fixtures (pytest)
├── pyproject.toml          # Configuration du package
└── requirements.txt        # Dépendances du projet

---

## ⚙️ Installation

1. Crée et active un environnement virtuel Python (Python >= 3.11 requis) :
   ```bash
   py -3.11 -m venv .venv
   # Windows PowerShell
   .venv\Scripts\Activate.ps1
   ```

2. Installe le package et les outils de développement en mode éditable :
   ```bash
   python -m pip install -e ".[dev]"
   ```

---

## 🛠️ Utilisation

### 1. Via la commande CLI
Une fois le package installé en mode éditable, tu peux exécuter directement la commande `datacompiler` dans ton terminal :

```bash
datacompiler chemin/vers/document.pdf
```

### 2. Utilisation en tant que bibliothèque
```python
from datacompiler import executer_pipeline

# Extrait et compile le PDF, écrit le PDF reconstruit.
document = executer_pipeline("chemin/vers/document.pdf", strategy="rebuilt")
print(f"Pages traitées : {len(document.pages)}")
```

---

## 🧪 Lancer les tests

Pour exécuter l'ensemble des tests automatisés avec `pytest` :

```bash
python -m pytest
```

Pour établir une première mesure de couverture :

```bash
python -m pytest --cov=datacompiler --cov-report=term-missing
```

Le champ `ImageElement.contains_text` reste à `null` (inconnu) pour les images
bitmap : la sonde OCR d'images basée sur Tesseract a été retirée. Il n'est pas
converti en `false`, afin de ne pas présenter une absence d'analyse comme un
résultat négatif.
