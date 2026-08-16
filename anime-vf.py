#!/usr/bin/env python3
import re
import sys
import shutil
import subprocess
import threading
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import customtkinter as ctk

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

BASE_URL = "https://anime-sama.to"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Referer": f"{BASE_URL}/"
}

def get_available_seasons(catalogue_url):
    """Analyse le catalogue et détecte automatiquement les versions VOSTFR et VF disponibles."""
    try:
        res = requests.get(catalogue_url, headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return []
            
        found_seasons = []
        matches = re.findall(r"panneauAnime\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)", res.text)
        
        base_path = catalogue_url.rstrip('/')
        for season, version in matches:
            url = f"{base_path}/{season}/{version}/"
            if url not in found_seasons:
                found_seasons.append(url)
        
        if not found_seasons:
            soup = BeautifulSoup(res.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if any(k in href.lower() for k in ['saison', 'film', 'oav', 'special']):
                    full_url = urljoin(catalogue_url, href)
                    if full_url not in found_seasons:
                        found_seasons.append(full_url)
                        
        # pour chaque saison trouvée, vérifier si l'autre version (VF/VOSTFR) existe via les liens de switch
        expanded_seasons = set(found_seasons)
        for url in found_seasons:
            clean_url = url.rstrip('/')
            if clean_url.endswith('/vostfr'):
                vf_variant = clean_url[:-7] + '/vf/'
                expanded_seasons.add(vf_variant)
            elif clean_url.endswith('/vf'):
                vostfr_variant = clean_url[:-3] + '/vostfr/'
                expanded_seasons.add(vostfr_variant)
            else:
                # Si l'URL n'a pas explicitement de suffixe de version, on teste les deux
                expanded_seasons.add(f"{clean_url}/vostfr/")
                expanded_seasons.add(f"{clean_url}/vf/")

        # Filtrer uniquement les URLs valides (qui répondent en 200)
        valid_seasons = []
        for url in sorted(list(expanded_seasons)):
            try:
                r = requests.head(url, headers=HEADERS, timeout=3)
                if r.status_code == 200:
                    valid_seasons.append(url)
                else:
                    # Fallback GET si HEAD est bloqué
                    r2 = requests.get(url, headers=HEADERS, timeout=4)
                    if r2.status_code == 200:
                        valid_seasons.append(url)
            except:
                # En cas de doute, on l'ajoute pour laisser une chance
                valid_seasons.append(url)

        return valid_seasons if valid_seasons else sorted(list(found_seasons))
    except Exception as e:
        print(f"Erreur catalogue: {e}")
        return []

def format_season_label(url):
    parts = [p for p in url.split('/') if p]
    if not parts:
        return "Saison principale"
    
    version = parts[-1].upper() if parts[-1] in ['vf', 'vostfr'] else ""
    saison_part = ""
    
    for p in reversed(parts):
        if p.lower() not in ['vf', 'vostfr', 'catalogue']:
            saison_part = p.replace('-', ' ').capitalize()
            break
            
    if version:
        return f"{saison_part} ({version})"
    return saison_part

def get_player_name(sample_url):
    sample_lower = sample_url.lower()
    if "sibnet" in sample_lower: return "Sibnet (Recommandé)"
    if "voe" in sample_lower: return "Voe"
    if "sendvid" in sample_lower: return "Sendvid"
    if "ansembed" in sample_lower or "vmpx" in sample_lower or "embed4me" in sample_lower: return "Ansembed / Vmpx"
    if "vk.com" in sample_lower: return "VK"
    return sample_url.split('/')[2] if '://' in sample_url else "Lecteur inconnu"

def parse_episodes_from_text(text, is_vf_requested, is_strictly_vf_source):
    lecteurs = {}
    matches = re.findall(r"(?:var|let|const)?\s*(eps[\w_]*)\s*=\s*\[(.*?)\]", text, re.DOTALL)
    for var_name, array_content in matches:
        var_name_lower = var_name.lower()
        var_is_vf = 'vf' in var_name_lower
        var_is_vostfr = 'vostfr' in var_name_lower
        
        if is_vf_requested:
            if not is_strictly_vf_source and not var_is_vf: continue
            if var_is_vostfr: continue
        else:
            if var_is_vf or is_strictly_vf_source: continue
            
        urls = re.findall(r"https?://[^\s'\",]+", array_content)
        if urls:
            base_label = get_player_name(urls[0])
            player_label = base_label
            counter = 2
            while player_label in lecteurs:
                player_label = f"{base_label} ({counter})"
                counter += 1
            lecteurs[player_label] = urls
    return lecteurs

def extract_episodes_from_page(page_url):
    if not page_url.endswith('/'): page_url += '/'
    is_vf_requested = '/vf/' in page_url.lower()
    
    clean_path_match = re.search(r'(saison[^/]+|film[^/]+|oav[^/]+|special[^/]+)/(vf|vostfr)/', page_url, re.IGNORECASE)
    
    js_urls_to_try = []
    if clean_path_match:
        base_catalogue = page_url.split('/catalogue/')[0] + '/catalogue/' + page_url.split('/catalogue/')[1].split('/')[0] + '/'
        sub_saison_version = clean_path_match.group(0)
        target_base = base_catalogue + sub_saison_version
        
        js_urls_to_try = [
            target_base + "episodes.js",
            target_base + "episodesVF.js",
            page_url + "episodes.js",
            page_url + "episodesVF.js"
        ]
    else:
        js_urls_to_try = [page_url + "episodes.js", page_url + "episodesVF.js"]

    for js_url in js_urls_to_try:
        try:
            res = requests.get(js_url, headers=HEADERS, timeout=10)
            if res.status_code == 200:
                is_strictly_vf = "vf" in js_url.lower()
                lecteurs = parse_episodes_from_text(res.text, is_vf_requested, is_strictly_vf)
                if lecteurs: return lecteurs
        except:
            continue
            
    try:
        res = requests.get(page_url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            lecteurs = parse_episodes_from_text(res.text, is_vf_requested, '/vf/' in page_url.lower())
            if lecteurs: return lecteurs
    except:
        pass
        
    return {}

def play_with_mpv(embed_url):
    referer = f"{BASE_URL}/"
    if any(x in embed_url for x in ["ansembed", "vmpx", "embed4me", "ant"]):
        referer = "https://ansembed.net/"
    elif "sibnet" in embed_url:
        referer = "https://video.sibnet.ru/"
    elif "voe.sx" in embed_url or "voe" in embed_url:
        referer = "https://voe.sx/"

    mpv_cmd = [
        "mpv",
        "--cache=yes",
        "--demuxer-max-bytes=150M",
        "--demuxer-readahead-secs=120",
        f"--ytdl-raw-options=referer={referer}",
        embed_url
    ]
    subprocess.run(mpv_cmd)


class AnimeApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("ScrapSama")
        self.geometry("600x620")
        self.resizable(False, False)

        self.seasons_data = []
        self.lecteurs_data = {}
        self.episodes_list = []

        self.title_label = ctk.CTkLabel(self, text="ScrapSama", font=ctk.CTkFont(size=22, weight="bold"))
        self.title_label.pack(pady=(15, 5))

        self.search_frame = ctk.CTkFrame(self)
        self.search_frame.pack(fill="x", padx=30, pady=5)

        self.entry_anime = ctk.CTkEntry(self.search_frame, placeholder_text="Ex: naruto, fire force...", width=380)
        self.entry_anime.pack(side="left", padx=(10, 10), pady=10)

        self.btn_search = ctk.CTkButton(self.search_frame, text="Rechercher", command=self.start_search_thread)
        self.btn_search.pack(side="left", padx=10, pady=10)

        self.status_label = ctk.CTkLabel(self, text="Entrez le nom d'un anime pour commencer", text_color="gray")
        self.status_label.pack(pady=2)

        self.lbl_season = ctk.CTkLabel(self, text="Saison / Version :")
        self.lbl_season.pack(anchor="w", padx=40, pady=(5, 2))
        self.combo_seasons = ctk.CTkOptionMenu(self, values=["---"], command=self.on_season_selected, state="disabled", width=520)
        self.combo_seasons.pack(padx=30, pady=(0, 5))

        self.lbl_player = ctk.CTkLabel(self, text="Lecteur :")
        self.lbl_player.pack(anchor="w", padx=40, pady=(5, 2))
        self.combo_players = ctk.CTkOptionMenu(self, values=["---"], command=self.on_player_selected, state="disabled", width=520)
        self.combo_players.pack(padx=30, pady=(0, 5))

        self.lbl_ep = ctk.CTkLabel(self, text="Épisode :")
        self.lbl_ep.pack(anchor="w", padx=40, pady=(5, 2))
        self.combo_episodes = ctk.CTkOptionMenu(self, values=["---"], state="disabled", width=520)
        self.combo_episodes.pack(padx=30, pady=(0, 10))

        self.btn_play = ctk.CTkButton(self, text="Lancer la vidéo (MPV)", font=ctk.CTkFont(size=15, weight="bold"), height=40, fg_color="green", hover_color="darkgreen", command=self.start_play_thread, state="disabled")
        self.btn_play.pack(fill="x", padx=30, pady=(10, 5))

        self.btn_quit = ctk.CTkButton(self, text="Quitter", font=ctk.CTkFont(size=14), height=35, fg_color="#b91c1c", hover_color="#991b1b", command=self.destroy)
        self.btn_quit.pack(fill="x", padx=30, pady=(5, 15))

    def set_status(self, text, color="white"):
        self.status_label.configure(text=text, text_color=color)

    def start_search_thread(self):
        query = self.entry_anime.get().strip().lower().replace(" ", "-")
        if not query:
            self.set_status("Veuillez entrer un nom d'anime", "red")
            return

        self.btn_search.configure(state="disabled")
        self.set_status("Recherche des saisons et versions...", "yellow")
        
        catalogue_url = f"{BASE_URL}/catalogue/{query}/"
        threading.Thread(target=self.search_anime, args=(catalogue_url,), daemon=True).start()

    def search_anime(self, catalogue_url):
        self.seasons_data = get_available_seasons(catalogue_url)
        
        if not self.seasons_data:
            self.after(0, lambda: self.set_status("Aucune saison trouvée pour cet anime", "red"))
            self.after(0, lambda: self.btn_search.configure(state="normal"))
            return

        season_labels = [format_season_label(url) for url in self.seasons_data]
        self.after(0, lambda: self.update_seasons_ui(season_labels))

    def update_seasons_ui(self, season_labels):
        self.combo_seasons.configure(values=season_labels, state="normal")
        self.combo_seasons.set(season_labels[0])
        self.btn_search.configure(state="normal")
        self.set_status(f"{len(season_labels)} option(s) de saison/version trouvée(s)", "green")
        self.on_season_selected(season_labels[0])

    def on_season_selected(self, choice):
        try:
            idx = self.combo_seasons.cget("values").index(choice)
            target_url = self.seasons_data[idx]
        except ValueError:
            return
        
        self.set_status("Chargement des lecteurs et épisodes...", "yellow")
        self.combo_players.configure(state="disabled", values=["---"])
        self.combo_players.set("---")
        self.combo_episodes.configure(state="disabled", values=["---"])
        self.combo_episodes.set("---")
        self.btn_play.configure(state="disabled")

        threading.Thread(target=self.load_episodes, args=(target_url,), daemon=True).start()

    def load_episodes(self, target_url):
        self.lecteurs_data = extract_episodes_from_page(target_url)
        
        if self.lecteurs_data:
            player_names = list(self.lecteurs_data.keys())
            self.after(0, lambda: self.update_players_ui(player_names))
        else:
            self.after(0, lambda: self.set_status("Aucun lecteur/épisode trouvé pour cette version", "red"))

    def update_players_ui(self, player_names):
        self.combo_players.configure(values=player_names, state="normal")
        self.combo_players.set(player_names[0])
        self.set_status("Épisodes chargés avec succès", "green")
        self.on_player_selected(player_names[0])

    def on_player_selected(self, player_choice):
        self.episodes_list = self.lecteurs_data.get(player_choice, [])
        ep_choices = [f"Épisode {i+1}" for i in range(len(self.episodes_list))]
        
        if ep_choices:
            self.combo_episodes.configure(values=ep_choices, state="normal")
            self.combo_episodes.set(ep_choices[0])
            self.btn_play.configure(state="normal")

    def start_play_thread(self, event=None):
        selected_ep_text = self.combo_episodes.get()
        try:
            ep_idx = int(selected_ep_text.split(" ")[1]) - 1
            embed_url = self.episodes_list[ep_idx]
        except (IndexError, ValueError):
            return

        self.set_status(f"Lecture de l'épisode {ep_idx + 1} dans MPV...", "cyan")
        threading.Thread(target=play_with_mpv, args=(embed_url,), daemon=True).start()


if __name__ == "__main__":
    if not shutil.which("mpv"):
        print("[Erreur] mpv n'est pas installé sur le système.")
        sys.exit(1)
        
    app = AnimeApp()
    app.mainloop()
    
    ###note du dev: les commentaires ont été rédigés par copilot vscode 'trop la flemme' (^__^)
    ###pour tout signalement de bug me contacter: neodark271@gmail.com
