"""
Zero-Friction Language Workspace (Streamlit) v5 — Supabase Cloud Edition

Что нового:
• Вместо Google Sheets подключена глобальная база Supabase (PostgreSQL) — без ограничений по размеру и зависаний.
• Двусторонняя синхронизация: данные читаются из Supabase и сохраняются в data.json, а любые оценки/правки мгновенно отправляются в облако в фоновом потоке.
• Адаптивный дизайн: кнопки-чипсы языков, крупные кнопки оценки под палец, адаптивные шрифты clamp, липкая шапка в очереди, метрики по 2 в ряд на телефонах.
• Защита хоткеев: Пробел и 1/2/3 отключаются при открытом окне стека недели и в полях ввода.
"""

import html
import json
import math
import os
import random
import re
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from supabase import create_client

st.set_page_config(page_title="Zero-Friction Language Workspace", page_icon="🎯", layout="wide")

DATA_FILE = Path(__file__).with_name("data.json")

TOP_N = 30       # "горлышко"
MAX_GRAD = 10    # максимум карточек в активном изучении/повторении в top30
TYPES = ["Выпускник", "Повторяем", "Старичок"]
TYPE_STYLE = {
    "Выпускник": {"bg": "#fff3e0", "border": "#fb8c00", "fg": "#b38600", "dot": "🟡"},
    "Повторяем": {"bg": "#fff3e0", "border": "#ff7043", "fg": "#d84315", "dot": "🟠"},
    "Старичок": {"bg": "#e3f2fd", "border": "#1e88e5", "fg": "#1976d2", "dot": "🔵"},
}
INT_COLS = {"position", "interval", "reviews", "streak", "star_days"}
SPEECH_CODES = ["es-ES", "en-GB", "en-US", "lv-LV", "de-DE", "fr-FR", "it-IT", "pl-PL", "pt-PT", "ru-RU"]
VOCAB_KINDS = ("vocab", "vocab_rev")

FIELDS = {
    "vocab": [("word", "Слово"), ("translation", "Перевод слова"), ("pron", "Произношение"),
              ("phrase", "Фраза"), ("phrase_tr", "Перевод фразы"), ("extra", "Доп"),
              ("in_stack", "В стеке")],
    "grammar": [("rule", "Правило"), ("cheat", "Шпаргалка"), ("phrase", "Фраза"),
                ("phrase_tr", "Перевод фразы"), ("extra", "Доп")],
}
COLS = {
    "vocab_base": [k for k, _ in FIELDS["vocab"]],
    "grammar_base": [k for k, _ in FIELDS["grammar"]],
    "stack": ["phrase", "note", "pron", "phrase_ex", "phrase_tr", "extra"],
    "vocab_pool": ["word", "type", "position", "interval", "reviews", "last", "weight", "streak", "due_date", "star_days"],
    "vocab_rev_pool": ["word", "type", "position", "interval", "reviews", "last", "weight", "streak", "due_date", "star_days"],
    "grammar_pool": ["rule", "type", "cheat", "position", "interval", "reviews", "last", "weight", "streak", "due_date", "star_days"],
}
POOLS = {
    "vocab": {
        "base": "vocab_base", "pool": "vocab_pool", "name": "word", "value": "translation",
        "offsets": {"hard": 30, "norm": 100, "easy": 500},
        "title": "Словарь", "emoji": "📘", "color": "#1a73e8",
        "caption": "📘 Фронт: слово → перевод", "reveal": "👁️ Показать перевод  (Пробел)",
    },
    "vocab_rev": {
        "base": "vocab_base", "pool": "vocab_rev_pool", "name": "word", "value": "translation",
        "offsets": {"hard": 30, "norm": 100, "easy": 500},
        "title": "Словарь ←", "emoji": "🔄", "color": "#8e24aa",
        "caption": "🔄 Бек: перевод → слово", "reveal": "👁️ Показать слово  (Пробел)",
    },
    "grammar": {
        "base": "grammar_base", "pool": "grammar_pool", "name": "rule", "value": "cheat",
        "offsets": {"hard": 10, "norm": 30, "easy": 100},
        "title": "Грамматика", "emoji": "📙", "color": "#2e7d32",
        "caption": "📙 Правило", "reveal": "👁️ Показать шпаргалку  (Пробел)",
    },
}
LEVEL_LABELS = {"hard": "🔴 Сложно", "norm": "🟡 Норм", "easy": "🟢 Легко"}

# ================= АДАПТИВНЫЙ CSS =================

st.markdown(
    """
<style>
/* ---------- ТИПОГРАФИКА И КОНТЕЙНЕРЫ ---------- */
div[data-testid="stMarkdownContainer"], div[data-testid="stCaptionContainer"] { overflow-wrap: anywhere; }
div[data-testid="stMetricValue"] { overflow-wrap: anywhere; }
div[data-testid="stMetricValue"] > div { white-space: normal !important; }
div[data-testid="stMetricLabel"] p { white-space: normal !important; }

/* ---------- ПЕРЕКЛЮЧАТЕЛЬ ЯЗЫКОВ (ПИЛЮЛИ) ---------- */
div[data-testid="stRadio"] div[role="radiogroup"] {
  display: flex !important;
  flex-wrap: nowrap !important;
  overflow-x: auto !important;
  -webkit-overflow-scrolling: touch !important;
  scrollbar-width: none !important;
  gap: 8px !important;
  padding: 4px 0 10px 0 !important;
}
div[data-testid="stRadio"] div[role="radiogroup"]::-webkit-scrollbar {
  display: none !important;
}
div[data-testid="stRadio"] div[role="radiogroup"] label {
  background: rgba(128, 128, 128, 0.12) !important;
  padding: 6px 14px !important;
  border-radius: 20px !important;
  border: 1px solid rgba(128, 128, 128, 0.22) !important;
  cursor: pointer !important;
  margin: 0 !important;
  white-space: nowrap !important;
  flex-shrink: 0 !important;
  transition: all 0.18s ease-in-out !important;
  -webkit-tap-highlight-color: transparent !important;
}
div[data-testid="stRadio"] div[role="radiogroup"] label:hover {
  background: rgba(128, 128, 128, 0.22) !important;
}
div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) {
  background: #1a73e8 !important;
  border-color: #1a73e8 !important;
}
div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) p,
div[data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) span {
  color: #ffffff !important;
  font-weight: 700 !important;
}
div[data-testid="stRadio"] div[role="radiogroup"] label > div:first-child,
div[data-testid="stRadio"] div[role="radiogroup"] label [data-testid="stRadioControl"],
div[data-testid="stRadio"] div[role="radiogroup"] label span[data-testid="stRadioControl"],
div[data-testid="stRadio"] div[role="radiogroup"] label input[type="radio"],
div[data-testid="stRadio"] div[role="radiogroup"] label svg {
  display: none !important;
}

/* ---------- ПЕРЕКЛЮЧАТЕЛЬ ЧИСТОГО РЕЖИМА ---------- */
div[data-testid="stToggle"] {
  display: flex !important;
  justify-content: flex-end !important;
  align-items: center !important;
  padding: 4px 0 !important;
}
div[data-testid="stToggle"] label {
  font-weight: 700 !important;
  font-size: 13.5px !important;
}
@media (max-width: 640px) {
  div[data-testid="stToggle"] {
    justify-content: flex-start !important;
    margin-top: 4px !important;
  }
}

/* ---------- КОНТЕЙНЕР КАРТОЧКИ ПОВТОРЕНИЯ ---------- */
div[class*="st-key-studycard_"] div[data-testid="stVerticalBlockBorderWrapper"],
div[class*="st-key-studycard_"] > div[data-testid="stVerticalBlock"] {
  border-radius: 14px !important;
  border: 1px solid rgba(128, 128, 128, 0.22) !important;
  background: rgba(128, 128, 128, 0.03) !important;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05) !important;
}

/* ---------- КНОПКА «ПОКАЗАТЬ ОТВЕТ» ---------- */
div[class*="st-key-reveal_"] {
  margin: 4px 0 !important;
}
div[class*="st-key-reveal_"] button {
  min-height: 42px !important;
  padding: 6px 14px !important;
  border: 1px solid rgba(128, 128, 128, 0.28) !important;
  border-radius: 10px !important;
  background: rgba(128, 128, 128, 0.08) !important;
  color: inherit !important;
  height: auto !important;
  width: 100% !important;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05) !important;
  transition: transform 0.1s ease, background 0.15s ease, border-color 0.15s ease !important;
}
div[class*="st-key-reveal_"] button p {
  font-size: clamp(13px, 3.2vw, 15px) !important;
  font-weight: 600 !important;
  margin: 0 !important;
}
div[class*="st-key-reveal_"] button:hover {
  background: rgba(128, 128, 128, 0.16) !important;
  border-color: rgba(128, 128, 128, 0.45) !important;
}
div[class*="st-key-reveal_"] button:active {
  transform: scale(0.98) !important;
}

/* Менее видная кнопка «Показать перевод» для чистого режима */
div[class*="st-key-studycard_"][class*="_clean"] div[class*="st-key-reveal_"] {
  margin: 2px 0 !important;
}
div[class*="st-key-studycard_"][class*="_clean"] div[class*="st-key-reveal_"] button {
  min-height: 38px !important;
  padding: 4px 12px !important;
  border: 1px solid rgba(128, 128, 128, 0.2) !important;
  border-radius: 9px !important;
  background: rgba(128, 128, 128, 0.04) !important;
  opacity: 0.62 !important;
  box-shadow: none !important;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
div[class*="st-key-studycard_"][class*="_clean"] div[class*="st-key-reveal_"] button p {
  font-size: 13.5px !important;
  font-weight: 600 !important;
  opacity: 0.9 !important;
}
div[class*="st-key-studycard_"][class*="_clean"] div[class*="st-key-reveal_"] button:hover {
  opacity: 1 !important;
  background: rgba(128, 128, 128, 0.14) !important;
  border-color: rgba(128, 128, 128, 0.4) !important;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06) !important;
}

/* ---------- КНОПКИ ОЦЕНКИ ---------- */
div[class*="st-key-btnrow_"] div[data-testid="stHorizontalBlock"] {
  display: flex !important;
  flex-wrap: nowrap !important;
  gap: 8px !important;
}
div[class*="st-key-btnrow_"] div[data-testid="stColumn"],
div[class*="st-key-btnrow_"] div[data-testid="column"] {
  min-width: 0 !important;
  flex: 1 1 0 !important;
  width: auto !important;
}
div[class*="st-key-grade_"] button {
  min-height: 56px !important;
  border-radius: 12px !important;
  height: auto !important;
  padding: 8px 6px !important;
  width: 100% !important;
  transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
div[class*="st-key-grade_"] button p {
  font-size: clamp(12.5px, 3.4vw, 15.5px) !important;
  font-weight: 800 !important;
  line-height: 1.25 !important;
  white-space: normal !important;
  letter-spacing: 0.2px !important;
}
div[class*="st-key-grade_"][class*="_hard"] button {
  background: linear-gradient(135deg, #ef5350 0%, #c62828 100%) !important;
  border: 1px solid rgba(255, 255, 255, 0.18) !important;
  box-shadow: 0 3px 10px rgba(198, 40, 40, 0.3) !important;
}
div[class*="st-key-grade_"][class*="_hard"] button p { color: #ffffff !important; }

div[class*="st-key-grade_"][class*="_norm"] button {
  background: linear-gradient(135deg, #fbc02d 0%, #f57f17 100%) !important;
  border: 1px solid rgba(255, 255, 255, 0.25) !important;
  box-shadow: 0 3px 10px rgba(245, 127, 23, 0.3) !important;
}
div[class*="st-key-grade_"][class*="_norm"] button p { color: #2e1c00 !important; }

div[class*="st-key-grade_"][class*="_easy"] button {
  background: linear-gradient(135deg, #43a047 0%, #2e7d32 100%) !important;
  border: 1px solid rgba(255, 255, 255, 0.18) !important;
  box-shadow: 0 3px 10px rgba(46, 125, 50, 0.3) !important;
}
div[class*="st-key-grade_"][class*="_easy"] button p { color: #ffffff !important; }

div[class*="st-key-grade_"] button:hover {
  filter: brightness(1.08) !important;
  transform: translateY(-2px) !important;
}
div[class*="st-key-grade_"][class*="_hard"] button:hover {
  box-shadow: 0 6px 16px rgba(198, 40, 40, 0.45) !important;
}
div[class*="st-key-grade_"][class*="_norm"] button:hover {
  box-shadow: 0 6px 16px rgba(245, 127, 23, 0.45) !important;
}
div[class*="st-key-grade_"][class*="_easy"] button:hover {
  box-shadow: 0 6px 16px rgba(46, 125, 50, 0.45) !important;
}
div[class*="st-key-grade_"] button:active {
  transform: translateY(1px) scale(0.98) !important;
}

/* ---------- ШАПКА СТЕКА НЕДЕЛИ ---------- */
.zf-hdr {
  background: linear-gradient(90deg, #5e35b1, #1e88e5);
  color: #fff;
  border-radius: 12px;
  padding: 10px 16px;
  font-size: clamp(15px, 3.5vw, 19px);
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px !important;
  box-shadow: 0 2px 8px rgba(94, 53, 177, 0.25);
  min-width: 0;
}
.zf-hdr span {
  white-space: nowrap !important;
  overflow: hidden;
  text-overflow: ellipsis;
}
.zf-hdr small {
  font-size: 13px;
  font-weight: 500;
  opacity: 0.9;
  margin-left: 8px;
  white-space: nowrap;
}

/* ---------- ЧИСТЫЙ РЕЖИМ (ТОПБАР И ОЧЕРЕДЬ) ---------- */
.zf-clean-topbar {
  display: flex !important;
  align-items: center !important;
  gap: 10px !important;
  flex-wrap: wrap !important;
}
.zf-clean-flag {
  font-size: 18px !important;
  font-weight: 800 !important;
  letter-spacing: -0.2px !important;
  color: inherit !important;
}
.zf-clean-pill {
  font-size: 11.5px !important;
  font-weight: 600 !important;
  padding: 3px 9px !important;
  border-radius: 20px !important;
  background: rgba(128, 128, 128, 0.12) !important;
  border: 1px solid rgba(128, 128, 128, 0.22) !important;
  opacity: 0.88 !important;
}

div[class*="st-key-clean_topbar"] div[data-testid="stPopover"] button {
  min-height: 38px !important;
  border-radius: 10px !important;
  font-weight: 600 !important;
  font-size: 13.5px !important;
}

/* ---------- НИЖНЯЯ ПАНЕЛЬ СТАТУСА (ФУТЕР КАРТОЧКИ) ---------- */
.zf-card-footer, .zf-card-bottombar {
  display: flex !important;
  justify-content: space-between !important;
  align-items: center !important;
  flex-wrap: nowrap !important;
  gap: 8px !important;
  margin-top: 10px !important;
  padding-top: 8px !important;
  border-top: 1px solid rgba(128, 128, 128, 0.14) !important;
  width: 100% !important;
  box-sizing: border-box !important;
}

.zf-status-pill {
  display: inline-flex !important;
  align-items: center !important;
  gap: 6px !important;
  padding: 4px 10px !important;
  border-radius: 8px !important;
  background: rgba(128, 128, 128, 0.08) !important;
  border: 1px solid rgba(128, 128, 128, 0.2) !important;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04) !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  color: inherit !important;
  white-space: nowrap !important;
  user-select: none !important;
  transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

.zf-pill-queue {
  cursor: help !important;
}
.zf-pill-queue:hover {
  background: rgba(128, 128, 128, 0.16) !important;
  border-color: rgba(128, 128, 128, 0.38) !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 3px 8px rgba(0, 0, 0, 0.08) !important;
}

.zf-pill-icon {
  font-size: 13px !important;
  line-height: 1 !important;
}

.zf-pill-title {
  opacity: 0.85 !important;
  font-size: 12px !important;
  white-space: nowrap !important;
}

.zf-pill-count {
  font-weight: 800 !important;
  font-size: 12px !important;
  color: inherit !important;
  background: rgba(128, 128, 128, 0.16) !important;
  padding: 1px 6px !important;
  border-radius: 6px !important;
  white-space: nowrap !important;
}

.zf-pill-info-dot {
  font-size: 10px !important;
  opacity: 0.75 !important;
  margin-left: 2px !important;
  padding: 1px 4px !important;
  border-radius: 4px !important;
  background: rgba(128, 128, 128, 0.18) !important;
  font-weight: 700 !important;
  line-height: 1 !important;
}

.zf-pill-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
  font-size: 11.5px !important;
  font-weight: 800 !important;
  padding: 1px 6px !important;
  border-radius: 5px !important;
  background: rgba(74, 222, 128, 0.12) !important;
  color: #4ade80 !important;
  border: 1px solid rgba(74, 222, 128, 0.25) !important;
  white-space: nowrap !important;
}

@media (prefers-color-scheme: light) {
  .zf-pill-code {
    background: rgba(22, 163, 74, 0.1) !important;
    color: #16a34a !important;
    border-color: rgba(22, 163, 74, 0.25) !important;
  }
}

.zf-chip-hover-wrap {
  position: relative !important;
  display: inline-flex !important;
  white-space: nowrap !important;
}
.zf-chip-popup {
  display: none !important;
  position: absolute !important;
  bottom: calc(100% + 8px) !important;
  left: 0 !important;
  min-width: 270px !important;
  max-width: 390px !important;
  background: rgba(26, 26, 28, 0.96) !important;
  color: #f0f6fc !important;
  border: 1px solid rgba(255, 255, 255, 0.16) !important;
  border-radius: 12px !important;
  padding: 10px 14px !important;
  font-size: 12px !important;
  line-height: 1.5 !important;
  box-shadow: 0 14px 36px rgba(0, 0, 0, 0.6) !important;
  backdrop-filter: blur(16px) !important;
  -webkit-backdrop-filter: blur(16px) !important;
  z-index: 9999 !important;
  pointer-events: none !important;
  animation: zfFadeIn 0.15s ease !important;
  white-space: normal !important;
}
@keyframes zfFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
.zf-chip-hover-wrap:hover .zf-chip-popup {
  display: block !important;
}
@media (prefers-color-scheme: light) {
  .zf-chip-popup {
    background: rgba(255, 255, 255, 0.96) !important;
    color: #1f1f1f !important;
    border-color: rgba(0, 0, 0, 0.12) !important;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.18) !important;
  }
}

@media (max-width: 480px) {
  .zf-status-pill {
    padding: 4px 8px !important;
    font-size: 11px !important;
  }
  .zf-pill-title {
    font-size: 11px !important;
  }
  .zf-pill-count {
    padding: 1px 5px !important;
    font-size: 11px !important;
  }
}

/* ---------- ТАБЛИЦА С ЛИПКОЙ ШАПКОЙ ---------- */
.zf-wrap {
  overflow-x: auto;
  overflow-y: auto;
  max-height: 480px;
  border: 1px solid rgba(128, 128, 128, 0.25);
  border-radius: 12px;
  position: relative;
  -webkit-overflow-scrolling: touch;
}
.zf-t {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
}
.zf-t th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: rgba(128, 128, 128, 0.18);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  color: inherit;
  text-align: left;
  padding: 8px 10px;
  white-space: nowrap;
  font-weight: 700;
  border-bottom: 2px solid rgba(128, 128, 128, 0.25);
}
.zf-t td {
  padding: 8px 10px;
  border-top: 1px solid rgba(128, 128, 128, 0.18);
  vertical-align: top;
  overflow-wrap: anywhere;
  min-width: 60px;
}
.zf-t td.ty { white-space: nowrap; }
.zf-t td.n { white-space: nowrap; text-align: right; }

/* ---------- БЛОК МЕТРИК ---------- */
div[class*="st-key-mrow_"] div[data-testid="stHorizontalBlock"] {
  display: flex !important;
  flex-wrap: wrap !important;
  gap: 0.5rem !important;
}
div[class*="st-key-mrow_"] div[data-testid="stColumn"],
div[class*="st-key-mrow_"] div[data-testid="column"] {
  flex: 1 1 calc(20% - 0.5rem) !important;
  min-width: 130px !important;
}

/* ---------- КАРТОЧКИ СТАТИСТИКИ ДАШБОРДА ---------- */
.zf-stats-grid {
  display: grid !important;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)) !important;
  gap: 10px !important;
  margin-bottom: 8px !important;
}
.zf-stat-card {
  background: rgba(128, 128, 128, 0.08) !important;
  border: 1px solid rgba(128, 128, 128, 0.22) !important;
  border-radius: 12px !important;
  padding: 12px 14px !important;
  display: flex !important;
  flex-direction: column !important;
  justify-content: space-between !important;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.03) !important;
  transition: transform 0.15s ease, border-color 0.15s ease !important;
}
.zf-stat-card:hover {
  transform: translateY(-2px) !important;
  border-color: rgba(128, 128, 128, 0.35) !important;
}
.zf-stat-header {
  font-size: 13px !important;
  font-weight: 700 !important;
  opacity: 0.88 !important;
  margin-bottom: 4px !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
}
.zf-stat-val {
  font-size: 24px !important;
  font-weight: 800 !important;
  line-height: 1.15 !important;
  margin-bottom: 6px !important;
}
.zf-stat-val small {
  font-size: 13px !important;
  font-weight: 500 !important;
  opacity: 0.7 !important;
  margin-left: 3px !important;
}
.zf-stat-sub {
  font-size: 11.5px !important;
  opacity: 0.72 !important;
  margin-top: 4px !important;
}
.zf-stat-badges {
  display: flex !important;
  flex-wrap: wrap !important;
  gap: 5px !important;
  margin-top: 2px !important;
}
.zf-badge-yellow {
  display: inline-flex !important;
  align-items: center !important;
  gap: 3px !important;
  background: rgba(241, 194, 50, 0.18) !important;
  color: inherit !important;
  border: 1px solid rgba(241, 194, 50, 0.45) !important;
  padding: 2px 7px !important;
  border-radius: 7px !important;
  font-size: 11.5px !important;
  font-weight: 600 !important;
}
.zf-badge-blue {
  display: inline-flex !important;
  align-items: center !important;
  gap: 3px !important;
  background: rgba(111, 168, 220, 0.18) !important;
  color: inherit !important;
  border: 1px solid rgba(111, 168, 220, 0.45) !important;
  padding: 2px 7px !important;
  border-radius: 7px !important;
  font-size: 11.5px !important;
  font-weight: 600 !important;
}
.zf-progress-bar {
  background: rgba(128, 128, 128, 0.2) !important;
  border-radius: 6px !important;
  height: 6px !important;
  width: 100% !important;
  overflow: hidden !important;
  margin-top: 8px !important;
}
.zf-progress-fill {
  background: linear-gradient(90deg, #1e88e5, #43a047) !important;
  height: 100% !important;
  border-radius: 6px !important;
  transition: width 0.3s ease !important;
}
.zf-stat-pct {
  font-size: 10.5px !important;
  opacity: 0.7 !important;
  margin-top: 3px !important;
  text-align: right !important;
}
.zf-stats-legend {
  font-size: 12px !important;
  line-height: 1.4 !important;
  opacity: 0.85 !important;
  margin-top: 8px !important;
  margin-bottom: 12px !important;
  padding: 7px 12px !important;
  background: rgba(128, 128, 128, 0.07) !important;
  border-radius: 8px !important;
  border-left: 3px solid #1a73e8 !important;
}

/* ---------- ШАПКА И ФУТЕР КАРТОЧКИ ПОВТОРЕНИЯ ---------- */
.zf-card-topbar, .zf-card-bottombar {
  display: flex !important;
  justify-content: space-between !important;
  align-items: center !important;
  flex-wrap: wrap !important;
  gap: 6px !important;
}
.zf-card-topbar {
  margin-bottom: 6px !important;
}
.zf-card-bottombar {
  margin-top: 10px !important;
  padding-top: 2px !important;
}
.zf-card-chip {
  display: inline-flex !important;
  align-items: center !important;
  gap: 4px !important;
  background: rgba(128, 128, 128, 0.14) !important;
  border: 1px solid rgba(128, 128, 128, 0.22) !important;
  padding: 3px 8px !important;
  border-radius: 7px !important;
  font-size: 11.5px !important;
  font-weight: 600 !important;
  color: inherit !important;
  white-space: nowrap !important;
  cursor: help !important;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.1s ease !important;
}
.zf-card-chip:hover {
  background: rgba(128, 128, 128, 0.22) !important;
  border-color: rgba(128, 128, 128, 0.38) !important;
}
.zf-card-chip b {
  font-weight: 800 !important;
}
.zf-card-topbar .zf-card-chip {
  background: rgba(0, 0, 0, 0.06) !important;
  border: 1px solid rgba(0, 0, 0, 0.12) !important;
  color: #1f1f1f !important;
  border-radius: 7px !important;
}
.zf-card-topbar .zf-card-chip:hover {
  background: rgba(0, 0, 0, 0.11) !important;
  border-color: rgba(0, 0, 0, 0.22) !important;
}
.zf-card-bottombar .zf-card-chip {
  background: rgba(128, 128, 128, 0.12) !important;
  border: 1px solid rgba(128, 128, 128, 0.22) !important;
  border-radius: 8px !important;
  padding: 4px 9px !important;
}

/* ---------- ПЛАНШЕТЫ (641px - 1024px) ---------- */
@media (min-width: 641px) and (max-width: 1024px) {
  div.block-container, div[data-testid="stMainBlockContainer"] {
    padding-left: 1.2rem !important;
    padding-right: 1.2rem !important;
    padding-top: 2rem !important;
  }
  div[class*="st-key-mrow_"] div[data-testid="stColumn"],
  div[class*="st-key-mrow_"] div[data-testid="column"] {
    flex: 1 1 calc(33.333% - 0.5rem) !important;
    min-width: calc(33.333% - 0.5rem) !important;
  }
}

/* ---------- СМАРТФОНЫ (<= 640px) ---------- */
@media (max-width: 640px) {
  div.block-container, div[data-testid="stMainBlockContainer"] {
    padding-left: 0.8rem !important;
    padding-right: 0.8rem !important;
    padding-top: 3.8rem !important;
    padding-bottom: 2.5rem !important;
  }
  header[data-testid="stHeader"] {
    background: transparent !important;
  }
  h1 { font-size: 1.35rem !important; padding: 0 !important; margin-bottom: 0.5rem !important; }
  
  /* 2 метрики в ряд */
  div[class*="st-key-mrow_"] div[data-testid="stColumn"],
  div[class*="st-key-mrow_"] div[data-testid="column"] {
    flex: 1 1 calc(50% - 0.5rem) !important;
    min-width: calc(50% - 0.5rem) !important;
  }
  
  /* карточки статистики на телефоне: 2 в ряд, 5-я на всю ширину */
  .zf-stats-grid {
    grid-template-columns: repeat(2, 1fr) !important;
    gap: 8px !important;
  }
  .zf-stat-card {
    padding: 10px 10px !important;
  }
  .zf-stat-card:last-child {
    grid-column: span 2 !important;
  }
  .zf-stat-val {
    font-size: 20px !important;
  }
  .zf-stat-header {
    font-size: 12px !important;
  }
  .zf-badge-yellow, .zf-badge-blue {
    font-size: 10.5px !important;
    padding: 2px 5px !important;
  }
  .zf-stats-legend {
    font-size: 11px !important;
    padding: 6px 9px !important;
  }
  
  .zf-card-topbar, .zf-card-bottombar {
    gap: 4px !important;
  }
  .zf-card-chip {
    font-size: 10px !important;
    padding: 2px 5px !important;
  }
  
  /* Кнопки и выпадающий блок управления стеком недели на мобильных */
  div[class*="st-key-stackhdr"] div[data-testid="column"] button {
    min-height: 42px !important;
    font-size: 13.5px !important;
    font-weight: 600 !important;
    border-radius: 10px !important;
    margin-top: 2px !important;
  }
  div[class*="st-key-stackhdr"] div[data-testid="stExpander"] {
    border-radius: 10px !important;
    border: 1px solid rgba(255, 255, 255, 0.12) !important;
    background: rgba(255, 255, 255, 0.03) !important;
    margin-bottom: 8px !important;
  }
  div[class*="st-key-stackhdr"] div[data-testid="stExpander"] summary {
    font-size: 13.5px !important;
    font-weight: 600 !important;
  }

  .zf-hdr {
    padding: 9px 14px !important;
    font-size: 15px !important;
    border-radius: 10px !important;
    margin-bottom: 8px !important;
  }
  .zf-hdr small { display: none !important; }
  div[class*="st-key-kbhint"] { display: none !important; }
  
  button[data-baseweb="tab"] {
    padding-left: 0.5rem !important; padding-right: 0.5rem !important;
  }
  button[data-baseweb="tab"] p { font-size: 13.5px !important; }
  
  .zf-t { font-size: 12px; }
  .zf-t th, .zf-t td { padding: 6px 7px; }
  .zf-compact .c-position, .zf-compact .c-pron, .zf-compact .c-interval, .zf-compact .c-last {
    display: none !important;
  }
}
</style>
""",
    unsafe_allow_html=True,
)

