#!/usr/bin/env python3
import re
import sys
import shutil
import subprocess
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Support vocal optionnel
try:
    import speech_recognition as sr
    VOICE_SUPPORTED = True
except ImportError:
    VOICE_SUPPORTED = False

BASE_URL = "https://anime-sama.to"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Referer": f"{BASE_URL}/"
}

def check_dependencies(use_voice=False):
    """Vérifie si mpv, yt-dlp et les bibliothèques vocales sont disponibles"""
    missing = []
    if not shutil.which("mpv"):
        missing.append("mpv")
    if not shutil.which("yt-dlp"):
        missing.append("yt-dlp")
        
    if missing:
        print(f"[Erreur] Dépendances manquantes -> {', '.join(missing)}")
        print("[Note] Installez-les avec votre gestionnaire de paquets (ex: sudo apt install mpv yt-dlp)")
        sys.exit(1)

    if use_voice and not VOICE_SUPPORTED:
        print("[Avertissement] Module de reconnaissance vocale manquant.")
        print("[Note] Installez les modules requis : pip install SpeechRecognition pyaudio")

def parse_number(text):
    """Convertit un texte vocal (chiffre ou mot) en entier"""
    text = text.strip().lower()
    word_to_num = {
        "un": 1, "une": 1, "premier": 1, "première": 1,
        "deux": 2, "second": 2, "seconde": 2,
        "trois": 3, "quatre": 4, "cinq": 5,
        "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10
    }
    if text in word_to_num:
        return word_to_num[text]
    
    numbers = re.findall(r'\d+', text)
    if numbers:
        return int(numbers[0])
    return None

def get_input(prompt_text, use_voice=False):
    """Récupère la saisie via le micro si activé, sinon via le clavier"""
    if use_voice and VOICE_SUPPORTED:
        recognizer = sr.Recognizer()
        with sr.Microphone() as source:
            print(f"\n[Vocal] {prompt_text} (Parlez maintenant...)")
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = recognizer.listen(source, timeout=6, phrase_time_limit=5)
                text = recognizer.recognize_google(audio, language="fr-FR")
                print(f"[Vocal] Compris : \"{text}\"")
                return text
            except sr.WaitTimeoutError:
                print("[Vocal] Aucun son détecté. Passage au clavier.")
            except sr.UnknownValueError:
                print("[Vocal] Parole non comprise. Passage au clavier.")
            except Exception as e:
                print(f"[Vocal] Erreur micro ({e}). Passage au clavier.")

    return input(f"{prompt_text} : ")

def get_player_name(sample_url):
    """Identifie l'hébergeur vidéo à partir de l'URL"""
    if "sibnet" in sample_url:
        return "Sibnet (Recommandé)"
    elif "ansembed" in sample_url or "vmpx" in sample_url:
        return "Ansembed / Vmpx"
    elif "sendvid" in sample_url:
        return "Sendvid"
    elif "vk.com" in sample_url:
        return "VK"
    elif "voe" in sample_url:
        return "Voe"
    else:
        return sample_url.split('/')[2] if '://' in sample_url else "Lecteur inconnu"

