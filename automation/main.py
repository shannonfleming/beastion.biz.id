import os
import json
import requests
import feedparser
import time
import re
import random
import warnings 
import pytz 
from datetime import datetime
from slugify import slugify
from io import BytesIO
from PIL import Image, ImageEnhance
from groq import Groq, APIError, RateLimitError

# --- SUPPRESS WARNINGS ---
warnings.filterwarnings("ignore", category=FutureWarning)

# --- GOOGLE INDEXING LIBS ---
try:
    from oauth2client.service_account import ServiceAccountCredentials
    from googleapiclient.discovery import build
except ImportError:
    print("⚠️ Warning: Google Indexing libs not installed. Running without Google Indexing.")

# ==========================================
# ⚙️ CONFIGURATION & SETUP
# ==========================================

# 1. API KEYS
GROQ_KEYS_RAW = os.environ.get("GROQ_API_KEY", "") 
GROQ_API_KEYS = [k.strip() for k in GROQ_KEYS_RAW.split(",") if k.strip()]

WEBSITE_URL = "https://beastion.biz.id" 
INDEXNOW_KEY = "e74819b68a0f40e98f6ec3dc24f610f0" 
GOOGLE_JSON_KEY = os.environ.get("GOOGLE_INDEXING_KEY", "") 

if not GROQ_API_KEYS:
    print("❌ FATAL ERROR: Groq API Key is missing! Set 'GROQ_API_KEY' env variable.")
    exit(1)

# 2. TIM PENULIS (NEWSROOM PERSONAS)
AUTHOR_PROFILES = [
    "Dave Harsya (Senior Analyst)", 
    "Sarah Jenkins (Chief Editor)",
    "Luca Romano (Transfer Specialist)", 
    "Marcus Reynolds (Premier League Correspondent)",
    "Elena Petrova (Tactical Expert)", 
    "Ben Foster (Sports Journalist)",
    "Mateo Rodriguez (European Football Analyst)"
]

# 3. KATEGORI RESMI
VALID_CATEGORIES = [
    "Transfer News", 
    "Premier League", 
    "Champions League", 
    "La Liga", 
    "International", 
    "Tactical Analysis"
]

# 4. SUMBER RSS
RSS_SOURCES = {
    "SkySports": "https://www.skysports.com/rss/12040",
    "BBC Football": "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "ESPN FC": "https://www.espn.com/espn/rss/soccer/news",
        "US Source": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-US&gl=US&ceid=US:en",
    "UK Source": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-GB&gl=GB&ceid=GB:en",
    "SkySports": "https://www.skysports.com/rss/12040"
}

# 5. DIRECTORIES
CONTENT_DIR = "content/posts"  # Pastikan sesuai folder Hugo Anda
IMAGE_DIR = "static/images"
DATA_DIR = "automation/data"
MEMORY_FILE = f"{DATA_DIR}/link_memory.json"
TARGET_PER_SOURCE = 1 

# 6. FALLBACK IMAGES
FALLBACK_IMAGES = [
    "https://images.unsplash.com/photo-1508098682722-e99c43a406b2?auto=format&fit=crop&w=1200&q=80",
    "https://images.unsplash.com/photo-1431324155629-1a6deb1dec8d?auto=format&fit=crop&w=1200&q=80"
]

