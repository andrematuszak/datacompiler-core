## ⚠️ Prérequis : version de Python

DataCompiler requiert **Python 3.11 ou supérieur** (testé en **Python 3.12**, macOS).
PaddleOCR / PaddlePaddle sont installés automatiquement comme dépendances ; le premier
lancement de l'OCR ciblé peut télécharger les modèles Paddle (connexion Internet requise).

---

## 🧪 Tests

Pour exécuter la suite de tests :

```bash
pip install -e ".[dev]"
pytest
```

Les tests qui s'appuient sur le PDF de référence `tests/fixtures/impots-revenu/impots-revenu.pdf` sont ignorés (skip) si ce fichier est absent. `tests/test_regression_word_count.py` est aussi ignoré tant que les sorties de ce PDF n'ont pas été générées.

---

## 📜 Licence

Projet sous licence propriétaire — tous droits réservés. Voir le fichier [LICENSE](LICENSE).
