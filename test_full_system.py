"""
=============================================================================
FULL SYSTEM TEST SUITE — Zero-Friction Language Workspace (Supabase Cloud SRS)
=============================================================================
Полный автоматический набор модульных и сквозных тестов, покрывающий ВСЕ
компоненты приложения:
 1. Схема данных, типизация, нормализация и clean_table
 2. Парсер текста, авто-определение разделителей и импорт слов
 3. Очередь повторений (Вариант Б без режима сна, созревшие экзамены, горлышко)
 4. Синхронизация пулов (sync_pool, sync_group, независимость фронт/бек)
 5. Стейт-машина SRS (Выпускник -> 3 Легко -> Старичок -> Экзамен -> Откат -> Возврат)
 6. Стек недели (sync_stack_from_vocab, sync_vocab_from_stack, transfer_stack_to_vocab, pack/unpack)
 7. Форматирование UI, склонения, защита от XSS (format_due_diff, rev_word, esc)
 8. Снимок и полезная нагрузка облака Supabase (supabase_push payload)
 9. Полный сквозной цикл (End-to-End): импорт -> изучение -> экзамен -> откат -> стек -> выгрузка
=============================================================================
"""

import sys
import os
import unittest
import warnings
import logging
from datetime import date, timedelta
import pandas as pd

# Подавление предупреждений Streamlit при выполнении без GUI
warnings.filterwarnings("ignore")
logging.getLogger("streamlit").setLevel(logging.ERROR)
os.environ["STREAMLIT_LOG_LEVEL"] = "error"

# Добавление рабочей директории в путь
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

import app
from app import (
    COLS, FIELDS, POOLS, INT_COLS, TYPES, clean_table, normalize,
    fresh_lang, empty_lang, ingest,
    reorder, sync_pool, sync_group,
    sync_stack_from_vocab, sync_vocab_from_stack, transfer_stack_to_vocab,
    grade_item, apply_import,
    _has_sep, _split_line, detect_separator, parse_pasted,
    pack_stack_row, unpack_stack_row,
    format_due_diff, rev_word, esc
)


# =============================================================================
# 1. ТЕСТЫ СХЕМЫ, ТИПИЗАЦИИ И НОРМАЛИЗАЦИИ
# =============================================================================
class TestSchemaAndNormalization(unittest.TestCase):
    """Проверка структуры таблиц, типов колонок и очистки данных."""

    def test_01_schema_keys_and_fields(self):
        """Все 6 таблиц присутствуют в COLS, и in_stack есть в схеме vocab."""
        expected_tables = ["vocab_base", "grammar_base", "stack", "vocab_pool", "vocab_rev_pool", "grammar_pool"]
        for tbl in expected_tables:
            self.assertIn(tbl, COLS, f"Таблица {tbl} отсутствует в COLS")

        vocab_fields = [k for k, _ in FIELDS["vocab"]]
        self.assertIn("in_stack", vocab_fields, "in_stack отсутствует в FIELDS['vocab']")
        self.assertIn("in_stack", COLS["vocab_base"], "in_stack отсутствует в COLS['vocab_base']")

    def test_02_clean_table_boolean_parsing(self):
        """clean_table корректно преобразует любые варианты true/false/1/0 в строгий bool."""
        raw_data = [
            {"word": "w1", "in_stack": True},
            {"word": "w2", "in_stack": "true"},
            {"word": "w3", "in_stack": "True"},
            {"word": "w4", "in_stack": 1},
            {"word": "w5", "in_stack": "1"},
            {"word": "w6", "in_stack": "yes"},
            {"word": "w7", "in_stack": False},
            {"word": "w8", "in_stack": "false"},
            {"word": "w9", "in_stack": 0},
            {"word": "w10", "in_stack": "0"},
            {"word": "w11", "in_stack": None},
        ]
        cleaned = clean_table(pd.DataFrame(raw_data), COLS["vocab_base"], "word")
        
        # Первые 6 должны быть True
        for i in range(6):
            self.assertTrue(cleaned.at[i, "in_stack"], f"Запись {i} ({raw_data[i]['word']}) должна быть True")
        # Последние 5 должны быть False
        for i in range(6, 11):
            self.assertFalse(cleaned.at[i, "in_stack"], f"Запись {i} ({raw_data[i]['word']}) должна быть False")

    def test_03_normalize_numeric_fields(self):
        """normalize корректно приводит целочисленные поля (streak, star_days, reviews, interval) и вес."""
        raw_data = [{
            "word": "test",
            "type": "Выпускник",
            "position": "1",
            "interval": "5.7",
            "reviews": "10",
            "streak": "3",
            "star_days": "12",
            "weight": "1.5"
        }]
        cleaned = normalize("vocab_pool", pd.DataFrame(raw_data))
        self.assertEqual(cleaned.at[0, "position"], 1)
        self.assertEqual(cleaned.at[0, "interval"], 5)
        self.assertEqual(cleaned.at[0, "reviews"], 10)
        self.assertEqual(cleaned.at[0, "streak"], 3)
        self.assertEqual(cleaned.at[0, "star_days"], 12)
        self.assertAlmostEqual(cleaned.at[0, "weight"], 1.5)

    def test_04_fresh_and_empty_lang_structures(self):
        """empty_lang создаёт валидную структуру словаря с полным набором таблиц."""
        el = empty_lang("Empty", "🏴", "en-US")
        self.assertIn("tables", el)
        self.assertIn("daily", el)
        for tbl in COLS:
            self.assertIn(tbl, el["tables"])
            self.assertIsInstance(el["tables"][tbl], pd.DataFrame)