# ==========================================
# 🧠 MEMORY & LINKING SYSTEM
# ==========================================
def load_link_memory():
    if not os.path.exists(MEMORY_FILE): return {}
    try:
        with open(MEMORY_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_link_to_memory(title, slug):
    os.makedirs(DATA_DIR, exist_ok=True)
    memory = load_link_memory()
    memory[title] = f"/{slug}"
    if len(memory) > 60: # Simpan 60 link terakhir
        memory = dict(list(memory.items())[-60:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_formatted_internal_links():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    # Ambil 3-4 link random untuk footer artikel
    selected_items = random.sample(items, min(4, len(items)))
    formatted_links = []
    for title, url in selected_items:
        formatted_links.append(f"- [{title}]({url})")
    return "\n".join(formatted_links)

# ==========================================
# 📡 INDEXING & RSS TOOLS
# ==========================================
def fetch_rss_feed(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200: return None
        return feedparser.parse(response.content)
    except: return None

def submit_to_google(url):
    if not GOOGLE_JSON_KEY: return
    try:
        creds_dict = json.loads(GOOGLE_JSON_KEY)
        SCOPES = ["https://www.googleapis.com/auth/indexing"]
        credentials = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)
        service = build("indexing", "v3", credentials=credentials)
        body = {"url": url, "type": "URL_UPDATED"}
        service.urlNotifications().publish(body=body).execute()
        print(f"      🚀 Google Indexing Submitted")
    except Exception as e:
        print(f"      ⚠️ Google Indexing Error: {e}")

def submit_to_indexnow(url):
    try:
        endpoint = "https://api.indexnow.org/indexnow"
        host = WEBSITE_URL.replace("https://", "").replace("http://", "")
        data = {
            "host": host,
            "key": INDEXNOW_KEY,
            "keyLocation": f"https://{host}/{INDEXNOW_KEY}.txt",
            "urlList": [url]
        }
        requests.post(endpoint, json=data, headers={'Content-Type': 'application/json'}, timeout=5)
        print(f"      🚀 IndexNow Submitted")
    except: pass

# ==========================================
# 🎨 IMAGE ENGINE (OPTIMIZED)
# ==========================================
def download_and_optimize_image(query, filename):
    if not filename.endswith(".webp"):
        filename = filename.rsplit(".", 1)[0] + ".webp"

    # Prompt Image Gen yang Lebih Realistis (Flux)
    base_prompt = f"sports press photography, {query}, realistic stadium background, 4k, canon eos r5, sharp focus, cinematic lighting, no text"
    safe_prompt = base_prompt.replace(" ", "%20")[:400]
    
    print(f"      🎨 Generating Image: {query[:30]}...")

    for attempt in range(2):
        seed = random.randint(1, 999999)
        image_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1200&height=675&nologo=true&model=flux-realism&seed={seed}"
        
        try:
            response = requests.get(image_url, timeout=45)
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content)).convert("RGB")
                
                # Image Enhancement (Agar Gambar Pop-Up)
                enhancer_sharp = ImageEnhance.Sharpness(img)
                img = enhancer_sharp.enhance(1.3) # Sedikit lebih tajam
                enhancer_color = ImageEnhance.Color(img)
                img = enhancer_color.enhance(1.1) # Warna sedikit lebih hidup

                output_path = f"{IMAGE_DIR}/{filename}"
                img.save(output_path, "WEBP", quality=85)
                
                print(f"      📸 Image Saved: {filename}")
                return f"/images/{filename}" 

        except Exception:
            time.sleep(2)
    
    print("      ⚠️ Image gen failed. Using Fallback.")
    return random.choice(FALLBACK_IMAGES)

# ==========================================
# 🤖 DYNAMIC STRUCTURE LOGIC (ANTI-ADBSENSE DETECT)
# ==========================================
def get_dynamic_structure_prompt(title):
    """
    Fungsi ini menentukan struktur artikel berdasarkan keyword judul.
    Tujuannya agar struktur H2/H3 tidak monoton (Boilerplate).
    """
    title_lower = title.lower()
    
    if any(x in title_lower for x in ['transfer', 'sign', 'deal', 'bid', 'contract']):
        # STRUKTUR A: BERITA TRANSFER
        return """
        MANDATORY STRUCTURE:
        1. **Executive Summary**: The core news in bold.
        2. **H2: The Deal Breakdown**: Fee, wages, contract length (use a Markdown Table).
        3. **H2: Tactical Fit**: Where does he play?
        4. **H2: The Ripple Effect**: How this impacts the squad.
        5. **H2: Final Verdict**: Is it a good signing?
        """
    elif any(x in title_lower for x in ['vs', 'win', 'loss', 'draw', 'score']):
        # STRUKTUR B: MATCH REPORT
        return """
        MANDATORY STRUCTURE:
        1. **Match Summary**: Brief result overview.
        2. **H2: Key Moments**: The turning points of the game.
        3. **H2: Tactical Battle**: Manager decisions.
        4. **H2: Player Ratings / MVP**: Who shone?
        5. **H2: Stat Attack**: Markdown table of key stats (Possession, xG, Shots).
        6. **H2: What's Next**: Upcoming fixtures.
        """
    else:
        # STRUKTUR C: UMUM / OPINI
        return """
        MANDATORY STRUCTURE:
        1. **Introduction**: Setting the scene.
        2. **H2: The Context**: Why this news matters now.
        3. **H2: The Analysis**: Deep dive into the issue.
        4. **H2: Fan Reaction**: What are people saying?
        5. **H2: Conclusion**: Expert opinion.
        """

# ==========================================
# 🤖 AI WRITER ENGINE (ANTI-HOAX)
# ==========================================
def get_groq_article_json(title, summary, link, internal_links_block, author_name):
    
    # 1. TANGGAL HARI INI (PENTING UNTUK ANTI-HOAX)
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    # 2. STRUKTUR DINAMIS
    structure_prompt = get_dynamic_structure_prompt(title)
    
    system_prompt = f"""
    You are {author_name}, a senior sports journalist for 'beastion.biz.id'.
    TODAY'S DATE: {current_date}.
    
    TASK: Write a unique, high-quality article based on the input.
    
    CRITICAL ANTI-HOAX RULES:
    1. **CHECK THE DATE:** 
       - If the match/event is in the FUTURE relative to {current_date}, write a **PREVIEW** or **PREDICTION**. Do NOT invent a final score.
       - If it is PAST, write a **REPORT**.
    2. **NO HALLUCINATION:** Do not invent fake quotes. Use generic editorial statements if specific quotes aren't in the snippet.
    
    {structure_prompt}
    
    JSON OUTPUT FORMAT:
    {{
        "title": "Engaging Headline (SEO Optimized, No Clickbait)",
        "description": "Meta description (max 150 chars)",
        "category": "Pick one: Transfer News, Premier League, Champions League, La Liga, International, Tactical Analysis",
        "main_keyword": "Main entity for image generation (e.g. 'Manchester United Stadium' or 'Lionel Messi')",
        "lsi_keywords": ["tag1", "tag2", "tag3"],
        "content_body": "Full article content in Markdown format..."
    }}
    """

    user_prompt = f"""
    News Title: {title}
    Snippet: {summary}
    Source Link: {link}
    
    Insert these Internal Links naturally under a 'Read More' header at the end:
    {internal_links_block}
    """

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
                temperature=0.6, # Balance antara kreatif dan akurat
                max_tokens=6500,
                response_format={"type": "json_object"}
            )
            return completion.choices[0].message.content
        except RateLimitError:
            time.sleep(2)
            continue
        except Exception as e:
            print(f"      ⚠️ Groq Error: {e}")
            continue
            
    return None