def get_available_seasons(catalogue_url):
    """Scanne la page principale d'un anime pour trouver toutes les saisons/versions"""
    print(f"[*] Scan de l'anime : {catalogue_url}")
    try:
        res = requests.get(catalogue_url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return []
            
        seasons = []
        soup = BeautifulSoup(res.text, 'html.parser')
        
        candidates = []
        for a in soup.find_all('a', href=True):
            candidates.append(a['href'])
        for elem in soup.find_all(['option', 'button', 'div'], value=True):
            candidates.append(elem['value'])
            
        regex_matches = re.findall(r'["\']([^"\']*(?:saison|film|oav|vostfr|/vf)[^"\']*)["\']', res.text, re.IGNORECASE)
        candidates.extend(regex_matches)
        
        for item in candidates:
            if any(item.endswith(ext) for ext in ['.js', '.css', '.png', '.jpg', '.jpeg', '.svg', '.webp']):
                continue
                
            full_url = urljoin(catalogue_url, item).split('#')[0].split('?')[0]
            if not full_url.endswith('/'):
                full_url += '/'
                
            if full_url.startswith(catalogue_url) and full_url != catalogue_url:
                if full_url not in seasons:
                    seasons.append(full_url)
                    
        seasons.sort()
        return seasons
    except Exception as e:
        print(f"[Erreur] Lors du scan des saisons : {e}")
        return []

def parse_episodes_js(js_content):
    """Parse le fichier JavaScript contenant les liens des épisodes"""
    lecteurs = {}
    matches = re.findall(r"var\s+(eps\d+)\s*=\s*\[(.*?)\];", js_content, re.DOTALL)
    
    for var_name, array_content in matches:
        urls = re.findall(r"https?://[^\s'\",]+", array_content)
        if urls:
            player_label = get_player_name(urls[0])
            lecteurs[player_label] = urls
            
    return lecteurs

def extract_episodes_from_page(page_url):
    """Charge le fichier episodes.js de la saison sélectionnée"""
    if not page_url.endswith('/'):
        page_url += '/'
        
    js_url = page_url + "episodes.js"
    print(f"[*] Chargement des épisodes : {js_url}")
    
    try:
        res = requests.get(js_url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return {}
        return parse_episodes_js(res.text)
    except Exception as e:
        print(f"[Erreur] Connexion échouée : {e}")
        return {}

def play_with_mpv(embed_url, in_terminal=False):
    """Lance MPV avec un buffer RAM pour éviter les coupures"""
    print(f"\n[+] Lancement de la vidéo...")
    user_agent = HEADERS['User-Agent']
    
    if "ansembed" in embed_url or "vmpx" in embed_url:
        referer = "https://ansembed.net/"
    elif "sibnet" in embed_url:
        referer = "https://video.sibnet.ru/"
    else:
        referer = f"{BASE_URL}/"
    
    mpv_cmd = [
        "mpv",
        "--cache=yes",
        "--demuxer-max-bytes=150M",
        "--demuxer-readahead-secs=120",
        f"--http-header-fields=Referer: {referer}, User-Agent: {user_agent}",
        f"--ytdl-raw-options=referer={referer},user-agent={user_agent}",
        embed_url
    ]
    
    if in_terminal:
        mpv_cmd.insert(1, "--vo=tct")

    subprocess.run(mpv_cmd)

if __name__ == "__main__":
    in_terminal = "--terminal" in sys.argv or "-t" in sys.argv
    use_voice = "--voice" in sys.argv or "-v" in sys.argv
    
    flags = ["--terminal", "-t", "--voice", "-v"]
    args = [arg for arg in sys.argv[1:] if arg not in flags]
    
    check_dependencies(use_voice=use_voice)
    
    if not args:
        print("Usage:")
        print("  anime-vf <nom-de-l-anime>             (Mode standard)")
        print("  anime-vf <nom-de-l-anime> -v          (Mode vocal)")
        print("  anime-vf <nom-de-l-anime> -t -v       (Mode vocal + terminal)")
        sys.exit(1)
        
    input_arg = args[0]
    
    if input_arg.startswith("http"):
        target_url = input_arg
    else:
        query = "-".join(args).lower()
        catalogue_url = f"{BASE_URL}/catalogue/{query}/"
        
        seasons = get_available_seasons(catalogue_url)
        
        if seasons:
            print("\nSaisons / Versions disponibles :")
            for idx, s_url in enumerate(seasons):
                short_name = s_url.replace(catalogue_url, "").rstrip('/')
                print(f"[{idx + 1}] {short_name}")
                
            raw_choice = get_input("Choisis une saison/version (numéro)", use_voice=use_voice)
            num_choice = parse_number(raw_choice)
            
            if num_choice and 1 <= num_choice <= len(seasons):
                target_url = seasons[num_choice - 1]
            else:
                print("[Erreur] Choix invalide, sélection par défaut de la première option.")
                target_url = seasons[0]
        else:
            target_url = f"{catalogue_url}saison1/vf/"

    lecteurs = extract_episodes_from_page(target_url)
    
    if lecteurs:
        print("\nLecteurs disponibles :")
        lecteur_keys = list(lecteurs.keys())
        for idx, key in enumerate(lecteur_keys):
            print(f"[{idx + 1}] {key} ({len(lecteurs[key])} épisodes)")
            
        raw_choice = get_input("Choisis un lecteur (ex: 1)", use_voice=use_voice)
        num_choice = parse_number(raw_choice)
        
        if num_choice and 1 <= num_choice <= len(lecteur_keys):
            selected_lecteur = lecteur_keys[num_choice - 1]
        else:
            print("[Erreur] Choix invalide, sélection par défaut du premier lecteur.")
            selected_lecteur = lecteur_keys[0]
            
        ep_list = lecteurs[selected_lecteur]
        
        raw_ep = get_input(f"Numéro de l'épisode (1 à {len(ep_list)})", use_voice=use_voice)
        ep_num = parse_number(raw_ep)
        
        if ep_num and 1 <= ep_num <= len(ep_list):
            play_with_mpv(ep_list[ep_num - 1], in_terminal=in_terminal)
        else:
            print("[Erreur] Numéro d'épisode invalide.")
    else:
        print("[Erreur] Aucun épisode ou anime trouvé à cette adresse.")