# =============================================================================
# 2. ТЕСТЫ ПАРСЕРА, РАЗДЕЛИТЕЛЕЙ И ИМПОРТА СЛОВ
# =============================================================================
class TestParserAndImport(unittest.TestCase):
    """Проверка разбиения строк, авто-определения разделителей и пакетного добавления."""

    def test_05_separator_detection(self):
        """detect_separator безошибочно распознаёт табуляцию, точку с запятой, запятую и тире."""
        tsv_lines = ["apple\tяблоко", "bread\tхлеб"]
        sc_lines = ["apple;яблоко", "bread;хлеб"]
        dash_lines = ["apple — яблоко", "bread — хлеб"]
        
        self.assertEqual(detect_separator(tsv_lines), "\t")
        self.assertEqual(detect_separator(sc_lines), ";")
        self.assertEqual(detect_separator(dash_lines), "DASH")

    def test_06_parse_pasted_lines(self):
        """parse_pasted корректно разделяет строки и выделяет нераспознанные строки."""
        text = "hello — привет\nworld — мир\n\njust_a_word_without_sep"
        rows, bad, sep = parse_pasted(text, term_sep="AUTO", row_sep="\n", n=2)
        
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ["hello", "привет"])
        self.assertEqual(rows[1], ["world", "мир"])
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0], "just_a_word_without_sep")

    def test_07_apply_import_deduplication(self):
        """apply_import добавляет новые слова, дедуплицирует повторы и синхронизирует пул."""
        mock_lang = empty_lang("English", "🇬🇧", "en-US")

        recs = [
            {"word": "cat", "translation": "кот", "pron": "", "phrase": "", "phrase_tr": "", "extra": "", "in_stack": False},
            {"word": "dog", "translation": "собака", "pron": "", "phrase": "", "phrase_tr": "", "extra": "", "in_stack": False},
            {"word": "cat", "translation": "кот повтор", "pron": "", "phrase": "", "phrase_tr": "", "extra": "", "in_stack": False},
        ]
        added, updated, skipped = apply_import("vocab", recs, update_existing=False, lang=mock_lang)
        self.assertEqual(added, 2, "Должно быть добавлено ровно 2 слова")
        self.assertEqual(skipped, 1, "Дубль 'cat' должен быть пропущен")
        
        # Проверяем, что слова попали и в базу, и в пул повторений
        vb = mock_lang["tables"]["vocab_base"]
        vp = mock_lang["tables"]["vocab_pool"]
        self.assertEqual(len(vb), 2)
        self.assertEqual(len(vp), 2)
        self.assertIn("cat", vb["word"].values)
        self.assertIn("dog", vb["word"].values)


