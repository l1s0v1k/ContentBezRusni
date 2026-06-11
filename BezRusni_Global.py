import asyncio
import re
import os
import time
import email.utils
import requests
import langdetect
from transliterate import translit
from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager, GlobalSystemMediaTransportControlsSession

BLACKLIST_URL = "https://raw.githubusercontent.com/placeholder/repo/main/blacklist.txt"

RU_LABELS = {
    "black star", "gazgolder", "rhymes music", "zhara music", 
    "vk records", "klever", "soyuz", "zvonko digital", 
    "effective records", "kaufman label", "music1", 
    "first music publishing", "cddk", "navigator records",
    "monolit", "nda sound", "zion music", "l'one", "velvet music",
    "atlantic records russia", "national digital aggregator"
}

RU_EXACT_WORDS = {
    "меня", "тебя", "что", "это", "мне", "тебе", "любовь", 
    "только", "если", "когда", "очень", "даже", "почему", 
    "здесь", "всегда", "никогда", "мимо", "сегодня", "теперь",
    "вообще", "конечно", "можно", "нельзя", "ничего", "сделать",
    "понять", "смотреть", "сказать",
    # Додані типові короткі слова, які відрізняються від українських
    "и", "да", "нет", "как", "где", "кто", "он", "она", "они", "их"
}

RU_ENDINGS = ["ое", "ие", "ее", "ую", "ого", "его"]

artist_cache: dict[str, str] = {}
mb_lock = asyncio.Lock()

def load_list(filename: str) -> set[str]:
    loaded_set = set()
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                name = line.strip().lower()
                if name:
                    loaded_set.add(name)
    return loaded_set

def sync_blacklist_sync() -> None:
    try:
        headers = {"User-Agent": "BezRusni/6.0"}
        if os.path.exists("global_blacklist.txt"):
            mtime = os.path.getmtime("global_blacklist.txt")
            http_date = email.utils.formatdate(mtime, usegmt=True)
            headers["If-Modified-Since"] = http_date
            
        resp = requests.get(BLACKLIST_URL, headers=headers, timeout=10)
        
        if resp.status_code == 200:
            with open("global_blacklist.txt", "w", encoding="utf-8") as f:
                f.write(resp.text)
            print("[System] Blacklist successfully updated from server.")
        elif resp.status_code == 304:
            pass
    except Exception:
        pass

async def sync_loop() -> None:
    while True:
        if BLACKLIST_URL != "https://raw.githubusercontent.com/placeholder/repo/main/blacklist.txt":
            await asyncio.to_thread(sync_blacklist_sync)
        await asyncio.sleep(86400)

def get_all_artists(artist_string: str) -> list[str]:
    # Прибрано \b після крапок, оскільки крапка не утворює межу слова (\b) з пробілом
    parts = re.split(r',|&|\bfeat\.|\bft\.|\bwith\b|\bі\b|\bта\b|\band\b', artist_string, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]

def clean_single_artist(name: str) -> str:
    name = re.sub(r'\(.*?\)', '', name)
    return name.strip()

def check_deezer_sync(artist: str, title: str) -> str:
    try:
        url = "https://api.deezer.com/search"
        params = {"q": f'artist:"{artist}" track:"{title}"'}
        resp = requests.get(url, params=params, headers={"User-Agent": "BezRusni/6.0"}, timeout=5)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        
        if data:
            track = data[0]
            album_id = track.get("album", {}).get("id")
            if album_id:
                album_url = f"https://api.deezer.com/album/{album_id}"
                album_resp = requests.get(album_url, headers={"User-Agent": "BezRusni/6.0"}, timeout=5)
                if album_resp.status_code == 200:
                    label = album_resp.json().get("label", "").lower()
                    if label:
                        for ru_label in RU_LABELS:
                            if ru_label in label:
                                return "RU"
        return "NONE"
    except Exception:
        return "NONE"