# ================= ЯЗЫКИ ПО УМОЛЧАНИЮ =================

DEFAULT_LANGS = [
    {
        "id": "es", "name": "Español", "flag": "🇪🇸", "speech": "es-ES",
        "vocab": [
            ("hola", "привет", "ˈo.la", "¡Hola! ¿Cómo estás?", "Привет! Как дела?", ""),
            ("gracias", "спасибо", "ˈɡɾa.θjas", "Muchas gracias por tu ayuda.", "Большое спасибо за помощь.", ""),
            ("por favor", "пожалуйста", "poɾ faˈβoɾ", "Un café, por favor.", "Один кофе, пожалуйста.", ""),
            ("la casa", "дом", "la ˈka.sa", "Mi casa es pequeña.", "Мой дом маленький.", ""),
            ("el agua", "вода", "el ˈa.ɣwa", "Quiero un vaso de agua.", "Хочу стакан воды.", "жен. р., но артикль el"),
            ("comer", "есть, кушать", "koˈmeɾ", "Vamos a comer a las dos.", "Пойдём обедать в два.", ""),
        ],
        "grammar": [
            ("Presente: глаголы на -ar", "o, as, a, amos, áis, an", "Hablo español.", "Я говорю по-испански.", "hablar → hablo, hablas…"),
            ("Ser vs Estar", "ser — суть, профессия; estar — состояние, место", "Soy médico. Estoy cansado.", "Я врач. Я устал.", ""),
            ("Tener (иметь)", "tengo, tienes, tiene, tenemos, tenéis, tienen", "Tengo dos hermanos.", "У меня двое братьев/сестёр.", "возраст: tengo 20 años"),
        ],
        "stack": [("¿Cómo te llamas?", "Как тебя зовут?"), ("Me gustaría un café", "Я бы хотел кофе"),
                  ("No entiendo", "Я не понимаю")],
    },
    {
        "id": "en", "name": "English", "flag": "🇬🇧", "speech": "en-GB",
        "vocab": [
            ("hello", "привет", "həˈləʊ", "Hello! How are you?", "Привет! Как дела?", ""),
            ("thank you", "спасибо", "ˈθæŋk juː", "Thank you very much.", "Большое спасибо.", ""),
            ("please", "пожалуйста", "pliːz", "Could you help me, please?", "Не могли бы вы мне помочь?", ""),
            ("water", "вода", "ˈwɔːtə", "Can I have some water?", "Можно мне воды?", ""),
        ],
        "grammar": [
            ("Present Simple", "I/you/we/they work · he/she/it works", "She works in a bank.", "Она работает в банке.", "3-е лицо ед. ч. +s"),
            ("Артикли a / an / the", "a + согласный звук, an + гласный звук, the — конкретный предмет", "an apple, a book, the sun", "яблоко, книга, солнце", ""),
        ],
        "stack": [("How's it going?", "Как дела?"), ("I'd like a coffee, please", "Я бы хотел кофе"),
                  ("I don't understand", "Я не понимаю")],
    },
    {
        "id": "lv", "name": "Latviešu", "flag": "🇱🇻", "speech": "lv-LV",
        "vocab": [
            ("sveiki", "привет, здравствуйте", "[свэ́йки]", "Sveiki! Kā jums klājas?", "Здравствуйте! Как у вас дела?", ""),
            ("paldies", "спасибо", "[па́лдиэс]", "Paldies par palīdzību.", "Спасибо за помощь.", ""),
            ("lūdzu", "пожалуйста", "[лу́дзу]", "Vienu kafiju, lūdzu.", "Один кофе, пожалуйста.", ""),
            ("ūdens", "вода", "[у́дэнс]", "Es dzeru ūdeni.", "Я пью воду.", "муж. р."),
        ],
        "grammar": [
            ("Род существительных", "муж.: -s, -š, -is · жен.: -a, -e", "Zēns ir labs. Meitene ir laba.", "Мальчик хороший. Девочка хорошая.", ""),
            ("Падежи (locījumi)", "6 падежей: nominatīvs, ģenitīvs, datīvs, akuzatīvs, instrumentālis, lokatīvs", "Es redzu māju.", "Я вижу дом.", "māju — винительный (akuzatīvs)"),
        ],
        "stack": [("Kā tevi sauc?", "Как тебя зовут?"), ("Vienu kafiju, lūdzu", "Один кофе, пожалуйста"),
                  ("Es nesaprotu", "Я не понимаю")],
    },
]

# ================= ДАННЫЕ И ХРАНЕНИЕ =================

def normalize(key, df):
    df = pd.DataFrame(df).reindex(columns=COLS[key])
    for c in COLS[key]:
        if c in INT_COLS:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
        elif c == "weight":
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(1.0).round(1).astype(float)
        elif c == "type":
            df[c] = df[c].where(df[c].isin(TYPES), "Выпускник")
        elif c == "in_stack":
            df[c] = df[c].apply(lambda v: True if str(v).lower() in ("true", "1", "t", "yes", "да") or v is True else False)
        else:
            df[c] = df[c].fillna("").astype(str)
    if "star_days" in df.columns and "type" in df.columns:
        df.loc[(df["type"] == "Старичок") & (df["star_days"] <= 0), "star_days"] = 5
    return df.reset_index(drop=True)


def fresh_lang(d):
    tables = {
        "vocab_base": normalize("vocab_base", pd.DataFrame(d["vocab"], columns=COLS["vocab_base"])),
        "grammar_base": normalize("grammar_base", pd.DataFrame(d["grammar"], columns=COLS["grammar_base"])),
        "stack": normalize("stack", pd.DataFrame(d["stack"], columns=["phrase", "note"] if (d["stack"] and len(d["stack"][0]) == 2) else COLS["stack"])),
        "vocab_pool": normalize("vocab_pool", pd.DataFrame(columns=COLS["vocab_pool"])),
        "vocab_rev_pool": normalize("vocab_rev_pool", pd.DataFrame(columns=COLS["vocab_rev_pool"])),
        "grammar_pool": normalize("grammar_pool", pd.DataFrame(columns=COLS["grammar_pool"])),
    }
    return {"name": d["name"], "flag": d["flag"], "speech": d["speech"], "tables": tables, "daily": {}}


def empty_lang(name, flag, speech):
    return fresh_lang({"name": name, "flag": flag, "speech": speech, "vocab": [], "grammar": [], "stack": []})


def ingest(saved):
    langs, cur = {}, None
    if isinstance(saved, dict) and "languages" in saved:
        for lid, ld in saved["languages"].items():
            raw = ld.get("tables", {})
            tables = {k: normalize(k, pd.DataFrame(raw.get(k, []))) for k in COLS}
            vb = tables["vocab_base"]
            stk = tables["stack"]
            if not stk.empty:
                v_words = set(vb["word"])
                new_v = []
                for _, r in stk.iterrows():
                    p = str(r.get("phrase", "")).strip()
                    if not p:
                        continue
                    if p not in v_words:
                        new_v.append({
                            "word": p, "translation": str(r.get("note", "")).strip(),
                            "pron": str(r.get("pron", "")).strip(),
                            "phrase": str(r.get("phrase_ex", "")).strip() or p,
                            "phrase_tr": str(r.get("phrase_tr", "")).strip() or str(r.get("note", "")).strip(),
                            "extra": str(r.get("extra", "")).strip() or "Из стека недели",
                            "in_stack": True
                        })
                        v_words.add(p)
                    else:
                        vb.loc[vb["word"] == p, "in_stack"] = True
                if new_v:
                    vb = normalize("vocab_base", pd.concat([vb, pd.DataFrame(new_v)], ignore_index=True))
                tables["vocab_base"] = vb
            daily = {str(k): int(v) for k, v in (ld.get("daily") or {}).items()}
            langs[lid] = {"name": ld.get("name", lid), "flag": ld.get("flag", "🌍"),
                          "speech": ld.get("speech", "es-ES"), "tables": tables, "daily": daily}
        cur = saved.get("current")
    if not langs:
        langs = {d["id"]: fresh_lang(d) for d in DEFAULT_LANGS}
    if cur not in langs:
        cur = next(iter(langs))
    return langs, cur