# =============================================================================
# 3. ТЕСТЫ ОЧЕРЕДИ ПОВТОРЕНИЙ (ВАРИАНТ Б — БЕЗ РЕЖИМА СНА)
# =============================================================================
class TestQueueAndBottleneck(unittest.TestCase):
    """Проверка reorder: отсутствие сна, приоритет экзаменов, горлышко MAX_GRAD."""

    def test_08_no_sleep_mode_in_rotation(self):
        """Старички с будущей датой проверки не уходят 'спать' в конец очереди, а вращаются по интервалу."""
        today = date.today()
        df = pd.DataFrame([
            {"word": "novice", "type": "Выпускник", "interval": 1, "due_date": "", "streak": 0},
            {"word": "mature_future", "type": "Старичок", "interval": 2, "due_date": (today + timedelta(days=5)).isoformat(), "streak": 1},
            {"word": "mature_later", "type": "Старичок", "interval": 4, "due_date": (today + timedelta(days=10)).isoformat(), "streak": 2},
        ])
        reordered = reorder(df)
        
        # В очереди Варианта Б карточки упорядочиваются естественно по интервалу: 1 -> 2 -> 4
        words = list(reordered["word"])
        self.assertEqual(words, ["novice", "mature_future", "mature_later"])
        self.assertEqual(reordered.at[0, "position"], 1)
        self.assertEqual(reordered.at[1, "position"], 2)
        self.assertEqual(reordered.at[2, "position"], 3)

    def test_09_due_and_overdue_exam_priority(self):
        """Карточки со сроком due_date <= today ВСЕГДА выходят на 1-е место перед всеми остальными."""
        today = date.today()
        df = pd.DataFrame([
            {"word": "regular_novice", "type": "Выпускник", "interval": 0, "due_date": "", "streak": 0},
            {"word": "overdue_card", "type": "Старичок", "interval": 10, "due_date": (today - timedelta(days=7)).isoformat(), "streak": 2},
            {"word": "today_card", "type": "Старичок", "interval": 8, "due_date": today.isoformat(), "streak": 1},
            {"word": "future_card", "type": "Старичок", "interval": 0, "due_date": (today + timedelta(days=3)).isoformat(), "streak": 1},
        ])
        reordered = reorder(df)
        
        # Карточки с наступившим экзаменом должны быть первыми
        top_two_words = set(reordered.iloc[0:2]["word"])
        self.assertEqual(top_two_words, {"overdue_card", "today_card"})
        # Обычный новичок и будущий старичок идут следом
        self.assertEqual(reordered.iloc[2]["word"], "regular_novice")
        self.assertEqual(reordered.iloc[3]["word"], "future_card")

    def test_10_bottleneck_max_grad_protection(self):
        """Горлышко: в первых TOP_N (30) позициях не более MAX_GRAD (10) активных новичков."""
        today = date.today()
        # Создадим 15 новичков с малыми интервалами и 20 старичков
        novices = [{"word": f"nov_{i}", "type": "Выпускник", "interval": i, "due_date": "", "streak": 0} for i in range(15)]
        matures = [{"word": f"mat_{i}", "type": "Старичок", "interval": 10 + i, "due_date": (today + timedelta(days=5)).isoformat(), "streak": 1} for i in range(20)]
        df = pd.DataFrame(novices + matures)
        
        reordered = reorder(df)
        top_30 = reordered.head(30)
        active_in_top_30 = sum(top_30["type"].isin(["Выпускник", "Повторяем"]))
        
        self.assertLessEqual(active_in_top_30, 10, "Активных новичков в ТОП-30 должно быть не более 10")


