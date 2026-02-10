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
    "UK Source": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-GB&gl=GB&ceid=GB:en"
}

# 5. DIRECTORIES
CONTENT_DIR = "content/posts"
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
# 🧠 MEMORY & LINKING SYSTEM (TETAP UTUH)
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
    if len(memory) > 60: 
        memory = dict(list(memory.items())[-60:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_formatted_internal_links():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    selected_items = random.sample(items, min(4, len(items)))
    formatted_links = []
    for title, url in selected_items:
        formatted_links.append(f"- [{title}]({url})")
    return "\n".join(formatted_links)

# ==========================================
# 📡 INDEXING & RSS TOOLS (TETAP UTUH)
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
# 🎨 IMAGE ENGINE (TETAP UTUH)
# ==========================================
def download_and_optimize_image(query, filename):
    if not filename.endswith(".webp"):
        filename = filename.rsplit(".", 1)[0] + ".webp"

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
                enhancer_sharp = ImageEnhance.Sharpness(img)
                img = enhancer_sharp.enhance(1.3)
                enhancer_color = ImageEnhance.Color(img)
                img = enhancer_color.enhance(1.1)

                output_path = f"{IMAGE_DIR}/{filename}"
                img.save(output_path, "WEBP", quality=85)
                
                print(f"      📸 Image Saved: {filename}")
                return f"/images/{filename}" 

        except Exception:
            time.sleep(2)
    
    return random.choice(FALLBACK_IMAGES)

# ==========================================
# 🧠 NEW: DYNAMIC NARRATIVE ENGINE (LOGIKA BARU)
# ==========================================
def get_narrative_style(title, summary):
    """
    Menentukan 'Angle' atau Sudut Pandang Unik agar artikel tidak generik.
    """
    text = (title + " " + summary).lower()
    
    # 1. GAYA: TRANSFER INSIDER (Fokus Uang & Kontrak)
    if any(x in text for x in ['transfer', 'deal', 'fee', 'bid', 'sign', 'loan']):
        return "THE INSIDER", "Focus on the financial breakdown, agent involvement, contract length, and how this signing fits the tactical jigsaw. Use headers like 'The Financial Package' or 'Where He Fits'."

    # 2. GAYA: TACTICAL ANALYST (Fokus Data & Strategi)
    elif any(x in text for x in ['vs', 'win', 'loss', 'tactic', 'formation', 'xg', 'draw']):
        return "THE ANALYST", "Focus on Expected Goals (xG), formations, key player battles, and manager decisions. Use headers like 'The Midfield Battle' or 'Defensive Fragility'."

    # 3. GAYA: HISTORIAN (Fokus Sejarah & Rekor)
    elif any(x in text for x in ['record', 'history', 'year', 'legend', 'anniversary']):
        return "THE HISTORIAN", "Compare this event to historical precedents. Use nostalgic tone. Headers like 'Echoes of the Past' or 'Breaking the Curse'."

    # 4. GAYA: COLUMNIST (Fokus Opini & Drama)
    else:
        return "THE COLUMNIST", "Focus on the narrative, fan sentiment, and future implications. Be opinionated. Headers like 'Why Fans Are Furious' or 'The turning Point'."

def get_banned_words_instruction():
    """
    Daftar kata yang DILARANG jadi Header agar struktur unik.
    """
    return "You are FORBIDDEN from using these generic headers: 'Introduction', 'Conclusion', 'The Context', 'The Analysis', 'Summary', 'Overview'. You must invent CREATIVE headers based on the content."

# ==========================================
# 🤖 AI WRITER ENGINE (MODIFIED FOR 1000+ WORDS)
# ==========================================
def get_groq_article_json(title, summary, link, internal_links_block, author_name):
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    narrative_style, specific_instructions = get_narrative_style(title, summary)
    banned_instruction = get_banned_words_instruction()
    
    system_prompt = f"""
    You are {author_name}, a top-tier sports journalist.
    TODAY'S DATE: {current_date}.
    
    YOUR GOAL: Write a **DEEP DIVE FEATURE ARTICLE** (Minimum 1000 words).
    NARRATIVE STYLE: {narrative_style}.
    
    {banned_instruction}
    
    SPECIFIC INSTRUCTIONS FOR THIS STYLE:
    {specific_instructions}
    
    CRITICAL RULES:
    1. **ANTI-HOAX:** Check the date. If the match is in the future, write a PREVIEW/PREDICTION. If past, write a REPORT.
    2. **RICH CONTENT:** You MUST include at least one Markdown Table (e.g., Stats, H2H, Transfer Fee Breakdown).
    3. **READABILITY:** Use short paragraphs, **bold** for emphasis, and > blockquotes for key takeaways.
    4. **STRUCTURE:** Do not use a fixed template. Flow naturally from the Hook -> Deep Analysis -> Future Implications.
    
    JSON OUTPUT FORMAT:
    {{
        "title": "A Viral, Specific Headline (No Clickbait)",
        "description": "SEO description (max 150 chars)",
        "category": "One of: Transfer News, Premier League, Champions League, La Liga, International, Tactical Analysis",
        "main_keyword": "Main entity for image generation",
        "lsi_keywords": ["tag1", "tag2", "tag3"],
        "content_body": "The full 1000+ word article in Markdown..."
    }}
    """

    user_prompt = f"""
    TOPIC: {title}
    DETAILS: {summary}
    SOURCE LINK: {link}
    
    WRITING PLAN (To ensure length):
    - **Section 1 (The Hook):** 200 words. Grab attention, set the scene.
    - **Section 2 (The Deep Dive):** 400 words. Analyzing the core issue/match details. Include DATA/TABLE here.
    - **Section 3 (The Context/Reaction):** 300 words. Quotes, fan mood, historical comparison.
    - **Section 4 (The Verdict):** 200 words. Strong closing opinion (Not just a summary).
    
    At the very end, add this 'Read More' section:
    {internal_links_block}
    """

    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name} - {narrative_style})...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7, 
                max_tokens=7000, # Max token besar untuk artikel panjang
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
# 🏁 MAIN LOOP (TETAP UTUH)
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    total_generated = 0

    print("🔥 STARTING ENGINE: 1000+ WORDS & UNIQUE STRUCTURE MODE...")

    for source_name, rss_url in RSS_SOURCES.items():
        print(f"\n📡 Fetching Source: {source_name}...")
        feed = fetch_rss_feed(rss_url)
        if not feed or not feed.entries: continue

        cat_success_count = 0
        
        for entry in feed.entries:
            if cat_success_count >= TARGET_PER_SOURCE: break

            clean_title = entry.title.split(" - ")[0]
            slug = slugify(clean_title, max_length=60, word_boundary=True)
            filename = f"{slug}.md"

            if os.path.exists(f"{CONTENT_DIR}/{filename}"): 
                continue

            current_author = random.choice(AUTHOR_PROFILES)
            print(f"   ⚡ Processing: {clean_title[:40]}...")
            
            links_block = get_formatted_internal_links()
            
            # Generate AI Content
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, links_block, current_author)
            
            if not raw_json: continue

            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError:
                print("      ❌ JSON Decode Error. Skipping.")
                continue

            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "International"

            # Generate Image
            img_name = f"{slug}.webp"
            keyword_for_image = data.get('main_keyword') or clean_title
            final_img = download_and_optimize_image(keyword_for_image, img_name)
            
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
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            save_link_to_memory(data['title'], slug)
            
            print(f"      ✅ Published: {filename}")
            
            full_url = f"{WEBSITE_URL}/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)
            
            cat_success_count += 1
            total_generated += 1
            
            # Sleep lebih lama agar AI tidak "burnout" dan hasil tetap bagus
            time.sleep(8)

    print(f"\n🎉 DONE! Total Articles Generated: {total_generated}")

if __name__ == "__main__":
    main()
