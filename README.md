# 🧹 DataCompiler

**DataCompiler** est un package Python modulaire conçu pour l'extraction, le diagnostic, la résolution et la reconstruction fidèle géométrique de documents PDF.

---

## 🚀 Structure du projet

L'architecture repose sur un *src-layout* moderne et modulaire :

```text
datacompiler/
├── src/
│   └── datacompiler/
│       ├── frontend/       # Extraction, OCR (PaddleOCR/Mistral), Diagnostic
│       ├── compile/        # Arbitrage native/OCR, résolution
│       ├── backend/        # Moteurs de rendu (PDF fidèle, DOCX, HTML, etc.)
│       ├── model/          # Modèles de données (Document, Word, BBox...)
│       └── pipeline.py     # Orchestrateur principal
├── tests/                  # Tests unitaires et fixtures (pytest)
├── pyproject.toml          # Configuration du package
└── requirements.txt        # Dépendances du projet

---

## ⚙️ Installation

1. Crée et active un environnement virtuel Python (Python >= 3.11 requis) :
   ```bash
   py -3.11 -m venv .venv
   # Windows PowerShell
   .venv\Scripts\Activate.ps1
   ```

2. Installe le package et les outils de développement en mode éditable :
   ```bash
   python -m pip install -e ".[dev]"
   ```

---

## 🛠️ Utilisation

### 1. Via la commande CLI
Une fois le package installé en mode éditable, tu peux exécuter directement la commande `datacompiler` dans ton terminal :

```bash
datacompiler chemin/vers/document.pdf
```

Sans option, la commande écrit `document_rebuilt.pdf` : un nouveau PDF qui suit l'ordre de lecture
résolu. Les glyphes vectoriels du texte inchangé sont conservés à l'écran et accompagnés d'une couche
de texte invisible sélectionnable. Les segments reconstruits sont, eux, émis comme texte visible ;
les images et dessins non textuels sont conservés. Pour garder le PDF d'origine intact et n'y ajouter que du texte caché, utilise la stratégie
`overlay` (le format `faithful-pdf` exige `--strategy`) :

```bash
datacompiler chemin/vers/document.pdf --strategy overlay
```

La stratégie `clean_overlay` est obsolète : elle lance `rebuilt` avec un avertissement.

Pour traduire en plus le document (par exemple en anglais), ajoute `--target-lang en`. Il faut
`python -m pip install -e ".[translation]"` et la variable d'environnement `DEEPL_AUTH_KEY` ; le texte
est envoyé à DeepL. Sans `--source-lang fr`, la langue source est détectée automatiquement, ce qui
demande l'extra `language` (`python -m pip install -e ".[language]"`). La commande écrit `document.en.xlf` (XLIFF à relire) et `document_en_rebuilt.pdf`.
`--no-translate` désactive toujours la traduction, même si `--target-lang` est présent : pratique pour
tester des fichiers sans rien envoyer à un service externe.
Pour ouvrir l'éditeur sans traduire, ajoute `--editor` : il permet de modifier le texte résolu
et ses boîtes, avec sauvegarde des corrections dans `document_rebuilt.layout.json`. Avec
`--target-lang`, `--editor` ouvre le même éditeur après traduction ; `--no-translate` garde
la voie d'édition générique. L'éditeur nécessite Tkinter et une session graphique.

### 2. Utilisation en tant que bibliothèque
```python
from datacompiler import executer_pipeline

# Extrait et compile le PDF, écrit le PDF reconstruit.
document = executer_pipeline("chemin/vers/document.pdf", strategy="rebuilt")
print(f"Pages traitées : {len(document.pages)}")
```

### Échange de traductions XLIFF

DataCompiler exporte les lignes résolues en unités XLIFF 1.2. Lorsqu'une ligne
traverse plusieurs cellules d'un tableau détecté, elle est séparée par cellule
pour que chaque traduction garde sa propre position. Les identifiants de page,
de mots et de bloc sont conservés dans une note DataCompiler afin de rattacher
les traductions au PDF. Le texte source du document n'est jamais remplacé à
l'import.

```python
from datacompiler.translation import (
    export_xliff, import_xliff, render_translated_pdf,
)