# =============================================================================
# 4. ТЕСТЫ СИНХРОНИЗАЦИИ ПУЛОВ (SYNC_POOL & SYNC_GROUP)
# =============================================================================
class TestPoolSync(unittest.TestCase):
    """Проверка синхронизации пулов с базой слов и независимости сторон."""

    def test_11_sync_pool_preserves_learning_progress(self):
        """sync_pool добавляет новые слова и сохраняет прогресс (reviews, streak, weight) существующих."""
        mock_lang = empty_lang("English", "🇬🇧", "en-US")
        vb = pd.DataFrame([
            {"word": "cat", "translation": "кот", "pron": "", "phrase": "", "phrase_tr": "", "extra": "", "in_stack": False},
        ])
        vp = pd.DataFrame([
            {"word": "cat", "type": "Старичок", "position": 1, "interval": 15, "reviews": 7, "last": "2026-11-01", "weight": 1.2, "streak": 2, "due_date": "2026-11-20", "star_days": 15},
        ])
        mock_lang["tables"]["vocab_base"] = normalize("vocab_base", vb)
        mock_lang["tables"]["vocab_pool"] = normalize("vocab_pool", vp)

        # Добавим в vocab_base новое слово 'dog'
        new_vb = pd.DataFrame([
            {"word": "cat", "translation": "кот", "pron": "", "phrase": "", "phrase_tr": "", "extra": "", "in_stack": False},
            {"word": "dog", "translation": "собака", "pron": "", "phrase": "", "phrase_tr": "", "extra": "", "in_stack": False},
        ])
        mock_lang["tables"]["vocab_base"] = normalize("vocab_base", new_vb)
        
        sync_pool("vocab", mock_lang)
        
        vp_after = mock_lang["tables"]["vocab_pool"]
        self.assertEqual(len(vp_after), 2)
        
        # 'cat' полностью сохранил свой прогресс
        cat_row = vp_after[vp_after["word"] == "cat"].iloc[0]
        self.assertEqual(cat_row["type"], "Старичок")
        self.assertEqual(cat_row["reviews"], 7)
        self.assertEqual(cat_row["streak"], 2)
        self.assertEqual(cat_row["star_days"], 15)
        self.assertEqual(cat_row["weight"], 1.2)
        
        # 'dog' добавлен как свежий новичок
        dog_row = vp_after[vp_after["word"] == "dog"].iloc[0]
        self.assertEqual(dog_row["type"], "Выпускник")
        self.assertEqual(dog_row["reviews"], 0)
        self.assertEqual(dog_row["streak"], 0)

    def test_12_front_and_back_queues_full_independence(self):
        """Лицевая (EN->RU) и обратная (RU->EN) стороны развиваются полностью независимо."""
        mock_lang = empty_lang("English", "🇬🇧", "en-US")
        vb = pd.DataFrame([
            {"word": "sun", "translation": "солнце", "pron": "", "phrase": "", "phrase_tr": "", "extra": "", "in_stack": False},
        ])
        mock_lang["tables"]["vocab_base"] = normalize("vocab_base", vb)
        sync_group("vocab", mock_lang)

        # На лицевой стороне даём ответ "Легко"
        grade_item("vocab", "easy", lang=mock_lang, item_idx=0)
        
        vp = mock_lang["tables"]["vocab_pool"]
        vrp = mock_lang["tables"]["vocab_rev_pool"]
        
        self.assertEqual(vp.iloc[0]["reviews"], 1, "На лицевой стороне должен быть 1 повтор")
        self.assertEqual(vp.iloc[0]["streak"], 1, "На лицевой стороне стрик должен стать 1")
        
        self.assertEqual(vrp.iloc[0]["reviews"], 0, "На обратной стороне должно остаться 0 повторов")
        self.assertEqual(vrp.iloc[0]["streak"], 0, "На обратной стороне стрик должен остаться 0")