def export_json():
    payload = {
        "version": 5,
        "current": st.session_state["cur"],
        "languages": {
            lid: {
                "name": ld["name"], "flag": ld["flag"], "speech": ld["speech"], "daily": ld["daily"],
                "tables": {k: df.to_dict("records") for k, df in ld["tables"].items()},
            }
            for lid, ld in st.session_state["langs"].items()
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=1,
                      default=lambda o: o.item() if hasattr(o, "item") else str(o))


def save_state():
    tmp = DATA_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(export_json(), encoding="utf-8")
        tmp.replace(DATA_FILE)
    except OSError as e:
        st.warning(f"Не удалось сохранить data.json: {e}")


def flash(msg):
    try:
        st.session_state["_flash"] = msg
    except Exception:
        pass


def cur_id():
    return st.session_state["cur"]


def L():
    return st.session_state["langs"][cur_id()]


def T(key):
    return L()["tables"][key]


def set_T(key, df):
    L()["tables"][key] = df


def today_str():
    return date.today().isoformat()


# ================= ЛОГИКА ПУЛОВ =================

def clean_table(df, cols, key):
    df = pd.DataFrame(df).reindex(columns=cols)
    for c in cols:
        if c == "in_stack":
            df[c] = df[c].apply(lambda v: True if str(v).lower() in ("true", "1", "t", "yes", "да") or v is True else False)
        else:
            df[c] = df[c].fillna("").astype(str).str.strip()
    df = df[df[key] != ""].drop_duplicates(subset=key, keep="first")
    return df.reset_index(drop=True)


def reorder(df):
    if df.empty:
        return df
    df = df.copy()
    df["interval"] = pd.to_numeric(df["interval"], errors="coerce").fillna(0).astype(int)
    today_str = date.today().isoformat()

    # Вариант Б (без спящего режима):
    # Карточки-«Старички» не уходят в конец очереди, а продолжают крутиться в активной колоде.
    # Карточки с наступившим сроком проверки (due_date <= today) получают приоритет проверки.
    df_due_col = df["due_date"].astype(str).str.strip() if "due_date" in df.columns else pd.Series([""] * len(df))
    is_due_star = (df["type"] == "Старичок") & ((df_due_col == "") | (df_due_col <= today_str))

    df["_sort_prio"] = is_due_star.map(lambda x: 0 if x else 1)
    sorted_df = df.sort_values(["_sort_prio", "interval"], kind="stable").drop(columns=["_sort_prio"])

    # Горлышко TOP_N (30) и MAX_GRAD (10):
    # В активном окне top_idx может быть не более MAX_GRAD активных новичков (Выпускник, Повторяем),
    # чтобы новые слова не забивали колоду.
    top_idx = []
    over_idx = []
    grads = 0

    for idx, row in sorted_df.iterrows():
        is_active = row["type"] in ("Выпускник", "Повторяем")
        if len(top_idx) < TOP_N and (not is_active or grads < MAX_GRAD):
            top_idx.append(idx)
            grads += int(is_active)
        else:
            over_idx.append(idx)

    ordered_idx = top_idx + over_idx
    df = df.loc[ordered_idx].reset_index(drop=True)

    # Сдвиг интервала к 0 для первой карточки в очереди
    if not df.empty and df.at[0, "interval"] > 0:
        df["interval"] = (df["interval"] - df.at[0, "interval"]).clip(lower=0).astype(int)

    df["position"] = range(1, len(df) + 1)
    return df


def sync_pool(kind, lang=None):
    lang = lang or L()
    cfg = POOLS[kind]
    name, value = cfg["name"], cfg["value"]
    base = lang["tables"][cfg["base"]]
    mapping = dict(zip(base[name], base[value]))
    if kind == "vocab_rev":
        mapping = {k: v for k, v in mapping.items() if str(v).strip()}
    pool = lang["tables"][cfg["pool"]].copy()

    pool = pool[pool[name].isin(mapping.keys())].drop_duplicates(subset=name)
    if kind == "grammar" and not pool.empty:
        pool["cheat"] = pool[name].map(mapping)

    existing = set(pool[name])
    new_rows = []
    for k, v in mapping.items():
        if k not in existing:
            row = {name: k, "type": "Выпускник", "position": 0, "interval": 0, "reviews": 0, "last": "", "weight": 1.0, "streak": 0, "due_date": "", "star_days": 5}
            if kind == "grammar":
                row["cheat"] = v
            new_rows.append(row)
    cols = COLS[cfg["pool"]]
    if new_rows:
        add = pd.DataFrame(new_rows).reindex(columns=cols)
        pool = add if pool.empty else pd.concat([pool, add], ignore_index=True)

    pool = normalize(cfg["pool"], pool.reindex(columns=cols))
    lang["tables"][cfg["pool"]] = reorder(pool) if not pool.empty else pool


def sync_group(kind, lang=None):
    for k in (VOCAB_KINDS if kind in VOCAB_KINDS else (kind,)):
        sync_pool(k, lang)


def sync_stack_from_vocab(lang=None):
    """Синхронизирует таблицу stack недели из vocab_base по флагу in_stack."""
    target_lang = lang or L()
    tb = target_lang.get("tables", {})
    if "vocab_base" not in tb:
        return
    vb = tb["vocab_base"]
    if vb.empty or "in_stack" not in vb.columns:
        return
    stk_rows = []
    for _, r in vb[vb["in_stack"] == True].iterrows():
        w = str(r.get("word", "")).strip()
        if w:
            stk_rows.append({
                "phrase": w,
                "note": str(r.get("translation", "")).strip(),
                "pron": str(r.get("pron", "")).strip(),
                "phrase_ex": str(r.get("phrase", "")).strip(),
                "phrase_tr": str(r.get("phrase_tr", "")).strip(),
                "extra": str(r.get("extra", "")).strip(),
            })
    tb["stack"] = normalize("stack", pd.DataFrame(stk_rows))


def sync_vocab_from_stack(stack_df=None, lang=None):
    """Обновляет флаги in_stack и данные слов в vocab_base на основе таблицы stack."""
    target_lang = lang or L()
    tb = target_lang.get("tables", {})
    if "vocab_base" not in tb:
        return
    stk = stack_df if stack_df is not None else tb.get("stack", pd.DataFrame())
    vb = tb["vocab_base"].copy()
    if vb.empty or "in_stack" not in vb.columns:
        return
    stk_phrases = set(stk["phrase"].astype(str).str.strip()) if not stk.empty else set()
    vb["in_stack"] = vb["word"].astype(str).str.strip().isin(stk_phrases)

    existing_words = set(vb["word"])
    new_rows = []
    if not stk.empty:
        for _, r in stk.iterrows():
            p = str(r.get("phrase", "")).strip()
            if not p:
                continue
            n = str(r.get("note", "")).strip()
            pron = str(r.get("pron", "")).strip()
            p_ex = str(r.get("phrase_ex", "")).strip() or p
            p_tr = str(r.get("phrase_tr", "")).strip() or n
            extra = str(r.get("extra", "")).strip() or "Из стека недели"
            if p not in existing_words:
                new_rows.append({
                    "word": p, "translation": n, "pron": pron,
                    "phrase": p_ex, "phrase_tr": p_tr, "extra": extra,
                    "in_stack": True
                })
                existing_words.add(p)
            else:
                mask_w = vb["word"] == p
                if n: vb.loc[mask_w, "translation"] = n
                if pron: vb.loc[mask_w, "pron"] = pron
                if p_ex and p_ex != p: vb.loc[mask_w, "phrase"] = p_ex
                if p_tr and p_tr != n: vb.loc[mask_w, "phrase_tr"] = p_tr
                if extra: vb.loc[mask_w, "extra"] = extra
    if new_rows:
        vb = normalize("vocab_base", pd.concat([vb, pd.DataFrame(new_rows)], ignore_index=True))
    tb["vocab_base"] = vb
    sync_group("vocab", target_lang)


def sync_all():
    for lang in st.session_state["langs"].values():
        for kind in POOLS:
            sync_pool(kind, lang)


def grade_item(kind, level, lang=None, item_idx=None):
    target_lang = lang or L()
    cfg = POOLS[kind]
    df = target_lang["tables"][cfg["pool"]].copy()
    if df.empty:
        return
    i = df.index[0] if item_idx is None else item_idx

    cur_type = str(df.at[i, "type"])
    cur_streak = int(df.at[i, "streak"]) if "streak" in df and pd.notna(df.at[i, "streak"]) else 0
    cur_days = int(df.at[i, "star_days"]) if "star_days" in df and pd.notna(df.at[i, "star_days"]) and int(df.at[i, "star_days"]) > 0 else 5
    cur_w = float(df.at[i, "weight"]) if "weight" in df and pd.notna(df.at[i, "weight"]) else 1.0

    today = date.today()
    is_star = cur_type == "Старичок"

    due_str = str(df.at[i, "due_date"]).strip() if "due_date" in df and pd.notna(df.at[i, "due_date"]) else ""
    is_due = True
    if is_star and due_str:
        try:
            is_due = (date.fromisoformat(due_str) <= today)
        except ValueError:
            is_due = True

    if is_star:
        if is_due:
            # Наступил день повторения по интервалу!
            if level == "easy":
                # Успешное повторение в день интервала (1 раз):
                # 1) Коэффициент увеличивается (+0.1)
                cur_w = min(2.5, round(cur_w + 0.1, 1))
                df.at[i, "weight"] = cur_w

                # 2) Новый интервал масштабируется с учётом выросшего коэффициента
                multiplier = max(1.4, round(2.0 * cur_w, 2))
                next_days = max(cur_days + 2, int(round(cur_days * multiplier)))

                df.at[i, "star_days"] = next_days
                df.at[i, "due_date"] = (today + timedelta(days=next_days)).isoformat()
                df.at[i, "streak"] = cur_streak + 1
                df.at[i, "type"] = "Старичок"

                flash(f"🔵 Повторение подтверждено! Коэф: +0.1 (x{cur_w:.1f}) → следующий интервал: {next_days} дн. ({df.at[i, 'due_date']})")
            else:
                # Оступился в день повторения («Сложно» или «Норм»):
                # Карточка переходит в «Повторяем», коэфф падает на -0.2, интервал откатывается на 1 шаг назад
                cur_w = max(0.5, round(cur_w - 0.2, 1))
                prev_days = max(5, cur_days // 2)

                df.at[i, "weight"] = cur_w
                df.at[i, "star_days"] = prev_days
                df.at[i, "due_date"] = ""
                df.at[i, "type"] = "Повторяем"
                df.at[i, "streak"] = 0

                flash(f"🟠 Карточка переведена в «Повторяем». Коэф: -0.2 (x{cur_w:.1f}), откат интервала до {prev_days} дн. Нужно 3 «Легко» подряд, чтобы вернуть «Старичка».")
        else:
            # Карточка-Старичок активна в общей колоде (плановый срок проверки ещё впереди)
            flash(f"🔵 Повторение в колоде! Плановая проверка: {due_str}. Карточка перемещена в очереди.")
    else:
        # Карточка «Выпускник» или «Повторяем» (активное изучение)
        if level == "easy":
            new_streak = cur_streak + 1
            df.at[i, "streak"] = new_streak

            if new_streak >= 3:
                # 3 «Легко» подряд: получает статус «Старичок»!
                # ВНИМАНИЕ: коэффициент НЕ увеличивается при получении статуса!
                # Он вырастет только тогда, когда наступит день повторения по интервалу.
                if cur_type == "Повторяем":
                    # Возврат в Старички: интервал восстанавливается с сохранённого шага
                    start_days = cur_days
                    flash(f"🎉 Статус «Старичок» возвращён! Интервал: {start_days} дн. ({today + timedelta(days=start_days)}). Коэф остался x{cur_w:.1f} (вырастет в день повторения).")
                else:
                    # Новый Старичок: стартовые 5 дней * weight
                    start_days = max(5, int(round(5 * cur_w)))
                    flash(f"🎉 Карточка стала «Старичком» (3 «Легко»)! Первое повторение через {start_days} дн. ({today + timedelta(days=start_days)}). Коэф: x{cur_w:.1f}")

                df.at[i, "type"] = "Старичок"
                df.at[i, "star_days"] = start_days
                df.at[i, "due_date"] = (today + timedelta(days=start_days)).isoformat()
                df.at[i, "streak"] = 0
            else:
                df.at[i, "type"] = cur_type
        else:
            # «Сложно» или «Норм»: сброс серии, коэфф не меняется
            df.at[i, "streak"] = 0

    new_w = float(df.at[i, "weight"])
    added_interval = int(round(cfg["offsets"][level] * new_w))
    df.at[i, "interval"] = int(df.at[i, "interval"]) + added_interval
    df.at[i, "reviews"] = int(df.at[i, "reviews"]) + 1
    df.at[i, "last"] = today_str()
    target_lang["tables"][cfg["pool"]] = reorder(df)
    target_lang["daily"][today_str()] = target_lang["daily"].get(today_str(), 0) + 1


# ================= SUPABASE CLOUD SYNC =================

@st.cache_resource(show_spinner=False)
def get_supabase_client():
    url = None
    key = None
    try:
        url = st.secrets.get("SUPABASE_URL")
        key = st.secrets.get("SUPABASE_KEY")
    except Exception:
        pass
    if not url or not key:
        url = "https://cshfhovnlfgrmgkrgbxk.supabase.co"
        key = "sb_publishable_UtF-re0WbIqw9dbhrb0iAw_Z5dSO-0t"
    try:
        return create_client(url, key)
    except Exception:
        return None


def pack_stack_row(r):
    note = str(r.get("note", "")).strip()
    pron = str(r.get("pron", "")).strip()
    phrase_ex = str(r.get("phrase_ex", "")).strip()
    phrase_tr = str(r.get("phrase_tr", "")).strip()
    extra = str(r.get("extra", "")).strip()

    if any([pron, phrase_ex, phrase_tr, extra]):
        payload = {
            "tr": note,
            "pron": pron,
            "ex": phrase_ex,
            "ex_tr": phrase_tr,
            "extra": extra
        }
        return json.dumps(payload, ensure_ascii=False)
    return note


def unpack_stack_row(raw_phrase, raw_note):
    res = {
        "phrase": str(raw_phrase).strip(),
        "note": str(raw_note).strip(),
        "pron": "",
        "phrase_ex": "",
        "phrase_tr": "",
        "extra": ""
    }
    raw_s = str(raw_note).strip()
    if raw_s.startswith("{") and raw_s.endswith("}"):
        try:
            d = json.loads(raw_s)
            if isinstance(d, dict) and "tr" in d:
                res["note"] = d.get("tr", "")
                res["pron"] = d.get("pron", "")
                res["phrase_ex"] = d.get("ex", "")
                res["phrase_tr"] = d.get("ex_tr", "")
                res["extra"] = d.get("extra", "")
        except Exception:
            pass
    return res


def supabase_pull(lid: str) -> bool:
    """Забирает данные языка из Supabase и обновляет таблицы в приложении."""
    client = get_supabase_client()
    if not client:
        return False
    lang = st.session_state["langs"][lid]

    # Сохраняем серии («streak») и даты из текущего буфера сессии, если в БД они еще не созданы
    cur_v_streaks, cur_v_due, cur_v_days = {}, {}, {}
    if "vocab_pool" in lang.get("tables", {}):
        vp_t = lang["tables"]["vocab_pool"]
        if "streak" in vp_t: cur_v_streaks = dict(zip(vp_t["word"], vp_t["streak"]))
        if "due_date" in vp_t: cur_v_due = dict(zip(vp_t["word"], vp_t["due_date"]))
        if "star_days" in vp_t: cur_v_days = dict(zip(vp_t["word"], vp_t["star_days"]))
    cur_vr_streaks, cur_vr_due, cur_vr_days = {}, {}, {}
    if "vocab_rev_pool" in lang.get("tables", {}):
        vr_t = lang["tables"]["vocab_rev_pool"]
        if "streak" in vr_t: cur_vr_streaks = dict(zip(vr_t["word"], vr_t["streak"]))
        if "due_date" in vr_t: cur_vr_due = dict(zip(vr_t["word"], vr_t["due_date"]))
        if "star_days" in vr_t: cur_vr_days = dict(zip(vr_t["word"], vr_t["star_days"]))

    # 1. Vocab
    v_res = client.table("vocab").select("*").eq("lang", lid).execute()
    v_rows = v_res.data or []
    if v_rows:
        cur_v_in_stack = {}
        if "vocab_base" in lang.get("tables", {}):
            vb_t = lang["tables"]["vocab_base"]
            if isinstance(vb_t, pd.DataFrame) and "word" in vb_t.columns and "in_stack" in vb_t.columns:
                cur_v_in_stack = dict(zip(vb_t["word"], vb_t["in_stack"]))

        base_dict = {}
        front_pool, back_pool = [], []
        for r in v_rows:
            w = r["word"]
            if w not in base_dict or (not base_dict[w].get("translation") and r.get("translation")):
                is_stk = bool(r.get("in_stack")) if "in_stack" in r and r.get("in_stack") is not None else bool(cur_v_in_stack.get(w, False))
                base_dict[w] = {
                    "word": w, "translation": r.get("translation", ""), "pron": r.get("pron", ""),
                    "phrase": r.get("phrase", ""), "phrase_tr": r.get("phrase_tr", ""), "extra": r.get("extra", ""),
                    "in_stack": is_stk
                }
            t_type = r.get("type", "Выпускник")
            pool_item = {
                "word": w, "type": t_type, "position": 0,
                "interval": int(r.get("interval", 0)), "reviews": int(r.get("reviews", 0)),
                "last": str(r.get("last_review", "")),
                "weight": round(float(r.get("weight", 1.0)), 1) if r.get("weight") is not None else 1.0
            }
            if r.get("direction") == "back":
                pool_item["streak"] = int(r.get("streak")) if r.get("streak") is not None and pd.notna(r.get("streak")) else cur_vr_streaks.get(w, 0)
                pool_item["due_date"] = str(r.get("due_date", "") or cur_vr_due.get(w, "")).strip()
                pool_item["star_days"] = int(r.get("star_days")) if r.get("star_days") is not None and pd.notna(r.get("star_days")) and int(r.get("star_days", 0)) > 0 else cur_vr_days.get(w, 5)
                back_pool.append(pool_item)
            else:
                pool_item["streak"] = int(r.get("streak")) if r.get("streak") is not None and pd.notna(r.get("streak")) else cur_v_streaks.get(w, 0)
                pool_item["due_date"] = str(r.get("due_date", "") or cur_v_due.get(w, "")).strip()
                pool_item["star_days"] = int(r.get("star_days")) if r.get("star_days") is not None and pd.notna(r.get("star_days")) and int(r.get("star_days", 0)) > 0 else cur_v_days.get(w, 5)
                front_pool.append(pool_item)

        lang["tables"]["vocab_base"] = normalize("vocab_base", pd.DataFrame(list(base_dict.values())))
        lang["tables"]["vocab_pool"] = reorder(normalize("vocab_pool", pd.DataFrame(front_pool)))
        lang["tables"]["vocab_rev_pool"] = reorder(normalize("vocab_rev_pool", pd.DataFrame(back_pool)))
        sync_stack_from_vocab(lang)

    # 2. Grammar
    cur_g_streaks, cur_g_due, cur_g_days = {}, {}, {}
    if "grammar_pool" in lang.get("tables", {}):
        gp_t = lang["tables"]["grammar_pool"]
        if "streak" in gp_t: cur_g_streaks = dict(zip(gp_t["rule"], gp_t["streak"]))
        if "due_date" in gp_t: cur_g_due = dict(zip(gp_t["rule"], gp_t["due_date"]))
        if "star_days" in gp_t: cur_g_days = dict(zip(gp_t["rule"], gp_t["star_days"]))

    g_res = client.table("grammar").select("*").eq("lang", lid).execute()
    g_rows = g_res.data or []
    if g_rows:
        base_list, pool_list = [], []
        for r in g_rows:
            rule = r["rule"]
            base_list.append({
                "rule": rule, "cheat": r.get("cheat", ""), "phrase": r.get("phrase", ""),
                "phrase_tr": r.get("phrase_tr", ""), "extra": r.get("extra", "")
            })
            gt_type = r.get("type", "Выпускник")
            pool_list.append({
                "rule": rule, "type": gt_type, "cheat": r.get("cheat", ""),
                "position": 0, "interval": int(r.get("interval", 0)),
                "reviews": int(r.get("reviews", 0)), "last": str(r.get("last_review", "")),
                "weight": round(float(r.get("weight", 1.0)), 1) if r.get("weight") is not None else 1.0,
                "streak": int(r.get("streak")) if r.get("streak") is not None and pd.notna(r.get("streak")) else cur_g_streaks.get(rule, 0),
                "due_date": str(r.get("due_date", "") or cur_g_due.get(rule, "")).strip(),
                "star_days": int(r.get("star_days")) if r.get("star_days") is not None and pd.notna(r.get("star_days")) and int(r.get("star_days", 0)) > 0 else cur_g_days.get(rule, 5)
            })
        lang["tables"]["grammar_base"] = normalize("grammar_base", pd.DataFrame(base_list))
        lang["tables"]["grammar_pool"] = reorder(normalize("grammar_pool", pd.DataFrame(pool_list)))

    # 3. Stack (синхронизируется напрямую из vocab по флагу in_stack)
    sync_stack_from_vocab(lang)
    try:
        s_res = client.table("stack").select("*").eq("lang", lid).execute()
        s_rows = s_res.data or []
        if s_rows and (lang["tables"]["stack"].empty if "stack" in lang["tables"] else True):
            rows_list = []
            for r in s_rows:
                p = str(r.get("phrase", "")).strip()
                raw_note = str(r.get("note", "")).strip()
                # 1) Сначала пробуем распаковать fallback JSON из note
                row_dict = unpack_stack_row(p, raw_note)
                # 2) Если в БД есть явные колонки и они не пустые, берем их в приоритете!
                if r.get("pron") is not None and str(r.get("pron", "")).strip():
                    row_dict["pron"] = str(r.get("pron", "")).strip()
                if r.get("phrase_ex") is not None and str(r.get("phrase_ex", "")).strip():
                    row_dict["phrase_ex"] = str(r.get("phrase_ex", "")).strip()
                if r.get("phrase_tr") is not None and str(r.get("phrase_tr", "")).strip():
                    row_dict["phrase_tr"] = str(r.get("phrase_tr", "")).strip()
                if r.get("extra") is not None and str(r.get("extra", "")).strip():
                    row_dict["extra"] = str(r.get("extra", "")).strip()
                # Гарантируем, что note содержит нормальный перевод, а не упакованный JSON
                if row_dict.get("note", "").startswith("{") and row_dict.get("note", "").endswith("}"):
                    unp = unpack_stack_row(p, row_dict["note"])
                    row_dict["note"] = unp.get("note", "")
                if not row_dict.get("note"):
                    row_dict["note"] = raw_note if not (raw_note.startswith("{") and raw_note.endswith("}")) else ""
                rows_list.append(row_dict)
            lang["tables"]["stack"] = normalize("stack", pd.DataFrame(rows_list))
            sync_vocab_from_stack(lang["tables"]["stack"], lang)
    except Exception:
        pass

    sync_group("vocab", lang)
    sync_group("grammar", lang)
    return True


def _safe_cloud_insert(client, table_name: str, rows: list):
    """Вставляет строки в Supabase с автоматической отсечкой колонок, которых еще нет в БД."""
    if not rows:
        return
    curr_rows = [dict(r) for r in rows]
    for _ in range(10):
        try:
            client.table(table_name).insert(curr_rows).execute()
            return
        except Exception as e:
            err_str = str(e)
            found_col = None
            m = re.search(r"Could not find the '(\w+)' column", err_str, re.IGNORECASE)
            if not m:
                m = re.search(r"'(\w+)' column", err_str, re.IGNORECASE)
            if m:
                found_col = m.group(1)
            else:
                for col in ["streak", "due_date", "star_days", "weight", "pron", "phrase_ex", "phrase_tr", "extra", "cheat", "in_stack"]:
                    if f"'{col}'" in err_str.lower() or f'"{col}"' in err_str.lower():
                        found_col = col
                        break
            if found_col and any(found_col in r for r in curr_rows):
                if table_name == "stack" and found_col in ("pron", "phrase_ex", "phrase_tr", "extra"):
                    for r in curr_rows:
                        val = str(r.get(found_col, "")).strip()
                        if val:
                            n_val = str(r.get("note", "")).strip()
                            d_note = {}
                            if n_val.startswith("{") and n_val.endswith("}"):
                                try:
                                    d_note = json.loads(n_val)
                                except Exception:
                                    d_note = {"tr": n_val}
                            else:
                                d_note = {"tr": n_val}
                            key_map = {"pron": "pron", "phrase_ex": "ex", "phrase_tr": "ex_tr", "extra": "extra"}
                            d_note[key_map.get(found_col, found_col)] = val
                            r["note"] = json.dumps(d_note, ensure_ascii=False)
                curr_rows = [{k: v for k, v in r.items() if k != found_col} for r in curr_rows]
            else:
                raise e


def supabase_push(lid: str, tb_snapshot=None) -> bool:
    """Выгружает текущее состояние языка в Supabase, включая weight, streak, due_date, star_days."""
    client = get_supabase_client()
    if not client:
        return False
    if tb_snapshot is not None:
        tb = tb_snapshot
    else:
        try:
            lang = st.session_state["langs"][lid]
            tb = lang["tables"]
        except Exception:
            return False

    # 1. Vocab
    v_base = {r["word"]: r for r in tb["vocab_base"].to_dict("records")}
    v_rows = []
    for r in tb["vocab_pool"].to_dict("records"):
        w = r["word"]
        b = v_base.get(w, {})
        v_rows.append({
            "lang": lid, "direction": "front", "word": w,
            "translation": b.get("translation", ""), "pron": b.get("pron", ""),
            "phrase": b.get("phrase", ""), "phrase_tr": b.get("phrase_tr", ""),
            "extra": b.get("extra", ""), "in_stack": bool(b.get("in_stack", False)),
            "type": r.get("type", "Выпускник"),
            "interval": int(r.get("interval", 0)), "reviews": int(r.get("reviews", 0)),
            "last_review": str(r.get("last", "")),
            "weight": round(float(r.get("weight", 1.0)), 1),
            "streak": int(r.get("streak", 0)),
            "due_date": str(r.get("due_date", "")),
            "star_days": int(r.get("star_days", 5)),
        })
    for r in tb["vocab_rev_pool"].to_dict("records"):
        w = r["word"]
        b = v_base.get(w, {})
        v_rows.append({
            "lang": lid, "direction": "back", "word": w,
            "translation": b.get("translation", ""), "pron": b.get("pron", ""),
            "phrase": b.get("phrase", ""), "phrase_tr": b.get("phrase_tr", ""),
            "extra": b.get("extra", ""), "in_stack": bool(b.get("in_stack", False)),
            "type": r.get("type", "Выпускник"),
            "interval": int(r.get("interval", 0)), "reviews": int(r.get("reviews", 0)),
            "last_review": str(r.get("last", "")),
            "weight": round(float(r.get("weight", 1.0)), 1),
            "streak": int(r.get("streak", 0)),
            "due_date": str(r.get("due_date", "")),
            "star_days": int(r.get("star_days", 5)),
        })
    client.table("vocab").delete().eq("lang", lid).execute()
    if v_rows:
        _safe_cloud_insert(client, "vocab", v_rows)

    # 2. Grammar
    g_base = {r["rule"]: r for r in tb["grammar_base"].to_dict("records")}
    g_rows = []
    for r in tb["grammar_pool"].to_dict("records"):
        rule = r["rule"]
        b = g_base.get(rule, {})
        g_rows.append({
            "lang": lid, "rule": rule, "cheat": r.get("cheat", b.get("cheat", "")),
            "phrase": b.get("phrase", ""), "phrase_tr": b.get("phrase_tr", ""),
            "extra": b.get("extra", ""), "type": r.get("type", "Выпускник"),
            "interval": int(r.get("interval", 0)), "reviews": int(r.get("reviews", 0)),
            "last_review": str(r.get("last", "")),
            "weight": round(float(r.get("weight", 1.0)), 1),
            "streak": int(r.get("streak", 0)),
            "due_date": str(r.get("due_date", "")),
            "star_days": int(r.get("star_days", 5)),
        })
    client.table("grammar").delete().eq("lang", lid).execute()
    if g_rows:
        _safe_cloud_insert(client, "grammar", g_rows)

    # 3. Stack (legacy fallback: если таблица stack в Supabase удалена, игнорируем)
    try:
        s_rows = []
        for r in tb["stack"].to_dict("records"):
            p = str(r.get("phrase", "")).strip()
            if p:
                s_rows.append({
                    "lang": lid,
                    "phrase": p,
                    "note": str(r.get("note", "")).strip(),
                    "pron": str(r.get("pron", "")).strip(),
                    "phrase_ex": str(r.get("phrase_ex", "")).strip(),
                    "phrase_tr": str(r.get("phrase_tr", "")).strip(),
                    "extra": str(r.get("extra", "")).strip(),
                })
        client.table("stack").delete().eq("lang", lid).execute()
        if s_rows:
            _safe_cloud_insert(client, "stack", s_rows)
    except Exception:
        pass

    try:
        st.session_state["last_sync_time"] = time.strftime("%H:%M:%S")
    except Exception:
        pass
    return True


def push_cloud_async(lid=None):
    """Фоновая отправка в Supabase без подвисания интерфейса."""
    target_lid = lid or cur_id()
    try:
        lang = st.session_state["langs"][target_lid]
        tb_snapshot = {
            k: v.copy() if hasattr(v, "copy") else v
            for k, v in lang["tables"].items()
        }
    except Exception:
        tb_snapshot = None

    def worker():
        try:
            supabase_push(target_lid, tb_snapshot=tb_snapshot)
        except Exception as e:
            print(f"[Supabase Push Error]: {e}")

    t = threading.Thread(target=worker, daemon=True)
    t.start()


def ensure_pulled(lid):
    ss = st.session_state
    if lid in ss["synced"]:
        return
    try:
        with st.spinner("⚡ Загружаю из Supabase Cloud…"):
            supabase_pull(lid)
        ss["synced"].add(lid)
        ss["ver"] += 1
        save_state()
    except Exception as e:
        ss["pull_err"][lid] = str(e)[:200]


def _badge():
    sync_time = st.session_state.get("last_sync_time", "")
    st.caption("⚡ **Supabase Cloud** · синхронизировано" + (f" ({sync_time})" if sync_time else ""))


# ================= ИМПОРТ СПИСКОМ =================

TERM_SEPS = {
    "Авто (определить сам)": "AUTO",
    "Тире ( — / – / - )": "DASH",
    "Табуляция (из Excel, Sheets, Quizlet)": "\t",
    "Запятая ,": ",",
    "Точка с запятой ;": ";",
    "Двоеточие :": ":",
    "Равно =": "=",
    "Вертикальная черта |": "|",
    "Свой разделитель…": "CUSTOM",
}
ROW_SEPS = {"Новая строка": "\n", "Точка с запятой ;": ";", "Свой разделитель…": "CUSTOM"}
DASH_RE = re.compile(r"\s+[-–—]\s+")
AUTO_ORDER = ["\t", "DASH", "|", ";", "=", ","]
AUTO_LABELS = {"\t": "табуляция", "DASH": "тире", "|": "«|»", ";": "«;»", "=": "«=»", ",": "запятая"}


def _has_sep(line, sep):
    return bool(DASH_RE.search(line)) if sep == "DASH" else sep in line


def _split_line(line, sep, n):
    parts = DASH_RE.split(line, maxsplit=n - 1) if sep == "DASH" else line.split(sep, n - 1)
    return parts if len(parts) >= 2 else None


def detect_separator(lines):
    best, best_count = None, 0
    for sep in AUTO_ORDER:
        count = sum(1 for ln in lines if _has_sep(ln, sep))
        if count > best_count:
            best, best_count = sep, count
    return best


def parse_pasted(text, term_sep, row_sep, n):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    raw = text.split(row_sep) if row_sep else text.split("\n")
    lines = [ln.strip() for ln in raw if ln.strip()]
    if not lines:
        return [], [], ""
    label = ""
    if term_sep == "AUTO":
        term_sep = detect_separator(lines)
        if term_sep is None:
            return [], lines, "не найден"
        label = AUTO_LABELS[term_sep]
    if not term_sep:
        return [], lines, "не задан"
    rows, bad = [], []
    for ln in lines:
        parts = _split_line(ln, term_sep, n)
        if parts:
            rows.append([p.strip() for p in parts] + [""] * (n - len(parts)))
        else:
            bad.append(ln)
    return rows, bad, label


def apply_import(kind, recs, update_existing, lang=None):
    target_lang = lang or (L() if "langs" in st.session_state else None)
    cfg = POOLS[kind]
    name = cfg["name"]
    base = (target_lang["tables"][cfg["base"]] if target_lang else T(cfg["base"])).copy()
    existing = {r[name]: r for r in base.to_dict("records")}
    added = updated = skipped = 0
    seen, new_rows = set(), []
    for rec in recs:
        n = rec[name]
        if n in seen:
            skipped += 1
            continue
        seen.add(n)
        if n in existing:
            changes = {k: v for k, v in rec.items() if k != name and v and existing[n].get(k, "") != v}
            if update_existing and changes:
                for k, v in changes.items():
                    base.loc[base[name] == n, k] = v
                updated += 1
            else:
                skipped += 1
        else:
            new_rows.append(rec)
            added += 1
    if new_rows:
        base = pd.concat([base, pd.DataFrame(new_rows)], ignore_index=True)
    norm_base = normalize(cfg["base"], base)
    if target_lang:
        target_lang["tables"][cfg["base"]] = norm_base
    else:
        set_T(cfg["base"], norm_base)
    sync_group(kind, target_lang)
    try:
        save_state()
        push_cloud_async()
    except Exception:
        pass
    return added, updated, skipped


def bulk_import(kind, ver):
    cfg = POOLS[kind]
    name = cfg["name"]
    cur = cur_id()
    fields = FIELDS[kind]
    labels = dict(fields)
    existing = {r[name]: r for r in T(cfg["base"]).to_dict("records")}

    example = (
        "hola — привет\ngracias — спасибо\npor favor — пожалуйста" if kind == "vocab" else
        "Ser vs Estar — ser: суть, профессия; estar: состояние, место\nTener — tengo, tienes, tiene"
    )
    st.caption("Одна строка = одна запись. Можно копировать из Quizlet, Excel, заметок или ChatGPT.")
    text = st.text_area("Список", height=180, placeholder=example, label_visibility="collapsed",
                        key=f"imp_text_{cur}_{kind}_{ver}")

    chosen = st.multiselect(
        "Что в каждой строке (по порядку слева направо)", [k for k, _ in fields],
        default=[k for k, _ in fields][:2], format_func=lambda k: labels[k], key=f"imp_cols_{cur}_{kind}",
    )
    c1, c2 = st.columns(2)
    term_label = c1.selectbox("Разделитель внутри строки", list(TERM_SEPS), key=f"imp_term_{cur}_{kind}")
    row_label = c2.selectbox("Разделитель между записями", list(ROW_SEPS), key=f"imp_row_{cur}_{kind}")
    term_sep, row_sep = TERM_SEPS[term_label], ROW_SEPS[row_label]
    if term_sep == "CUSTOM":
        term_sep = c1.text_input("Свой разделитель", key=f"imp_term_c_{cur}_{kind}") or None
    if row_sep == "CUSTOM":
        row_sep = c2.text_input("Свой разделитель строк", key=f"imp_row_c_{cur}_{kind}") or "\n"

    o1, o2 = st.columns(2)
    dup_mode = o1.radio("Если запись уже есть", ["Пропускать", "Обновлять заполненные поля"],
                        key=f"imp_dup_{cur}_{kind}", horizontal=True)
    allow_no_sep = o2.checkbox("Добавлять строки без разделителя", key=f"imp_nosep_{cur}_{kind}")
    update_existing = dup_mode != "Пропускать"

    if not text.strip():
        st.info("Вставьте список выше для предпросмотра.")
        return
    if name not in chosen or len(chosen) < 2:
        st.error(f"Выберите минимум два поля, включая «{labels[name]}».")
        return

    rows, bad, used = parse_pasted(text, term_sep, row_sep, len(chosen))
    recs = [dict(zip(chosen, r)) for r in rows]
    recs = [r for r in recs if r[name]]
    if allow_no_sep and bad:
        recs += [{**{k: "" for k in chosen}, name: ln} for ln in bad]
        bad = []
    if used:
        st.caption(f"Определён разделитель: **{used}**")

    preview, seen = [], set()
    n_new = n_upd = 0
    for rec in recs:
        n = rec[name]
        if n in seen:
            status = "⏭️ дубль в списке"
        elif n in existing:
            changed = any(v and existing[n].get(k, "") != v for k, v in rec.items() if k != name)
            if update_existing and changed:
                status, n_upd = "♻️ обновить", n_upd + 1
            else:
                status = "⏭️ уже есть"
        else:
            status, n_new = "✅ новое", n_new + 1
        seen.add(n)
        preview.append({"Статус": status, **{labels[k]: rec[k] for k in chosen}})

    if preview:
        st.dataframe(pd.DataFrame(preview), hide_index=True, use_container_width=True,
                     height=min(80 + 35 * len(preview), 320))
    if bad:
        st.warning(f"Не распознано строк: {len(bad)}.")

    label = f"➕ Добавить {n_new}" + (f" и обновить {n_upd}" if n_upd else "")
    if st.button(label, key=f"imp_go_{cur}_{kind}", type="primary", use_container_width=True,
                 disabled=(n_new + n_upd) == 0):
        added, updated, skipped = apply_import(kind, recs, update_existing)
        st.session_state["ver"] += 1
        flash(f"Добавлено: {added}, обновлено: {updated}, пропущено: {skipped}")
        st.rerun()


# ================= ВСПОМОГАТЕЛЬНЫЙ UI =================

def esc(s):
    return html.escape(str(s)).replace("$", "&#36;")


def fit_px(text, big, small):
    n = len(str(text))
    return big if n <= 14 else int(max(small, big - (n - 14) * 0.5))


def kcont(key):
    try:
        return st.container(key=key)
    except TypeError:
        return st.container()


def kcont_border(key):
    try:
        return st.container(border=True, key=key)
    except TypeError:
        return st.container(border=True)


def html_table(df, cols, labels, compact=False):
    head = "".join(f'<th class="c-{c}">{esc(labels.get(c, c))}</th>' for c in cols)
    body = []
    for row in df[cols].itertuples(index=False):
        tds = []
        for c, v in zip(cols, row):
            if c == "type":
                ts = TYPE_STYLE.get(v)
                style = (f' style="background:{ts["bg"]} !important;color:{ts["fg"]} !important;font-weight:700"'
                         if ts else "")
                tds.append(f'<td class="ty c-type"{style}>{esc(v)}</td>')
            elif c in INT_COLS:
                tds.append(f'<td class="n c-{c}">{esc(v)}</td>')
            else:
                tds.append(f'<td class="c-{c}">{esc(v)}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="zf-wrap{" zf-compact" if compact else ""}"><table class="zf-t"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def speak_row(items, lang_code, compact=False):
    items = [(label, text) for label, text in items if text]
    if not items:
        return
    btns = "".join(f'<button class="b" data-i="{i}">{esc(label)}</button>' for i, (label, _) in enumerate(items))
    texts = json.dumps([t for _, t in items], ensure_ascii=False).replace("</", r"<\/")
    b_css = """
.b{
  flex:1;
  min-height:44px;
  padding:8px 14px;
  border:1px solid rgba(128,128,128,.24);
  border-radius:12px;
  background:rgba(128,128,128,.09);
  color:inherit;
  font-size:14px;
  font-weight:700;
  letter-spacing:0.1px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  gap:6px;
  cursor:pointer;
  box-shadow:0 1px 3px rgba(0,0,0,.06);
  transition:all .18s cubic-bezier(0.4,0,0.2,1);
  -webkit-tap-highlight-color:transparent;
  user-select:none;
}
.b:hover{
  background:rgba(128,128,128,.18);
  border-color:rgba(128,128,128,.42);
  transform:translateY(-1px);
  box-shadow:0 3px 8px rgba(0,0,0,.1);
}
.b:active{
  background:rgba(128,128,128,.26);
  transform:scale(.98);
}
@media (prefers-color-scheme: dark){
  .b{color:#f0f6fc;}
}
@media (prefers-color-scheme: light){
  .b{color:#1f1f1f;background:rgba(0,0,0,.05);border-color:rgba(0,0,0,.16);}
  .b:hover{background:rgba(0,0,0,.09);border-color:rgba(0,0,0,.26);}
}
"""
    page = f"""
<style>
body{{margin:0;font-family:system-ui,-apple-system,BlinkMacSystemFont,sans-serif;background:transparent}}
.row{{display:flex;gap:8px}}
{b_css}
</style>
<div class="row">__BTNS__</div>
<script>
var T = __TEXTS__;
document.querySelectorAll('.b').forEach(function (b) {{
  b.onclick = function () {{
    try {{
      window.speechSynthesis.cancel();
      var u = new SpeechSynthesisUtterance(T[+b.dataset.i]);
      u.lang = __LANG__; u.rate = 0.9;
      window.speechSynthesis.speak(u);
    }} catch(e) {{}}
    try {{ b.blur(); if (window.parent) window.parent.focus(); }} catch(e) {{}}
  }};
}});
window.addEventListener('keydown', function(e) {{
  try {{
    if (window.parent && window.parent.__zfH) {{
      window.parent.__zfH(e);
    }}
  }} catch(err) {{}}
}}, true);
</script>"""
    page = page.replace("__BTNS__", btns).replace("__TEXTS__", texts).replace("__LANG__", json.dumps(lang_code))
    components.html(page, height=52)


STACK_COLORS = [("#fff3e0", "#fb8c00"), ("#e3f2fd", "#1e88e5"), ("#e8f5e9", "#43a047"),
                ("#f3e5f5", "#8e24aa"), ("#ffebee", "#e53935")]


def stack_cards(stack, lang_code):
    cards, heights = [], []
    for i, r in enumerate(stack.itertuples()):
        bg, bd = STACK_COLORS[i % len(STACK_COLORS)]
        phrase = str(getattr(r, "phrase", "")).strip()
        note = str(getattr(r, "note", "")).strip()
        pron = str(getattr(r, "pron", "")).strip()
        phrase_ex = str(getattr(r, "phrase_ex", "")).strip()
        phrase_tr = str(getattr(r, "phrase_tr", "")).strip()
        extra = str(getattr(r, "extra", "")).strip()

        has_details = bool(pron or phrase_ex or phrase_tr or extra)

        details_parts = []
        if pron:
            shown_pron = pron if pron.startswith("[") or pron.startswith("/") else f"/ {pron} /"
            details_parts.append(f'<div class="d-row">🗣️ <b>Произношение:</b> <span class="d-val">{esc(shown_pron)}</span></div>')
        if phrase_ex:
            ex_esc = html.escape(phrase_ex, quote=True)
            details_parts.append(f'<div class="d-row">💬 <b>Пример:</b> <span class="d-val">{esc(phrase_ex)}</span> <span class="s spk-ex" data-ex="{ex_esc}">🔊</span></div>')
            if phrase_tr:
                details_parts.append(f'<div class="d-sub">↳ {esc(phrase_tr)}</div>')
        if extra:
            details_parts.append(f'<div class="d-row">💡 <b>Заметка:</b> <span class="d-val">{esc(extra)}</span></div>')

        hint_html = '<div class="hint">👁️ нажми, чтобы увидеть детали</div>' if has_details else ''
        details_html = f'<div class="details" style="display:none;">{"".join(details_parts)}</div>' if has_details else ''

        phrase_esc = html.escape(phrase, quote=True)
        cards.append(
            f'<div class="c" style="background:{bg};border-left:7px solid {bd}" data-t="{phrase_esc}">'
            f'<div class="p"><span>{esc(phrase)}</span> <span class="s spk-btn">🔊</span></div>'
            f'<div class="n">{esc(note)}</div>'
            f'{hint_html}'
            f'{details_html}'
            f'</div>'
        )
        h = 56 + 26 * math.ceil(len(phrase) / 22) + (20 * math.ceil(len(note) / 30) if note else 0)
        if has_details:
            h += 22
        heights.append(h)

    est = sum(max(heights[j:j + 3]) + 14 for j in range(0, len(heights), 3)) if heights else 80
    page = """
<style>
body{margin:0;padding:2px 2px 6px 2px;font-family:system-ui,sans-serif;background:transparent}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(250px,100%),1fr));gap:10px}
.c{border-radius:12px;padding:12px 14px;cursor:pointer;color:#1f1f1f;box-shadow:0 1px 3px rgba(0,0,0,.12);min-width:0;user-select:none;-webkit-tap-highlight-color:transparent;transition:box-shadow .15s ease}
.c:hover{box-shadow:0 3px 8px rgba(0,0,0,.18)}
.c:active{transform:scale(.99)}
.p{font-size:clamp(16px,4.5vw,22px);font-weight:800;line-height:1.25;overflow-wrap:anywhere;display:flex;align-items:center;justify-content:space-between}
.n{font-size:clamp(13px,3.5vw,16px);margin-top:5px;color:#3b3b3b;overflow-wrap:anywhere}
.s{font-size:16px;opacity:.65;cursor:pointer;padding:2px 6px;border-radius:6px;transition:opacity .15s,background .15s}
.s:hover{opacity:1;background:rgba(0,0,0,.08)}
.hint{font-size:11px;opacity:.65;margin-top:7px;font-weight:600}
.details{margin-top:9px;padding-top:7px;border-top:1px dashed rgba(0,0,0,.18);font-size:12px;line-height:1.45;animation:zfFadeIn .18s ease}
@keyframes zfFadeIn{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:translateY(0)}}
.d-row{margin-bottom:4px;color:#222;overflow-wrap:anywhere}
.d-sub{margin-left:14px;font-size:11.5px;color:#2e7d32;font-style:italic;margin-top:-2px;margin-bottom:4px;overflow-wrap:anywhere}
.d-val{font-weight:600}
@media (max-width:640px){
  .g{grid-template-columns:repeat(auto-fit,minmax(min(145px,100%),1fr));gap:7px}
  .c{padding:9px 11px;border-radius:10px;border-left-width:5px !important}
  .p{font-size:14.5px}.n{font-size:12px;margin-top:2px}.s{font-size:12px}.hint{font-size:10px}
}
</style>
<div class="g" id="g">__CARDS__</div>
<script>
function speak(e, text) {
  if (e) e.stopPropagation();
  try {
    window.speechSynthesis.cancel();
    var u = new SpeechSynthesisUtterance(text);
    u.lang = __LANG__; u.rate = 0.9;
    window.speechSynthesis.speak(u);
  } catch(err) {}
}

document.querySelectorAll('.spk-btn').forEach(function(b) {
  b.onclick = function(e) {
    e.stopPropagation();
    var card = b.closest('.c');
    if (card) speak(e, card.dataset.t);
  };
});
document.querySelectorAll('.spk-ex').forEach(function(b) {
  b.onclick = function(e) {
    e.stopPropagation();
    speak(e, b.dataset.ex);
  };
});

document.querySelectorAll('.c').forEach(function (c) {
  c.onclick = function (e) {
    var details = c.querySelector('.details');
    if (details) {
      var isHidden = details.style.display === 'none';
      details.style.display = isHidden ? 'block' : 'none';
      var hint = c.querySelector('.hint');
      if (hint) {
        hint.innerHTML = isHidden ? '▲ скрыть детали' : '👁️ нажми, чтобы увидеть детали';
      }
      fit();
    } else {
      speak(e, c.dataset.t);
    }
  };
});

var g = document.getElementById('g');
function fit() {
  try {
    if (window.frameElement) {
      window.frameElement.style.height = (document.body.scrollHeight + 14) + 'px';
    }
  } catch(e) {}
}
window.addEventListener('load', fit);
window.addEventListener('resize', fit);
if (window.ResizeObserver) { new ResizeObserver(fit).observe(g); }
setTimeout(fit, 80); setTimeout(fit, 350);
</script>"""
    page = page.replace("__CARDS__", "".join(cards)).replace("__LANG__", json.dumps(lang_code))
    components.html(page, height=max(90, est), scrolling=False)


def keyboard_hook():
    components.html(
        """
<script>
(function () {
  var p = window.parent;
  if (!p || !p.document) return;
  try { p.focus(); } catch(e) {}
  function clickBtn(txt) {
    var bs = p.document.querySelectorAll('button');
    for (var i = 0; i < bs.length; i++) {
      var b = bs[i];
      if (b.offsetParent !== null && !b.disabled && (b.innerText || '').indexOf(txt) > -1) {
        b.click();
        return true;
      }
    }
    return false;
  }
  p.__zfH = function (e) {
    var t = e.target, tag = ((t && t.tagName) || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || (t && t.isContentEditable)) return;
    if (p.document.querySelector('div[role="dialog"]')) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.code === 'Space') {
      if (clickBtn('Показать')) e.preventDefault();
    } else if (e.key === '1') {
      if (clickBtn('Сложно')) e.preventDefault();
    } else if (e.key === '2') {
      if (clickBtn('Норм')) e.preventDefault();
    } else if (e.key === '3') {
      if (clickBtn('Легко')) e.preventDefault();
    }
  };
  if (!p.__zfKeyboardInstalled) {
    p.__zfKeyboardInstalled = true;
    p.document.addEventListener('keydown', function(e) {
      if (p.__zfH) p.__zfH(e);
    }, true);
  }
})();
</script>""",
        height=0,
    )


def answer_html(kind, answer, rec):
    big = fit_px(answer, 26 if kind in VOCAB_KINDS else 20, 16)
    parts = [f'<div style="font-size:clamp(17px,4.5vw,{big}px);font-weight:800;line-height:1.25;color:#1f1f1f;overflow-wrap:anywhere">'
             f'{esc(answer) if answer else "(не заполнено)"}</div>']
    if kind == "vocab_rev" and rec.get("pron"):
        parts.append(f'<div style="font-size:clamp(13px,3.5vw,16px);color:#3b3b3b;margin-top:3px;overflow-wrap:anywhere">{esc(rec["pron"])}</div>')
    if rec.get("phrase"):
        parts.append(f'<div style="margin-top:8px;font-size:clamp(14px,3.8vw,17px);font-weight:700;color:#1f1f1f;overflow-wrap:anywhere">{esc(rec["phrase"])}</div>')
        if rec.get("phrase_tr"):
            parts.append(f'<div style="font-size:clamp(13px,3.4vw,15.5px);color:#2e7d32;margin-top:2px;overflow-wrap:anywhere">{esc(rec["phrase_tr"])}</div>')
    if rec.get("extra"):
        parts.append(f'<div style="margin-top:6px;font-size:clamp(11.5px,3vw,13px);color:#4e4e4e;overflow-wrap:anywhere">📝 {esc(rec["extra"])}</div>')
    return ('<div class="c" style="background:#e8f5e9;border-left:7px solid #43a047;border-radius:12px;'
            'padding:12px 14px;margin:8px 0;box-shadow:0 1px 3px rgba(0,0,0,0.12);color:#1f1f1f">' + "".join(parts) + "</div>")


def format_due_diff(seconds):
    seconds = int(seconds)
    if seconds <= 0:
        return "сейчас"
    if seconds >= 86400:
        d = seconds // 86400
        h = (seconds % 86400) // 3600
        return f"{d} д {h} ч" if h > 0 else f"{d} д"
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h} ч {m} м" if m > 0 else f"{h} ч"
    if seconds >= 60:
        return f"{seconds // 60} мин"
    return f"{seconds} сек"


def rev_word(n):
    n = int(n)
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} повтор"
    elif 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return f"{n} повтора"
    return f"{n} повторов"


def do_reveal(rkey, val, kind=None):
    st.session_state[rkey] = val
    if kind:
        lang = L()
        cfg = POOLS.get(kind)
        if cfg and cfg["pool"] in lang["tables"]:
            pool = lang["tables"][cfg["pool"]].copy()
            if not pool.empty:
                i = pool.index[0]
                cur_t = str(pool.at[i, "type"])
                if cur_t == "Старичок":
                    # «Старичок» подсмотрел перевод: оступился!
                    # Переходит в «Повторяем», коэфф падает на 0.2, интервал откатывается на 1 шаг назад
                    cur_w = float(pool.at[i, "weight"]) if "weight" in pool and pd.notna(pool.at[i, "weight"]) else 1.0
                    cur_days = int(pool.at[i, "star_days"]) if "star_days" in pool and pd.notna(pool.at[i, "star_days"]) and int(pool.at[i, "star_days"]) > 0 else 5
                    new_w = max(0.5, round(cur_w - 0.2, 1))
                    pool.at[i, "weight"] = new_w
                    prev_days = max(5, cur_days // 2)
                    pool.at[i, "star_days"] = prev_days
                    if "due_date" in pool.columns:
                        pool.at[i, "due_date"] = ""
                    pool.at[i, "type"] = "Повторяем"
                # Для всех типов: подглядывание сбрасывает серию в 0
                if "streak" in pool.columns:
                    pool.at[i, "streak"] = 0
                lang["tables"][cfg["pool"]] = pool
                save_state()


def do_grade(kind, level, rkey):
    grade_item(kind, level)
    st.session_state.pop(rkey, None)
    st.session_state["_peeked"] = False
    st.session_state["_active_card_key"] = None
    if kind in VOCAB_KINDS:
        st.session_state["mix_dir"] = random.choice(VOCAB_KINDS)
    save_state()
    push_cloud_async()


def render_card(kind, compact=False):
    cfg = POOLS[kind]
    lang, cur = L(), cur_id()
    name = cfg["name"]
    is_vocab = kind in VOCAB_KINDS
    rev = kind == "vocab_rev"
    pool, base = T(cfg["pool"]), T(cfg["base"])
    card_suffix = "clean" if compact else "full"
    with kcont_border(f"studycard_{cur}_{kind}_{card_suffix}"):
        if pool.empty:
            st.caption(cfg["caption"])
            msg = f"Пул пуст. Добавь данные во вкладке «{'Словарь' if is_vocab else 'Грамматика'}»."
            if rev:
                msg += " Для обратного режима у слов должен быть заполнен перевод."
            st.warning(msg)
            return

        top = pool.iloc[0]
        found = base[base[name] == top[name]]
        rec = found.iloc[0].to_dict() if not found.empty else {}
        ts = TYPE_STYLE.get(top["type"], TYPE_STYLE["Выпускник"])

        cur_type = str(top["type"])
        is_star = cur_type == "Старичок"
        is_repeat = cur_type == "Повторяем"
        streak = int(top.get("streak", 0)) if "streak" in top and pd.notna(top.get("streak")) else (3 if is_star else 0)
        due_str = str(top.get("due_date", "")).strip()
        star_days = int(top.get("star_days", 5)) if "star_days" in top and pd.notna(top.get("star_days")) and int(top.get("star_days", 0)) > 0 else 5

        today = date.today()
        is_due = False
        days_rem = 0
        if due_str:
            try:
                due_d = date.fromisoformat(due_str)
                days_rem = (due_d - today).days
                is_due = days_rem <= 0
            except ValueError:
                is_due = True
        else:
            is_due = True

        if is_star:
            if is_due:
                if days_rem < 0:
                    type_title = f"🔵 Выучено (Старичок) · 🔔 Проверка (просрочено на {-days_rem} дн)"
                else:
                    type_title = "🔵 Выучено (Старичок) · 🔔 Пора проверить!"
                nxt_w = min(2.5, round(weight + 0.1, 1))
                nxt_est = max(star_days + 2, int(round(star_days * max(1.4, round(2.0 * nxt_w, 2)))))
                type_desc = f"Срок повторения наступил! Нажмите «Легко», чтобы подтвердить (коэфф: +0.1 → x{nxt_w:.1f}, интервал вырастет с {star_days} до {nxt_est} дн). При ошибке карточка перейдет в «Повторяем»."
            else:
                type_title = f"🔵 Выучено (Старичок) · 📅 Через {days_rem} дн ({due_str})"
                type_desc = f"Карточка активна в общей колоде. Нажмите «Легко» / «Норм» / «Сложно» для тренировки в очереди. Плановая проверка наступит {due_str}."
        elif is_repeat:
            type_title = f"🟠 Повторяем ({streak}/3)" if streak > 0 else "🟠 Повторяем (0/3)"
            type_desc = f"Бывший «Старичок» на восстановлении памяти. Серия «Легко»: {streak} из 3 (нужно 3 «Легко» подряд, чтобы вернуть статус. Коэфф. x{weight:.1f} зафиксирован и вырастет в день повторения)."
        else:
            type_title = f"🟡 Учим ({streak}/3)" if streak > 0 else "🟡 Учим (Выпускник)"
            type_desc = f"Карточка в активном изучении. Серия «Легко»: {streak} из 3 (нужно 3 «Легко» подряд, чтобы стать «Старичком» и получить первый интервал)."

        grads = int((pool["type"] == "Выпускник").sum())
        reps = int((pool["type"] == "Повторяем").sum())

        today_s = date.today().isoformat()
        pool_due = pool["due_date"].fillna("").astype(str).str.strip() if "due_date" in pool.columns else pd.Series([""] * len(pool))

        # Разделяем Старичков: созревшие к проверке сегодня vs активные в колоде
        is_star_mask = pool["type"] == "Старичок"
        is_due_mask = is_star_mask & ((pool_due == "") | (pool_due <= today_s))
        is_deck_mask = is_star_mask & (pool_due > today_s)

        due_stars = int(is_due_mask.sum())
        deck_stars = int(is_deck_mask.sum())

        # Активная очередь на сегодня: те, кому нужно уделить внимание прямо сейчас
        active_today = grads + reps + due_stars
        total_all = len(pool)

        weight = float(top.get("weight", 1.0)) if "weight" in top and pd.notna(top.get("weight")) else 1.0
        weight_str = f"x{weight:.1f}"

        unit_word = "слово" if is_vocab else "правило"
        if active_today % 10 == 1 and active_today % 100 != 11:
            active_lbl = f"{active_today} {unit_word}"
        elif 2 <= active_today % 10 <= 4 and not (12 <= active_today % 100 <= 14):
            active_lbl = f"{active_today} {'слова' if is_vocab else 'правила'}"
        else:
            active_lbl = f"{active_today} {'слов' if is_vocab else 'правил'}"

        if total_all % 10 == 1 and total_all % 100 != 11:
            total_lbl = f"{total_all} {unit_word}"
        elif 2 <= total_all % 10 <= 4 and not (12 <= total_all % 100 <= 14):
            total_lbl = f"{total_all} {'слова' if is_vocab else 'правила'}"
        else:
            total_lbl = f"{total_all} {'слов' if is_vocab else 'правил'}"

        weight_label = "Коэфф. слова" if is_vocab else "Коэфф. правила"

        if due_stars > 0:
            pill_count_html = f'{total_all} <small style="font-weight:700;font-size:11px;color:#ef5350;">(🔔 {due_stars} к проверке)</small>'
        else:
            pill_count_html = f'{total_all}'

        nxt_names = list(pool[name].iloc[1:4])
        if rev:
            tr_map = dict(zip(base["word"], base["translation"]))
            nxt = [tr_map.get(x, "") for x in nxt_names]
        else:
            nxt = nxt_names

        nxt_clean = ' · '.join(map(str, nxt))
        nxt_html = (
            f'<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(128,128,128,0.2);">'
            f'⏭️ <b style="opacity:0.9;">Дальше:</b> '
            f'<span style="opacity:0.85;">{esc(nxt_clean)}</span></div>'
        ) if nxt else ""
        streak_badge = f"{streak}/3 (выучено)" if is_star else f"{streak}/3"
        if is_star:
            status_badge = "🔔 Пора проверить!" if is_due else f"📅 Интервал: {star_days} дн (до {due_str})"
        elif is_repeat:
            status_badge = f"Восстановление: {streak}/3"
        else:
            status_badge = f"Изучение: {streak}/3"

        queue_counts = []
        if grads > 0:
            queue_counts.append(f"🟡 На изучении: {grads}")
        if reps > 0:
            queue_counts.append(f"🟠 Повторяем: {reps}")
        if due_stars > 0:
            queue_counts.append(f"🔔 Пора проверить: {due_stars}")
        if deck_stars > 0:
            queue_counts.append(f"🔵 Старички в колоде: {deck_stars}")
        if not queue_counts:
            queue_counts.append("🎉 Все карточки выучены!")

        hdr = f"📋 В очереди: {total_lbl} (к проверке: {due_stars})" if due_stars > 0 else f"📋 В очереди: {total_lbl}"
        tooltip_lines = [
            hdr,
            " · ".join(queue_counts),
            f"⚡ {weight_label}: {weight_str}",
            f"🔥 Серия «Легко»: {streak_badge}",
            f"⏱️ Статус: {status_badge}",
        ]
        if nxt:
            tooltip_lines.append(f"⏭️ Дальше: {nxt_clean}")
        tooltip_text = "\n".join(tooltip_lines)

        st.caption(cfg["caption"])

        if is_vocab:
            w = top[name]
            vp = T("vocab_pool")
            vr = T("vocab_rev_pool")
            v_match = vp[vp["word"] == w]
            vr_match = vr[vr["word"] == w]

            v_revs = int(v_match.iloc[0]["reviews"]) if not v_match.empty else 0
            vr_revs = int(vr_match.iloc[0]["reviews"]) if not vr_match.empty else 0

            if v_revs > vr_revs:
                ratio_hint = "Фронт повторяли чаще Бека"
            elif vr_revs > v_revs:
                ratio_hint = "Бек повторяли чаще Фронта"
            elif v_revs > 0:
                ratio_hint = "Повторено поровну в обе стороны"
            else:
                ratio_hint = "Новое слово"

            ratio_html = (
                f'<span class="zf-card-chip" title="Повторений: Фронт — {v_revs}, Бек — {vr_revs} ({ratio_hint})">'
                f'📘 Фронт: <b>{rev_word(v_revs)}</b> &nbsp;·&nbsp; 🔄 Бек: <b>{rev_word(vr_revs)}</b></span>'
            )
        else:
            reviews_cnt = int(top["reviews"])
            ratio_html = (
                f'<span class="zf-card-chip" title="Сколько раз вы повторяли это правило">'
                f'🔁 <b>{rev_word(reviews_cnt)}</b></span>'
            )

        prompt = (rec.get("translation", "") or "(нет перевода)") if rev else top[name]
        size = fit_px(prompt, 34 if is_vocab else 28, 18)
        pron = rec.get("pron", "") if kind == "vocab" else ""
        pron_html = ""
        if pron:
            shown_pron = pron if pron.startswith("[") else f"/ {pron} /"
            pron_html = (f'<div style="font-size:clamp(13px,3.5vw,16px);color:#3b3b3b;margin-top:3px;overflow-wrap:anywhere">'
                         f'{esc(shown_pron)}</div>')

        topbar_html = (
            '<div class="zf-card-topbar">'
            f'<span class="zf-card-chip" title="{type_desc}" style="border:1px solid {ts["border"]};">{type_title}</span>'
            f'{ratio_html}'
            '</div>'
        )

        st.markdown(
            f'<div class="c" style="background:{ts["bg"]};border-left:7px solid {ts["border"]};border-radius:12px;'
            f'padding:12px 14px;color:#1f1f1f;box-shadow:0 1px 3px rgba(0,0,0,0.12);margin-bottom:6px;">'
            f'{topbar_html}'
            f'<div style="font-size:clamp(18px,5.5vw,{size}px);font-weight:800;line-height:1.25;color:#1f1f1f;margin-top:8px;overflow-wrap:anywhere">'
            f'{esc(prompt)} <span style="font-size:15px;opacity:0.55;">🔊</span></div>{pron_html}</div>',
            unsafe_allow_html=True,
        )

        rkey = f"rv_{cur}_{kind}"
        shown = st.session_state.get("auto_reveal", False) or st.session_state.get(rkey) == top[name]
        if kind == "vocab":
            answer = rec.get("translation", "")
        elif rev:
            answer = top[name]
        else:
            answer = top["cheat"] or rec.get("cheat", "")
        # Перевод показывается прямо под словом
        if shown:
            st.markdown(answer_html(kind, answer, rec), unsafe_allow_html=True)

        # Кнопки оценки (Сложно / Норм / Легко) расположены выше кнопки «Показать перевод»
        with kcont(f"btnrow_{cur}_{kind}"):
            cols = st.columns(3)
            for col, level in zip(cols, ("hard", "norm", "easy")):
                eff_offset = int(round(cfg["offsets"][level] * weight))
                label = f"{LEVEL_LABELS[level]} (+{eff_offset})"
                col.button(
                    label,
                    key=f"grade_{cur}_{kind}_{level}",
                    on_click=do_grade,
                    args=(kind, level, rkey),
                    use_container_width=True,
                )

        # Кнопка «Показать перевод» (если ответ еще не открыт)
        if not shown:
            st.button(
                cfg["reveal"],
                key=f"reveal_{cur}_{kind}",
                on_click=do_reveal,
                args=(rkey, top[name], kind),
                use_container_width=True,
            )

        if kind == "vocab":
            speak_row([("🔊 Слово", top[name]), ("🔊 Фраза", rec.get("phrase", ""))], lang["speech"], compact=compact)
        elif rev:
            if shown:
                speak_row([("🔊 Слово", top[name]), ("🔊 Фраза", rec.get("phrase", ""))], lang["speech"], compact=compact)
        else:
            speak_row([("🔊 Шпаргалка", answer), ("🔊 Фраза", rec.get("phrase", ""))], lang["speech"], compact=compact)

        queue_chips = []
        if grads > 0:
            queue_chips.append(f'<span style="background:rgba(251,140,0,0.18);color:#ff9800;padding:2px 8px;border-radius:6px;font-weight:700;font-size:11.5px;">🟡 На изучении: {grads}</span>')
        if reps > 0:
            queue_chips.append(f'<span style="background:rgba(245,124,0,0.18);color:#f57c00;padding:2px 8px;border-radius:6px;font-weight:700;font-size:11.5px;">🟠 Повторяем: {reps}</span>')
        if due_stars > 0:
            queue_chips.append(f'<span style="background:rgba(239,83,80,0.18);color:#ef5350;padding:2px 8px;border-radius:6px;font-weight:700;font-size:11.5px;">🔔 Пора проверить: {due_stars}</span>')
        if deck_stars > 0:
            queue_chips.append(f'<span style="background:rgba(30,136,229,0.18);color:#42a5f5;padding:2px 8px;border-radius:6px;font-weight:700;font-size:11.5px;">🔵 В колоде: {deck_stars}</span>')
        queue_chips_html = f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px;">{"".join(queue_chips)}</div>' if queue_chips else ''
        total_chip_html = f'<span style="opacity:0.75;font-size:11px;">(🔔 к проверке: {due_stars})</span>' if due_stars > 0 else ''

        bottom_bar_html = (
            '<div class="zf-card-footer">'
            '<div class="zf-chip-hover-wrap">'
            f'<div class="zf-status-pill zf-pill-queue" title="{html.escape(tooltip_text, quote=True)}">'
            '<span class="zf-pill-icon">📋</span>'
            '<span class="zf-pill-title">В очереди:</span>'
            f'<span class="zf-pill-count">{pill_count_html}</span>'
            '<span class="zf-pill-info-dot">ℹ️</span>'
            '</div>'
            '<div class="zf-chip-popup">'
            '<div style="font-weight:800;font-size:12.5px;margin-bottom:6px;display:flex;align-items:center;gap:6px;">'
            '<span>📋 В очереди на сегодня:</span>'
            f'<span style="background:rgba(128,128,128,0.22);padding:1px 6px;border-radius:6px;">{esc(active_lbl)}</span>'
            f'{total_chip_html}'
            '</div>'
            f'{queue_chips_html}'
            '<div style="margin-top:4px;font-size:11.5px;opacity:0.88;display:flex;gap:8px;flex-wrap:wrap;">'
            f'<span>⚡ <b>{esc(weight_label)}:</b> <code>{weight_str}</code></span>'
            f'<span>🔥 <b>Серия:</b> <code>{streak_badge}</code></span>'
            f'<span>⏱️ <code>{esc(status_badge)}</code></span>'
            '</div>'
            f'{nxt_html}'
            '</div>'
            '</div>'
            '<div class="zf-status-pill zf-pill-weight" title="Коэффициент сложности: растёт (+0.1) при подтверждении «Легко» в день проверки, снижается (-0.2) при ошибке">'
            '<span class="zf-pill-icon">⚡</span>'
            f'<span class="zf-pill-title">{esc(weight_label)}:</span>'
            f'<span class="zf-pill-code">{weight_str}</span>'
            '</div>'
            '</div>'
        )
        st.markdown(bottom_bar_html, unsafe_allow_html=True)


# ================= ИНИЦИАЛИЗАЦИЯ =================

if "loaded" not in st.session_state:
    saved = {}
    if DATA_FILE.exists():
        try:
            saved = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saved = {}
    langs, cur = ingest(saved)
    st.session_state.update(langs=langs, cur=cur, ver=0, loaded=True, mix_dir=random.choice(VOCAB_KINDS),
                            synced=set(), pull_err={}, last_sync_time="")
    sync_all()
    save_state()

if "_flash" in st.session_state:
    st.toast(st.session_state.pop("_flash"))


# ================= ШАПКА И ПЕРЕКЛЮЧАТЕЛЬ ЯЗЫКА =================

langs = st.session_state["langs"]
ids = list(langs)
focus_mode = st.session_state.get("focus_mode", False)

if focus_mode:
    # 🎯 ШАПКА ЧИСТОГО РЕЖИМА
    with kcont("clean_topbar"):
        h_col1, h_col2 = st.columns([1.5, 1.5], vertical_alignment="center")

        cur_lang = L()
        cur_mode = st.session_state.get("dash_mode", "📘 Слова")
        cur_dir = st.session_state.get("dash_dir", "Фронт: слово → перевод")
        mode_summary = cur_mode
        if cur_mode != "📙 Грамматика":
            dir_short = "Фронт" if "Фронт" in cur_dir else ("Бек" if "Бек" in cur_dir else "⇄ Микс")
            mode_summary += f" · {dir_short}"

        with h_col1:
            st.markdown(
                f'<div class="zf-clean-topbar">'
                f'<span class="zf-clean-flag">{cur_lang["flag"]} <b>{cur_lang["name"]}</b></span>'
                f'<span class="zf-clean-pill">{esc(mode_summary)}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with h_col2:
            c_set, c_tog = st.columns([1, 1.3], vertical_alignment="center")
            with c_set:
                with st.popover("⚙️ Настройки", use_container_width=True, help="Настройки чистого режима"):
                    st.markdown("### ⚙️ Настройки чистого режима")
                    st.markdown("##### 🌍 Язык")
                    clean_choice = st.radio(
                        "Язык (Чистый режим)",
                        ids,
                        index=ids.index(cur_id()),
                        label_visibility="collapsed",
                        key="clean_lang_choice",
                        format_func=lambda i: f"{langs[i]['flag']} {langs[i]['name']}",
                    )
                    if clean_choice != cur_id():
                        st.session_state["cur"] = clean_choice
                        save_state()
                        st.rerun()

                    st.markdown("---")
                    st.markdown("##### 📚 Что повторяем")
                    mode_options = ["📘 Слова", "📙 Грамматика", "Обе карточки"]
                    cur_m = st.session_state.get("dash_mode", "📘 Слова")
                    m_idx = mode_options.index(cur_m) if cur_m in mode_options else 0
                    mode_val = st.radio(
                        "Что повторяем (Чистый режим)",
                        mode_options,
                        index=m_idx,
                        label_visibility="collapsed",
                        key="clean_dash_mode",
                    )
                    if mode_val != st.session_state.get("dash_mode"):
                        st.session_state["dash_mode"] = mode_val
                        st.rerun()

                    if mode_val != "📙 Грамматика":
                        st.markdown("---")
                        st.markdown("##### 🔄 Направление слов")
                        dir_options = ["Фронт: слово → перевод", "Бек: перевод → слово", "⇄ Вперемешку"]
                        cur_d = st.session_state.get("dash_dir", "Фронт: слово → перевод")
                        d_idx = dir_options.index(cur_d) if cur_d in dir_options else 0
                        dir_val = st.radio(
                            "Направление слов (Чистый режим)",
                            dir_options,
                            index=d_idx,
                            label_visibility="collapsed",
                            key="clean_dash_dir",
                        )
                        if dir_val != st.session_state.get("dash_dir"):
                            st.session_state["dash_dir"] = dir_val
                            st.rerun()

                    st.markdown("---")
                    st.markdown("##### 📌 Стек недели")
                    c_st1, c_st2 = st.columns([1, 1])
                    if c_st1.button("✏️ Изменить", key="clean_open_stack", use_container_width=True):
                        stack_dialog()
                    stk = T("stack")
                    has_stk = not stk.empty and any(str(p).strip() for p in stk["phrase"])
                    if c_st2.button("🎓 В стек слов", key="clean_transfer_stack", use_container_width=True, disabled=not has_stk):
                        stack_to_vocab_dialog()

            with c_tog:
                focus_toggle = st.toggle(
                    "🎯 Чистый режим",
                    value=True,
                    key="focus_mode_toggle",
                    help="Оставляет только самое главное: стек недели и карточки повторения без лишних вкладок и графиков."
                )
                if not focus_toggle:
                    st.session_state["focus_mode"] = False
                    st.rerun()
else:
    # 🌍 ОБЫЧНЫЙ РЕЖИМ (ДАШБОРД)
    h_col1, h_col2 = st.columns([3.2, 1.8], vertical_alignment="center")
    with h_col1:
        choice = st.radio(
            "Язык", ids, index=ids.index(cur_id()), horizontal=True, label_visibility="collapsed",
            format_func=lambda i: f"{langs[i]['flag']} {langs[i]['name']}",
        )
        if choice != cur_id():
            st.session_state["cur"] = choice
            save_state()
            st.rerun()

    with h_col2:
        focus_toggle = st.toggle(
            "🎯 Чистый режим",
            value=False,
            key="focus_mode_toggle",
            help="Оставляет только самое главное: стек недели и карточки повторения без лишних вкладок и графиков."
        )
        if focus_toggle:
            st.session_state["focus_mode"] = True
            st.rerun()

ensure_pulled(cur_id())

if not focus_mode:
    st.title(f"{L()['flag']} {L()['name']}")
    _badge()


# ================= САЙДБАР =================

with st.sidebar:
    st.header("⚙️ Управление")
    st.toggle("Всегда показывать ответ сразу", key="auto_reveal",
              help="Тогда перевод/шпаргалка открыты без нажатия на кнопку.")
    if st.button("🔄 Синхронизировать пулы", use_container_width=True):
        sync_all()
        save_state()
        push_cloud_async()
        flash("Пулы обновлены")
        st.rerun()

    st.markdown("---")
    st.subheader("🌍 Языки")
    with st.expander("➕ Добавить язык"):
        with st.form("add_lang", clear_on_submit=True):
            new_name = st.text_input("Название", placeholder="Deutsch")
            new_flag = st.text_input("Флаг / эмодзи", value="🌍")
            new_speech = st.selectbox("Голос для озвучки", SPEECH_CODES)
            if st.form_submit_button("Добавить", use_container_width=True):
                if not new_name.strip():
                    st.error("Впиши название.")
                else:
                    base_id = re.sub(r"[^a-z0-9]+", "", new_name.lower()) or "lang"
                    lid, n = base_id, 2
                    while lid in langs:
                        lid, n = f"{base_id}{n}", n + 1
                    langs[lid] = empty_lang(new_name.strip(), new_flag.strip() or "🌍", new_speech)
                    st.session_state["cur"] = lid
                    save_state()
                    push_cloud_async(lid)
                    flash(f"Язык добавлен: {new_name.strip()}")
                    st.rerun()
    if len(langs) > 1:
        with st.expander("🗑 Удалить текущий язык"):
            sure = st.checkbox(f"Да, удалить «{L()['name']}» со всеми данными", key=f"del_ok_{cur_id()}")
            if st.button("Удалить", disabled=not sure, use_container_width=True):
                del langs[cur_id()]
                st.session_state["cur"] = next(iter(langs))
                save_state()
                flash("Язык удалён")
                st.rerun()

    st.markdown("---")
    st.caption("⚡ **Supabase Cloud**: сохраняется автоматически")

    st.markdown("---")
    st.subheader("💾 Резервная копия")
    st.download_button("⬇️ Скачать data.json", export_json(), file_name="data.json",
                       mime="application/json", use_container_width=True)
    up = st.file_uploader("Восстановить из data.json", type="json")
    if up is not None and st.button("♻️ Восстановить", use_container_width=True):
        try:
            data = json.loads(up.getvalue().decode("utf-8"))
            new_langs, new_cur = ingest(data)
            st.session_state["langs"], st.session_state["cur"] = new_langs, new_cur
            sync_all()
            save_state()
            for _l in new_langs:
                supabase_push(_l)
            st.session_state["ver"] += 1
            flash("Данные восстановлены")
            st.rerun()
        except Exception as e:
            st.error(f"Не удалось прочитать файл: {e}")


def stack_dialog_body():
    st.caption("Фразы на изучаемом языке с полными полями словаря (перевод, транскрипция, пример и контекст).")

    with st.expander("➕ Быстро добавить слово со всеми полями", expanded=False):
        c1, c2 = st.columns(2)
        nw_phrase = c1.text_input("Слово / фраза*", key=f"add_stk_p_{cur_id()}")
        nw_note = c2.text_input("Перевод*", key=f"add_stk_n_{cur_id()}")
        c3, c4 = st.columns(2)
        nw_pron = c3.text_input("Произношение [транскрипция]", key=f"add_stk_pr_{cur_id()}")
        nw_extra = c4.text_input("Заметка / контекст", key=f"add_stk_ex_{cur_id()}")
        c5, c6 = st.columns(2)
        nw_ex = c5.text_input("Пример предложения", key=f"add_stk_pe_{cur_id()}")
        nw_ex_tr = c6.text_input("Перевод примера", key=f"add_stk_pet_{cur_id()}")

        if st.button("➕ Добавить в стек недели", key=f"btn_add_stk_row_{cur_id()}", use_container_width=True):
            if not nw_phrase.strip() or not nw_note.strip():
                st.warning("Заполните как минимум слово и перевод.")
            else:
                curr_s = T("stack").copy()
                new_row = {
                    "phrase": nw_phrase.strip(), "note": nw_note.strip(),
                    "pron": nw_pron.strip(), "phrase_ex": nw_ex.strip(),
                    "phrase_tr": nw_ex_tr.strip(), "extra": nw_extra.strip()
                }
                curr_s = pd.concat([curr_s, pd.DataFrame([new_row])], ignore_index=True)
                cleaned = clean_table(curr_s, COLS["stack"], "phrase")
                set_T("stack", cleaned)
                sync_vocab_from_stack(cleaned)
                save_state()
                push_cloud_async()
                st.session_state["ver"] += 1
                flash(f"Добавлено в стек: {nw_phrase}")
                st.rerun()

    with st.form(f"stack_form_{cur_id()}"):
        edited = st.data_editor(
            T("stack"), num_rows="dynamic", hide_index=True, use_container_width=True,
            key=f"stack_ed_{cur_id()}_{st.session_state['ver']}",
            column_config={
                "phrase": st.column_config.TextColumn("Слово / фраза", required=True),
                "note": st.column_config.TextColumn("Перевод", required=True),
                "pron": st.column_config.TextColumn("Произношение"),
                "phrase_ex": st.column_config.TextColumn("Пример фразы"),
                "phrase_tr": st.column_config.TextColumn("Перевод примера"),
                "extra": st.column_config.TextColumn("Заметка"),
            },
        )
        c_sub1, c_sub2 = st.columns([1, 1])
        save_btn = c_sub1.form_submit_button("💾 Сохранить стек", use_container_width=True, type="primary")
        transfer_btn = c_sub2.form_submit_button("🎓 Сохранить и в стек слов", use_container_width=True, help="Сохранить стек и сразу скопировать фразы в стек слов как новичков (стек недели остаётся)")
        if save_btn:
            cleaned = clean_table(edited, COLS["stack"], "phrase")
            set_T("stack", cleaned)
            sync_vocab_from_stack(cleaned)
            save_state()
            push_cloud_async()
            st.session_state["ver"] += 1
            flash("Стек сохранён")
            st.rerun()
        if transfer_btn:
            cleaned = clean_table(edited, COLS["stack"], "phrase")
            set_T("stack", cleaned)
            sync_vocab_from_stack(cleaned)
            cnt = transfer_stack_to_vocab(selected_phrases=None, remove_from_stack=False)
            flash(f"🎉 Стек сохранён и перенесён в словарь ({cnt} карточек добавлены как новички)")
            st.rerun()


stack_dialog = st.dialog("✏️ Стек недели", width="large")(stack_dialog_body)


def transfer_stack_to_vocab(selected_phrases=None, remove_from_stack=False, lang=None):
    target_lang = lang or (L() if "langs" in st.session_state else None)
    if not target_lang:
        return 0
    tb = target_lang["tables"]
    stack = tb.get("stack", pd.DataFrame())
    if stack.empty:
        return 0

    items_dict = {}
    for _, r in stack.iterrows():
        p = str(r.get("phrase", "")).strip()
        if p:
            if selected_phrases is None or p in selected_phrases:
                items_dict[p] = {
                    "note": str(r.get("note", "")).strip(),
                    "pron": str(r.get("pron", "")).strip(),
                    "phrase_ex": str(r.get("phrase_ex", "")).strip(),
                    "phrase_tr": str(r.get("phrase_tr", "")).strip(),
                    "extra": str(r.get("extra", "")).strip(),
                }

    if not items_dict:
        return 0

    v_base = tb.get("vocab_base", pd.DataFrame()).copy()
    existing_words = set(v_base["word"]) if not v_base.empty else set()
    new_rows = []

    for p, row_data in items_dict.items():
        n = row_data.get("note", "")
        pron = row_data.get("pron", "")
        p_ex = row_data.get("phrase_ex", "") or p
        p_tr = row_data.get("phrase_tr", "") or n
        extra = row_data.get("extra", "") or "Из стека недели"

        if p not in existing_words:
            new_rows.append({
                "word": p,
                "translation": n,
                "pron": pron,
                "phrase": p_ex,
                "phrase_tr": p_tr,
                "extra": extra,
                "in_stack": not remove_from_stack,
            })
            existing_words.add(p)
        else:
            mask_w = v_base["word"] == p
            if n: v_base.loc[mask_w, "translation"] = n
            if pron: v_base.loc[mask_w, "pron"] = pron
            if p_ex and p_ex != p: v_base.loc[mask_w, "phrase"] = p_ex
            if p_tr and p_tr != n: v_base.loc[mask_w, "phrase_tr"] = p_tr
            if extra: v_base.loc[mask_w, "extra"] = extra
            if remove_from_stack:
                v_base.loc[mask_w, "in_stack"] = False

    if new_rows:
        v_base = normalize("vocab_base", pd.concat([v_base, pd.DataFrame(new_rows)], ignore_index=True))
    tb["vocab_base"] = v_base

    sync_group("vocab", target_lang)

    # Для перенесённых фраз гарантируем статус «Выпускник» (Новичок) и интервал 0
    transferred_set = set(items_dict.keys())
    for pkey in ("vocab_pool", "vocab_rev_pool"):
        pool_df = tb.get(pkey, pd.DataFrame()).copy()
        if not pool_df.empty:
            mask = pool_df["word"].isin(transferred_set)
            if mask.any():
                pool_df.loc[mask, "type"] = "Выпускник"
                pool_df.loc[mask, "interval"] = 0
                pool_df.loc[mask, "streak"] = 0
                pool_df.loc[mask, "due_date"] = ""
                pool_df.loc[mask, "star_days"] = 5
                tb[pkey] = reorder(pool_df)

    if remove_from_stack:
        # Оставляем в стеке недели только те фразы, которые пользователь НЕ отмечал (остаются для практики)
        remaining_stack = stack[~stack["phrase"].astype(str).str.strip().isin(transferred_set)]
        tb["stack"] = clean_table(remaining_stack, COLS["stack"], "phrase")
        vb = tb.get("vocab_base", pd.DataFrame()).copy()
        vb.loc[vb["word"].isin(transferred_set), "in_stack"] = False
        tb["vocab_base"] = vb

    try:
        st.session_state["dash_mode"] = "📘 Слова"
        save_state()
        push_cloud_async()
        st.session_state["ver"] += 1
    except Exception:
        pass
    return len(items_dict)


def stack_to_vocab_dialog_body():
    stack = T("stack")
    items = []
    if not stack.empty:
        for _, r in stack.iterrows():
            p = str(r.get("phrase", "")).strip()
            n = str(r.get("note", "")).strip()
            if p:
                items.append((p, n, r.to_dict()))

    if not items:
        st.info("📌 В стеке недели пока нет фраз. Сначала добавьте фразы через «✏️ Изменить», чтобы потренировать их и перенести в карточки.")
        return

    st.markdown("##### 🎓 Выберите фразы для переноса в стек слов")
    st.caption(
        "Отметьте галочками те фразы, которые вы уже хорошо потренировали. "
        "Они будут добавлены в **основной стек слов (карточки)** со статусом **🟡 «Выпускник» (Новичок)** с интервалом `0`. "
        "Фразы, с которых вы снимете галочку, останутся в стеке недели для дальнейшей практики!"
    )

    tr_ver = st.session_state.get("tr_ver", 0)

    def set_all_transfer(val):
        for idx in range(len(items)):
            st.session_state[f"tr_chk_{cur_id()}_{tr_ver}_{idx}"] = val

    c_all1, c_all2 = st.columns([1, 1])
    c_all1.button("✅ Выбрать все", on_click=set_all_transfer, args=(True,), key=f"sel_all_tr_{cur_id()}_{tr_ver}", use_container_width=True)
    c_all2.button("⬜ Снять все", on_click=set_all_transfer, args=(False,), key=f"desel_all_tr_{cur_id()}_{tr_ver}", use_container_width=True)

    st.markdown("---")
    selected_phrases = []
    for idx, (p, n, r_d) in enumerate(items):
        key = f"tr_chk_{cur_id()}_{tr_ver}_{idx}"
        if key not in st.session_state:
            st.session_state[key] = True
        extra_info = []
        pron_val = str(r_d.get("pron", "")).strip()
        ex_val = str(r_d.get("phrase_ex", "")).strip()
        if pron_val: extra_info.append(f"[{pron_val}]")
        if ex_val: extra_info.append(f"ex: {ex_val}")
        details_str = f" ({', '.join(extra_info)})" if extra_info else ""
        label = f"**{p}**" + (f" — *{n}*" if n else "") + details_str
        if st.checkbox(label, key=key):
            selected_phrases.append(p)

    n_sel = len(selected_phrases)
    btn_label = f"🚀 Перенести выбранные ({n_sel} из {len(items)}) в слова" if n_sel > 0 else "Выберите хотя бы 1 фразу"

    col_act1, col_act2 = st.columns([2, 1], vertical_alignment="center")
    if col_act1.button(btn_label, type="primary", use_container_width=True, disabled=(n_sel == 0), key=f"transfer_confirm_btn_{tr_ver}"):
        cnt = transfer_stack_to_vocab(selected_phrases=selected_phrases, remove_from_stack=True)
        st.session_state["tr_ver"] = tr_ver + 1
        flash(f"🎉 Перенесено в стек слов: {cnt} (карточки добавлены как новички)")
        st.rerun()

    if col_act2.button("Отмена", use_container_width=True, key=f"transfer_cancel_btn_{tr_ver}"):
        st.rerun()


stack_to_vocab_dialog = st.dialog("🎓 Перенос в стек слов", width="medium")(stack_to_vocab_dialog_body)


def render_dashboard_stats(vp, vr, gp):
    today_reviews = L()["daily"].get(today_str(), 0)
    total_reviews = int(vp["reviews"].sum() + vr["reviews"].sum() + gp["reviews"].sum()) if not (vp.empty and vr.empty and gp.empty) else 0

    v_total = len(vp)
    vp_grad = int((vp["type"] == "Выпускник").sum()) if not vp.empty else 0
    vp_star = int((vp["type"] == "Старичок").sum()) if not vp.empty else 0
    vp_pct = int(round((vp_star / v_total) * 100)) if v_total > 0 else 0

    vr_total = len(vr)
    vr_grad = int((vr["type"] == "Выпускник").sum()) if not vr.empty else 0
    vr_star = int((vr["type"] == "Старичок").sum()) if not vr.empty else 0
    vr_pct = int(round((vr_star / vr_total) * 100)) if vr_total > 0 else 0

    g_total = len(gp)
    gp_grad = int((gp["type"] == "Выпускник").sum()) if not gp.empty else 0
    gp_star = int((gp["type"] == "Старичок").sum()) if not gp.empty else 0
    gp_pct = int(round((gp_star / g_total) * 100)) if g_total > 0 else 0

    html = f"""<div class="zf-stats-grid">
  <div class="zf-stat-card">
    <div class="zf-stat-header"><span>🔥 Сегодня</span></div>
    <div class="zf-stat-val">{today_reviews} <small>повторов</small></div>
    <div class="zf-stat-sub">🎯 дневной прогресс</div>
  </div>
  <div class="zf-stat-card">
    <div class="zf-stat-header"><span>🔁 Всего повторов</span></div>
    <div class="zf-stat-val">{total_reviews} <small>раз</small></div>
    <div class="zf-stat-sub">📈 вся история</div>
  </div>
  <div class="zf-stat-card">
    <div class="zf-stat-header"><span>📘 Фронт (Слово → Перевод)</span></div>
    <div class="zf-stat-val">{v_total} <small>слов</small></div>
    <div class="zf-stat-badges">
      <span class="zf-badge-yellow" title="Карточки в активном изучении / повторении">🟡 Учим: <b>{vp_grad}</b></span>
      <span class="zf-badge-blue" title="Освоенные слова (оценка «Легко»)">🔵 Выучено: <b>{vp_star}</b></span>
    </div>
    <div class="zf-progress-bar" title="Освоено: {vp_pct}%"><div class="zf-progress-fill" style="width: {vp_pct}%;"></div></div>
    <div class="zf-stat-pct">{vp_pct}% освоено</div>
  </div>
  <div class="zf-stat-card">
    <div class="zf-stat-header"><span>🔄 Бек (Перевод → Слово)</span></div>
    <div class="zf-stat-val">{vr_total} <small>слов</small></div>
    <div class="zf-stat-badges">
      <span class="zf-badge-yellow" title="Карточки в активном изучении / повторении">🟡 Учим: <b>{vr_grad}</b></span>
      <span class="zf-badge-blue" title="Освоенные слова (оценка «Легко»)">🔵 Выучено: <b>{vr_star}</b></span>
    </div>
    <div class="zf-progress-bar" title="Освоено: {vr_pct}%"><div class="zf-progress-fill" style="width: {vr_pct}%;"></div></div>
    <div class="zf-stat-pct">{vr_pct}% освоено</div>
  </div>
  <div class="zf-stat-card">
    <div class="zf-stat-header"><span>📙 Грамматика</span></div>
    <div class="zf-stat-val">{g_total} <small>правил</small></div>
    <div class="zf-stat-badges">
      <span class="zf-badge-yellow" title="Правила на изучении">🟡 Учим: <b>{gp_grad}</b></span>
      <span class="zf-badge-blue" title="Освоенные правила (оценка «Легко»)">🔵 Выучено: <b>{gp_star}</b></span>
    </div>
    <div class="zf-progress-bar" title="Освоено: {gp_pct}%"><div class="zf-progress-fill" style="width: {gp_pct}%;"></div></div>
    <div class="zf-stat-pct">{gp_pct}% освоено</div>
  </div>
</div>
<div class="zf-stats-legend">
  💡 <b>Как читать статусы:</b> 
  <span class="zf-badge-yellow" style="padding:1px 6px;">🟡 Учим</span> («Выпускники») — новые карточки и слова на этапе повторения · 
  <span class="zf-badge-blue" style="padding:1px 6px;">🔵 Выучено</span> («Старички») — карточки, перешедшие в долговременную память (оценка «Легко»)
</div>"""
    st.markdown(html, unsafe_allow_html=True)


# ================= ПРОЦЕСС ОБУЧЕНИЯ (СТЕК + КАРТОЧКА) =================

def render_study_flow(compact=False):
    stack = T("stack")
    has_stack = not stack.empty and any(str(p).strip() for p in stack["phrase"])
    s_key = "_c" if compact else ""
    with kcont(f"stackhdr{s_key}_{cur_id()}"):
        st.markdown(
            '<div class="zf-hdr"><span>📌 СТЕК НЕДЕЛИ</span> <small>нажми на фразу — услышишь</small></div>',
            unsafe_allow_html=True,
        )
        if compact:
            with st.expander("⚙️ Действия: Изменить / В стек слов", expanded=False):
                c_btn1, c_btn2 = st.columns([1, 1])
                if c_btn1.button("✏️ Изменить", key=f"stack_edit{s_key}_{cur_id()}", use_container_width=True,
                                 help="Изменить стек недели"):
                    stack_dialog()
                if c_btn2.button("🎓 В стек слов", key=f"stack_to_vocab{s_key}_{cur_id()}", use_container_width=True,
                                 disabled=not has_stack,
                                 help="Перенести фразы недели в стек слов как новичков"):
                    stack_to_vocab_dialog()
        else:
            c_btn1, c_btn2 = st.columns([1, 1])
            if c_btn1.button("✏️ Изменить стек", key=f"stack_edit{s_key}_{cur_id()}", use_container_width=True,
                             help="Изменить стек недели"):
                stack_dialog()
            if c_btn2.button("🎓 В стек слов", key=f"stack_to_vocab{s_key}_{cur_id()}", use_container_width=True,
                             disabled=not has_stack,
                             help="Перенести фразы недели в стек слов как новичков"):
                stack_to_vocab_dialog()
    if not has_stack:
        st.caption("Стек недели пуст. Нажми «✏️ Изменить стек», чтобы добавить фразы.")
    else:
        stack_cards(stack, L()["speech"])

    if not compact:
        st.markdown("---")
        st.subheader("🔥 Повторение")
        c1, c2 = st.columns([1.1, 1.9], vertical_alignment="center")
        with c1:
            mode = st.radio("Что повторяем", ["📘 Слова", "📙 Грамматика", "Обе карточки"], horizontal=True,
                            label_visibility="collapsed", key="dash_mode")
        vkind = "vocab"
        with c2:
            if mode != "📙 Грамматика":
                direction = st.radio("Направление слов",
                                     ["Фронт: слово → перевод", "Бек: перевод → слово", "⇄ Вперемешку"],
                                     horizontal=True, label_visibility="collapsed", key="dash_dir")
                if direction.startswith("Бек"):
                    vkind = "vocab_rev"
                elif direction.startswith("⇄"):
                    vkind = st.session_state.get("mix_dir", "vocab")
                    if vkind not in VOCAB_KINDS:
                        vkind = "vocab"
    else:
        st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
        mode = st.session_state.get("dash_mode", "📘 Слова")
        direction = st.session_state.get("dash_dir", "Фронт: слово → перевод")
        vkind = "vocab"
        if mode != "📙 Грамматика":
            if direction.startswith("Бек"):
                vkind = "vocab_rev"
            elif direction.startswith("⇄"):
                vkind = st.session_state.get("mix_dir", "vocab")
                if vkind not in VOCAB_KINDS:
                    vkind = "vocab"

    if mode == "📘 Слова":
        render_card(vkind, compact=compact)
    elif mode == "📙 Грамматика":
        render_card("grammar", compact=compact)
    else:
        c1, c2 = st.columns(2)
        with c1:
            render_card(vkind, compact=compact)
        with c2:
            render_card("grammar", compact=compact)
    if not compact:
        with kcont("kbhint"):
            st.caption("⌨️ На компьютере: Пробел — показать ответ, 1 / 2 / 3 — Сложно / Норм / Легко.")
    keyboard_hook()


# ---------- ВКЛАДКА ПУЛА (Словарь / Грамматика) ----------
def pool_tab(kind):
    cfg = POOLS[kind]
    name, value = cfg["name"], cfg["value"]
    ver, cur = st.session_state["ver"], cur_id()
    base_key = cfg["base"]
    fields = FIELDS[kind]
    labels = dict(fields)
    labels.update({"position": "Позиция", "type": "Тип", "interval": "Интервал", "reviews": "Повторов", "last": "Последний"})

    pkind = kind
    if kind == "vocab":
        d = st.radio("Направление", ["Фронт: слово → перевод", "Бек: перевод → слово"], horizontal=True,
                     key=f"dir_{cur}", label_visibility="collapsed")
        if d.startswith("Бек"):
            pkind = "vocab_rev"
        st.caption("У каждого направления своя очередь, свои интервалы и свой счётчик повторов.")
    rev = pkind == "vocab_rev"
    pool_key = POOLS[pkind]["pool"]
    pool = T(pool_key)

    grads_n = int((pool["type"] == "Выпускник").sum())
    reps_n = int((pool["type"] == "Повторяем").sum())
    today_s = date.today().isoformat()
    pool_due = pool["due_date"].fillna("").astype(str).str.strip() if "due_date" in pool.columns else pd.Series([""] * len(pool))
    due_n = int(((pool["type"] == "Старичок") & ((pool_due == "") | (pool_due <= today_s))).sum())
    deck_n = int(((pool["type"] == "Старичок") & (pool_due > today_s)).sum())

    labels.update({"weight": "Коэфф", "streak": "Серия", "due_date": "Срок проверки", "star_days": "Шаг (дн)"})

    stats_parts = [f"Всего в очереди: **{len(pool)}**"]
    if grads_n > 0: stats_parts.append(f"🟡 Учим: **{grads_n}**")
    if reps_n > 0: stats_parts.append(f"🟠 Повторяем: **{reps_n}**")
    if due_n > 0: stats_parts.append(f"🔔 К проверке: **{due_n}**")
    if deck_n > 0: stats_parts.append(f"🔵 В колоде: **{deck_n}**")
    stats_parts.append(f"Всего повторов: **{int(pool['reviews'].sum())}**")
    st.caption(" · ".join(stats_parts))

    # --- Добавление ---
    with st.expander("➕ Добавить", expanded=False):
        tab_one, tab_bulk = st.tabs(["✍️ По одному", "📥 Вставить списком"])

        with tab_one:
            with st.form(f"add_{cur}_{kind}", clear_on_submit=True):
                vals = {}
                cols = st.columns(2)
                for i, (k, label) in enumerate(fields):
                    if k == "in_stack":
                        vals[k] = cols[i % 2].checkbox("📌 Сразу в стек недели", value=False)
                    else:
                        vals[k] = cols[i % 2].text_input(label)
                if st.form_submit_button("Добавить", use_container_width=True):
                    vals = {k: (v.strip() if isinstance(v, str) else bool(v)) for k, v in vals.items()}
                    base = T(base_key)
                    if not vals[name]:
                        st.error(f"Впиши поле «{labels[name]}».")
                    elif vals[name] in set(base[name]):
                        st.warning(f"«{vals[name]}» уже есть в списке.")
                    else:
                        set_T(base_key, normalize(base_key, pd.concat([base, pd.DataFrame([vals])], ignore_index=True)))
                        sync_group(kind)
                        sync_stack_from_vocab()
                        save_state()
                        push_cloud_async()
                        flash(f"Добавлено: {vals[name]}")
                        st.rerun()

        with tab_bulk:
            bulk_import(kind, ver)

    # --- Очередь повторения (только просмотр) ---
    st.markdown("#### 📋 Очередь повторения")
    if pool.empty:
        st.info("Пока пусто. Добавь первую запись выше.")
    else:
        s1, s2 = st.columns([3, 1])
        q = s1.text_input("🔎 Поиск", key=f"search_{cur}_{pkind}", placeholder="часть слова, перевода, фразы")
        show_all = s2.checkbox("Все поля", key=f"allf_{cur}_{pkind}")
        base = T(base_key)
        view = pool.drop(columns=["cheat"], errors="ignore").merge(base, on=name, how="left").fillna("")
        if show_all:
            cols_show = ["position"] + [k for k, _ in fields] + ["type", "interval", "reviews", "last"]
            if rev:
                cols_show = ["position", "translation", "word"] + [c for c in cols_show if c not in ("position", "word", "translation")]
        elif rev:
            cols_show = ["position", "translation", "word", "pron", "type", "interval", "reviews", "last"]
        elif kind == "vocab":
            cols_show = ["position", "word", "translation", "pron", "type", "interval", "reviews", "last"]
        else:
            cols_show = ["position", "rule", "cheat", "type", "interval", "reviews", "last"]
        view = view[cols_show]
        if q:
            mask = view.apply(lambda r: q.lower() in " ".join(map(str, r.values)).lower(), axis=1)
            view = view[mask]
        st.markdown(html_table(view, cols_show, labels, compact=not show_all), unsafe_allow_html=True)
        st.caption(f"Показано: {len(view)} из {len(pool)}")

    # --- Правка списка ---
    with st.expander("✏️ Редактировать список (изменить, удалить, добавить строки)"):
        st.caption("Двойной клик по ячейке — правка. Строки удаляются выбором и клавишей Delete.")
        with st.form(f"edit_{cur}_{kind}"):
            col_cfg = {}
            for k, label in fields:
                if k == "in_stack":
                    col_cfg[k] = st.column_config.CheckboxColumn("В стеке", default=False)
                else:
                    col_cfg[k] = st.column_config.TextColumn(label, required=(k == name))
            edited = st.data_editor(
                T(base_key), num_rows="dynamic", hide_index=True, use_container_width=True, height=400,
                key=f"{cur}_{kind}_base_ed_{ver}",
                column_config=col_cfg,
            )
            if st.form_submit_button("💾 Сохранить список"):
                set_T(base_key, clean_table(edited, COLS[base_key], name))
                sync_group(kind)
                sync_stack_from_vocab()
                save_state()
                push_cloud_async()
                st.session_state["ver"] += 1
                flash("Список сохранён, облако обновлено")
                st.rerun()

    # --- Правка типа, интервала и повторов ---
    if not pool.empty:
        with st.expander("🎚 Изменить тип, интервал и число повторов"):
            st.caption("Например, вернуть «Старичка» в «Выпускники» или подвинуть запись в очереди.")
            with st.form(f"progress_{cur}_{pkind}"):
                cols_show = ["position", name, "type", "interval", "reviews"]
                edited_p = st.data_editor(
                    pool[cols_show], hide_index=True, use_container_width=True, height=400,
                    key=f"{cur}_{pool_key}_pool_ed_{ver}", disabled=["position", name],
                    column_config={
                        "position": st.column_config.NumberColumn("Позиция"),
                        name: st.column_config.TextColumn(labels[name]),
                        "type": st.column_config.SelectboxColumn("Тип", options=TYPES, required=True),
                        "interval": st.column_config.NumberColumn("Интервал", min_value=0, step=1),
                        "reviews": st.column_config.NumberColumn("Повторов", min_value=0, step=1),
                    },
                )
                if st.form_submit_button("💾 Сохранить"):
                    new_pool = T(pool_key).copy()
                    new_pool["type"] = edited_p["type"].values
                    new_pool["interval"] = pd.to_numeric(edited_p["interval"], errors="coerce").fillna(0).astype(int).values
                    new_pool["reviews"] = pd.to_numeric(edited_p["reviews"], errors="coerce").fillna(0).astype(int).values
                    if "streak" in new_pool.columns:
                        new_pool.loc[(new_pool["type"] == "Старичок") & (new_pool["streak"] < 3), "streak"] = 3
                        new_pool.loc[(new_pool["type"] != "Старичок") & (new_pool["streak"] >= 3), "streak"] = 0
                    if "due_date" in new_pool.columns:
                        new_pool.loc[new_pool["type"] != "Старичок", "due_date"] = ""
                    set_T(pool_key, reorder(new_pool))
                    save_state()
                    push_cloud_async()
                    st.session_state["ver"] += 1
                    flash("Прогресс обновлён")
                    st.rerun()


if focus_mode:
    render_study_flow(compact=True)
else:
    tab_dash, tab_vocab, tab_gram, tab_stats = st.tabs(["🎯 Дашборд", "📘 Словарь", "📙 Грамматика", "📊 Прогресс"])

    # ---------- ДАШБОРД ----------
    with tab_dash:
        vp, vr, gp = T("vocab_pool"), T("vocab_rev_pool"), T("grammar_pool")
        with st.expander("📊 Статистика и прогресс", expanded=False):
            render_dashboard_stats(vp, vr, gp)
        render_study_flow(compact=False)

    with tab_vocab:
        pool_tab("vocab")

    with tab_gram:
        pool_tab("grammar")

    # ---------- ПРОГРЕСС ----------
    with tab_stats:
        lang = L()
        vp, vr, gp = T("vocab_pool"), T("vocab_rev_pool"), T("grammar_pool")
        week = sum(lang["daily"].get((date.today() - timedelta(days=i)).isoformat(), 0) for i in range(7))
        with kcont(f"mrow_stats1_{cur_id()}"):
            s = st.columns(2)
            s[0].metric("Повторов сегодня", lang["daily"].get(today_str(), 0))
            s[1].metric("За 7 дней", week)
        with kcont(f"mrow_stats2_{cur_id()}"):
            s = st.columns(3)
            s[0].metric("Фронт", int(vp["reviews"].sum()), help="Повторов: слово → перевод")
            s[1].metric("Бек", int(vr["reviews"].sum()), help="Повторов: перевод → слово")
            s[2].metric("Правила", int(gp["reviews"].sum()))

        st.markdown("#### Повторы по дням (14 дней)")
        days = [(date.today() - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
        chart = pd.DataFrame({"Повторов": [lang["daily"].get(d, 0) for d in days]}, index=[d[5:] for d in days])
        st.bar_chart(chart)

        cs = st.columns(3)
        for col, kind in zip(cs, ("vocab", "vocab_rev", "grammar")):
            cfg = POOLS[kind]
            pool = T(cfg["pool"])
            fk = "vocab" if kind in VOCAB_KINDS else "grammar"
            col.markdown(f"#### {cfg['caption']}")
            col.caption("Чаще всего повторяли")
            if pool.empty:
                col.info("Пока пусто.")
                continue
            top10 = (pool.sort_values("reviews", ascending=False).head(10)
                     [[cfg["name"], "type", "reviews", "last"]]
                     .rename(columns={cfg["name"]: dict(FIELDS[fk])[cfg["name"]], "type": "Тип",
                                      "reviews": "Повторов", "last": "Последний"}))
            col.dataframe(top10, hide_index=True, use_container_width=True)
            col.caption(f"Ни разу не повторялось: {int((pool['reviews'] == 0).sum())} из {len(pool)}")

        st.markdown("#### Все языки")
        rows = []
        for lid, ld in st.session_state["langs"].items():
            v, vrr, g = ld["tables"]["vocab_pool"], ld["tables"]["vocab_rev_pool"], ld["tables"]["grammar_pool"]
            rows.append({
                "Язык": f"{ld['flag']} {ld['name']}", "Слов": len(v), "Правил": len(g),
                "Повторов →": int(v["reviews"].sum()), "Повторов ←": int(vrr["reviews"].sum()),
                "Повторов правил": int(g["reviews"].sum()),
                "Сегодня": ld["daily"].get(today_str(), 0),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