units = export_xliff(
    document, "document-fr-en.xlf",
    source_language="fr", target_language="en",
)
# Traduire document-fr-en.xlf dans un outil CAT compatible, puis :
translation = import_xliff("document-fr-en-translated.xlf", expected_units=units)
application = render_translated_pdf(
    document, translation, "document-en-rebuilt.pdf",
    expected_units=units,
)
print("Segments traduits :", len(application.translated_units))
```

Pour corriger manuellement le placement et le style dans une interface de
bureau légère, remplacez l'appel final par `edit_translation_pdf`. L'aperçu
permet de sélectionner, déplacer ou redimensionner chaque segment, de corriger
son texte et sa taille, et de régler le gras, l'italique ou les exposants et
indices. Le bouton d'ajout crée un bloc de texte libre. L'enregistrement
permet aussi de scinder un segment fusionné en deux blocs déplaçables. Il
produit le PDF et un fichier `.layout.json` qui conserve ces corrections par
ID XLIFF pour les rendus suivants. L'interface requiert un environnement
Python avec Tkinter et une session graphique.
La couleur du texte se règle par mot ou bloc avec le sélecteur natif du système
et peut être réinitialisée sur la couleur source. Cette couleur d'édition est
indépendante de l'échantillonnage des tracés glyphiques et est conservée dans le
sidecar. Le texte natif est édité au niveau des mots résolus : un lien tel que
`impots.gouv.fr` peut avoir sa couleur propre lorsqu'il constitue un mot extrait
distinct. Aucun regroupement ou découpage automatique de segments n'est effectué.

```python
from datacompiler.translation import edit_translation_pdf

application = edit_translation_pdf(
    document, translation, "document-en-lqa.pdf",
    expected_units=units,
)
```

Le même éditeur s'ouvre directement après la traduction CLI :

```powershell
datacompiler document.pdf --target-lang en --edit-translation
```

Pour éditer directement le document résolu sans créer de traduction :

```powershell
datacompiler document.pdf --editor
```

L'API Python propose également `edit_document_pdf(document, "document_rebuilt.pdf")`
pour ouvrir ce mode sur un document déjà résolu.

Les mots résolus reçoivent des identifiants stables fondés sur la page et l'identifiant du mot.
Dans ce mode, les tracés des glyphes vectoriels sont remplacés par du texte natif, qu'ils aient
été modifiés ou non ; les dessins non reconnus restent conservés. Le sidecar `.layout.json`
préserve le texte, les boîtes et les styles pris en charge.

### Relecture humaine dans Matecat

DataCompiler peut créer un projet Matecat à partir du XLIFF qu'il vient de
produire, puis récupérer le XLIFF après la relecture humaine. Le PDF original
n'est pas envoyé : Matecat reçoit le texte des segments et les notes XLIFF
nécessaires au rattachement des segments. Le texte est toutefois transmis au
serveur Matecat configuré.

```python
from datacompiler.translation import (
    MatecatClient, submit_document_to_matecat, import_matecat_xliff,
    render_translated_pdf,
)

client = MatecatClient()  # lit MATECAT_API_KEY et MATECAT_BASE_URL
project, units = submit_document_to_matecat(
    document, client, "document-fr-en.xlf",
    source_language="fr-FR", target_language="en-US",
    project_name="Document à relire",
)
print("Projet créé :", project.project_id)
if project.editor_url:
    print("Éditeur :", project.editor_url)
elif project.project_id and project.project_password:
    print(client.get_project_urls(project.project_id, project.project_password))

# Après la relecture dans Matecat :
translation = import_matecat_xliff(
    client, project, "document-fr-en-reviewed.xlf", expected_units=units,
)
render_translated_pdf(
    document, translation, "document-en-rebuilt.pdf", expected_units=units,
)
```

Configure `MATECAT_API_KEY` avec la clé API Matecat au format demandé par
Matecat. `MATECAT_BASE_URL` vaut par défaut `https://www.matecat.com` ; il pourra
pointer vers ton instance, par exemple `https://matecat.data-compiler.com`, une
fois celle-ci déployée. Les identifiants restent dans l'environnement et ne
doivent pas être inscrits dans le dépôt. La session d'édition humaine se fait
dans l'interface Web Matecat ; DataCompiler prépare le projet et reprend le
XLIFF exporté avant de reconstruire le PDF.

