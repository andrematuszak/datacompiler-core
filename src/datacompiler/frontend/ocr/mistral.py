"""mistral.py — Backend OCR utilisant l'API de Mistral AI.

Remplit page.ocr.words (PAS page.ocr.blocks) à partir du markdown renvoyé
par l'API, tokenisé BRUTEMENT (split sur les espaces, syntaxe markdown
comprise dans les tokens : "|", "---", "^{14}", "..."). Choix volontaire
pour une première version qui marche -- alignment.py fera un diff plus
bruyant sur les tableaux qu'avec du texte nettoyé, mais c'est un problème
à mesurer avant de le résoudre, pas à anticiper. Cf. discussion : si le
diff s'avère trop perturbé par la syntaxe markdown (le tableau RÉSIDENCE
en particulier), nettoyer/normaliser avant tokenisation sera la suite
logique.

Mistral ne fournit ni bbox ni confiance par mot dans ce mode d'appel --
bbox=None (cf. alignment.py, qui n'aligne que par séquence de texte pour
cette raison) et confidence=None (confidence.confiance_ocr() applique
0.5 par défaut dans ce cas, pas de traitement spécial nécessaire ici).
"""

import base64
import os

from datacompiler.model.document import Document, Word
from datacompiler.frontend.ocr.base import OcrBackend

MODELE_OCR = "mistral-ocr-latest"


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

        # Import différé : mistralai est une dépendance optionnelle (comme
        # pytesseract pour TesseractBackend) -- ne doit pas empêcher le
        # reste du package de s'importer si absent.
        from mistralai import Mistral

        client = Mistral(api_key=api_key)

        # PDF local encodé en base64 -- alternative à l'upload+URL signée
        # (client.files.upload puis get_signed_url), plus simple pour un
        # fichier local unique, au prix de charger tout le PDF en mémoire.
        # À revoir si des documents volumineux posent problème (max 50 Mo
        # côté API de toute façon).
        with open(pdf_path, "rb") as f:
            pdf_base64 = base64.b64encode(f.read()).decode("utf-8")

        # L'API Mistral OCRise le PDF ENTIER en un seul appel par défaut.
        # NOTE (découvert en documentant ce module) : l'API accepte en
        # réalité un paramètre `pages` (liste d'index 0-based ou plage,
        # ex. "0,1,2") -- contrairement à ce que suggérait l'ancien
        # commentaire ici. Pas exploité pour l'instant (économie de coût
        # potentielle si on ne veut OCRiser qu'une partie du document),
        # `pages` reste donc indicatif comme pour les autres backends
        # partagés, à activer plus tard si besoin.
        response = client.ocr.process(
            model=MODELE_OCR,
            document={
                "type": "document_url",
                "document_url": f"data:application/pdf;base64,{pdf_base64}",
            },
        )

        for page_result in response.pages:
            idx = page_result.index  # 0-based, cf. JSON de test (pages[i].index)
            if idx >= len(doc.pages):
                continue  # sécurité : Mistral ne devrait jamais renvoyer plus de pages que le Document

            page_obj = doc.pages[idx]
            # ⚠️ page_obj.number est 1-INDEXÉ (cf. extract/__init__.py,
            # page_number=idx+1) alors que `pages` ici, si fourni, suivrait
            # plutôt la convention 0-indexée de l'API Mistral -- incohérence
            # dormante tant que personne ne passe `pages` pour ce backend
            # (jamais le cas actuellement dans pipeline.py). À corriger si
            # ce paramètre est un jour réellement utilisé pour Mistral.
            if pages is not None and page_obj.number not in pages:
                continue

            markdown = page_result.markdown or ""
            tokens = markdown.split()

            mots = [
                Word(
                    id=-1,  # renumérotation finale par compile/compiler.py
                    text=tok,
                    resolved_text=tok,
                    bbox=None,  # Mistral ne fournit pas de bbox par mot
                    confidence=None,  # confidence.confiance_ocr() -> 0.5 par défaut
                    source="ocr",
                )
                for tok in tokens
            ]

            page_obj.ocr.engine = f"mistral-{MODELE_OCR}"
            page_obj.ocr.words = mots  # ré-appel idempotent : remplace, n'accumule pas

        return doc