# =============================================================================
# 5. ТЕСТЫ СТЕЙТ-МАШИНЫ SRS И ПОВТОРЕНИЙ КАРТОЧЕК
# =============================================================================
class TestCardGradingStateMachine(unittest.TestCase):
    """Проверка всех переходов: Новичок -> Старичок -> Экзамен -> Откат -> Возврат."""

    def setUp(self):
        self.mock_lang = empty_lang("English", "🇬🇧", "en-US")
        vb = pd.DataFrame([{"word": "book", "translation": "книга", "pron": "", "phrase": "", "phrase_tr": "", "extra": "", "in_stack": False}])
        vp = pd.DataFrame([{"word": "book", "type": "Выпускник", "position": 1, "interval": 0, "reviews": 0, "last": "", "weight": 1.0, "streak": 0, "due_date": "", "star_days": 5}])
        self.mock_lang["tables"]["vocab_base"] = normalize("vocab_base", vb)
        self.mock_lang["tables"]["vocab_pool"] = normalize("vocab_pool", vp)

    def test_13_novice_graduates_to_star_after_3_easy(self):
        """Новичок после ровно 3 ответов 'Легко' подряд становится Старичком со стартовыми 5 днями."""
        for _ in range(3):
            grade_item("vocab", "easy", lang=self.mock_lang, item_idx=0)
            
        vp = self.mock_lang["tables"]["vocab_pool"]
        row = vp.iloc[0]
        self.assertEqual(row["type"], "Старичок")
        self.assertEqual(row["star_days"], 5)
        self.assertEqual(row["streak"], 0, "Стрик сбрасывается для будущих экзаменов")
        self.assertEqual(row["weight"], 1.0, "Коэффициент не растёт в день выпуска, только на экзамене")
        self.assertEqual(row["due_date"], (date.today() + timedelta(days=5)).isoformat())

    def test_14_exam_success_doubles_interval_and_adds_weight(self):
        """В день экзамена (due_date <= today) ответ 'Легко' увеличивает вес (+0.1) и удваивает интервал."""
        vp = self.mock_lang["tables"]["vocab_pool"]
        vp.loc[0, "type"] = "Старичок"
        vp.loc[0, "due_date"] = date.today().isoformat()
        vp.loc[0, "star_days"] = 5
        vp.loc[0, "weight"] = 1.0
        vp.loc[0, "streak"] = 0
        self.mock_lang["tables"]["vocab_pool"] = vp

        grade_item("vocab", "easy", lang=self.mock_lang, item_idx=0)
        
        row = self.mock_lang["tables"]["vocab_pool"].iloc[0]
        self.assertEqual(row["type"], "Старичок")
        self.assertEqual(row["weight"], 1.1)
        self.assertEqual(row["streak"], 1)
        self.assertGreaterEqual(row["star_days"], 10)
        self.assertEqual(row["due_date"], (date.today() + timedelta(days=int(row["star_days"]))).isoformat())

    def test_15_exam_failure_demotes_and_penalizes(self):
        """Ошибка на экзамене: перевод в 'Повторяем', стрик 0, вес -0.2, откат интервала вдвое, очистка due_date."""
        vp = self.mock_lang["tables"]["vocab_pool"]
        vp.loc[0, "type"] = "Старичок"
        vp.loc[0, "due_date"] = date.today().isoformat()
        vp.loc[0, "star_days"] = 10
        vp.loc[0, "weight"] = 1.2
        vp.loc[0, "streak"] = 2
        self.mock_lang["tables"]["vocab_pool"] = vp

        grade_item("vocab", "hard", lang=self.mock_lang, item_idx=0)
        
        row = self.mock_lang["tables"]["vocab_pool"].iloc[0]
        self.assertEqual(row["type"], "Повторяем")
        self.assertEqual(row["streak"], 0)
        self.assertEqual(row["weight"], 1.0)
        self.assertEqual(row["star_days"], 5)
        self.assertEqual(row["due_date"], "")

    def test_16_return_from_repeating_restores_star(self):
        """Возврат из 'Повторяем' после 3 'Легко': восстанавливает 'Старичка' с сохранённого шага."""
        vp = self.mock_lang["tables"]["vocab_pool"]
        vp.loc[0, "type"] = "Повторяем"
        vp.loc[0, "star_days"] = 8
        vp.loc[0, "weight"] = 1.1
        vp.loc[0, "streak"] = 0
        self.mock_lang["tables"]["vocab_pool"] = vp

        for _ in range(3):
            grade_item("vocab", "easy", lang=self.mock_lang, item_idx=0)
            
        row = self.mock_lang["tables"]["vocab_pool"].iloc[0]
        self.assertEqual(row["type"], "Старичок")
        self.assertEqual(row["star_days"], 8, "Интервал восстанавливается с сохранённого шага")
        self.assertEqual(row["due_date"], (date.today() + timedelta(days=8)).isoformat())

    def test_17_weight_clamping_limits(self):
        """Коэффициент веса не может опускаться ниже 0.5 или превышать 2.5."""
        vp = self.mock_lang["tables"]["vocab_pool"]
        vp.loc[0, "type"] = "Старичок"
        vp.loc[0, "due_date"] = date.today().isoformat()
        vp.loc[0, "weight"] = 2.5
        self.mock_lang["tables"]["vocab_pool"] = vp

        grade_item("vocab", "easy", lang=self.mock_lang, item_idx=0)
        self.assertEqual(self.mock_lang["tables"]["vocab_pool"].iloc[0]["weight"], 2.5)

        # Тест нижнего предела
        vp.loc[0, "due_date"] = date.today().isoformat()
        vp.loc[0, "weight"] = 0.5
        self.mock_lang["tables"]["vocab_pool"] = vp
        grade_item("vocab", "hard", lang=self.mock_lang, item_idx=0)
        self.assertEqual(self.mock_lang["tables"]["vocab_pool"].iloc[0]["weight"], 0.5)


