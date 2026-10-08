# Changelog

Toutes les modifications notables apportées au projet **DataCompiler** seront consignées dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/) et ce projet respecte le [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-07

### ✨ Added (Fonctionnalités initiales)
- **Pipeline de compilation PDF en 6 étapes** :
  1. **Extraction** hybride parallèle (PyMuPDF + pdfplumber).
  2. **Diagnostic** automatique de la qualité du texte et de l'intégrité visuelle.
  3. **OCR Page entière** (intégration de l'API Mistral — désactivé dans le flux actif, voir « Limitations connues »).
  4. **OCR Ciblé** pour zones vectorisées avec PaddleOCR.
  5. **Arbitrage & Compilation** (reconstruction de la mise en page et résolution des conflits).
  6. **Moteurs de rendu** multi-formats (PDF Fidèle, Flow, Reconstruit, Markdown, HTML, DOCX).
- **Interface CLI** : Commande `datacompiler` disponible en ligne de commande.
- **Documentation et Exemples** : Guide d'installation (macOS / Windows), Quickstart (CLI et Python) dans le `README.md` et script `examples/basic_usage.py`.

### ⚠️ Limitations connues
- L'OCR pleine page (Mistral) est désactivé : l'alignement global OCR ↔ natif n'est pas encore validé.
- L'option CLI `--format` est acceptée mais ignorée ; utiliser `--strategy`.
- Un seul format de sortie par exécution ; les fichiers sont écrits à côté du PDF source.

### 🔧 Added
- `examples/basic_usage.py` : génère un PDF d'exemple (ou accepte un chemin en argument) au lieu de dépendre d'un document de test.
- Tests dépendant du PDF de référence : ignorés (skip) si le fichier est absent.
- Polices embarquées : suppression des variantes `.woff`/`.woff2` et des polices Marianne, non utilisées par le code ; ajout de `backend/fonts/README.md` (licences).
- `.gitignore` : sorties générées, caches d'outils et dossier `private/`.
- Python requis : 3.11+ (testé en 3.12).
- `pytest` déplacé des dépendances obligatoires vers l'extra `[dev]`.

[0.1.0]: https://github.com/andrematuszak/datacompiler/releases/tag/v0.1.0
