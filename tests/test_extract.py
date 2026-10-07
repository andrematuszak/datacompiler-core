from datacompiler import Document
from datacompiler.frontend.extract import extraire

def test_extraction_pdf(sample_pdf):
    """Teste l'extraction à partir du fichier PDF partagé."""
    doc = Document()
    extraire(doc, str(sample_pdf))
    
    assert len(doc.pages) > 0
    page = doc.pages[0]
    
    # Vérifie que des mots natifs ont bien été extraits de la première page
    assert len(page.native.words) > 0
    
    # Reconstitution du texte à partir des mots
    texte_page = " ".join(w.text for w in page.native.words)
    assert texte_page != ""
