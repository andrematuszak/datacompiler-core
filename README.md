# DataCompiler

DataCompiler extrait et résout le texte des PDF, puis produit un PDF reconstruit
suivant l'ordre de lecture. Il peut aussi préparer une traduction à relire et
ouvrir un éditeur de bureau pour corriger le texte et sa mise en page.

## Prérequis

- Python **3.11 ou supérieur** (testé avec Python 3.12 sur macOS).
- Tkinter et une session graphique uniquement pour utiliser l'un des éditeurs.
- Une connexion Internet peut être nécessaire au premier démarrage de PaddleOCR
  (téléchargement de modèles), ainsi que pour les services DeepL et Matecat.

## Installation

Depuis la racine du dépôt, crée et active un environnement virtuel :

```bash
python3 -m venv .venv                      # macOS / Linux
source .venv/bin/activate                 # macOS / Linux
# Windows PowerShell : py -3.11 -m venv .venv
# puis : .venv\Scripts\Activate.ps1
```

Installe DataCompiler et ses dépendances de base :

```bash
python -m pip install -e .
```

PaddlePaddle et PaddleOCR sont des dépendances de base requises pour le parcours
reconstruit documenté. Leur installation ajoute un moteur natif conséquent ; le
premier traitement OCR peut aussi télécharger des modèles et nécessite une
connexion Internet. `pyproject.toml` garde le client Mistral dans un extra
distinct, facultatif. Les extras supplémentaires sont :

```bash
python -m pip install -e ".[translation]"            # traduction DeepL
python -m pip install -e ".[translation,translation-quality]"  # DeepL + COMETKiwi
python -m pip install -e ".[mistral]"                 # client OCR Mistral facultatif
python -m pip install -e ".[dev]"                    # tests et outils de développement
```

Les dépendances principales comprennent `langdetect` ; la détection de langue
ne nécessite donc pas d'extra `language`. Le premier lancement de PaddleOCR
peut télécharger ses modèles. L'OCR pleine page n'est pas implémenté dans cette
version.

## Utilisation en ligne de commande

Après l'installation, la commande `datacompiler` est disponible dans
l'environnement virtuel :

```bash
datacompiler chemin/vers/document.pdf
```

Le parcours recommandé est la reconstruction : la commande crée
`document_rebuilt.pdf`, un nouveau PDF suivant l'ordre de lecture résolu. Le
texte reconstruit est visible et sélectionnable ; les images et dessins non
textuels sont conservés. `rebuilt` est la stratégie par défaut et peut être
indiquée explicitement :

```bash
datacompiler document.pdf --strategy rebuilt
```

### OCR

Le pipeline s'appuie sur PaddleOCR pour l'OCR ciblé des zones vectorielles. En
mode par défaut `--ocr-mode auto`, la langue est déterminée à partir du texte natif quand c'est
possible. Pour un PDF dont le texte natif ne permet pas cette détection,
indique la langue PaddleOCR explicitement :

```bash
datacompiler document.pdf --paddle-lang en
```

`--ocr-mode vector` limite le traitement à l'OCR ciblé ; `--ocr-mode skip`
désactive l'OCR et ne correspond donc pas au parcours recommandé. Les scans
sans texte natif exploitable ne bénéficient pas d'un OCR pleine page dans cette
version. L'option `--ocr-mode force` n'est pas implémentée.

### Traduction automatique et éditeurs

La traduction CLI utilise DeepL. Installe l'extra `translation` et définis
`DEEPL_AUTH_KEY` dans l'environnement : le texte des segments est envoyé à
DeepL. La langue source est détectée par défaut ; tu peux la préciser.

```bash
export DEEPL_AUTH_KEY="..."  # macOS / Linux ; définir la variable d'environnement sous Windows
datacompiler document.pdf --target-lang en
datacompiler document.pdf --target-lang en --source-lang fr
```

