from datacompiler.frontend.diagnostic import diagnostiquer

def test_diagnostic_qualite_texte(sample_document):
    """Teste la fonction de diagnostic en utilisant le document partagé."""
    diagnostiquer(sample_document)
    
    # Le diagnostic est attaché au document
    diag = sample_document.diagnostic
    
    assert diag is not None
    assert diag.confiance_suffisante is True
    assert diag.native_text_quality > 0.8