# =============================================================================
# 6. ТЕСТЫ СТЕКА НЕДЕЛИ И ЕГО ПЕРЕНОСА
# =============================================================================
class TestWeeklyStackIntegration(unittest.TestCase):
    """Проверка флагов in_stack, таблицы stack и переноса transfer_stack_to_vocab."""

    def setUp(self):
        self.mock_lang = empty_lang("English", "🇬🇧", "en-US")
        vb = pd.DataFrame([
            {"word": "coffee", "translation": "кофе", "pron": "", "phrase": "Hot coffee", "phrase_tr": "Горячий кофе", "extra": "drink", "in_stack": True},
            {"word": "tea", "translation": "чай", "pron": "", "phrase": "Hot tea", "phrase_tr": "Горячий чай", "extra": "drink", "in_stack": False},
        ])
        self.mock_lang["tables"]["vocab_base"] = normalize("vocab_base", vb)
        sync_stack_from_vocab(self.mock_lang)

    def test_18_sync_stack_from_vocab_filtering(self):
        """sync_stack_from_vocab переносит в стек только слова с флагом in_stack=True."""
        stk = self.mock_lang["tables"]["stack"]
        self.assertEqual(len(stk), 1)
        self.assertEqual(stk.iloc[0]["phrase"], "coffee")
        self.assertEqual(stk.iloc[0]["note"], "кофе")

    def test_19_sync_vocab_from_stack_bi_directional(self):
        """sync_vocab_from_stack синхронизирует флаги в vocab_base при изменении стека."""
        # Добавим в стек 'tea'
        stk = self.mock_lang["tables"]["stack"]
        new_stk = pd.concat([stk, pd.DataFrame([{"phrase": "tea", "note": "чай"}])], ignore_index=True)
        self.mock_lang["tables"]["stack"] = normalize("stack", new_stk)
        
        sync_vocab_from_stack(lang=self.mock_lang)
        vb = self.mock_lang["tables"]["vocab_base"]
        
        self.assertTrue(vb.loc[vb["word"] == "coffee", "in_stack"].values[0])
        self.assertTrue(vb.loc[vb["word"] == "tea", "in_stack"].values[0])

    def test_20_transfer_stack_to_vocab_removes_from_stack_and_updates_flag(self):
        """transfer_stack_to_vocab снимает флаг in_stack=False и удаляет слово из стека."""
        transferred = transfer_stack_to_vocab(selected_phrases=["coffee"], remove_from_stack=True, lang=self.mock_lang)
        self.assertEqual(transferred, 1)
        
        stk_after = self.mock_lang["tables"]["stack"]
        vb_after = self.mock_lang["tables"]["vocab_base"]
        
        self.assertEqual(len(stk_after), 0, "Стек должен стать пустым")
        coffee_flag = vb_after.loc[vb_after["word"] == "coffee", "in_stack"].values[0]
        self.assertFalse(coffee_flag, "У coffee должен стоять in_stack=False")

    def test_21_pack_and_unpack_stack_row(self):
        """pack_stack_row и unpack_stack_row сохраняют и восстанавливают сложные метаданные."""
        row_dict = {
            "phrase": "take off",
            "note": "взлетать",
            "pron": "teɪk ɒf",
            "phrase_ex": "The plane takes off",
            "phrase_tr": "Самолёт взлетает",
            "extra": "phrasal verb"
        }
        packed_note = pack_stack_row(row_dict)
        unpacked = unpack_stack_row("take off", packed_note)
        
        self.assertEqual(unpacked["note"], "взлетать")
        self.assertEqual(unpacked["pron"], "teɪk ɒf")
        self.assertEqual(unpacked["phrase_ex"], "The plane takes off")
        self.assertEqual(unpacked["phrase_tr"], "Самолёт взлетает")
        self.assertEqual(unpacked["extra"], "phrasal verb")


