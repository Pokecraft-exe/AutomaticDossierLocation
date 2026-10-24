#!/usr/bin/env python3
"""Récupération des bulletins de salaire depuis Digiposte.

Playwright n'est pas disponible sur Termux (pas de build Android de ses
navigateurs). Le module propose donc deux méthodes :

- "selenium" : pilote le Chromium de Termux (paquet x11-repo/chromium, qui
  fournit aussi chromedriver) en mode headless. Fonctionne aussi sur PC.
- "manuel"   : ouvre Digiposte dans le navigateur Android, l'utilisateur
  télécharge le PDF et le module le récupère dans le dossier Download,
  vérifie son nom avec la regex et le range au bon endroit.

"auto" (défaut) tente selenium puis bascule en manuel en cas d'échec.

Utilisation autonome :
    python -m modules.digiposte_fetcher [--manuel] [--reset-secrets]
"""

import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

if __package__ in (None, ""):  # exécution directe : python modules/digiposte_fetcher.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from modules.dates import formater, periodes, variables
else:
    from .dates import formater, periodes, variables

RACINE = Path(__file__).resolve().parent.parent
FICHIER_SECRETS = RACINE / "secrets.json"
CLE_SECRETS = "digiposte"
EST_TERMUX = "com.termux" in os.environ.get("PREFIX", "")
DELAI = 30  # secondes d'attente max pour un élément / un téléchargement


# --------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------

def charger_secrets(reinitialiser=False):
    """Lit secrets.json, ou le crée en demandant email et mot de passe."""
    secrets = {}
    if FICHIER_SECRETS.exists():
        with open(FICHIER_SECRETS, encoding="utf-8") as f:
            secrets = json.load(f)
    if reinitialiser or not secrets.get(CLE_SECRETS, {}).get("email"):
        print(f"Identifiants Digiposte (stockés localement dans {FICHIER_SECRETS.name}) :")
        secrets[CLE_SECRETS] = {
            "email": input("  Email : ").strip(),
            "mot_de_passe": getpass.getpass("  Mot de passe : "),
        }
        with open(FICHIER_SECRETS, "w", encoding="utf-8") as f:
            json.dump(secrets, f, indent=2)
        os.chmod(FICHIER_SECRETS, 0o600)
    return secrets[CLE_SECRETS]


# --------------------------------------------------------------------------
# Cibles à récupérer
# --------------------------------------------------------------------------

def cibles(piece, racine):
    """(libellé, regex compilée, destination) pour chaque mois manquant."""
    resultat = []
    for periode in periodes(piece):
        destination = racine / formater(piece["chemin"], periode)
        if destination.exists():
            continue
        v = variables(periode)
        libelle = f"{v['mois_nom']} {v['year']}"
        regex = re.compile(formater(piece["regex_recherche"], periode))
        resultat.append((libelle, regex, destination))
    return resultat


