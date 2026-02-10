import os
import json
import requests
import feedparser
import time
import re
import random
import warnings 
import string
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
from groq import Groq, APIError

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning)

# --- GOOGLE INDEXING LIBS ---
try:
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False

# ==========================================
# ⚙️ CONFIGURATION & SETUP
# ==========================================

GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://beastion.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# TIM PENULIS (Persona)
AUTHOR_PROFILES = [
    "Dave Harsya (Senior Analyst)", "Sarah Jenkins (Chief Editor)",
    "Luca Romano (Transfer Specialist)", "Marcus Reynolds (Premier League Correspondent)",
    "Elena Petrova (Tactical Expert)", "Ben Foster (Sports Journalist)"
]

VALID_CATEGORIES = [
    "Transfer News", "Premier League", "Champions League", 
    "La Liga", "International", "Tactical Analysis"
]

RSS_SOURCES = {
    "SkySports": "https://www.skysports.com/rss/12040",
    "BBC Football": "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "ESPN FC": "https://www.espn.com/espn/rss/soccer/news",
    "Google News US": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-US&gl=US&ceid=US:en"
}

CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_SOURCE = 1 

# ==========================================
# 📸 MASSIVE UNSPLASH ID POOL (Backup)
# ==========================================
# Hanya ID-nya saja biar rapi. Script akan menyusun URL-nya.
UNSPLASH_IDS = {
    "stadium": [
        "1522778119026-d647f0565c6a", "1489944440615-453fc2b6a9a9", "1431324155629-1a6deb1dec8d", 
        "1579952363873-27f3bde9be2b", "1518091043644-c1d4457512c6", "1508098682722-e99c43a406b2",
        "1574629810360-7efbbe195018", "1577223625816-7546f13df25d", "1624880357913-a85cbdec04ca"
    ],
    "player": [
        "1516246844974-e39556ee0945", "1627341852895-467406c55cc0", "1628891544265-2766863640b3",
        "1575361204480-aadea25e6e68", "1636232707255-08cc5a65383f", "1551958219-acbc608c6377",
        "1543796076-bb4d48d0a87a", "1504450758481-7338abc0f511", "1526232761682-d26e03ac148e"
    ],
    "generic": [
        "1552667466-07770ae110d0", "1614632537202-608f060a1201", "1560008516-22462875355a",
        "1517466787929-bc90951d0974", "1556388169-583b27b40929", "1576921350172-10b27152069b"
    ]
}