# ==========================================
# 🏁 MAIN LOOP
# ==========================================
def main():
    # Setup Directories
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    total_generated = 0

    print("🔥 STARTING AUTOMATION ENGINE (FULL VERSION)...")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Fetching Source: {source_name}...")
        feed = fetch_rss_feed(rss_url)
        if not feed or not feed.entries: continue

        cat_success_count = 0
        
        for entry in feed.entries:
            if cat_success_count >= TARGET_PER_SOURCE: break

            # 1. Filter Judul & Slug
            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"

            # 2. Skip jika file sudah ada
            if os.path.exists(f"{CONTENT_DIR}/{filename}"): 
                continue

            # 3. Pilih Author & Siapkan Links
            current_author = random.choice(AUTHOR_PROFILES)
            print(f"   ⚡ Processing: {clean_title[:40]}...")
            
            links_block = get_formatted_internal_links()
            
            # 4. Generate AI Content (JSON)
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, links_block, current_author)
            
            if not raw_json: continue

            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError:
                print("      ❌ JSON Decode Error. Skipping.")
                continue

            # 5. Validasi Kategori
            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "International"

            # 6. Generate Gambar (Image Engine)
            img_name = f"{slug}.webp"
            keyword_for_image = data.get('main_keyword') or clean_title
            final_img = download_and_optimize_image(keyword_for_image, img_name)
            
            # 7. Metadata (Markdown Frontmatter)
            date_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
            tags_list = data.get('lsi_keywords', [])
            
            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {date_now}
author: "{current_author.split('(')[0].strip()}"
categories: ["{data['category']}"]
tags: {json.dumps(tags_list)}
featured_image: "{final_img}"
featured_image_alt: "Image showing {data.get('main_keyword', 'Football Match')}"
description: "{data['description'].replace('"', "'")}"
slug: "{slug}"
draft: false
---

{data['content_body']}

---
*Reference: Analysis based on reports from [{source_name}]({entry.link}). Content generated for informational purposes.*
"""
            # 8. Save File
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            # 9. Update Memory & Indexing
            save_link_to_memory(data['title'], slug)
            
            print(f"      ✅ Published: {filename}")
            
            # Indexing Auto
            full_url = f"{WEBSITE_URL}/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)
            
            cat_success_count += 1
            total_generated += 1
            
            # 10. Sleep (Anti-Spam)
            time.sleep(5)

    print(f"\n🎉 DONE! Total Articles Generated: {total_generated}")

if __name__ == "__main__":
    main()
