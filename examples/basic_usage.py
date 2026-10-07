"""Exemple d'utilisation de DataCompiler.

Depuis la racine du dépôt :

    python examples/basic_usage.py                 # génère un PDF d'exemple puis le traite
    python examples/basic_usage.py mon_fichier.pdf # traite votre propre PDF

Les fichiers de sortie sont écrits à côté du PDF source (ex. mon_fichier_propre.pdf).
"""
import sys
from pathlib import Path

DOSSIER_DEMO = Path("output")


def creer_pdf_exemple(destination: Path) -> Path:
    """Crée un petit PDF d'exemple (texte natif, aucune donnée personnelle)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    destination.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(destination), pagesize=A4)
    _, hauteur = A4

    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, hauteur - 90, "DataCompiler - document d'exemple")

    c.setFont("Helvetica", 11)
    lignes = [
        "Ce document est généré automatiquement pour tester le pipeline.",
        "Il contient du texte natif sur plusieurs lignes et un petit tableau.",
        "",
        "Référence : EX-0001        Date : 01/01/2026        Montant : 123,45 EUR",
    ]
    y = hauteur - 130
    for ligne in lignes:
        c.drawString(72, y, ligne)
        y -= 18

    # Petit tableau
    y -= 10
    for i, (a, b) in enumerate([("Désignation", "Montant"), ("Article A", "10,00"), ("Article B", "20,50")]):
        c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 11)
        c.drawString(72, y, a)
        c.drawRightString(300, y, b)
        c.line(72, y - 4, 300, y - 4)
        y -= 20

    c.showPage()
    c.save()
    return destination


def main() -> None:
    from datacompiler.pipeline import executer_pipeline

    if len(sys.argv) > 1:
        pdf_source = Path(sys.argv[1])
        if not pdf_source.exists():
            raise SystemExit(f"❌ Fichier introuvable : {pdf_source}")
    else:
        pdf_source = creer_pdf_exemple(DOSSIER_DEMO / "exemple.pdf")
        print(f"📄 PDF d'exemple généré : {pdf_source}")

    print(f"🚀 Traitement de {pdf_source}...")
    # Un appel = un format de sortie (choisi par `strategy`).
    doc = executer_pipeline(str(pdf_source), strategy="overlay")

    sortie = pdf_source.with_name(pdf_source.stem + "_propre.pdf")
    print(f"✅ Terminé : {len(doc.pages)} page(s) traitée(s).")
    print(f"   Sortie : {sortie}")


if __name__ == "__main__":
    main()
