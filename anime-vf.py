#!/usr/bin/env python3
import re
import sys
import subprocess
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://anime-sama.to"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Referer": f"{BASE_URL}/"
}

def get_player_name(sample_url):
    """Identifie le nom du lecteur vidéo pour un affichage clair"""
    if "sibnet" in sample_url:
        return "Sibnet (Recommandé - Stable)"
    elif "ansembed" in sample_url or "vmpx" in sample_url:
        return "Ansembed / Vmpx"
    elif "sendvid" in sample_url:
        return "Sendvid"
    elif "vk.com" in sample_url:
        return "VK"
    elif "voe" in sample_url:
        return "Voe"
    else:
        # Extrait le nom de domaine par défaut
        return sample_url.split('/')[2] if '://' in sample_url else "Lecteur inconnu"

def parse_episodes_js(js_content):
    lecteurs = {}
    matches = re.findall(r"var\s+(eps\d+)\s*=\s*\[(.*?)\];", js_content, re.DOTALL)
    
    for var_name, array_content in matches:
        urls = re.findall(r"https?://[^\s'\",]+", array_content)
        if urls:
            player_label = get_player_name(urls[0])
            lecteurs[player_label] = urls
            
    return lecteurs

def extract_episodes_from_page(page_url):
    if not page_url.endswith('/'):
        page_url += '/'
        
    js_url = page_url + "episodes.js"
    print(f"Lecture de : {js_url}")
    res = requests.get(js_url, headers=HEADERS)
    
    if res.status_code != 200:
        print(f"Impossible de charger {js_url} (HTTP {res.status_code})")
        return {}

    return parse_episodes_js(res.text)

def get_available_seasons(catalogue_url):
    print(f"🔍 Scan de la page principale : {catalogue_url}")
    res = requests.get(catalogue_url, headers=HEADERS)
    if res.status_code != 200:
        return []
        
    soup = BeautifulSoup(res.text, 'html.parser')
    seasons = []
    
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/saison' in href or '/vf' in href or '/vostfr' in href:
            full_url = href if href.startswith('http') else BASE_URL + href
            if full_url not in seasons and full_url != catalogue_url:
                seasons.append(full_url)
                
    return seasons

def play_with_mpv(embed_url):
    print(f"\n🎬 Lancement dans MPV...")
    print(f"🔗 Flux : {embed_url}")
    
    user_agent = HEADERS['User-Agent']
    
    # Adapte le Referer en fonction du serveur hôte pour éviter la 403 CDN
    if "ansembed" in embed_url or "vmpx" in embed_url:
        referer = "https://ansembed.net/"
    elif "sibnet" in embed_url:
        referer = "https://video.sibnet.ru/"
    else:
        referer = f"{BASE_URL}/"
    
    mpv_cmd = [
        "mpv",
        f"--http-header-fields=Referer: {referer}, User-Agent: {user_agent}",
        f"--ytdl-raw-options=referer={referer},user-agent={user_agent}",
        embed_url
    ]
    subprocess.run(mpv_cmd)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python anime-vf.py <nom-de-l-anime> OU <URL>")
        sys.exit(1)
        
    input_arg = sys.argv[1]
    
    if input_arg.startswith("http"):
        target_url = input_arg
    else:
        query = "-".join(sys.argv[1:]).lower()
        catalogue_url = f"{BASE_URL}/catalogue/{query}/"
        
        seasons = get_available_seasons(catalogue_url)
        if seasons:
            print("\nSaisons / Versions disponibles :")
            for idx, s_url in enumerate(seasons):
                short_name = s_url.rstrip('/').split('/')[-2:]
                print(f"[{idx + 1}] {'/'.join(short_name)}")
                
            choice = int(input("\nChoisis une version (numéro) : ")) - 1
            target_url = seasons[choice]
        else:
            target_url = f"{catalogue_url}saison1/vf/"

    lecteurs = extract_episodes_from_page(target_url)
    
    if lecteurs:
        print("\nLecteurs disponibles :")
        lecteur_keys = list(lecteurs.keys())
        for idx, key in enumerate(lecteur_keys):
            print(f"[{idx + 1}] {key} ({len(lecteurs[key])} épisodes)")
            
        l_choice = int(input("\nChoisis un lecteur (ex: 1) : ")) - 1
        selected_lecteur = lecteur_keys[l_choice]
        ep_list = lecteurs[selected_lecteur]
        
        ep_num = int(input(f"Numéro de l'épisode (1 à {len(ep_list)}) : ")) - 1
        if 0 <= ep_num < len(ep_list):
            play_with_mpv(ep_list[ep_num])
        else:
            print("Numéro d'épisode invalide.")
    else:
        print("Aucun lecteur / épisode trouvé à cette adresse.")
        print("veuillez relancer le script svp")