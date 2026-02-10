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
from groq import Groq, APIError, RateLimitError

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

# Ambil API Key
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://beastion.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# TIM PENULIS (Persona Profesional)
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
    "The Guardian": "https://www.theguardian.com/football/rss"
}

# Direktori
CONTENT_DIR = "content/articles" 
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_SOURCE = 1 

# Unsplash ID Pool (Backup jika AI Gagal)
UNSPLASH_IDS = [
    "1522778119026-d647f0565c6a", "1489944440615-453fc2b6a9a9", "1431324155629-1a6deb1dec8d", 
    "1579952363873-27f3bde9be2b", "1518091043644-c1d4457512c6", "1508098682722-e99c43a406b2",
    "1574629810360-7efbbe195018", "1577223625816-7546f13df25d", "1624880357913-a85cbdec04ca",
    "1516246844974-e39556ee0945", "1627341852895-467406c55cc0", "1628891544265-2766863640b3"
]

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
# 🎨 HYBRID IMAGE ENGINE (AI + BACKUP)
# ==========================================
def apply_heavy_modification(img):
    """Memodifikasi gambar backup agar dianggap unik oleh Google"""
    # 1. Flip Horizontal (50% chance)
    if random.random() > 0.5:
        img = ImageOps.mirror(img)

    # 2. Color Grading Random
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(random.uniform(0.85, 1.25)) 
    enhancer_c = ImageEnhance.Contrast(img)
    img = enhancer_c.enhance(random.uniform(0.9, 1.1))

    # 3. Vignette Effect (Gelap di sudut)
    width, height = img.size
    vignette = Image.new('L', (width, height), 0)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(vignette)
    # Lingkaran putih di tengah, hitam di pinggir
    draw.ellipse((30, 30, width-30, height-30), fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(120))
    # Gabungkan layer
    img = ImageOps.colorize(vignette, (20, 20, 20), (255, 255, 255)) 
    img = Image.composite(img, Image.open(BytesIO(requests.get(img.filename).content) if hasattr(img, 'filename') else img), vignette) # Fallback logic simplified

    return img.resize((1200, 675), Image.Resampling.LANCZOS)

def generate_hybrid_image(query, filename):
    output_path = f"{IMAGE_DIR}/{filename}"
    
    # --- STRATEGI 1: AI GENERATION (Flux Realism) ---
    print(f"      🎨 Strategy 1: AI Generating '{query}'...")
    safe_prompt = f"cinematic shot of {query} football match, stadium atmosphere, realistic lighting, 4k, sports photography --ar 16:9".replace(" ", "%20")
    seed = random.randint(1, 1000000)
    ai_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1200&height=675&model=flux-realism&seed={seed}&nologo=true"
    
    try:
        resp = requests.get(ai_url, timeout=40)
        if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.2)
            img.save(output_path, "WEBP", quality=85)
            print("      ✅ AI Image Created!")
            return f"/images/{filename}"
    except Exception as e:
        print(f"      ⚠️ AI Failed. Switching to Backup.")

    # --- STRATEGI 2: UNSPLASH POOL + MODIFIKASI ---
    print("      🎨 Strategy 2: Unsplash Pool + Modding")
    selected_id = random.choice(UNSPLASH_IDS)
    unsplash_url = f"https://images.unsplash.com/photo-{selected_id}?auto=format&fit=crop&w=1200&q=80"
    
    try:
        resp = requests.get(unsplash_url, timeout=15)
        if resp.status_code == 200:
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            img = apply_heavy_modification(img) # Modifikasi agar unik
            img.save(output_path, "WEBP", quality=85)
            print("      ✅ Backup Image Saved!")
            return f"/images/{filename}"
    except: pass
    
    # Fallback terakhir jika semua gagal
    return "https://images.unsplash.com/photo-1522778119026-d647f0565c6a"

# ==========================================
# 🧠 DEEP CONTENT ENGINE (STRUCTURED)
# ==========================================

