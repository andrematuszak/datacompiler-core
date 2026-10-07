# Changelog

Toutes les modifications notables apportées au projet **DataCompiler** seront consignées dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/) et ce projet respecte le [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-06

### ✨ Added (Fonctionnalités initiales)
- **Pipeline de compilation PDF en 6 étapes** :
  1. **Extraction** hybride parallèle (PyMuPDF + pdfplumber).
  2. **Diagnostic** automatique de la qualité du texte et de l'intégrité visuelle.
  3. **OCR Page entière** (intégration de l'API Mistral).
  4. **OCR Ciblé** pour zones vectorisées avec PaddleOCR.
  5. **Arbitrage & Compilation** (reconstruction de la mise en page et résolution des conflits).
  6. **Moteurs de rendu** multi-formats (PDF Fidèle, Flow, Reconstruit, Markdown, HTML, DOCX).
- **Interface CLI** : Commande `datacompiler` disponible en ligne de commande.
- **Documentation et Exemples** : Guide d'installation (macOS / Windows), Quickstart dans le `README.md` et script `examples/basic_usage.py`.