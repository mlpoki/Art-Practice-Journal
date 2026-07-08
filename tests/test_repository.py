import tempfile
import unittest
from pathlib import Path

from art_practice_journal.db import JournalRepository
from art_practice_journal.storage import get_app_paths, save_config


class JournalRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.paths = get_app_paths(self.root)
        self.repo = JournalRepository(self.paths)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_and_search_entry(self):
        entry_id = self.repo.create_entry(
            title="人物速写",
            practice_type="绘画",
            practice_date="2026-07-04",
            start_time="09:00",
            end_time="10:30",
            duration_minutes=90,
            note="练习头部比例",
            tags="速写, 人体",
        )

        entry = self.repo.get_entry(entry_id)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.title, "人物速写")
        self.assertEqual(entry.duration_minutes, 90)

        results = self.repo.list_entries(search="头部", practice_type="绘画")
        self.assertEqual([item.id for item in results], [entry_id])

    def test_list_tags_and_filter_entries_by_tag(self):
        first = self.repo.create_entry("A", "绘画", "2026-07-05", "08:00", "09:00", 60, "", "临摹, 人体")
        self.repo.create_entry("B", "写作", "2026-07-05", "10:00", "11:00", 60, "", "草稿")

        self.assertEqual(set(self.repo.list_tags()), {"临摹", "人体", "草稿"})
        results = self.repo.list_entries(tag_filter="人体")

        self.assertEqual([entry.id for entry in results], [first])

    def test_attachment_is_copied_to_library(self):
        source = self.root / "draft.docx"
        source.write_bytes(b"fake docx")
        entry_id = self.repo.create_entry(
            "小说练习",
            "写作",
            "2026-07-04",
            "20:00",
            "21:00",
            60,
            "完成场景草稿",
            "小说",
        )

        attachments = self.repo.add_attachments(entry_id, [source], "2026-07-04")
        source.unlink()

        self.assertEqual(len(attachments), 1)
        stored = Path(attachments[0].stored_path)
        self.assertTrue(stored.exists())
        self.assertEqual(attachments[0].original_name, "draft.docx")
        self.assertEqual(attachments[0].kind, "document")

    def test_attachment_rename_order_and_delete(self):
        first = self.root / "first.txt"
        second = self.root / "second.txt"
        first.write_text("first", encoding="utf-8")
        second.write_text("second", encoding="utf-8")
        entry_id = self.repo.create_entry("附件管理", "绘画", "2026-07-04", "09:00", "10:00", 60, "", "")
        attachments = self.repo.add_attachments(entry_id, [first, second], "2026-07-04")

        self.repo.rename_attachment(attachments[0].id, "renamed.txt")
        ordered_ids = [attachments[1].id, attachments[0].id]
        self.repo.set_attachment_order(entry_id, ordered_ids)
        ordered = self.repo.list_attachments(entry_id)

        self.assertEqual([item.id for item in ordered], ordered_ids)
        self.assertEqual(ordered[1].original_name, "renamed.txt")

        stored_path = Path(ordered[0].stored_path)
        self.assertTrue(stored_path.exists())
        deleted = self.repo.delete_attachment(ordered[0].id)

        self.assertIsNotNone(deleted)
        self.assertFalse(stored_path.exists())
        self.assertEqual([item.id for item in self.repo.list_attachments(entry_id)], [attachments[0].id])

    def test_stats_include_totals_and_type_breakdown(self):
        self.repo.create_entry("A", "绘画", "2026-07-04", "08:00", "09:00", 60, "", "")
        self.repo.create_entry("B", "写作", "2026-07-04", "10:00", "12:00", 120, "", "")
        self.repo.create_entry("C", "绘画", "2026-07-05", "08:00", "09:00", 30, "", "")

        stats = self.repo.stats()

        self.assertEqual(stats["total"]["count"], 3)
        self.assertEqual(stats["total"]["minutes"], 210)
        self.assertEqual(stats["total_days"], 2)
        by_type = {row["practice_type"]: row["minutes"] for row in stats["by_type"]}
        self.assertEqual(by_type["绘画"], 90)
        self.assertEqual(by_type["写作"], 120)

    def test_calendar_month_summary_uses_primary_type_and_empty_state(self):
        self.assertEqual(self.repo.calendar_month(2026, 7), {})

        self.repo.create_entry("A", "绘画", "2026-07-04", "08:00", "09:00", 60, "", "")
        self.repo.create_entry("B", "写作", "2026-07-04", "10:00", "12:00", 120, "", "")
        self.repo.create_entry("C", "素描", "2026-07-05", "10:00", "10:45", 45, "", "")
        self.repo.create_entry("D", "绘画", "2026-08-01", "10:00", "10:45", 45, "", "")

        july = self.repo.calendar_month(2026, 7)

        self.assertEqual(july["2026-07-04"]["minutes"], 180)
        self.assertEqual(july["2026-07-04"]["primary_type"], "写作")
        self.assertEqual(july["2026-07-04"]["types"]["绘画"], 60)
        self.assertEqual(july["2026-07-04"]["types"]["写作"], 120)
        self.assertEqual(july["2026-07-05"]["minutes"], 45)
        self.assertNotIn("2026-08-01", july)

    def test_practice_months_returns_only_months_with_records(self):
        self.assertEqual(self.repo.practice_months(), [])

        self.repo.create_entry("A", "绘画", "2026-05-04", "08:00", "09:00", 60, "", "")
        self.repo.create_entry("B", "写作", "2026-07-04", "10:00", "12:00", 120, "", "")
        self.repo.create_entry("C", "素描", "2026-07-05", "10:00", "10:45", 45, "", "")

        self.assertEqual(self.repo.practice_months(), ["2026-05", "2026-07"])

    def test_time_segments_are_saved_and_replaced(self):
        entry_id = self.repo.create_entry(
            "分段练习",
            "绘画",
            "2026-07-04",
            "09:00",
            "11:30",
            120,
            "",
            "",
            [("09:00", "10:00", 60), ("10:30", "11:30", 60)],
        )

        segments = self.repo.list_time_segments(entry_id)
        self.assertEqual([(s.start_time, s.end_time, s.duration_minutes) for s in segments], [
            ("09:00", "10:00", 60),
            ("10:30", "11:30", 60),
        ])

        self.repo.update_entry(
            entry_id,
            "分段练习",
            "绘画",
            "2026-07-04",
            "12:00",
            "12:45",
            45,
            "",
            "",
            [("12:00", "12:45", 45)],
        )

        segments = self.repo.list_time_segments(entry_id)
        self.assertEqual([(s.start_time, s.end_time, s.duration_minutes) for s in segments], [
            ("12:00", "12:45", 45),
        ])

    def test_custom_paths_are_loaded_from_config(self):
        custom_data = self.root / "library"
        custom_db = self.root / "custom" / "journal.db"
        custom_attachments = self.root / "media"
        custom_thumbnails = self.root / "thumbs"

        save_config(
            {
                "data_dir": str(custom_data),
                "db_path": str(custom_db),
                "attachments_dir": str(custom_attachments),
                "thumbnails_dir": str(custom_thumbnails),
            },
            self.root,
        )

        paths = get_app_paths(self.root)

        self.assertEqual(paths.data_dir, custom_data.resolve())
        self.assertEqual(paths.db_path, custom_db.resolve())
        self.assertEqual(paths.attachments_dir, custom_attachments.resolve())
        self.assertEqual(paths.thumbnails_dir, custom_thumbnails.resolve())
        self.assertTrue(custom_attachments.exists())
        self.assertTrue(custom_thumbnails.exists())


if __name__ == "__main__":
    unittest.main()
