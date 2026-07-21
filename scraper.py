#!/usr/bin/env python3
"""
Surveille trouverunlogement.lescrous.fr et alerte par email
quand un nouveau logement correspondant aux critères apparaît.

Fonctionne sans navigateur automatisé : les pages de résultats du
site sont générées côté serveur (framework DSFR / Svelte), donc un
simple requests.get() suffit à récupérer le HTML final.
"""

import json
import os
import re
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# Configuration (modifiable via variables d'environnement / secrets GitHub)
# --------------------------------------------------------------------------

# URL de recherche du CROUS. Pour l'obtenir : va sur trouverunlogement.lescrous.fr,
# choisis la campagne ("Pour l'année prochaine 2026-2027"), filtre si besoin,
# puis copie l'URL affichée dans la barre d'adresse.
SEARCH_URL = os.environ.get(
    "SEARCH_URL",
    "https://trouverunlogement.lescrous.fr/tools/47/search",
)

# Préfixe de code postal à garder (33 = Gironde -> Bordeaux, Pessac, Talence,
# Gradignan, Mérignac, Lormont, Bègles...). Laisse vide ("") pour ne pas filtrer.
POSTAL_PREFIX = os.environ.get("POSTAL_PREFIX", "33")

# Types de cohabitation à garder (un des mots doit apparaître dans la carte).
# Laisse vide pour ne pas filtrer par type.
COHAB_INCLUDE = [
    s.strip().lower()
    for s in os.environ.get("COHAB_INCLUDE", "Individuel").split(",")
    if s.strip()
]

# Surface minimale en m² (0 = pas de filtre). Permet d'exclure les petites
# chambres si tu ne veux que des vrais studios.
SURFACE_MIN = float(os.environ.get("SURFACE_MIN", "0"))

# Nombre max de pages de résultats à parcourir (sécurité anti-boucle infinie)
MAX_PAGES = int(os.environ.get("MAX_PAGES", "15"))

STATE_PATH = Path("data/state.json")
RECAP_PATH = Path("docs/index.html")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; crous-watch/1.0; "
        "usage personnel de veille de logement etudiant)"
    )
}


# --------------------------------------------------------------------------
# Scraping
# --------------------------------------------------------------------------

def fetch_page(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def page_url(base_url: str, page_num: int) -> str:
    # Le site utilise ?page=N pour la pagination ; on préserve les autres
    # paramètres éventuels de l'URL de recherche (bounds, filtres...).
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query))
    if page_num > 1:
        query["page"] = str(page_num)
    else:
        query.pop("page", None)
    new_query = urlencode(query)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def parse_cards(soup: BeautifulSoup) -> list[dict]:
    cards = soup.select('div[class*="fr-card"]')
    results = []
    for card in cards:
        link_tag = card.find("a", href=True)
        if not link_tag:
            continue
        name = link_tag.get_text(strip=True)
        href = link_tag["href"]
        if href.startswith("/"):
            href = "https://trouverunlogement.lescrous.fr" + href

        text = card.get_text(" ", strip=True)

        postal_match = re.search(r"\b(\d{5})\b", text)
        postal = postal_match.group(1) if postal_match else ""

        surface_match = re.search(r"(\d+(?:[.,]\d+)?)\s*m²", text)
        surface = float(surface_match.group(1).replace(",", ".")) if surface_match else None

        price_match = re.search(r"(\d[\d\s]*(?:[.,]\d+)?)\s*€", text)
        price = price_match.group(1).replace(" ", "") if price_match else ""

        # ID unique et stable = numéro d'annonce dans l'URL
        id_match = re.search(r"/accommodations/(\d+)", href)
        listing_id = id_match.group(1) if id_match else href

        results.append(
            {
                "id": listing_id,
                "name": name,
                "url": href,
                "address_text": text,
                "postal": postal,
                "surface": surface,
                "price": price,
            }
        )
    return results


def matches_filters(listing: dict) -> bool:
    if POSTAL_PREFIX and not listing["postal"].startswith(POSTAL_PREFIX):
        return False
    if COHAB_INCLUDE:
        text_lower = listing["address_text"].lower()
        if not any(word in text_lower for word in COHAB_INCLUDE):
            return False
    if SURFACE_MIN and (listing["surface"] is None or listing["surface"] < SURFACE_MIN):
        return False
    return True