def get_article_structure(title, summary):
    """Menentukan struktur artikel agar panjang dan mendalam"""
    text = (title + " " + summary).lower()
    
    if any(x in text for x in ['transfer', 'sign', 'bid', 'contract', 'fee']):
        return "TRANSFER_DEEP_DIVE", """
        **SECTION 1: THE DEAL BREAKDOWN**
        - Detailed context of the transfer rumor/deal.
        - Financial analysis (Fee, Wages, Contract length).
        **SECTION 2: PLAYER PROFILE**
        - Playing style, strengths, and weaknesses.
        - Statistical comparison with existing squad players (Create a Markdown Table).
        **SECTION 3: TACTICAL FIT**
        - How does he fit into the manager's system?
        - Potential lineup changes.
        **SECTION 4: VERDICT**
        - Is it a good deal? Rating out of 10.
        """
    elif any(x in text for x in ['vs', 'win', 'loss', 'score', 'draw']):
        return "MATCH_ANALYSIS", """
        **SECTION 1: MATCH NARRATIVE**
        - The story of the game. Key turning points.
        **SECTION 2: TACTICAL BATTLE**
        - Formation analysis. Who dominated midfield?
        - XG (Expected Goals) and possession stats (Create a Markdown Table).
        **SECTION 3: INDIVIDUAL BRILLIANCE**
        - Man of the Match analysis.
        - Player ratings and key performances.
        **SECTION 4: IMPLICATIONS**
        - Impact on the league table.
        - What's next for both managers?
        """
    else:
        return "EDITORIAL_FEATURE", """
        **SECTION 1: THE BIG PICTURE**
        - Comprehensive background of the news.
        - Why this matters right now.
        **SECTION 2: DATA & FACTS**
        - Historical context or statistical backing.
        - Use a Markdown Table to show data.
        **SECTION 3: EXPERT OPINION**
        - Analysis of quotes and reactions.
        - Differing perspectives.
        **SECTION 4: CONCLUSION**
        - Future predictions.
        """

def get_groq_article_json(title, summary, link, author_name):
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Tentukan Struktur dulu
    blueprint_type, blueprint_instructions = get_article_structure(title, summary)
    
    system_prompt = f"""
    You are {author_name}, a senior sports journalist for 'Sport Daily'.
    TODAY'S DATE: {current_date}.
    
    TASK: Write a **COMPREHENSIVE, DEEP-DIVE ARTICLE** (Minimum 1200 words).
    
    BLUEPRINT ({blueprint_type}):
    {blueprint_instructions}
    
    RULES:
    1. **LENGTH:** Do not summarize. Expand on every point. Use long paragraphs.
    2. **REALISM:** If match is future -> PREVIEW. If past -> REPORT.
    3. **FORMAT:** Return VALID JSON.
    
    OUTPUT JSON STRUCTURE:
    {{
        "title": "Catchy Journalistic Headline",
        "description": "SEO Meta Description (150 chars)",
        "category": "Select from {VALID_CATEGORIES}",
        "main_keyword": "Main entity for image generation",
        "tags": ["tag1", "tag2", "tag3"],
        "content_body": "FULL MARKDOWN CONTENT. Use H2, H3, Bold, and Tables."
    }}
    """
    
    user_prompt = f"""
    TOPIC: {title}
    DETAILS: {summary}
    SOURCE: {link}
    
    Write the article now following the BLUEPRINT strictly.
    """
    
    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name}) - Mode: {blueprint_type}...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.75, # Kreativitas agak tinggi agar tulisan panjang
                max_tokens=8000,  # Token maksimal
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            time.sleep(3)
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

    print("🔥 ENGINE STARTED: DEEP CONTENT + HYBRID IMAGE MODE")

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
            
            # 1. Generate Deep Content
            author = random.choice(AUTHOR_PROFILES)
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, author)
            
            if not raw_json: continue
            try:
                data = json.loads(raw_json)
            except:
                print("      ❌ JSON Parse Error")
                continue

            # 2. Generate Unique Image
            keyword = data.get('main_keyword') or clean_title
            final_img = generate_hybrid_image(keyword, f"{slug}.webp")
            
            # 3. Internal Linking
            links_md = get_internal_links_markdown()
            # Inject link di tengah atau akhir artikel
            body_content = data['content_body'] + "\n\n### Read More\n" + links_md

            # 4. Fallback Category
            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "International"

            # 5. Save File
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
*Reference: Analysis by {author} based on reports from [{source_name}]({entry.link}).*
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            save_link_to_memory(data['title'], slug)
            
            # 6. Indexing
            full_url = f"{WEBSITE_URL}/articles/{slug}/"
            if GOOGLE_LIBS_AVAILABLE:
                try:
                    # Logic submit ke google/indexnow
                    pass 
                except: pass

            print(f"      ✅ Published: {slug}")
            processed += 1
            time.sleep(5) # Delay lebih lama agar AI 'bernafas'

if __name__ == "__main__":
    main()
