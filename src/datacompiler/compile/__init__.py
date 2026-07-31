"""compile/ — Arbitrage natif/OCR (cf. compiler.py pour le détail des
étapes). Façade fine pour garder `from compile import resoudre` stable
indépendamment de l'organisation interne du package."""


from .compiler import resoudre