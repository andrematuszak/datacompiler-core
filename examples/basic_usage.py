from pathlib import Path
from datacompiler.pipeline import traiter_document

# Exemple d'utilisation du pipeline DataCompiler
pdf_source = Path("tests/fixtures/impots-revenu/impots-revenu.pdf")

if pdf_source.exists():
    print(f"🚀 Traitement de {pdf_source}...")
    
    # Exécution du pipeline complet
    doc = traiter_document(
        pdf_path=str(pdf_source),
        output_format="faithful_pdf",
        output_path="sortie_propre.pdf"
    )
    
    print("✅ Traitement terminé ! Fichier généré : sortie_propre.pdf")
else:
    print(f"❌ Fichier introuvable : {pdf_source}")