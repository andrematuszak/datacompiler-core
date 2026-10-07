"""Exemple d'utilisation de DataCompiler.

Lancer depuis la racine du dépôt :
    python examples/basic_usage.py
"""
from pathlib import Path

from datacompiler.pipeline import executer_pipeline

PDF_SOURCE = Path("tests/fixtures/impots-revenu/impots-revenu.pdf")

if not PDF_SOURCE.exists():
    raise SystemExit(f"❌ Fichier introuvable : {PDF_SOURCE} (lancez le script depuis la racine du dépôt)")

print(f"🚀 Traitement de {PDF_SOURCE}...")

# Un appel = un format de sortie (choisi par `strategy`).
# La sortie est écrite à côté du PDF source : ..._propre.pdf
doc = executer_pipeline(str(PDF_SOURCE), strategy="overlay")

print(f"✅ Terminé : {len(doc.pages)} page(s) traitée(s).")
print(f"   Sortie : {PDF_SOURCE.with_name(PDF_SOURCE.stem + '_propre.pdf')}")
