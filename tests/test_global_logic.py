import unittest
import unittest.mock
import sys
import os
import re

# Додаємо батьківську директорію в sys.path, щоб імпортувати BezRusni_Global
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from BezRusni_Global import get_all_artists

class TestGlobalLogic(unittest.TestCase):
    def test_get_all_artists_splits_correctly(self):
        """Перевіряємо, що виконавці коректно розділяються за сполучниками, зокрема 'і' та 'та'."""
        self.assertEqual(get_all_artists("Miyagi і Andy Panda"), ["Miyagi", "Andy Panda"])
        self.assertEqual(get_all_artists("Потап та Настя"), ["Потап", "Настя"])
        self.assertEqual(get_all_artists("Artist and Band"), ["Artist", "Band"])
        self.assertEqual(get_all_artists("Eminem feat. Rihanna"), ["Eminem", "Rihanna"])
        self.assertEqual(get_all_artists("Snoop Dogg ft. Dr. Dre"), ["Snoop Dogg", "Dr. Dre"])
        self.assertEqual(get_all_artists("Daft Punk with Pharrell"), ["Daft Punk", "Pharrell"])
        
        # Має залишитись цілим (літера 'І' на початку слова не повинна розбити рядок)
        self.assertEqual(get_all_artists("Іван Дорн"), ["Іван Дорн"]) 
        
        # Складний випадок з кількома розділювачами
        self.assertEqual(get_all_artists("Some Artist і Other Artist та Third Artist"), ["Some Artist", "Other Artist", "Third Artist"])

    def test_text_for_ua_check_logic(self):
        """Перевіряємо логіку ізоляції сполучника 'і' для детектування українських літер."""
        # Відтворюємо мінімальну логіку з process_track для тестування без мокінгу сесій Windows
        def simulate_ua_check(full_artist, title):
            text = f"{full_artist} {title}".lower()
            text_for_ua_check = re.sub(r'\bі\b', '', text)
            ua_unique = ['і', 'ї', 'є', 'ґ']
            return any(char in text_for_ua_check for char in ua_unique)

        # "і" як сполучник не повинно викликати True (бо це може бути підстава від локалізації YT Music)
        self.assertFalse(simulate_ua_check("Miyagi і Andy Panda", "Трэк"))
        
        # Якщо є реальна українська літера (наприклад, 'і' всередині слова, або 'ї', 'є', 'ґ'), має бути True
        self.assertTrue(simulate_ua_check("Скрябін", "Мовчати")) # "Скрябін" містить 'і'
        self.assertTrue(simulate_ua_check("Океан Ельзи", "Вставай, моя країно!")) # "країно" містить 'ї'
        
        # Перевірка, що 'і' в слові не видаляється (воно видаляється тільки якщо стоїть окремо \bі\b)
        self.assertTrue(simulate_ua_check("Іван Дорн", "Трек")) # 'і' є частиною "Іван"
        self.assertTrue(simulate_ua_check("Miyagi", "Пісня")) # 'і' є частиною "Пісня"

    def test_ru_exact_words(self):
        """Перевіряємо, що додані короткі слова ('и', 'да', 'нет') спрацьовують правильно."""
        from BezRusni_Global import RU_EXACT_WORDS
        
        # Переконаємось, що наші нові слова є у словнику
        for word in ["и", "да", "нет", "как", "где", "кто", "он", "она", "они", "их"]:
            self.assertIn(word, RU_EXACT_WORDS)
            
        def simulate_dictionary_check(text):
            words = re.findall(r'\b[а-яА-ЯёЁ]+\b', text.lower())
            for w in words:
                if w in RU_EXACT_WORDS:
                    return True
            return False

        # Типові російські фрази з новими словами
        self.assertTrue(simulate_dictionary_check("Кот и собака"))
        self.assertTrue(simulate_dictionary_check("Он ушел"))
        self.assertTrue(simulate_dictionary_check("Где ты"))
        
        # Українські фрази не повинні спрацьовувати
        self.assertFalse(simulate_dictionary_check("Кіт і собака")) # 'і' немає в RU_EXACT_WORDS
        self.assertFalse(simulate_dictionary_check("Де ти")) # 'де' немає
        self.assertFalse(simulate_dictionary_check("Він пішов")) # 'він' немає

    @unittest.mock.patch('requests.get')
    def test_check_wikidata_sync_other_country(self, mock_get):
        """Перевіряємо, що гурт з іноземною країною походження отримує статус OTHER, а не NONE."""
        from BezRusni_Global import check_wikidata_sync, artist_cache
        
        # Імітуємо відповідь пошуку Wikidata
        mock_search_resp = unittest.mock.Mock()
        mock_search_resp.status_code = 200
        mock_search_resp.json.return_value = {
            "search": [{"id": "Q12345"}]
        }
        
        # Імітуємо відповідь із властивостями (P495 - Країна походження: США Q30)
        mock_entity_resp = unittest.mock.Mock()
        mock_entity_resp.status_code = 200
        mock_entity_resp.json.return_value = {
            "entities": {
                "Q12345": {
                    "claims": {
                        "P495": [
                            {"mainsnak": {"datavalue": {"value": {"id": "Q30"}}}}
                        ]
                    }
                }
            }
        }
        
        mock_get.side_effect = [mock_search_resp, mock_entity_resp]
        
        # Очистимо кеш перед тестом
        artist_cache.clear()
        
        # Виклик функції
        result = check_wikidata_sync("Mocked Western Band")
        
        # Має повернутись OTHER, бо знайдено країну США (Q30), що не є RU чи UA
        self.assertEqual(result, "OTHER")

if __name__ == '__main__':
    unittest.main()