L'intégration utilise les API publiques Matecat : création de projet par
`/api/v1/new`, informations projet par `/api/v2/projects/...`, et export XLIFF
par `/api/v2/xliff/...`. Les identifiants de segments sont validés à la reprise ;
un XLIFF dont le texte source a été modifié ou dont les IDs ne correspondent
plus est refusé pour éviter de placer une traduction au mauvais endroit.

`render_translated_pdf` produit un PDF reconstruit et ne modifie pas le modèle
source. Chaque segment traduit reste à sa position et dans sa boîte d'origine,
sans recomposition ni retour à la ligne. Pour une même boîte logique (bloc natif,
cellule ou zone reconnue), la taille source est conservée sans réduction
automatique : le placement et les ajustements typographiques relèvent du LQA.
La position, la couleur et le style source sont conservés au mieux. Les
traductions absentes conservent leur texte source.
Les commentaires PDF sont désactivés par défaut pour préserver la lisibilité ;
`render_translated_pdf(..., include_comments=True)` les ajoute à la demande.
Ils indiquent alors le texte source et traduit, le moteur, l'estimation de
qualité et les besoins de relecture. Une estimation COMETKiwi est marquée comme
non calibrée et ne représente pas une probabilité que la traduction soit exacte.

La détection automatique utilise le texte natif du PDF avant l'OCR ciblé et
alimente PaddleOCR avec la langue détectée. Elle est aussi accessible via
`detect_document_languages(document)` pour annoter les lignes résolues et
`detect_language(text)` pour une détection ponctuelle. Pour les PDF sans texte
natif exploitable (notamment les scans), passe `--paddle-lang en` ou l'argument
`paddle_lang="en"` à la place ; aucune langue n'est supposée par défaut.

### Prétraduction automatique et contrôle qualité

Le SDK officiel DeepL est proposé comme moteur facultatif. Il faut installer
`python -m pip install -e ".[translation]"` et fournir `DEEPL_AUTH_KEY` dans
l'environnement. Le texte des segments sera alors envoyé au service DeepL.
DeepL renvoie une traduction et sa langue source détectée, mais aucun score de
confiance de la traduction.

```python
from datacompiler.translation import (
    CometKiwiQualityEstimator, translate_xliff_file,
)

quality = CometKiwiQualityEstimator()  # nécessite le téléchargement du modèle
translation = translate_xliff_file(
    "document-fr-en.xlf", "document-fr-en-machine.xlf",
    context="Formulaire fiscal français; conserver les références légales.",
    # glossary="ID_DE_GLOSSAIRE",  # facultatif
    quality_estimator=quality,
)
```

Pour trier les segments à relire, l'extra `translation-quality` ajoute
COMETKiwi : `python -m pip install -e ".[translation,translation-quality]"`.
Il estime la qualité sans traduction de référence ; les scores ne sont pas des
probabilités calibrées. Les segments sous le seuil (0,65 par défaut) reçoivent
une note DataCompiler dans le XLIFF et restent `approved="no"` pour être
vérifiés par une personne dans Matecat. Le modèle est volumineux et son accès
peut demander l'acceptation de sa licence sur Hugging Face.

---

## 🧪 Lancer les tests

Pour exécuter l'ensemble des tests automatisés avec `pytest` :

```bash
python -m pytest
```

Pour établir une première mesure de couverture :

```bash
python -m pytest --cov=datacompiler --cov-report=term-missing
```

Le champ `ImageElement.contains_text` reste à `null` (inconnu) pour les images
bitmap : la sonde OCR d'images basée sur Tesseract a été retirée. Il n'est pas
converti en `false`, afin de ne pas présenter une absence d'analyse comme un
résultat négatif.