def check_wikidata_sync(artist: str) -> str:
    if not artist:
        return "NONE"
    if artist in artist_cache:
        return artist_cache[artist]
    try:
        search_url = "https://www.wikidata.org/w/api.php"
        search_params = {
            "action": "wbsearchentities",
            "search": artist,
            "language": "en",
            "format": "json",
            "limit": 1
        }
        search_resp = requests.get(search_url, params=search_params, headers={"User-Agent": "BezRusni/6.0"}, timeout=5)
        search_resp.raise_for_status()
        search_list = search_resp.json().get("search", [])
        if not search_list:
            artist_cache[artist] = "NONE"
            return "NONE"
            
        entity_id = search_list[0].get("id")
        if not entity_id:
            artist_cache[artist] = "NONE"
            return "NONE"
            
        entity_url = "https://www.wikidata.org/w/api.php"
        entity_params = {
            "action": "wbgetentities",
            "ids": entity_id,
            "props": "claims",
            "format": "json"
        }
        entity_resp = requests.get(entity_url, params=entity_params, headers={"User-Agent": "BezRusni/6.0"}, timeout=5)
        entity_resp.raise_for_status()
        claims = entity_resp.json().get("entities", {}).get(entity_id, {}).get("claims", {})
        
        p27 = claims.get("P27", []) # Громадянство (для людей)
        p103 = claims.get("P103", []) # Рідна мова
        p495 = claims.get("P495", []) # Країна походження (для гуртів)
        p17 = claims.get("P17", []) # Країна (додатково)
        
        all_claims = p27 + p103 + p495 + p17
        
        is_other = False
        for claim in all_claims:
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if isinstance(value, dict):
                target_id = value.get("id")
                if target_id in ("Q159", "Q7737"):
                    artist_cache[artist] = "RU"
                    return "RU"
                elif target_id in ("Q212", "Q9027"):
                    artist_cache[artist] = "UA"
                    return "UA"
                elif target_id:
                    is_other = True
                    
        if is_other:
            artist_cache[artist] = "OTHER"
            return "OTHER"
            
        artist_cache[artist] = "NONE"
        return "NONE"
    except Exception:
        return "NONE"

def check_musicbrainz_recording_sync(artist: str, title: str) -> str:
    try:
        url = "https://musicbrainz.org/ws/2/recording"
        query = f'recording:"{title}" AND artist:"{artist}"'
        params = {"query": query, "fmt": "json"}
        resp = requests.get(url, params=params, headers={"User-Agent": "BezRusni/6.0"}, timeout=5)
        resp.raise_for_status()
        recordings = resp.json().get("recordings", [])
        if not recordings:
            return "NONE"
        is_other = False
        for rec in recordings:
            for isrc_val in rec.get("isrcs", []):
                if isinstance(isrc_val, dict):
                    isrc = isrc_val.get("id", "").upper()
                else:
                    isrc = str(isrc_val).upper()
                    
                if isrc.startswith("RU"):
                    return "RU"
                if isrc.startswith("UA"):
                    return "UA"
                elif isrc:
                    is_other = True
            for credit in rec.get("artist-credit", []):
                area = credit.get("artist", {}).get("area", {}).get("name", "").lower()
                if area == "russia":
                    return "RU"
                if area == "ukraine":
                    return "UA"
                elif area:
                    is_other = True
                    
        if is_other:
            return "OTHER"
            
        return "NONE"
    except Exception:
        return "NONE"

async def safe_check_musicbrainz(artist: str, title: str) -> str:
    async with mb_lock:
        await asyncio.sleep(1.1)
        return await asyncio.to_thread(check_musicbrainz_recording_sync, artist, title)

async def check_artist_origin(artist: str, title: str) -> str:
    dz_res = await asyncio.to_thread(check_deezer_sync, artist, title)
    if dz_res != "NONE":
        return dz_res

    wiki_res = await asyncio.to_thread(check_wikidata_sync, artist)
    if wiki_res != "NONE":
        return wiki_res
        
    mb_res = await safe_check_musicbrainz(artist, title)
    if mb_res != "NONE":
        return mb_res
        
    if re.search(r'[а-яА-ЯёЁіІїЇєЄґҐ]', title) and not re.search(r'[а-яА-ЯёЁіІїЇєЄґҐ]', artist):
        try:
            cyrillic_artist = translit(artist, 'ru')
            if cyrillic_artist and cyrillic_artist != artist:
                dz_res_cyr = await asyncio.to_thread(check_deezer_sync, cyrillic_artist, title)
                if dz_res_cyr != "NONE":
                    return dz_res_cyr
                wiki_res_cyr = await asyncio.to_thread(check_wikidata_sync, cyrillic_artist)
                if wiki_res_cyr != "NONE":
                    return wiki_res_cyr
                mb_res_cyr = await safe_check_musicbrainz(cyrillic_artist, title)
                if mb_res_cyr != "NONE":
                    return mb_res_cyr
        except Exception:
            pass
            
    return "NONE"

