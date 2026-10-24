# AutomaticDossierLocation

Constitution et mise à jour automatique d'un dossier de location (logement de
particulier ou d'agence, hors résidence étudiante) pour un **étudiant avec
garant**, compatible **Termux** (Android).

## Arborescence

```
main.py                    # crée les dossiers, lit la config, affiche la synthèse
config_dossier.json        # liste des pièces (demandeur / garant)
modules/
  dates.py                 # calcul des mois à récupérer + interpolation des masques
  digiposte_fetcher.py     # récupération des bulletins de salaire sur Digiposte
demandeur/  garant/        # pièces locales (créés automatiquement, ignorés par git)
secrets.json               # identifiants Digiposte (créé au 1er lancement, ignoré par git)
```

## Installation sur Termux

Playwright **n'est pas disponible sur Termux** (aucun build Android de ses
navigateurs). Le module Digiposte utilise donc **Selenium + le Chromium de
Termux**, avec repli automatique sur un **mode manuel**.

```sh
pkg update
pkg install python git
termux-setup-storage                    # accès au dossier Download du téléphone

# Optionnel : mode automatique (Selenium)
pkg install x11-repo
pkg install chromium                    # fournit chromium-browser ET chromedriver
pip install -r requirements.txt
```

Sur PC : `pip install -r requirements.txt` suffit (Selenium Manager télécharge
le bon chromedriver si Chrome/Chromium est installé).

## Utilisation

```sh
python main.py              # crée demandeur/, garant/, modules/ + synthèse des pièces
python main.py --fetch      # télécharge aussi les pièces dynamiques manquantes
python -m modules.digiposte_fetcher [--manuel | --selenium] [--reset-secrets]
```

Les pièces statiques sont à déposer à la main aux chemins indiqués dans
`config_dossier.json` ; la synthèse indique ✓ / ✗ pour chacune.

## Configuration (`config_dossier.json`)

Deux sections, `demandeur` et `garant`, contenant chacune une liste de pièces :

| Clé | Rôle |
|---|---|
| `nom_piece` | description de la pièce |
| `chemin` | emplacement local (masque formaté pour les pièces dynamiques) |
| `dynamique` | `true` si la pièce évolue dans le temps |
| `nom_site`, `url_scraper` | site source et URL de connexion |
| `regex_recherche` | regex de recherche du document, formatée comme une f-string |
| `nom_module` | module de `modules/` chargé pour la récupération |
| `nombre_mois` | nombre de mois consécutifs à récupérer (3 pour les bulletins) |
| `decalage_mois` | mois à sauter avant le premier (1 = commencer au mois précédent) |
| `methode` | `auto` (défaut), `selenium` ou `manuel` |
| `dossier_telechargements` | (optionnel, mode manuel) dossier où chercher les PDF |

Variables disponibles dans `chemin` et `regex_recherche` : `{year}`,
`{month:02d}`, `{mois_nom}` (ex. « septembre »). Les accolades propres aux
regex doivent être **doublées** : `\d{{2}}`.

## Modes de récupération Digiposte

- **selenium** : Chromium headless se connecte avec `secrets.json`, demande le
  code de vérification si Digiposte en envoie un, cherche un document dont le
  libellé correspond à la regex et le télécharge. Si une étape échoue, une
  capture `digiposte_erreur.png` est enregistrée. Les sélecteurs sont
  génériques (champs email/mot de passe, boutons « Se connecter »,
  « Télécharger ») : il faudra peut-être les ajuster si l'interface de
  Digiposte change. Mettez `DOSSIER_HEADLESS=0` (sur PC) pour voir le
  navigateur, et `DOSSIER_CHROMIUM=/chemin/chrome` pour imposer un binaire.
- **manuel** : ouvre Digiposte dans le navigateur Android (`termux-open-url`),
  vous téléchargez le bulletin, puis le script récupère le PDF dans
  `~/storage/downloads`, vérifie son nom avec la regex (ou vous demande de
  confirmer) et le range au bon chemin. Un PDF déjà présent dans Download et
  dont le nom correspond est repris directement.
- **auto** : selenium si disponible, sinon (ou pour les mois non trouvés) manuel.

## Sécurité et conformité

- `secrets.json` est créé avec les droits `600` et exclu par `.gitignore`, de
  même que `demandeur/`, `garant/` et tous les PDF : vos pièces ne doivent
  jamais être publiées.
- La liste des pièces se limite à celles autorisées par le
  **décret n° 2015-1437** (identité, domicile, activité/statut, ressources,
  avis d'imposition). Ne pas ajouter de pièces interdites (relevés bancaires,
  photo d'identité, carte Vitale, attestation de bonne tenue de compte, etc.).
