"""mistral.py — Backend OCR utilisant l'API de Mistral AI.

Ce module remplace l'ancien ocr.py et s'intègre directement dans 
l'architecture commune des backends via OcrBackend.
"""

import os

from datacompiler.model.document import Document
from datacompiler.frontend.ocr.base import OcrBackend


class MistralBackend(OcrBackend):
    name = "mistral"

    def __init__(self, api_key: str = None):
        # Récupère la clé passée en paramètre OU cherche dans l'environnement
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY")

    def ocraliser(self, doc: Document, pdf_path: str, pages: list = None, **kwargs) -> Document:
        # 1. Vérification de la clé API
        api_key = kwargs.get("api_key") or self.api_key
        
        if not api_key:
            raise ValueError(
                "Clé API Mistral manquante ! "
                "Veuillez définir la variable d'environnement MISTRAL_API_KEY "
                "ou la passer explicitement lors de l'instanciation."
            )

        # L'API Mistral OCRise le PDF ENTIER en un seul appel -- pas de
        # sélection de pages possible côté API. `pages` n'est donc PAS un
        # vrai filtre ici : soit on appelle l'API, soit on ne l'appelle pas.
        
        # 2. TODO : Insérez ici la logique d'appel à l'API Mistral.
        # (L'ancien code qui se trouvait dans ocr.py doit être placé ou appelé ici).
        # Exemple pseudo-code :
        #
        # client = Mistral(api_key=api_key)
        # response = client.ocr.process(document=pdf_path)
        # 
        # Pour chaque page de la réponse :
        #   doc.pages[i].ocr.words = ... (remplir avec les résultats de Mistral)
        #   doc.pages[i].ocr.engine = "mistral"

        return doc