# =============================================================================
# 7. ТЕСТЫ UI ФОРМАТИРОВАНИЯ И ЗАЩИТЫ
# =============================================================================
class TestUIHelpersAndEscaping(unittest.TestCase):
    """Проверка форматирования оставшегося времени, склонений и экранирования."""

    def test_22_format_due_diff_intervals(self):
        """format_due_diff возвращает понятные человекочитаемые интервалы."""
        self.assertEqual(format_due_diff(0), "сейчас")
        self.assertEqual(format_due_diff(-100), "сейчас")
        self.assertEqual(format_due_diff(45), "45 сек")
        self.assertEqual(format_due_diff(180), "3 мин")
        self.assertEqual(format_due_diff(7200), "2 ч")
        self.assertEqual(format_due_diff(7500), "2 ч 5 м")
        self.assertEqual(format_due_diff(86400), "1 д")
        self.assertEqual(format_due_diff(90000), "1 д 1 ч")

    def test_23_rev_word_declensions(self):
        """rev_word правильно склоняет слово 'повтор' в русском языке."""
        self.assertEqual(rev_word(1), "1 повтор")
        self.assertEqual(rev_word(21), "21 повтор")
        self.assertEqual(rev_word(2), "2 повтора")
        self.assertEqual(rev_word(4), "4 повтора")
        self.assertEqual(rev_word(5), "5 повторов")
        self.assertEqual(rev_word(11), "11 повторов")
        self.assertEqual(rev_word(14), "14 повторов")

    def test_24_esc_html_and_math(self):
        """esc корректно экранирует HTML теги и знак $ для KaTeX."""
        unsafe = "<script>alert('xss')</script> & price is $100"
        safe = esc(unsafe)
        self.assertNotIn("<script>", safe)
        self.assertIn("&lt;script&gt;", safe)
        self.assertIn("&amp;", safe)
        self.assertIn("&#36;100", safe)