def ranger(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


# --------------------------------------------------------------------------
# Méthode Selenium
# --------------------------------------------------------------------------

def creer_driver(dossier_telechargement):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service

    options = webdriver.ChromeOptions()
    if os.environ.get("DOSSIER_HEADLESS", "1") != "0":
        options.add_argument("--headless=new")
    for arg in ("--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--window-size=1280,2000"):
        options.add_argument(arg)
    options.add_experimental_option("prefs", {
        "download.default_directory": str(dossier_telechargement),
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
    })

    navigateur = os.environ.get("DOSSIER_CHROMIUM") or next(
        filter(None, map(shutil.which, ("chromium-browser", "chromium", "google-chrome"))), None)
    if navigateur:
        options.binary_location = navigateur
    chromedriver = shutil.which("chromedriver")
    if EST_TERMUX and not (navigateur and chromedriver):
        raise RuntimeError("chromium/chromedriver absents : pkg install x11-repo && pkg install chromium")
    # Hors Termux, sans chromedriver dans le PATH, Selenium Manager le télécharge.
    service = Service(executable_path=chromedriver) if chromedriver else Service()

    driver = webdriver.Chrome(options=options, service=service)
    try:
        driver.execute_cdp_cmd("Browser.setDownloadBehavior",
                               {"behavior": "allow", "downloadPath": str(dossier_telechargement)})
    except Exception:
        pass
    return driver


def _premier_visible(driver, selecteurs, delai=DELAI):
    """Attend et renvoie le premier élément visible parmi des sélecteurs CSS."""
    from selenium.webdriver.common.by import By

    fin = time.time() + delai
    while time.time() < fin:
        for sel in selecteurs:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed() and el.is_enabled():
                    return el
        time.sleep(0.5)
    return None


def _cliquer_texte(driver, motif, delai=5):
    """Clique sur le premier bouton/lien visible dont le texte ou l'aria-label correspond."""
    from selenium.webdriver.common.by import By

    regex = re.compile(motif, re.I)
    fin = time.time() + delai
    while time.time() < fin:
        for el in driver.find_elements(By.CSS_SELECTOR, "button, a, [role='button']"):
            texte = f"{el.text} {el.get_attribute('aria-label') or ''} {el.get_attribute('title') or ''}"
            if regex.search(texte) and el.is_displayed():
                driver.execute_script("arguments[0].click();", el)
                return True
        time.sleep(0.5)
    return False


SELECTEUR_LIBELLES = ("a, button, [role='button'], [role='link'], [role='menuitem'], [role='row'], "
                      "[role='treeitem'], li, tr, [title], [aria-label], span, p, div")

# Un seul aller-retour WebDriver : éléments visibles + leur libellé
_JS_LIBELLES = """
return Array.from(document.querySelectorAll(arguments[0]))
  .filter(e => e.getClientRects().length > 0)
  .map(e => [e, (e.innerText || e.getAttribute('title') || e.getAttribute('aria-label') || '').trim()]);
"""


def _trouver_libelle(driver, regex):
    """Élément visible le plus spécifique (libellé le plus court) correspondant à la regex."""
    candidats = [(len(t), el) for el, t in driver.execute_script(_JS_LIBELLES, SELECTEUR_LIBELLES)
                 if t and regex.search(t)]
    return min(candidats, key=lambda c: c[0])[1] if candidats else None


def _cliquer_libelle(driver, motif, delai=DELAI):
    """Clique sur une entrée de menu, un dossier... dont le libellé correspond à la regex."""
    regex = re.compile(motif, re.I | re.S)
    fin = time.time() + delai
    while time.time() < fin:
        element = _trouver_libelle(driver, regex)
        if element is not None:
            driver.execute_script("arguments[0].scrollIntoView(); arguments[0].click();", element)
            time.sleep(2)  # chargement de la vue suivante (SPA)
            return
        time.sleep(0.5)
    raise RuntimeError(f"élément introuvable pour la navigation : {motif}")


def _revenir_au_dossier(driver, piece):
    """Ferme un éventuel aperçu puis refait la navigation depuis le menu (sans recharger la page)."""
    from selenium.webdriver.common.keys import Keys

    try:
        driver.switch_to.active_element.send_keys(Keys.ESCAPE)
    except Exception:
        pass
    _cliquer_texte(driver, r"^\s*(fermer|retour|close)\s*$", delai=1)
    _naviguer(driver, piece)


def _naviguer(driver, piece):
    """Depuis l'accueil connecté, suit les étapes de 'navigation' (regex cliquées dans l'ordre)."""
    for etape in piece.get("navigation", []):
        _cliquer_libelle(driver, etape)


def _connexion(driver, url, identifiants):
    driver.get(url)
    _cliquer_texte(driver, r"tout accepter|accepter", delai=5)  # bandeau cookies

    champ_email = _premier_visible(driver, ["input[type='email']", "input[name*='mail' i]",
                                            "input[id*='mail' i]", "input[name*='login' i]"])
    if not champ_email:
        raise RuntimeError("champ email introuvable sur la page de connexion")
    champ_email.clear()
    champ_email.send_keys(identifiants["email"])

    champ_mdp = _premier_visible(driver, ["input[type='password']"], delai=3)
    if not champ_mdp:  # formulaire en deux étapes
        _cliquer_texte(driver, r"continuer|suivant")
        champ_mdp = _premier_visible(driver, ["input[type='password']"])
    if not champ_mdp:
        raise RuntimeError("champ mot de passe introuvable")
    champ_mdp.send_keys(identifiants["mot_de_passe"])
    if not _cliquer_texte(driver, r"se connecter|connexion|valider"):
        champ_mdp.submit()

    # Double authentification éventuelle (code par SMS / email)
    champ_code = _premier_visible(driver, ["input[autocomplete='one-time-code']", "input[name*='code' i]",
                                           "input[id*='otp' i]"], delai=10)
    if champ_code:
        champ_code.send_keys(input("Code de vérification reçu : ").strip())
        _cliquer_texte(driver, r"valider|confirmer|continuer")


def _nouveau_fichier(dossier, avant, delai=DELAI):
    fin = time.time() + delai
    while time.time() < fin:
        nouveaux = [f for f in dossier.iterdir()
                    if f.name not in avant and not f.name.endswith((".crdownload", ".tmp"))]
        if nouveaux:
            return max(nouveaux, key=lambda f: f.stat().st_mtime)
        time.sleep(0.5)
    return None


def _telecharger_document(driver, regex, dossier):
    """Trouve le document dont le libellé correspond à la regex et le télécharge."""
    element = _trouver_libelle(driver, regex)
    if element is None:
        return None

    avant = {f.name for f in dossier.iterdir()}
    # Bouton de téléchargement propre à la ligne si présent, sinon clic sur la ligne (aperçu)
    bouton = driver.execute_script("""
        const motif = /télécharger|download/i;
        return Array.from(arguments[0].querySelectorAll('a, button, [role="button"]')).find(b =>
            motif.test(b.innerText + ' ' + (b.getAttribute('aria-label') || '') + ' ' + (b.title || '')));
    """, element)
    cible = bouton if bouton is not None else element
    driver.execute_script("arguments[0].scrollIntoView(); arguments[0].click();", cible)
    fichier = _nouveau_fichier(dossier, avant, delai=5)
    if fichier is None and _cliquer_texte(driver, r"télécharger|download"):
        fichier = _nouveau_fichier(dossier, avant)
    return fichier


def recuperer_selenium(piece, a_faire):
    identifiants = charger_secrets()
    obtenus = []
    with tempfile.TemporaryDirectory() as tmp:
        dossier = Path(tmp)
        driver = creer_driver(dossier)
        try:
            _connexion(driver, piece["url_scraper"], identifiants)
            _naviguer(driver, piece)  # ex. menu "Coffre" puis dossier "Orange ... Bulletins"
            time.sleep(2)  # laisse la liste de documents se remplir (SPA)
            for libelle, regex, destination in a_faire:
                fichier = _telecharger_document(driver, regex, dossier)
                if fichier is None:
                    # la vue a pu changer (aperçu ouvert...) : on ferme et on revient au dossier
                    _revenir_au_dossier(driver, piece)
                    time.sleep(2)
                    fichier = _telecharger_document(driver, regex, dossier)
                if fichier:
                    obtenus.append(ranger(fichier, destination))
                else:
                    print(f"[!] Aucun document Digiposte ne correspond pour {libelle} ({regex.pattern})")
        except Exception:
            capture = RACINE / "digiposte_erreur.png"
            try:
                driver.save_screenshot(str(capture))
                print(f"[i] Capture d'écran de diagnostic : {capture}")
            except Exception:
                pass
            raise
        finally:
            driver.quit()
    return obtenus


# --------------------------------------------------------------------------
# Méthode manuelle (navigateur Android + dossier Download)
# --------------------------------------------------------------------------

def dossier_telechargements(piece):
    candidats = [piece.get("dossier_telechargements"), "~/storage/downloads",
                 "/sdcard/Download", "~/Téléchargements", "~/Downloads"]
    for c in filter(None, candidats):
        p = Path(c).expanduser()
        if p.is_dir():
            return p
    raise RuntimeError("dossier de téléchargements introuvable (sur Termux : termux-setup-storage)")


def ouvrir_url(url):
    if shutil.which("termux-open-url"):
        subprocess.run(["termux-open-url", url], check=False)
    else:
        webbrowser.open(url)


def recuperer_manuel(piece, a_faire):
    dossier = dossier_telechargements(piece)
    print(f"[i] Dossier surveillé : {dossier}")
    obtenus = []
    utilises = set()
    ouvert = False
    for libelle, regex, destination in a_faire:
        pdfs = sorted(dossier.glob("*.pdf"), key=lambda f: f.stat().st_mtime, reverse=True)
        deja_la = next((f for f in pdfs if regex.search(f.name)), None)
        if deja_la:
            print(f"[i] {libelle} : fichier existant {deja_la.name}")
            utilises.add(deja_la)
            obtenus.append(ranger(deja_la, destination))
            continue

        if not ouvert:
            ouvrir_url(piece["url_scraper"])
            ouvert = True
        debut = time.time()
        chemin = " > ".join(piece.get("navigation_texte", []))
        if chemin and len(obtenus) == 0:
            print(f"[i] Dans {piece.get('nom_site', 'le site')} : {chemin}")
        rep = input(f"Téléchargez le bulletin de {libelle} depuis {piece.get('nom_site', 'le site')}, "
                    "puis Entrée (s = passer) : ").strip().lower()
        if rep == "s":
            continue
        recents = [f for f in dossier.glob("*.pdf") if f.stat().st_mtime >= debut - 5 and f not in utilises]
        recents.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        fichier = next((f for f in recents if regex.search(f.name)), None)
        if fichier is None and recents:
            if input(f"  Utiliser {recents[0].name} pour {libelle} ? [o/N] ").strip().lower() == "o":
                fichier = recents[0]
        if fichier:
            utilises.add(fichier)
            obtenus.append(ranger(fichier, destination))
        else:
            print(f"[!] Aucun PDF récupéré pour {libelle}")
    return obtenus


# --------------------------------------------------------------------------
# Point d'entrée appelé par main.py
# --------------------------------------------------------------------------

def selenium_disponible():
    try:
        import selenium  # noqa: F401
    except ImportError:
        return False
    return not EST_TERMUX or bool(shutil.which("chromedriver"))


def recuperer(piece, racine=RACINE, methode=None):
    """Télécharge les mois manquants d'une pièce dynamique ; renvoie les fichiers créés."""
    a_faire = cibles(piece, Path(racine))
    if not a_faire:
        print("[i] Tous les documents sont déjà présents.")
        return []
    methode = methode or piece.get("methode", "auto")

    if methode == "selenium" or (methode == "auto" and selenium_disponible()):
        try:
            obtenus = recuperer_selenium(piece, a_faire)
            restants = [c for c in a_faire if not c[2].exists()]
            if methode == "selenium" or not restants:
                return obtenus
            print("[i] Documents manquants : passage en mode manuel.")
            return obtenus + recuperer_manuel(piece, restants)
        except Exception as e:
            if methode == "selenium":
                raise
            print(f"[!] Échec Selenium ({e}) : passage en mode manuel.")
    elif methode == "auto":
        print("[i] Selenium/chromedriver indisponible : mode manuel.")
    return recuperer_manuel(piece, a_faire)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Récupération Digiposte")
    parser.add_argument("--manuel", action="store_true", help="forcer le mode manuel")
    parser.add_argument("--selenium", action="store_true", help="forcer le mode Selenium")
    parser.add_argument("--reset-secrets", action="store_true", help="ressaisir les identifiants")
    parser.add_argument("--config", type=Path, default=RACINE / "config_dossier.json")
    args = parser.parse_args()

    if args.reset_secrets:
        charger_secrets(reinitialiser=True)
    with open(args.config, encoding="utf-8") as f:
        config = json.load(f)
    methode = "manuel" if args.manuel else "selenium" if args.selenium else None
    nom = Path(__file__).stem
    for section in ("demandeur", "garant"):
        for piece in config.get(section, []):
            if piece.get("dynamique") and piece.get("nom_module") == nom:
                print(f">>> [{section}] {piece['nom_piece']}")
                for f in recuperer(piece, RACINE, methode):
                    print(f"[OK] {f.relative_to(RACINE)}")


if __name__ == "__main__":
    main()