La commande produit `document.en.xlf` (XLIFF à relire) et
`document_en_rebuilt.pdf`. `--no-translate` empêche l'appel à DeepL même si
`--target-lang` est indiqué.

Les deux options d'édition couvrent des parcours différents :

```bash
# Éditer le texte résolu, sans lancer de traduction
datacompiler document.pdf --editor

# Traduire, puis ouvrir l'éditeur de traduction
datacompiler document.pdf --target-lang en --edit-translation
```

`--edit-translation` exige `--target-lang` et ne peut pas être associé à
`--no-translate`. `--editor` ouvre l'éditeur générique sans cible de traduction ;
avec `--target-lang`, il ouvre l'éditeur de traduction, sauf si
`--no-translate` désactive la traduction. L'option `--editor` exige la sortie
PDF reconstruite. Les deux éditeurs nécessitent Tkinter et une session graphique.

Dans l'éditeur, sélectionne un bloc pour modifier son texte, sa taille, son
gras/italique, son exposant ou indice, sa couleur, sa position et ses dimensions.
Le sélecteur de couleur natif règle la couleur du texte ; « Couleur source »
annule ce choix. La couleur personnalisée est indépendante de l'échantillonnage
des tracés glyphiques et est conservée dans le fichier de corrections.

Tu peux aussi ajouter un bloc texte, supprimer un bloc ou le restaurer, et
scinder le bloc sélectionné en deux blocs dont le texte est modifiable. Pour
fusionner ou aligner plusieurs blocs, sélectionne-les dans la liste avec
Ctrl/Cmd+clic ou Maj+clic. La fusion exige que les blocs soient sur la même
page. L'alignement utilise le dernier bloc sélectionné comme référence et permet
d'aligner les bords gauche, droit, haut ou bas, ou les centres horizontal et
vertical ; il conserve les tailles et l'ordre de lecture. Les nouveaux blocs
ajoutés par le bouton apparaissent sur la première page.

