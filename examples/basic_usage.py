# examples/basic_usage.py
from datacleaner.core.document import Document
from datacleaner.core.extract import extraire
from datacleaner.renderers.faithful_pdf import reconstruire_pdf_direct

def main():
    pdf_entree = "tests/fixtures/test1.pdf"
    pdf_sortie = "output_demo.pdf"
    
    print(f"1. Extraction de {pdf_entree}...")
    donnees_brutes = extraire(pdf_entree)
    
    print("2. Création de l'objet Document...")
    doc = Document(donnees_brutes)
    
    print("3. Reconstruction du PDF...")
    reconstruire_pdf_direct(doc, pdf_sortie)
    
    print(f"✅ Terminé ! PDF généré dans : {pdf_sortie}")

if __name__ == "__main__":
    main()