def scrape_all() -> list[dict]:
    all_listings = []
    seen_ids = set()
    page = 1
    while page <= MAX_PAGES:
        url = page_url(SEARCH_URL, page)
        try:
            soup = fetch_page(url)
        except requests.RequestException as e:
            print(f"Erreur réseau page {page}: {e}", file=sys.stderr)
            break

        listings = parse_cards(soup)
        if not listings:
            break

        new_on_page = 0
        for listing in listings:
            if listing["id"] not in seen_ids:
                seen_ids.add(listing["id"])
                all_listings.append(listing)
                new_on_page += 1

        if new_on_page == 0:
            break

        page += 1

    return all_listings


# --------------------------------------------------------------------------
# État persistant
# --------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------

def send_email(new_listings: list[dict]) -> None:
    user = os.environ.get("GMAIL_USER")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    to_addr = os.environ.get("MAIL_TO", user)

    if not user or not app_password:
        print("GMAIL_USER / GMAIL_APP_PASSWORD manquants, email non envoyé.", file=sys.stderr)
        return

    lines = [f"{len(new_listings)} nouveau(x) logement(s) CROUS disponible(s) :\n"]
    for listing in new_listings:
        surface = f"{listing['surface']} m²" if listing["surface"] else "surface non précisée"
        price = f"{listing['price']} €" if listing["price"] else "prix non précisé"
        lines.append(f"- {listing['name']} ({surface}, {price})\n  {listing['url']}")

    body = "\n\n".join(lines)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"[CROUS] {len(new_listings)} nouveau(x) logement(s) disponible(s)"
    msg["From"] = user
    msg["To"] = to_addr

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, app_password)
        server.sendmail(user, [to_addr], msg.as_string())

    print(f"Email envoyé à {to_addr} ({len(new_listings)} annonce(s)).")


# --------------------------------------------------------------------------
# Récapitulatif consultable (page GitHub Pages)
# --------------------------------------------------------------------------

def render_recap(current_listings: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    rows = []
    for listing in sorted(current_listings, key=lambda l: (l["surface"] or 0), reverse=True):
        surface = f"{listing['surface']} m²" if listing["surface"] else "-"
        price = f"{listing['price']} €" if listing["price"] else "-"
        rows.append(
            f"<tr><td><a href='{listing['url']}' target='_blank'>{listing['name']}</a></td>"
            f"<td>{listing['postal']}</td><td>{surface}</td><td>{price}</td></tr>"
        )

    table_body = "\n".join(rows) if rows else "<tr><td colspan='4'>Aucun logement ne correspond aux critères actuellement.</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Veille logements CROUS</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
th, td {{ text-align: left; padding: 0.5rem; border-bottom: 1px solid #ddd; }}
th {{ background: #f5f5f5; }}
.meta {{ color: #666; font-size: 0.9rem; }}
</style>
</head>
<body>
<h1>Veille logements CROUS</h1>
<p class="meta">Dernière vérification : {now} — {len(current_listings)} logement(s) correspondant aux critères
(code postal {POSTAL_PREFIX or "tous"}, type {', '.join(COHAB_INCLUDE) or "tous"}{f", surface ≥ {SURFACE_MIN} m²" if SURFACE_MIN else ""}).</p>
<table>
<thead><tr><th>Résidence</th><th>Code postal</th><th>Surface</th><th>Prix</th></tr></thead>
<tbody>
{table_body}
</tbody>
</table>
</body>
</html>
"""
    RECAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECAP_PATH.write_text(html, encoding="utf-8")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    all_listings = scrape_all()
    matching = [l for l in all_listings if matches_filters(l)]

    print(f"{len(all_listings)} logement(s) trouvés au total, {len(matching)} correspondent aux critères.")

    state = load_state()
    known_ids = set(state.keys())
    current_ids = {l["id"] for l in matching}

    new_ids = current_ids - known_ids
    new_listings = [l for l in matching if l["id"] in new_ids]

    if new_listings:
        print(f"{len(new_listings)} nouveau(x) logement(s) détecté(s).")
        send_email(new_listings)
    else:
        print("Aucun nouveau logement.")

    # Met à jour l'état : on garde uniquement les logements toujours présents + les nouveaux
    new_state = {l["id"]: {"name": l["name"], "url": l["url"]} for l in matching}
    save_state(new_state)

    render_recap(matching)


if __name__ == "__main__":
    main()