L'enregistrement produit le PDF et un fichier `.layout.json` associé. Ce
sidecar versionné conserve les corrections par identifiant stable de segment
(ou de mot résolu dans l'éditeur générique) et est rechargé automatiquement aux
ouvertures suivantes. Les tracés des glyphes vectoriels remplacés sont exclus
du rendu pour éviter de superposer l'ancien texte au nouveau ; les éléments
graphiques non textuels restent conservés.

## Utilisation comme bibliothèque

`executer_pipeline` traite le document et écrit le PDF reconstruit par défaut :

```python
from datacompiler import executer_pipeline

document = executer_pipeline("document.pdf", strategy="rebuilt")
print(f"Pages traitées : {len(document.pages)}")
```

Pour éditer le texte résolu sans traduction, utilise `edit_document_pdf`.
Pour un flux traduit, exporte les unités XLIFF, importe le XLIFF relu et choisis
`render_translated_pdf` pour le rendu direct ou `edit_translation_pdf` pour le
rendu avec édition de mise en page :

```python
from datacompiler.translation import (
    export_xliff, import_xliff, render_translated_pdf,
)

units = export_xliff(
    document, "document-fr-en.xlf",
    source_language="fr", target_language="en",
)
# Traduire / relire le XLIFF dans un outil compatible, puis :
translation = import_xliff(
    "document-fr-en-reviewed.xlf", expected_units=units,
)
application = render_translated_pdf(
    document, translation, "document-en-rebuilt.pdf",
    expected_units=units,
)
print("Segments traduits :", len(application.translated_units))
```

Pour ouvrir l'éditeur sur le texte résolu sans traduction, appelle
`edit_document_pdf(document, "document-rebuilt.pdf")`. Pour éditer le rendu
traduit au lieu du rendu direct, remplace `render_translated_pdf` par :

```python
from datacompiler.translation import edit_translation_pdf

application = edit_translation_pdf(
    document, translation, "document-en-lqa.pdf",
    expected_units=units,
)
```

L'export est au format XLIFF 1.2. Une ligne qui traverse plusieurs cellules
d'un tableau détecté est séparée par cellule. Les identifiants de page, de mots
et de bloc sont conservés dans une note DataCompiler ; l'import valide les
identifiants et ne remplace pas le texte source du document.

`render_translated_pdf` conserve les segments traduits dans leurs boîtes
d'origine, sans recomposition ni retour à la ligne. Il n'effectue pas de
réduction automatique de taille pour faire tenir le texte. Les segments sans
traduction conservent leur texte source. Les commentaires PDF sont désactivés
par défaut ; `render_translated_pdf(..., include_comments=True)` les ajoute avec
le texte source et traduit, le moteur, l'estimation de qualité et les besoins
de relecture. Une estimation COMETKiwi est non calibrée : ce n'est pas une
probabilité que la traduction soit exacte.

### Différences avec la release publique 0.1.0

La release publique `andrematuszak/datacompiler` v0.1.0 est une wheel
précompilée pour macOS 12+ Apple Silicon et Python 3.12. Son README présente
`overlay` comme stratégie par défaut et indique que `--format` est ignoré.
Cette branche source documente le parcours `rebuilt`, déclare Python 3.11 ou
plus et son CLI traite `--format`. La contrainte macOS/Python 3.12 concerne la
wheel publiée ; suis son README pour cette installation. Pour le code source de
cette branche, suis les étapes ci-dessus. Les autres stratégies peuvent rester
disponibles dans le CLI, mais ne sont pas le parcours recommandé ni documenté
ici.

### Relecture dans Matecat

DataCompiler peut soumettre le XLIFF à Matecat et importer le XLIFF après
relecture. Le PDF original n'est pas envoyé, mais le texte des segments l'est.
La session de relecture s'effectue dans l'interface Web Matecat.

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

Configure `MATECAT_API_KEY` avec la clé API attendue par Matecat.
`MATECAT_BASE_URL` vaut par défaut `https://www.matecat.com` et peut pointer
vers une autre instance. Les clés doivent rester dans l'environnement, pas dans
le dépôt. L'intégration utilise les API publiques Matecat pour créer le projet,
en récupérer les informations et exporter le XLIFF. Les identifiants et le
texte source sont validés à l'import pour éviter de rattacher une traduction
au mauvais segment.

### Qualité des traductions

L'extra `translation-quality` ajoute COMETKiwi, un estimateur local sans
référence de traduction. Il peut annoter les segments sous le seuil de 0,65 par
défaut dans le XLIFF et les marquer à relire. Le modèle est volumineux et son
téléchargement peut nécessiter l'acceptation de sa licence sur Hugging Face.

```python
from datacompiler.translation import (
    CometKiwiQualityEstimator, translate_xliff_file,
)

quality = CometKiwiQualityEstimator()  # téléchargement du modèle requis
translation = translate_xliff_file(
    "document-fr-en.xlf", "document-fr-en-machine.xlf",
    context="Formulaire fiscal français ; conserver les références légales.",
    # glossary="ID_DE_GLOSSAIRE",  # facultatif
    quality_estimator=quality,
)
```

### Détection de langue

La détection utilise le texte natif du PDF avant l'OCR ciblé et fournit une
langue à PaddleOCR lorsqu'elle est disponible. Elle est également accessible
par `detect_document_languages(document)` pour annoter les lignes résolues et
`detect_language(text)` pour un texte ponctuel. Les textes trop courts ou
incertains peuvent ne donner lieu à aucune détection.

## Tests

Installe les outils de développement puis lance les tests :

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Pour afficher la couverture :

```bash
python -m pytest --cov=datacompiler --cov-report=term-missing
```

Pour les images bitmap, `ImageElement.contains_text` reste à `null` (inconnu) :
la sonde OCR d'images basée sur Tesseract a été retirée. Cette valeur n'est pas
convertie en `false`, afin de ne pas présenter une absence d'analyse comme un
résultat négatif.