# ==========================================
# 🧠 HELPER FUNCTIONS
# ==========================================
def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try:
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/articles/{slug}" 
    if len(memory) > 200: memory = dict(list(memory.items())[-200:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_internal_links_markdown():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    count = min(4, len(items))
    selected_items = random.sample(items, count)
    return "\n".join([f"- [{title}]({url})" for title, url in selected_items])

def fetch_rss_feed(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        return feedparser.parse(response.content) if response.status_code == 200 else None
    except: return None

# ==========================================
# 🎨 ADVANCED IMAGE ENGINE
# ==========================================
def apply_heavy_modification(img):
    """Membuat gambar unik dengan Vignette + Color Grading + Noise"""
    
    # 1. Flip Horizontal (Random)
    if random.random() > 0.5:
        img = ImageOps.mirror(img)

    # 2. Color Grading (Saturation & Contrast)
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(random.uniform(0.8, 1.3)) # Sedikit pudar atau vivid
    
    enhancer_c = ImageEnhance.Contrast(img)
    img = enhancer_c.enhance(random.uniform(0.9, 1.15))

    # 3. Add Vignette (Gelap di pinggir) - Anti Duplicate Check
    width, height = img.size
    # Buat layer hitam transparan
    vignette = Image.new('L', (width, height), 0)
    # Gambar lingkaran putih di tengah
    from PIL import ImageDraw
    draw = ImageDraw.Draw(vignette)
    draw.ellipse((20, 20, width-20, height-20), fill=255)
    # Blur lingkaran agar jadi gradasi
    vignette = vignette.filter(ImageFilter.GaussianBlur(100))
    # Gabungkan
    img = ImageOps.colorize(vignette, (10, 10, 10), (255, 255, 255)) # Ini trik composite sederhana
    
    # Resize sedikit untuk mengubah hash pixel
    img = img.resize((1200, 675), Image.Resampling.LANCZOS)
    
    return img

def generate_hybrid_image(query, filename):
    """Mencoba AI dulu, jika gagal baru pakai Unsplash Pool"""
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # --- STRATEGI 1: AI GENERATION (Prioritas - 100% Unik) ---
    print(f"      🎨 Strategy 1: AI Generating '{query}'...")
    
    # Prompt trick: Fokus ke atmosfer stadion/lapangan agar wajah tidak aneh
    safe_prompt = f"cinematic shot of {query} football match atmosphere, stadium lights, blurred crowd, ultra realistic, 4k, sports photography --ar 16:9".replace(" ", "%20")
    
    # Random seed memastikan gambar beda tiap kali request
    seed = random.randint(1, 1000000)
    ai_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1200&height=675&model=flux-realism&seed={seed}&nologo=true"
    
    try:
        resp = requests.get(ai_url, timeout=45)
        if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            
            # Tetap lakukan sedikit modifikasi
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.2)
            
            img.save(output_path, "WEBP", quality=85)
            print("      ✅ AI Image Created!")
            return f"/images/{filename}"
    except Exception as e:
        print(f"      ⚠️ AI Failed ({e}). Switching to Strategy 2.")

    # --- STRATEGI 2: UNSPLASH POOL + MODIFIKASI (Backup) ---
    print("      🎨 Strategy 2: Unsplash Pool + Modding")
    
    # Pilih ID berdasarkan query (sederhana)
    if any(x in query.lower() for x in ['stadium', 'fan', 'arena', 'match']):
        pool = UNSPLASH_IDS['stadium']
    elif any(x in query.lower() for x in ['player', 'coach', 'manager', 'transfer']):
        pool = UNSPLASH_IDS['player']
    else:
        pool = UNSPLASH_IDS['generic']
    
    selected_id = random.choice(pool)
    unsplash_url = f"https://images.unsplash.com/photo-{selected_id}?auto=format&fit=crop&w=1200&q=80"
    
    try:
        resp = requests.get(unsplash_url, timeout=15)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            
            # TERAPKAN MODIFIKASI BERAT AGAR UNIK
            img = apply_heavy_modification(img)
            
            img.save(output_path, "WEBP", quality=85)
            print("      ✅ Unsplash Image Modified & Saved!")
            return f"/images/{filename}"
    except: pass
    
    # Last Resort
    return "https://images.unsplash.com/photo-1522778119026-d647f0565c6a?auto=format&fit=crop&w=1200"

# ==========================================
# 🧠 AI WRITER
# ==========================================
def get_groq_article_json(title, summary, link, author_name):
    # Dapatkan tanggal hari ini agar tidak halusinasi berita masa depan
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    system_prompt = f"""
    You are {author_name}, a professional sports journalist. DATE: {current_date}.
    
    TASK: Write a 1000-word news article.
    
    RULES:
    1. REALISM: If the match hasn't happened yet (check date), write a PREVIEW/PREDICTION. If passed, write REPORT.
    2. NO FAKE QUOTES: Do not invent quotes. Use general analysis.
    3. FORMAT: Valid JSON.
    
    OUTPUT JSON:
    {{
        "title": "Journalistic Headline",
        "description": "SEO Description",
        "category": "One of {VALID_CATEGORIES}",
        "main_keyword": "Main Subject for Image Gen (e.g. Old Trafford Stadium)",
        "tags": ["tag1", "tag2"],
        "content_body": "Markdown content with H2, H3, and Bold text."
    }}
    """
    
    user_prompt = f"Topic: {title}\nSnippet: {summary}\nRef: {link}"
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name})...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=6500,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            time.sleep(2)
        except Exception as e:
            print(f"      ⚠️ Groq Error: {e}")
            
    return None

# ==========================================
# 🏁 MAIN WORKFLOW
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    print("🔥 ENGINE STARTED: Hybrid Image & Anti-Hallucination Mode")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Reading: {source_name}")
        feed = fetch_rss_feed(rss_url)
        if not feed: continue

        processed = 0
        for entry in feed.entries:
            if processed >= TARGET_PER_SOURCE: break
            
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"
            
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): continue
            
            print(f"   ⚡ Processing: {clean_title[:40]}...")
            
            # 1. Generate Text
            author = random.choice(AUTHOR_PROFILES)
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, author)
            
            if not raw_json: continue
            
            try:
                data = json.loads(raw_json)
            except:
                print("      ❌ JSON Error")
                continue

            # 2. Generate Image (Hybrid Strategy)
            img_query = data.get('main_keyword') or clean_title
            # Tambahkan kata 'Stadium' atau 'Match' biar AI bikin gambar wide shot yang bagus
            if "stadium" not in img_query.lower() and "match" not in img_query.lower():
                img_query += " football match action"
                
            final_img = generate_hybrid_image(img_query, f"{slug}.webp")
            
            # 3. Internal Linking
            links_md = get_internal_links_markdown()
            # Inject link di akhir artikel
            body_content = data['content_body'] + "\n\n### Read More\n" + links_md

            # 4. Save Markdown
            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "International"

            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")}
author: "{author}"
categories: ["{data['category']}"]
tags: {json.dumps(data.get('tags', []))}
featured_image: "{final_img}"
description: "{data['description'].replace('"', "'")}"
slug: "{slug}"
draft: false
weight: {random.randint(1, 10)}
---

{body_content}

---
*Source: Analysis by {author} based on coverage from [{source_name}]({entry.link}).*
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            save_link_to_memory(data['title'], slug)
            
            # 5. Indexing (Optional)
            full_url = f"{WEBSITE_URL}/articles/{slug}/"
            if GOOGLE_LIBS_AVAILABLE:
                try:
                    submit_to_indexnow(full_url) # type: ignore
                    from oauth2client.service_account import ServiceAccountCredentials
                    from googleapiclient.discovery import build
                    # (Code indexing google di sini...)
                except: pass

            print(f"      ✅ Published: {slug}")
            processed += 1
            time.sleep(3)

if __name__ == "__main__":
    main()
