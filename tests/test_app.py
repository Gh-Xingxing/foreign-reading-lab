# -*- coding: utf-8 -*-

import json
import os
import tempfile
import unittest
from pathlib import Path

from app import server


class ForeignReadingLabTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["FOREIGN_READING_DB"] = str(Path(self.temp_dir.name) / "test.sqlite3")
        os.environ["FOREIGN_READING_AI_MODE"] = "mock"
        os.environ.pop("FOREIGN_READING_API_KEY", None)
        server.initialize_database()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_seed_article_has_reader_structure(self) -> None:
        with server.database() as conn:
            articles = server.list_articles(conn)
            self.assertGreaterEqual(len(articles), 1)
            article = server.get_article(conn, articles[0]["id"])
        self.assertEqual(article["title"], "The City That Learned to Listen")
        self.assertGreaterEqual(len(article["paragraphs"]), 5)
        self.assertGreaterEqual(len(article["paragraphs"][0]["sentences"]), 1)
        self.assertGreaterEqual(len(article["vocabulary"]), 1)

    def test_import_article_and_analysis(self) -> None:
        content = (
            "A newsroom can be a laboratory for public attention. "
            "Editors decide which small changes deserve a second look.\n\n"
            "The best feature stories do not merely report events. "
            "They arrange evidence so that readers can notice cause, consequence, and character."
        )
        with server.database() as conn:
            article_id = server.create_article(
                conn,
                {
                    "title": "A Small Test Article",
                    "source": "Unit Test",
                    "content": content,
                },
            )
            article = server.get_article(conn, article_id)
            analysis = server.get_analysis(conn, article_id)
        self.assertEqual(article["title"], "A Small Test Article")
        self.assertEqual(len(article["paragraphs"]), 2)
        self.assertIn("thesis", analysis)
        self.assertIn("ielts_training", analysis)
        self.assertIn("study_flow", analysis)
        self.assertEqual(analysis["source"], "mock")

    def test_tools_and_saves(self) -> None:
        with server.database() as conn:
            article_id = server.list_articles(conn)[0]["id"]
            article = server.get_article(conn, article_id)
            sentence = article["paragraphs"][0]["sentences"][0]
            lookup = server.lookup_word("resilient", sentence["text"])
            pattern = server.analyze_sentence(sentence["text"])
            highlight = server.insert_row(
                conn,
                "highlights",
                {
                    "article_id": article_id,
                    "sentence_id": sentence["id"],
                    "text": sentence["text"],
                    "note": "test",
                },
            )
            saved = server.get_article(conn, article_id)
            vocab_id = saved["vocabulary"][0]["id"]
            updated = server.update_vocabulary_status(conn, {"id": vocab_id, "status": "mastered"})
        self.assertIn("有韧性", lookup["translation_cn"])
        self.assertIn("pattern", pattern)
        self.assertEqual(highlight["note"], "test")
        self.assertGreaterEqual(len(saved["highlights"]), 2)
        self.assertEqual(updated["status"], "mastered")

    def test_exports_are_downloadable(self) -> None:
        with server.database() as conn:
            article_id = server.list_articles(conn)[0]["id"]
            markdown = server.export_markdown(conn, article_id)
            pdf = server.export_pdf(conn, article_id)
        self.assertTrue(markdown.startswith("# The City That Learned to Listen"))
        self.assertIn("## 全文赏析", markdown)
        self.assertIn("## 雅思题型训练", markdown)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"%%EOF", pdf[-32:])

    def test_api_handlers(self) -> None:
        get_response = server.handle_get("/api/articles", {})
        payload = json.loads(get_response.body.decode("utf-8"))
        self.assertEqual(get_response.status, 200)
        self.assertIn("articles", payload)

        post_response = server.handle_post(
            "/api/tools/translate",
            {"text": "A city becomes resilient not when it conquers uncertainty, but when it learns to listen."},
        )
        result = json.loads(post_response.body.decode("utf-8"))["result"]
        self.assertEqual(post_response.status, 200)
        self.assertEqual(result["source"], "mock")

        status_response = server.handle_post(
            "/api/vocabulary/status",
            {"id": 1, "status": "reviewing"},
        )
        status_result = json.loads(status_response.body.decode("utf-8"))["vocabulary"]
        self.assertEqual(status_response.status, 200)
        self.assertEqual(status_result["status"], "reviewing")


if __name__ == "__main__":
    unittest.main()