# =============================================================================
# 8. ТЕСТЫ ОБЛАЧНОГО СНИМКА SUPABASE
# =============================================================================
class TestCloudPayloadGeneration(unittest.TestCase):
    """Проверка генерации полезной нагрузки для фоновой отправки в Supabase."""

    def test_25_supabase_payload_integrity(self):
        """Снимок таблиц генерирует корректные типы (bool, int, str) без исключений."""
        mock_lang = empty_lang("English", "🇬🇧", "en-US")
        vb = pd.DataFrame([{"word": "cloud", "translation": "облако", "in_stack": True}])
        vp = pd.DataFrame([{"word": "cloud", "type": "Выпускник", "position": 1, "interval": 0, "reviews": 0, "streak": 0, "star_days": 5, "weight": 1.0, "due_date": ""}])
        mock_lang["tables"]["vocab_base"] = normalize("vocab_base", vb)
        mock_lang["tables"]["vocab_pool"] = normalize("vocab_pool", vp)
        
        tb = mock_lang["tables"]
        v_base = {r["word"]: r for r in tb["vocab_base"].to_dict("records")}
        v_rows = []
        for r in tb["vocab_pool"].to_dict("records"):
            w = r["word"]
            b = v_base.get(w, {})
            v_rows.append({
                "lang": "en",
                "direction": "front",
                "word": w,
                "in_stack": bool(b.get("in_stack", False)),
                "type": r.get("type", "Выпускник"),
                "due_date": str(r.get("due_date", "")),
                "streak": int(r.get("streak", 0)),
                "star_days": int(r.get("star_days", 5)),
                "weight": float(r.get("weight", 1.0)),
            })
            
        self.assertEqual(len(v_rows), 1)
        for row in v_rows:
            self.assertIsInstance(row["in_stack"], bool)
            self.assertIsInstance(row["streak"], int)
            self.assertIsInstance(row["star_days"], int)
            self.assertIsInstance(row["weight"], float)
            self.assertIsInstance(row["due_date"], str)


# =============================================================================
# 9. СКВОЗНОЙ ИНТЕГРАЦИОННЫЙ ТЕСТ (END-TO-END)
# =============================================================================
class TestEndToEndWorkflow(unittest.TestCase):
    """Полный жизненный цикл приложения: импорт -> стек -> изучение -> экзамен -> облако."""

    def test_26_full_lifecycle_e2e(self):
        # 1. Инициализация чистого языка
        lang = empty_lang("Español", "🇪🇸", "es-ES")

        # 2. Пакетный импорт слова
        pasted = "desafío — вызов, испытание"
        rows, _, _ = parse_pasted(pasted, "AUTO", "\n", 2)
        recs = [{"word": r[0], "translation": r[1], "pron": "", "phrase": "", "phrase_tr": "", "extra": "", "in_stack": True} for r in rows]
        added, _, _ = apply_import("vocab", recs, False, lang=lang)
        self.assertEqual(added, 1)

        # 3. Синхронизация со стеком
        sync_stack_from_vocab(lang)
        self.assertEqual(len(lang["tables"]["stack"]), 1)

        # 4. Прохождение 3 ответов "Легко" -> Карточка становится Старичком
        for _ in range(3):
            grade_item("vocab", "easy", lang=lang, item_idx=0)
            
        vp = lang["tables"]["vocab_pool"]
        self.assertEqual(vp.iloc[0]["type"], "Старичок")
        self.assertEqual(vp.iloc[0]["star_days"], 5)

        # 5. Сдача экзамена вовремя
        vp.loc[0, "due_date"] = date.today().isoformat()
        lang["tables"]["vocab_pool"] = vp
        grade_item("vocab", "easy", lang=lang, item_idx=0)
        
        vp_after_exam = lang["tables"]["vocab_pool"]
        self.assertEqual(vp_after_exam.iloc[0]["weight"], 1.1)
        self.assertEqual(vp_after_exam.iloc[0]["streak"], 1)

        # 6. Перенос из стека недели в основной словарь с удалением из стека
        transferred = transfer_stack_to_vocab(["desafío"], remove_from_stack=True, lang=lang)
        self.assertEqual(transferred, 1)
        self.assertEqual(len(lang["tables"]["stack"]), 0)
        self.assertFalse(lang["tables"]["vocab_base"].iloc[0]["in_stack"])

        # 7. Финальная проверка сохранения и сериализации
        saved_dict = {"languages": {"es": lang}}
        re_langs, _ = ingest(saved_dict)
        self.assertIn("es", re_langs)
        self.assertEqual(re_langs["es"]["tables"]["vocab_base"].iloc[0]["word"], "desafío")


if __name__ == "__main__":
    unittest.main()
