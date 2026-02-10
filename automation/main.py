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
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    print("⚠️ Warning: Google Indexing libs not installed.")
    GOOGLE_LIBS_AVAILABLE = False

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
    print("❌ FATAL ERROR: Groq API Key is missing!")
    exit(1)

# 2. TIM PENULIS (LENGKAP)
AUTHOR_PROFILES = [
    "Dave Harsya (Senior Analyst)", 
    "Sarah Jenkins (Chief Editor)",
    "Luca Romano (Transfer Specialist)", 
    "Marcus Reynolds (Premier League Correspondent)",
    "Elena Petrova (Tactical Expert)", 
    "Ben Foster (Sports Journalist)"
]

# 3. KATEGORI RESMI
VALID_CATEGORIES = [
    "Transfer News", "Premier League", "Champions League", 
    "La Liga", "International", "Tactical Analysis"
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
    if len(memory) > 100: 
        memory = dict(list(memory.items())[-100:])
    with open(MEMORY_FILE, 'w') as f: json.dump(memory, f, indent=2)

def get_internal_links_markdown():
    memory = load_link_memory()
    items = list(memory.items())
    if not items: return ""
    selected_items = random.sample(items, min(4, len(items)))
    links_md = ""
    for title, url in selected_items:
        links_md += f"- [{title}]({url})\n"
    return links_md

def inject_links_in_middle(content_body, links_markdown):
    """
    Menyuntikkan link di Tengah Artikel (Paragraf ke-4 atau ke-5).
    """
    if not links_markdown: return content_body
    
    paragraphs = content_body.split('\n\n')
    injection_block = f"""
> **Recommended for you:**
>
{"> " + links_markdown.replace("- ", "> - ")}
"""
    # Cari posisi tengah yang aman
    target_index = min(4, len(paragraphs) - 1)
    if target_index < 1: target_index = 1
    
    paragraphs.insert(target_index, injection_block)
    return '\n\n'.join(paragraphs)

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
    if not GOOGLE_JSON_KEY or not GOOGLE_LIBS_AVAILABLE: return
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
# 🎨 IMAGE ENGINE
# ==========================================
def download_and_optimize_image(query, filename):
    if not filename.endswith(".webp"):
        filename = filename.rsplit(".", 1)[0] + ".webp"

    base_prompt = f"editorial sports photography, {query}, realistic stadium background, 4k, canon eos r5, sharp focus, cinematic lighting, no text"
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
                return f"/images/{filename}" 

        except Exception:
            time.sleep(2)
    
    return random.choice(FALLBACK_IMAGES)

# ==========================================
# 🧠 MEGA-PROMPT ENGINE (1500 WORDS + UNIQUE HEADERS)
# ==========================================
def get_article_blueprint(title, summary):
    """
    Blueprint Struktur Artikel.
    Note: Teks di sini adalah PANDUAN STRUKTUR, bukan judul final.
    """
    text = (title + " " + summary).lower()
    
    if any(x in text for x in ['transfer', 'sign', 'bid', 'fee', 'contract']):
        return "TRANSFER_SAGA", """
        **STRUCTURE GUIDE 1: FINANCIALS (300 Words)**
        - H2 Requirement: Create a unique headline about the Money/Cost involved.
          - H3: Wages and Transfer Fee breakdown (Markdown Table Required).
          - H3: Contract clauses details.
        
        **STRUCTURE GUIDE 2: PLAYER ANALYSIS (400 Words)**
        - H2 Requirement: Create a unique headline about the Player's Skills.
          - H3: Strengths analysis.
            - H4: Stats comparison.
          - H3: Weaknesses.
        
        **STRUCTURE GUIDE 3: TACTICS (300 Words)**
        - H2 Requirement: Create a unique headline about fitting into the team.
          - H3: Manager's tactical plan.
            - H4: Lineup changes.
        
        **STRUCTURE GUIDE 4: CONCLUSION (250 Words)**
        - H2 Requirement: A powerful closing statement headline.
          - H3: Final verdict on the deal.
        """
        
    elif any(x in text for x in ['vs', 'win', 'loss', 'score', 'highlight', 'draw']):
        return "MATCH_DEEP_DIVE", """
        **STRUCTURE GUIDE 1: NARRATIVE (300 Words)**
        - H2 Requirement: A dramatic headline summarizing the match vibe.
          - H3: Pre-match context vs Reality.
          
        **STRUCTURE GUIDE 2: TACTICS (400 Words)**
        - H2 Requirement: A headline about specific tactical battles.
          - H3: Midfield analysis.
            - H4: Key movements.
          - H3: Defensive structure.
            - H4: Errors committed.
            
        **STRUCTURE GUIDE 3: MOMENTS (300 Words)**
        - H2 Requirement: A headline about the turning point.
          - H3: Goal analysis.
          - H3: Controversy/VAR check.
          
        **STRUCTURE GUIDE 4: DATA (300 Words)**
        - H2 Requirement: A headline about the stats/ratings.
          - H3: Player Ratings Table (Markdown).
          - H3: xG Analysis.
        """
        
    else:
        return "EDITORIAL_FEATURE", """
        **STRUCTURE GUIDE 1: CONTEXT (300 Words)**
        - H2 Requirement: A headline about the history/background.
          - H3: Timeline of events.
            - H4: How it started.
            
        **STRUCTURE GUIDE 2: ANALYSIS (400 Words)**
        - H2 Requirement: A deep dive headline into the core issue.
          - H3: Data/Facts (Markdown Table Required).
          - H3: Historical comparison.
            - H4: Past examples.
            
        **STRUCTURE GUIDE 3: REACTION (300 Words)**
        - H2 Requirement: A headline about public/expert sentiment.
          - H3: Fan reactions.
          - H3: Pundit opinions.
          
        **STRUCTURE GUIDE 4: FUTURE (250 Words)**
        - H2 Requirement: A predictive headline about what comes next.
          - H3: Long-term impact.
        """

def clean_json_response(content):
    content = re.sub(r'```json\s*', '', content)
    content = re.sub(r'```\s*$', '', content)
    return content.strip()

def get_groq_article_json(title, summary, link, author_name):
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    blueprint_type, blueprint_structure = get_article_blueprint(title, summary)
    
    # SYSTEM PROMPT DIMODIFIKASI AGAR HEADER UNIK
    system_prompt = f"""
    You are {author_name}, a world-class senior sports journalist.
    
    DATE: {current_date}.
    
    YOUR MISSION: 
    Write a 1500-WORD Deep Dive Article. Output strictly valid JSON.
    
    🚨 CRITICAL RULES FOR HEADERS (H2, H3, H4):
    1. **NEVER** use generic words like "Section 1", "Introduction", "The Deal", "Tactical Analysis", "Conclusion", or "Verdict".
    2. **YOU MUST REWRITE** every H2 and H3 headline to be CREATIVE, UNIQUE, and SPECIFIC to the news topic.
    3. Example: Instead of "Tactical Fit", write "How Calafiori Unlock's Arteta's Left Side".
    4. Example: Instead of "The Verdict", write "Why this £40m Gamble Will Pay Off".
    
    STRUCTURE TO FOLLOW (Do not copy the labels, follow the logic):
    {blueprint_structure}
    
    JSON OUTPUT FORMAT:
    {{
        "title": "Viral Editorial Headline (No Clickbait)",
        "description": "SEO Description (160 chars)",
        "category": "One of: Transfer News, Premier League, Champions League, La Liga, International, Tactical Analysis",
        "main_keyword": "Entity name for image generation",
        "tags": ["tag1", "tag2", "tag3"],
        "content_body": "Full Markdown content. Make H2/H3 headers unique/contextual."
    }}
    """

    user_prompt = f"""
    TOPIC: {title}
    DETAILS: {summary}
    SOURCE LINK: {link}
    
    INSTRUCTIONS:
    - Write deep, analytical paragraphs.
    - Include at least one Markdown Table.
    - Ensure all H2/H3 headers are unique and catchy (No "Section 1" text in final output!).
    """

    for api_key in GROQ_API_KEYS:
        client = Groq(api_key=api_key)
        try:
            print(f"      🤖 AI Writing ({author_name}) - Pattern: {blueprint_type}...")
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7, # Sedikit kreatif untuk judul
                max_tokens=8000, 
                response_format={"type": "json_object"}
            )
            
            raw_content = completion.choices[0].message.content
            cleaned_json = clean_json_response(raw_content)
            
            # Validasi
            json.loads(cleaned_json)
            return cleaned_json
            
        except RateLimitError:
            time.sleep(5)
            continue
        except Exception as e:
            print(f"      ⚠️ Groq Error: {e}")
            continue
            
    return None

