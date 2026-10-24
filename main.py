#!/usr/bin/env python3
"""Constitution automatique d'un dossier de location (étudiant + garant).

Usage :
    python main.py              # crée l'arborescence et affiche la synthèse
    python main.py --fetch      # récupère en plus les pièces dynamiques
"""

import argparse
import importlib
import json
import sys
from pathlib import Path

from modules.dates import periodes, formater

RACINE = Path(__file__).resolve().parent
FICHIER_CONFIG = RACINE / "config_dossier.json"
SECTIONS = ("demandeur", "garant")


def creer_structure():
    """Crée les dossiers demandeur/, garant/ et modules/ s'ils n'existent pas."""
    for dossier in (*SECTIONS, "modules"):
        (RACINE / dossier).mkdir(exist_ok=True)


def charger_config(chemin=FICHIER_CONFIG):
    try:
        with open(chemin, encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        sys.exit(f"[ERREUR] Fichier de configuration introuvable : {chemin}")
    except json.JSONDecodeError as e:
        sys.exit(f"[ERREUR] JSON invalide dans {chemin} : {e}")

    for section in SECTIONS:
        if not isinstance(config.get(section), list):
            sys.exit(f"[ERREUR] La section '{section}' doit être une liste de pièces.")
    return config


def chemins_attendus(piece):
    """Chemins locaux attendus pour une pièce (plusieurs si dynamique multi-mois)."""
    if not piece.get("dynamique"):
        return [RACINE / piece["chemin"]]
    return [RACINE / formater(piece["chemin"], p) for p in periodes(piece)]


def afficher_synthese(config):
    total = presentes = 0
    for section in SECTIONS:
        print(f"\n=== {section.upper()} ===")
        for piece in config[section]:
            chemins = chemins_attendus(piece)
            ok = [c for c in chemins if c.exists()]
            total += len(chemins)
            presentes += len(ok)
            statut = "OK " if len(ok) == len(chemins) else "-- "
            type_piece = "dynamique" if piece.get("dynamique") else "statique"
            print(f" [{statut}] {piece['nom_piece']} ({type_piece})")
            for c in chemins:
                print(f"         {'✓' if c.exists() else '✗'} {c.relative_to(RACINE)}")
            if piece.get("dynamique"):
                print(f"         source : {piece.get('nom_site')} -> module {piece.get('nom_module')}")
    print(f"\nPièces présentes : {presentes}/{total}")


def recuperer_dynamiques(config):
    for section in SECTIONS:
        for piece in config[section]:
            if not piece.get("dynamique"):
                continue
            nom_module = piece.get("nom_module")
            print(f"\n>>> {piece['nom_piece']} via {nom_module}")
            try:
                module = importlib.import_module(f"modules.{nom_module}")
            except ImportError as e:
                print(f"[ERREUR] Module '{nom_module}' indisponible : {e}")
                continue
            try:
                fichiers = module.recuperer(piece, RACINE)
                for f in fichiers:
                    print(f"[OK] {f.relative_to(RACINE)}")
            except Exception as e:  # un module défaillant ne bloque pas les autres
                print(f"[ERREUR] {nom_module} : {e}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch", action="store_true", help="télécharger les pièces dynamiques")
    parser.add_argument("--config", type=Path, default=FICHIER_CONFIG, help="fichier de configuration JSON")
    args = parser.parse_args()

    creer_structure()
    config = charger_config(args.config)
    if args.fetch:
        recuperer_dynamiques(config)
    afficher_synthese(config)


if __name__ == "__main__":
    main()
