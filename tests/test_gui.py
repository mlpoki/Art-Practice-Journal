import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QPoint, Qt, QTime
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QLabel, QTimeEdit, QVBoxLayout, QWidget

from art_practice_journal.app import (
    DeleteConfirmDialog,
    DetailPanel,
    DateHintBubble,
    EntryDetailDialog,
    EntryDialog,
    MainWindow,
    PracticeCalendarWidget,
    SmoothScrollArea,
    StatsPage,
    TimelinePage,
    TimelineRail,
    apply_style,
    chip,
    clear_layout,
    current_minute,
    timeline_note_preview,
)
from art_practice_journal.db import JournalRepository
from art_practice_journal.storage import get_app_paths


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
        apply_style(instance)
    return instance


class GuiDialogTests(unittest.TestCase):
    def setUp(self):
        app()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = JournalRepository(get_app_paths(self.root))

    def tearDown(self):
        self.tmp.cleanup()

    def test_entry_dialog_is_windowed_scrollable_and_timer_toggles(self):
        dialog = EntryDialog(self.repo)

        self.assertTrue(dialog.windowFlags() & QDialog().windowFlags())
        self.assertGreaterEqual(dialog.minimumHeight(), 520)
        self.assertEqual(dialog.timer_button.text(), "开始计时")
        self.assertEqual(dialog.date_edit.calendarWidget().objectName(), "calendarPopup")

        dialog.toggle_timer()
        self.assertTrue(dialog.timer_running)
        self.assertTrue(dialog.live_timer.isActive())
        self.assertEqual(dialog.timer_button.text(), "暂停计时")
        dialog.start_edit.setTime(current_minute().addSecs(-3600))
        dialog.update_live_timer()
        self.assertIn("计时中", dialog.duration_preview.text())

        dialog.toggle_timer()
        self.assertFalse(dialog.timer_running)
        self.assertFalse(dialog.live_timer.isActive())
        self.assertEqual(dialog.timer_button.text(), "继续计时")
        self.assertEqual(len(dialog.time_segments), 1)
        self.assertIn("第 1 段", dialog.segment_view.summary_label.text())

        dialog.toggle_timer()
        self.assertTrue(dialog.timer_running)
        self.assertEqual(dialog.timer_button.text(), "暂停计时")
        dialog.toggle_timer()
        self.assertFalse(dialog.live_timer.isActive())

    def test_view_and_delete_dialogs_can_render_text(self):
        entry_id = self.repo.create_entry(
            "查看测试",
            "绘画",
            "2026-07-04",
            "09:00",
            "10:00",
            60,
            "完整文字记录",
            "测试",
        )

        detail = EntryDetailDialog(self.repo, entry_id)
        delete = DeleteConfirmDialog("查看测试")

        self.assertEqual(detail.windowTitle(), "查看记录")
        self.assertEqual(delete.windowTitle(), "删除记录")

    def test_chips_use_stable_google_day_palette(self):
        attachment_chip = chip("3 个附件", "#ea4335")
        style = attachment_chip.styleSheet()

        self.assertIn("background: #fce8e6", style)
        self.assertIn("color: #c5221f", style)
        self.assertNotIn("#ea433512", style)

    def test_clear_layout_detaches_widgets_immediately(self):
        parent = QWidget()
        layout = QVBoxLayout(parent)
        label = QLabel("旧内容")
        layout.addWidget(label)

        clear_layout(layout)

        self.assertEqual(layout.count(), 0)
        self.assertIsNone(label.parent())

    def test_stats_page_layout_includes_total_days_and_calendar(self):
        current = QDate.currentDate()
        current_text = current.toString("yyyy-MM-dd")
        next_text = current.addDays(1).toString("yyyy-MM-dd")
        self.repo.create_entry("统计测试", "绘画", current_text, "09:00", "10:00", 60, "", "")
        self.repo.create_entry("写作测试", "写作", next_text, "10:00", "11:30", 90, "", "")
        page = StatsPage(self.repo)

        first_count = page.layout.count()
        cards = page.findChildren(QFrame, "metricCard")
        calendar = page.findChild(PracticeCalendarWidget)

        self.assertEqual(len(cards), 5)
        self.assertIsNotNone(calendar)
        self.assertEqual(page.metric_row_one.count(), 3)
        self.assertEqual(page.metric_row_two.count(), 2)
        self.assertEqual(calendar.month_date.toString("yyyy-MM"), current.toString("yyyy-MM"))
        self.assertEqual(calendar.data[current_text]["duration"], "01:00")
        self.assertTrue(calendar.grid.has_same_week_connection(current))
        self.assertLessEqual(calendar.grid.minimumHeight(), 220)
        calendar.select_date(current)
        self.assertEqual(calendar.selected_date, current)

        page.refresh()
        second_count = page.layout.count()
        page.refresh()
        third_count = page.layout.count()

        self.assertEqual(first_count, second_count)
        self.assertEqual(second_count, third_count)

    def test_practice_calendar_compresses_without_clipping_dates(self):
        self.repo.create_entry("统计测试", "绘画", "2026-07-07", "09:00", "10:00", 60, "", "")
        calendar = PracticeCalendarWidget(self.repo)
        calendar.month_date = QDate(2026, 7, 1)
        calendar.load_month()
        calendar.grid.resize(760, 190)

        calendar.grid.grab()

        self.assertEqual(len(calendar.grid.date_rects), 31)
        self.assertTrue(all(rect.top() >= 0 for rect in calendar.grid.date_rects.values()))
        self.assertTrue(all(rect.bottom() <= calendar.grid.height() + 1 for rect in calendar.grid.date_rects.values()))
        self.assertLessEqual(calendar.grid.recommended_height(760), 300)

    def test_practice_calendar_draws_unbroken_same_week_connection(self):
        self.repo.create_entry("A", "绘画", "2026-07-04", "09:00", "10:00", 60, "", "")
        self.repo.create_entry("B", "绘画", "2026-07-05", "10:00", "11:00", 60, "", "")
        calendar = PracticeCalendarWidget(self.repo)
        calendar.month_date = QDate(2026, 7, 1)
        calendar.load_month()
        calendar.grid.resize(760, 260)

        calendar.grid.grab()

        self.assertEqual(len(calendar.grid.connection_rects), 1)
        rect = calendar.grid.connection_rects[0]
        day4 = calendar.grid.date_rects["2026-07-04"]
        day5 = calendar.grid.date_rects["2026-07-05"]
        self.assertLessEqual(rect.left(), day4.center().x())
        self.assertGreaterEqual(rect.right(), day5.center().x())

    def test_practice_calendar_navigation_only_uses_record_months(self):
        self.repo.create_entry("五月记录", "绘画", "2026-05-04", "09:00", "10:00", 60, "", "")
        self.repo.create_entry("七月记录", "写作", "2026-07-05", "10:00", "11:00", 60, "", "")
        calendar = PracticeCalendarWidget(self.repo)
        calendar.month_date = QDate(2026, 7, 1)
        calendar.load_month()

        self.assertTrue(calendar.prev_btn.isEnabled())
        self.assertFalse(calendar.next_btn.isEnabled())

        calendar.change_month(-1)

        self.assertEqual(calendar.month_date, QDate(2026, 5, 1))
        self.assertFalse(calendar.prev_btn.isEnabled())
        self.assertTrue(calendar.next_btn.isEnabled())

        calendar.change_month(1)

        self.assertEqual(calendar.month_date, QDate(2026, 7, 1))
        self.assertTrue(calendar.prev_btn.isEnabled())
        self.assertFalse(calendar.next_btn.isEnabled())

    def test_note_field_enter_inserts_manual_line_break(self):
        dialog = EntryDialog(self.repo)
        dialog.note_edit.setFocus()

        QTest.keyClicks(dialog.note_edit, "first")
        QTest.keyClick(dialog.note_edit, Qt.Key_Return)
        QTest.keyClicks(dialog.note_edit, "second")

        self.assertEqual(dialog.note_edit.toPlainText(), "first\nsecond")

    def test_entry_dialog_can_add_manual_time_segments(self):
        dialog = EntryDialog(self.repo)
        dialog.start_edit.setTime(dialog.start_edit.time().fromString("09:00", "HH:mm"))
        dialog.end_edit.setTime(dialog.end_edit.time().fromString("10:00", "HH:mm"))
        dialog.add_manual_segment()
        dialog.start_edit.setTime(dialog.start_edit.time().fromString("10:30", "HH:mm"))
        dialog.end_edit.setTime(dialog.end_edit.time().fromString("11:00", "HH:mm"))
        dialog.add_manual_segment()

        values = dialog.values()

        self.assertEqual(len(dialog.time_segments), 2)
        self.assertIn("第 2 段", dialog.segment_view.summary_label.text())
        self.assertEqual(values["start_time"], "09:00")
        self.assertEqual(values["end_time"], "11:00")
        self.assertEqual(values["duration_minutes"], 90)
        self.assertEqual(values["time_segments"], [("09:00", "10:00", 60), ("10:30", "11:00", 30)])

    def test_entry_dialog_can_delete_time_segments(self):
        dialog = EntryDialog(self.repo)
        dialog.time_segments = [("09:00", "10:00", 60), ("10:30", "11:00", 30)]
        dialog.refresh_segment_combo()

        dialog.delete_time_segment(1)
        values = dialog.values()

        self.assertEqual(dialog.time_segments, [("09:00", "10:00", 60)])
        self.assertIn("第 1 段", dialog.segment_view.summary_label.text())
        self.assertEqual(values["duration_minutes"], 60)
        self.assertEqual(values["time_segments"], [("09:00", "10:00", 60)])

    def test_entry_dialog_can_edit_time_segment_start_and_end(self):
        dialog = EntryDialog(self.repo)
        dialog.time_segments = [("09:00", "10:00", 60), ("10:30", "11:00", 30)]
        dialog.refresh_segment_combo()
        dialog.segment_view.expanded = True
        dialog.segment_view.render()

        editors = dialog.segment_view.findChildren(QTimeEdit)
        self.assertEqual(len(editors), 4)
        editors[2].setTime(QTime.fromString("10:15", "HH:mm"))
        editors[3].setTime(QTime.fromString("11:15", "HH:mm"))
        values = dialog.values()

        self.assertEqual(dialog.time_segments[1], ("10:15", "11:15", 60))
        self.assertEqual(values["duration_minutes"], 120)
        self.assertEqual(values["time_segments"], [("09:00", "10:00", 60), ("10:15", "11:15", 60)])

    def test_timeline_preview_preserves_manual_line_breaks(self):
        preview = timeline_note_preview("第一行\n第二行\n第三行")

        self.assertEqual(preview, "第一行\n第二行\n第三行")

    def test_detail_panel_uses_scroll_area_for_many_attachments(self):
        entry_id = self.repo.create_entry(
            "附件测试",
            "绘画",
            "2026-07-04",
            "09:00",
            "10:00",
            60,
            "记录",
            "",
        )
        sources = []
        for index in range(5):
            source = self.root / f"attachment-{index}.txt"
            source.write_text(f"file {index}", encoding="utf-8")
            sources.append(source)
        self.repo.add_attachments(entry_id, sources, "2026-07-04")

        panel = DetailPanel(self.repo)
        panel.resize(360, 260)
        panel.render_entry(entry_id)

        self.assertIsInstance(panel.scroll, SmoothScrollArea)
        self.assertEqual(panel.scroll.smooth_timer.interval(), 16)
        self.assertTrue(panel.scroll.widgetResizable())
        self.assertEqual(panel.scroll.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        self.assertGreater(panel.content.sizeHint().height(), panel.height())

    def test_smooth_scroll_area_amplifies_touchpad_delta_and_accumulates_target(self):
        scroll = SmoothScrollArea()
        scroll.verticalScrollBar().setRange(0, 1000)
        scroll.verticalScrollBar().setValue(100)

        self.assertGreaterEqual(scroll.wheel_scroll_step(-8, 0), 24)

        scroll.smooth_scroll_to(200)
        self.assertEqual(scroll.current_scroll_target(), 200)
        scroll.smooth_scroll_to(scroll.current_scroll_target() + scroll.wheel_scroll_step(-8, 0))

        self.assertGreaterEqual(scroll.smooth_target_value, 224)

    def test_detail_panel_can_move_and_delete_attachments(self):
        entry_id = self.repo.create_entry(
            "附件管理",
            "绘画",
            "2026-07-04",
            "09:00",
            "10:00",
            60,
            "记录",
            "",
        )
        first = self.root / "first.txt"
        second = self.root / "second.txt"
        first.write_text("first", encoding="utf-8")
        second.write_text("second", encoding="utf-8")
        attachments = self.repo.add_attachments(entry_id, [first, second], "2026-07-04")

        panel = DetailPanel(self.repo)
        panel.render_entry(entry_id)
        panel.move_attachment(attachments[1].id, -1)
        moved = self.repo.list_attachments(entry_id)
        self.assertEqual([item.id for item in moved], [attachments[1].id, attachments[0].id])

        stored_path = Path(moved[0].stored_path)
        panel.delete_attachment(moved[0].id)
        remaining = self.repo.list_attachments(entry_id)

        self.assertFalse(stored_path.exists())
        self.assertEqual([item.id for item in remaining], [attachments[0].id])

    def test_main_window_detail_panel_is_resizable_with_splitter(self):
        window = MainWindow()

        self.assertEqual(window.content_splitter.count(), 2)
        self.assertIs(window.content_splitter.widget(1), window.detail)
        self.assertGreaterEqual(window.detail.maximumWidth(), 16777215)
        self.assertIsInstance(window.stats_scroll, SmoothScrollArea)
        self.assertIs(window.stats_scroll.widget(), window.stats_page)

    def test_timeline_tag_filter_date_default_and_rail(self):
        self.repo.create_entry("A", "绘画", "2026-07-05", "08:00", "09:00", 60, "", "临摹, 人体")
        self.repo.create_entry("B", "绘画", "2026-07-05", "10:00", "11:00", 60, "", "草稿")
        page = TimelinePage(self.repo)

        tags = {page.tag_filter.itemText(index) for index in range(page.tag_filter.count())}
        self.assertIn("人体", tags)
        self.assertFalse(page.date_filter_active)
        self.assertEqual(page.date_filter.date(), QDate.currentDate())
        self.assertIsInstance(page.scroll, SmoothScrollArea)
        self.assertEqual(page.scroll.smooth_timer.interval(), 16)
        self.assertEqual(page.scroll.verticalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)
        self.assertEqual(page.timeline_rail.count, 1)

        page.tag_filter.setCurrentText("人体")
        self.assertEqual(len(page.cards), 1)
        self.assertIn("A", page.cards[0].entry.title)

    def test_timeline_rail_groups_days_and_shows_overflow(self):
        rail = TimelineRail()
        rail.resize(34, 120)
        rail.set_markers(
            [
                {"date": "2026-07-06", "card_index": 0, "entry_count": 4},
                {"date": "2026-07-05", "card_index": 4, "entry_count": 1},
                {"date": "2026-07-04", "card_index": 5, "entry_count": 1},
                {"date": "2026-07-03", "card_index": 6, "entry_count": 1},
            ]
        )

        busy_gap = rail.logical_dot_y(1) - rail.logical_dot_y(0)
        quiet_gap = rail.logical_dot_y(2) - rail.logical_dot_y(1)

        self.assertEqual(rail.count, 4)
        self.assertGreater(busy_gap, quiet_gap)
        self.assertTrue(rail.has_more_after)

        rail.set_scroll_ratio(1)
        self.assertTrue(rail.has_more_before)

    def test_timeline_rail_centers_short_marker_groups_and_exposes_dates(self):
        rail = TimelineRail()
        rail.resize(34, 120)
        rail.set_markers(
            [
                {"date": "2026-07-06", "card_index": 0, "entry_count": 1},
                {"date": "2026-07-05", "card_index": 1, "entry_count": 1},
            ]
        )

        y0 = rail.dot_y(0)
        y1 = rail.dot_y(1)

        self.assertAlmostEqual((y0 + y1) / 2, rail.height() / 2, delta=1)
        self.assertEqual(rail.marker_date(0), "2026-07-06")
        self.assertEqual(rail.index_at_y(y0), 0)
        self.assertEqual(rail.index_at_y(y1), 1)

    def test_timeline_rail_uses_delayed_fading_date_hint(self):
        rail = TimelineRail()
        rail.resize(34, 120)
        rail.set_markers([{"date": "2026-07-06", "card_index": 0, "entry_count": 1}])

        self.assertIsInstance(rail.date_hint, DateHintBubble)
        self.assertTrue(rail.date_hint.testAttribute(Qt.WA_TranslucentBackground))
        self.assertEqual(rail.hover_delay_timer.interval(), 1000)
        self.assertEqual(rail.date_hint.fade_animation.duration(), 180)

        rail.hover_index = 0
        rail.hover_global_pos = QPoint(120, 120)
        rail.show_hover_marker_date()

        self.assertEqual(rail.date_hint.label.text(), "2026-07-06")
        self.assertEqual(rail.date_hint.fade_animation.endValue(), 1.0)

        rail.date_hint.fade_out()
        self.assertTrue(rail.date_hint.hide_when_faded)
        self.assertEqual(rail.date_hint.fade_animation.endValue(), 0.0)


if __name__ == "__main__":
    unittest.main()
