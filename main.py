import csv
import json
import random
import re
import time
from pathlib import Path
from typing import Dict, List

import requests
import requests_cache
import streamlit as st
from bs4 import BeautifulSoup

try:
    from unidecode import unidecode
except ModuleNotFoundError:
    def unidecode(txt: str) -> str:
        accents = str.maketrans(
            "éèêáààüùíóçñäö",
            "eeeaauuio cn"
        )
        return txt.translate(accents)

# --- Load Countries from CSV ---
CSV_FILE = Path("countries.csv")
@st.cache_data(ttl=60*60*24)
def load_countries() -> List[str]:
    if not CSV_FILE.exists():
        st.error(f"Country list file not found: {CSV_FILE}")
        return []
    with CSV_FILE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [row["Country"].strip() for row in reader if row.get("Country")]

COUNTRIES = load_countries()
PLACEHOLDER = "Select a country..."

BASE_URL = "https://www.geometas.com"
DATA_FILE = Path("geometas_data.json")

# HTTP cache: SQLite, 7-day TTL
requests_cache.install_cache("geometas_http", expire_after=60*60*24*7)
HEADERS = {"User-Agent": "GeometasQuiz/CSV-Enabled"}
SPECIAL_SLUGS = {
    "curaçao": "curaao",
    "réunion": "runion",
    "u.s. virgin islands": "us_virgin_islands",
    "u.s. minor outlying islands": "us_minor_outlying_islands",
}

# --- Helpers ---
def slugify(country: str) -> str:
    s = re.sub(r"\s*\([^)]*\)", "", country).strip().lower()
    s = SPECIAL_SLUGS.get(s, s)
    s = unidecode(s)
    s = re.sub(r"[&·\.,]+", "", s)
    s = re.sub(r"[\s\-]+", "_", s)
    return s.replace("'", "")


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_country(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    metas = []
    for block in soup.select("div[class*='py-6']"):
        anchors = block.find_all("a", href=re.compile(r"/metas/detail"))
        img_anchor = next((a for a in anchors if a.find("img")), None)
        text_anchor = next((a for a in anchors if not a.find("img")), None)
        if not img_anchor or not text_anchor:
            continue
        img = img_anchor.find("img")
        img_url = img.get("src", "")
        if img_url.startswith("/"):
            img_url = BASE_URL + img_url
        text = text_anchor.get_text(strip=True)
        metas.append({"meta": text, "image_url": img_url})
    return metas

# --- Scrape & Cache ---
def scrape() -> Dict[str, List[Dict]]:
    st.info("🔄 Scraping Geometas… please wait 1-2 minutes.")
    data: Dict[str, List[Dict]] = {}
    progress = st.progress(0)
    for i, country in enumerate(COUNTRIES, 1):
        slug = slugify(country)
        url = f"{BASE_URL}/metas/countries/{slug}/"
        try:
            html = fetch_html(url)
            metas = parse_country(html)
            data[country] = metas
        except Exception as e:
            st.warning(f"⚠️ {country}: {e}")
            data[country] = []
        progress.progress(i/len(COUNTRIES))
    DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    st.success("✅ Scrape complete – data saved.")
    return data

@st.cache_data(ttl=60*60*24)
def load_data() -> Dict[str, List[Dict]]:
    if DATA_FILE.exists():
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            if any(data.values()):
                return data
            st.warning("Cached data empty – refetching.")
        except Exception:
            st.warning("Corrupted cache – refetching.")
    return scrape()

# --- Quiz UI ---
def run_quiz(data: Dict[str, List[Dict]]):
    st.title("🌍 Geometas Country Quiz")
    if not any(data.values()):
        st.error("No metas found. Click 'Force rescrape' in sidebar.")
        return

    # Build list of countries that have at least one meta with an image
    available = [c for c, metas in data.items() if metas and any(m.get("image_url") for m in metas)]
    if not available:
        st.error("No available metas with images to quiz on.")
        return

    # Initialize cumulative score & attempts once
    if 'score' not in st.session_state:
        st.session_state.score = 0
        st.session_state.attempts = 0

    # Pick a new question when needed
    if 'current_meta' not in st.session_state:
        country = random.choice(available)
        valid = [m for m in data[country] if m.get("image_url")]
        st.session_state.current_meta = random.choice(valid)
        st.session_state.current_country = country
        st.session_state.show_meta = False

    meta = st.session_state.current_meta
    country = st.session_state.current_country

    # Display the image
    st.image(meta["image_url"], use_container_width=True)

    # Dropdown + placeholder
    options = [PLACEHOLDER] + COUNTRIES
    guess = st.selectbox("Guess the country:", options, key="guess_dropdown")
    submit_disabled = (guess == PLACEHOLDER) or st.session_state.show_meta

    # Submit answer
    if st.button("Submit", disabled=submit_disabled):
        st.session_state.attempts += 1
        if guess == country:
            st.session_state.score += 1
            st.success("Correct! 🎉")
        else:
            st.error(f"Wrong – it was **{country}**.")
        st.markdown(f"**Meta:** {meta['meta']}")
        st.metric("Score", f"{st.session_state.score}/{st.session_state.attempts}")
        st.session_state.show_meta = True

    # Next question (after reveal)
    if st.session_state.show_meta:
        next_clicked = st.button("Next question", key="next_btn")
        if next_clicked:
            # clear question state but keep score
            for k in ("current_meta", "current_country", "show_meta", "guess_dropdown"):
                st.session_state.pop(k, None)
            st.rerun()

# --- Main ---
def main():
    st.sidebar.header("⚙️ Data Controls")
    if st.sidebar.button("Force rescrape"):
        if DATA_FILE.exists():
            DATA_FILE.unlink()
        load_data.clear()
        st.rerun()
    with st.spinner("Loading data…"):
        data = load_data()
    if st.sidebar.checkbox("Show raw JSON"):
        st.sidebar.write(data)
    run_quiz(data)

if __name__ == "__main__":
    main()