async def process_track(session: GlobalSystemMediaTransportControlsSession, full_artist: str, title: str) -> None:
    whitelist = load_list("whitelist.txt")
    blacklist = load_list("global_blacklist.txt")
    
    if full_artist.lower() in whitelist:
        print(f"[Score: -100] {full_artist} - {title} -> Result (Safe) (Reason: Whitelist Track)")
        return

    score = 0
    reason = "None"
    text = f"{full_artist} {title}".lower()
    ru_unique = ['ё', 'ы', 'э', 'ъ']
    ua_unique = ['і', 'ї', 'є', 'ґ']

    # Ігноруємо самостійну літеру "і" (як сполучник), щоб уникнути хибного маркування треку
    # через українську локалізацію YouTube Music, яка додає "і" між іменами виконавців.
    text_for_ua_check = re.sub(r'\bі\b', '', text)

    if any(char in text for char in ru_unique):
        score = 100
        reason = "RU_UNIQUE_LETTERS"
    elif any(char in text_for_ua_check for char in ua_unique):
        score = -100
        reason = "UA_UNIQUE_LETTERS"
    else:
        words = re.findall(r'\b[а-яА-ЯёЁ]+\b', text)
        dict_hit = False
        for w in words:
            if w in RU_EXACT_WORDS:
                dict_hit = True
                break
            for ending in RU_ENDINGS:
                if w.endswith(ending) and len(w) > 3:
                    dict_hit = True
                    break
            if dict_hit:
                break
                
        if dict_hit:
            score += 50
            reason = "Dictionary RU Match"
        else:
            try:
                detected = langdetect.detect(text)
                if detected == 'ru':
                    # Знижено з 50 до 30, оскільки langdetect часто помиляється на коротких фразах 
                    # зі спільними словами (наприклад "за горизонтами"), що давало хибні блокування.
                    score += 30
                    reason = "LangDetect RU"
            except Exception:
                pass

    if score < 66 and score != -100:
        artists = get_all_artists(full_artist)
        artist_statuses = []
        
        for artist in artists:
            clean_name = clean_single_artist(artist)
            if not clean_name:
                continue
                
            if clean_name.lower() in blacklist:
                artist_statuses.append("RU")
                score = 100
                reason = f"Global Blacklist ({clean_name})"
                break
                
            if clean_name.lower() in whitelist:
                artist_statuses.append("WHITELIST")
                continue
                
            status = await check_artist_origin(clean_name, title)
            artist_statuses.append(status)
            
        if "WHITELIST" in artist_statuses:
            score = -100
            reason = "Collaborative Verification (Whitelist Artist Protected)"
        elif "RU" in artist_statuses and score != 100:
            score = 100
            reason = "Hard Evidence (RU Artist/Label Found)"
        elif score != 100:
            unknown_count = artist_statuses.count("NONE")
            ua_count = artist_statuses.count("UA")
            
            if unknown_count > 0:
                score += (25 * unknown_count)
                if reason == "None":
                    reason = f"Unknown Artist (+{25 * unknown_count})"
                else:
                    reason += f", Unknown Artist (+{25 * unknown_count})"
                    
            if ua_count > 0:
                score -= (15 * ua_count)
                reason += f", API UA Bonus (-{15 * ua_count})"

    if score > 65:
        print(f"[Score: {score}] {full_artist} - {title} -> Result (BANNED) (Reason: {reason})")
        await session.try_skip_next_async()
    else:
        if 40 <= score <= 65:
            reason = f"Grey Zone ({reason})"
        print(f"[Score: {score}] {full_artist} - {title} -> Result (Safe) (Reason: {reason if reason != 'None' else 'Under threshold'})")

async def monitor_media() -> None:
    manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
    last_track_id = ""
    
    asyncio.create_task(sync_loop())

    while True:
        try:
            session = manager.get_current_session()
            if session:
                props = await session.try_get_media_properties_async()
                if props:
                    artist = props.artist or ""
                    title = props.title or ""
                    current_track_id = f"{artist}-{title}"
                    
                    if current_track_id != last_track_id and (artist or title):
                        last_track_id = current_track_id
                        await process_track(session, artist, title)
        except Exception:
            pass
            
        await asyncio.sleep(1)

def main() -> None:
    asyncio.run(monitor_media())

if __name__ == "__main__":
    main()