# ==========================================
# 🏁 MAIN LOOP
# ==========================================
def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    total_generated = 0
    print("🔥 STARTING ENGINE (MEGA-CONTENT MODE: UNIQUE HEADERS)...")

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

            if os.path.exists(f"{CONTENT_DIR}/{filename}"): continue
            
            current_author = random.choice(AUTHOR_PROFILES)
            print(f"   ⚡ Processing: {clean_title[:40]}...")
            
            # 1. GENERATE KONTEN (AI)
            raw_json = get_groq_article_json(clean_title, entry.summary, entry.link, current_author)
            
            if not raw_json: 
                print("      ❌ Content Generation Failed")
                continue
            
            try:
                data = json.loads(raw_json)
            except: 
                print("      ❌ JSON Parse Error")
                continue

            if data.get('category') not in VALID_CATEGORIES:
                data['category'] = "International"

            # 2. GENERATE IMAGE
            img_name = f"{slug}.webp"
            keyword_for_image = data.get('main_keyword') or clean_title
            final_img = download_and_optimize_image(keyword_for_image, img_name)
            
            # 3. INJECT LINKS
            links_md = get_internal_links_markdown()
            final_body = inject_links_in_middle(data['content_body'], links_md)

            # 4. SAVE FILE
            date_now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+00:00")
            tags_list = data.get('tags', [])
            
            md_content = f"""---
title: "{data['title'].replace('"', "'")}"
date: {date_now}
author: "{current_author.split('(')[0].strip()}"
categories: ["{data['category']}"]
tags: {json.dumps(tags_list)}
featured_image: "{final_img}"
featured_image_alt: "{data.get('main_keyword')}"
description: "{data['description'].replace('"', "'")}"
slug: "{slug}"
draft: false
---

{final_body}

---
*Reference: Analysis based on reports from [{source_name}]({entry.link}). Content generated for informational purposes.*
"""
            with open(f"{CONTENT_DIR}/{filename}", "w", encoding="utf-8") as f:
                f.write(md_content)
            
            # 5. MEMORY & INDEXING
            save_link_to_memory(data['title'], slug)
            
            print(f"      ✅ Published: {filename}")
            
            full_url = f"{WEBSITE_URL}/{slug}/"
            submit_to_indexnow(full_url)
            submit_to_google(full_url)
            
            cat_success_count += 1
            total_generated += 1
            
            time.sleep(10)

    print(f"\n🎉 DONE! Total Articles Generated: {total_generated}")

if __name__ == "__main__":
    main()
