from __future__ import annotations

import csv
import calendar
import sys
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QPoint, QPointF, QDate, QDateTime, QPropertyAnimation, QRectF, QSize, QTime, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QCalendarWidget,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .db import Entry, JournalRepository
from .storage import AppPaths, get_app_paths, save_config


GOOGLE_BLUE = "#1a73e8"
GOOGLE_RED = "#ea4335"
GOOGLE_YELLOW = "#fbbc04"
GOOGLE_GREEN = "#34a853"
BORDER = "#dadce0"
TEXT = "#202124"
MUTED = "#5f6368"
SURFACE = "#ffffff"
APP_BG = "#f8fafd"


def minutes_label(minutes: int) -> str:
    hours, mins = divmod(max(0, minutes), 60)
    if hours and mins:
        return f"{hours}小时 {mins}分钟"
    if hours:
        return f"{hours}小时"
    return f"{mins}分钟"


def duration_hhmm(minutes: int) -> str:
    hours, mins = divmod(max(0, minutes), 60)
    return f"{hours:02d}:{mins:02d}"


def qdate_to_text(value: QDate) -> str:
    return value.toString("yyyy-MM-dd")


def qtime_to_text(value: QTime) -> str:
    return value.toString("HH:mm")


def configure_date_edit(date_edit: QDateEdit) -> None:
    date_edit.setCalendarPopup(True)
    calendar = date_edit.calendarWidget()
    if calendar is None:
        calendar = QCalendarWidget(date_edit)
        date_edit.setCalendarWidget(calendar)
    calendar.setObjectName("calendarPopup")
    calendar.setGridVisible(False)
    calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)


def duration_between(start: QTime, end: QTime) -> int:
    seconds = start.secsTo(end)
    if seconds < 0:
        seconds += 24 * 60 * 60
    return max(0, seconds // 60)


def segment_duration(start_time: str, end_time: str) -> int:
    start = QTime.fromString(start_time, "HH:mm")
    end = QTime.fromString(end_time, "HH:mm")
    if not start.isValid() or not end.isValid():
        return 0
    return duration_between(start, end)


def segment_label(index: int, start_time: str, end_time: str, duration_minutes: int) -> str:
    return f"第 {index} 段  {start_time}-{end_time}  ·  {minutes_label(duration_minutes)}"


def entry_time_segments(repo: JournalRepository, entry: Entry) -> list[tuple[str, str, int]]:
    stored_segments = repo.list_time_segments(entry.id)
    if stored_segments:
        return [
            (segment.start_time, segment.end_time, segment.duration_minutes)
            for segment in stored_segments
        ]
    return [(entry.start_time, entry.end_time, entry.duration_minutes)]


def segment_dropdown(segments: list[tuple[str, str, int]]) -> QComboBox:
    combo = QComboBox()
    combo.setObjectName("segmentCombo")
    for index, (start_time, end_time, duration_minutes) in enumerate(segments, start=1):
        combo.addItem(segment_label(index, start_time, end_time, duration_minutes))
    if segments:
        combo.setCurrentIndex(len(segments) - 1)
    return combo


def current_minute() -> QTime:
    now = QDateTime.currentDateTime().time()
    return QTime(now.hour(), now.minute())


def chip(text: str, color: str = GOOGLE_BLUE) -> QLabel:
    palettes = {
        GOOGLE_BLUE: ("#e8f0fe", "#d2e3fc", "#1967d2"),
        GOOGLE_GREEN: ("#e6f4ea", "#ceead6", "#137333"),
        GOOGLE_RED: ("#fce8e6", "#fad2cf", "#c5221f"),
        GOOGLE_YELLOW: ("#fef7e0", "#feefc3", "#b06000"),
    }
    background, border, foreground = palettes.get(color, ("#f1f3f4", "#dadce0", color))
    label = QLabel(text)
    label.setStyleSheet(
        f"""
        QLabel {{
            background: {background};
            color: {foreground};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 4px 9px;
            font-size: 12px;
            font-weight: 600;
        }}
        """
    )
    return label


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        child_layout = item.layout()
        widget = item.widget()
        if child_layout is not None:
            clear_layout(child_layout)
            child_layout.setParent(None)
            child_layout.deleteLater()
        elif widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def timeline_note_preview(note: str, max_chars: int = 140, max_lines: int = 4) -> str:
    lines = note.strip().splitlines()
    if not lines:
        return ""
    preview = "\n".join(lines[:max_lines])
    if len(preview) > max_chars:
        return preview[:max_chars].rstrip() + "..."
    if len(lines) > max_lines:
        return preview + "\n..."
    return preview


class NoteTextEdit(QTextEdit):
    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.insertPlainText("\n")
            event.accept()
            return
        super().keyPressEvent(event)


class TimeSegmentsWidget(QFrame):
    delete_requested = Signal(int)
    segment_changed = Signal(int, str, str)

    def __init__(self) -> None:
        super().__init__()
        self.segments: list[tuple[str, str, int]] = []
        self.expanded = False
        self.setObjectName("segmentPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        summary = QFrame()
        summary.setObjectName("segmentSummary")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(12, 8, 8, 8)
        summary_layout.setSpacing(8)

        self.summary_label = QLabel("暂无时间段")
        self.summary_label.setObjectName("bodyText")
        self.summary_label.setWordWrap(True)
        self.toggle_button = QPushButton("展开")
        self.toggle_button.setObjectName("segmentToggleButton")
        self.toggle_button.clicked.connect(self.toggle_expanded)
        summary_layout.addWidget(self.summary_label, 1)
        summary_layout.addWidget(self.toggle_button)
        layout.addWidget(summary)

        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        layout.addWidget(self.rows_host)
        self.rows_host.setVisible(False)

    def set_segments(self, segments: list[tuple[str, str, int]]) -> None:
        self.segments = list(segments)
        self.render()

    def toggle_expanded(self) -> None:
        self.expanded = not self.expanded
        self.render()

    def render(self) -> None:
        if not self.segments:
            self.summary_label.setText("暂无时间段")
            self.toggle_button.setEnabled(False)
            self.toggle_button.setText("展开")
            self.rows_host.setVisible(False)
            clear_layout(self.rows_layout)
            return

        latest_index = len(self.segments)
        latest = self.segments[-1]
        self.summary_label.setText(segment_label(latest_index, latest[0], latest[1], latest[2]))
        self.toggle_button.setEnabled(True)
        self.toggle_button.setText("收起" if self.expanded else "展开")
        self.rows_host.setVisible(self.expanded)
        clear_layout(self.rows_layout)
        if not self.expanded:
            return

        for index, (start_time, end_time, duration_minutes) in enumerate(self.segments):
            row = QFrame()
            row.setObjectName("segmentRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 8, 8, 8)
            row_layout.setSpacing(8)
            label = QLabel(f"第 {index + 1} 段")
            label.setObjectName("bodyText")
            label.setMinimumWidth(52)
            start_edit = QTimeEdit()
            start_edit.setObjectName("segmentTimeEdit")
            start_edit.setDisplayFormat("HH:mm")
            start_edit.setTime(QTime.fromString(start_time, "HH:mm"))
            end_edit = QTimeEdit()
            end_edit.setObjectName("segmentTimeEdit")
            end_edit.setDisplayFormat("HH:mm")
            end_edit.setTime(QTime.fromString(end_time, "HH:mm"))
            duration_label = QLabel(minutes_label(duration_minutes))
            duration_label.setObjectName("muted")
            duration_label.setMinimumWidth(72)
            delete_btn = QPushButton("X")
            delete_btn.setObjectName("segmentDeleteButton")
            delete_btn.setFixedSize(30, 30)
            delete_btn.setToolTip("删除这个时间段")
            delete_btn.clicked.connect(lambda _checked=False, i=index: self.delete_requested.emit(i))
            start_edit.timeChanged.connect(
                lambda _time, i=index, s=start_edit, e=end_edit, d=duration_label: self.update_segment_from_row(i, s, e, d)
            )
            end_edit.timeChanged.connect(
                lambda _time, i=index, s=start_edit, e=end_edit, d=duration_label: self.update_segment_from_row(i, s, e, d)
            )
            row_layout.addWidget(label)
            row_layout.addWidget(start_edit)
            row_layout.addWidget(QLabel("至"))
            row_layout.addWidget(end_edit)
            row_layout.addWidget(duration_label, 1)
            row_layout.addWidget(delete_btn)
            self.rows_layout.addWidget(row)

    def update_segment_from_row(
        self,
        index: int,
        start_edit: QTimeEdit,
        end_edit: QTimeEdit,
        duration_label: QLabel,
    ) -> None:
        if not 0 <= index < len(self.segments):
            return
        start_time = qtime_to_text(start_edit.time())
        end_time = qtime_to_text(end_edit.time())
        duration_minutes = segment_duration(start_time, end_time)
        self.segments[index] = (start_time, end_time, duration_minutes)
        duration_label.setText(minutes_label(duration_minutes))
        latest_index = len(self.segments)
        latest = self.segments[-1]
        self.summary_label.setText(segment_label(latest_index, latest[0], latest[1], latest[2]))
        self.segment_changed.emit(index, start_time, end_time)


class DropFilesBox(QFrame):
    files_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.files: list[str] = []
        self.setAcceptDrops(True)
        self.setObjectName("dropBox")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel("上传附件")
        title.setObjectName("sectionTitle")
        hint = QLabel("拖入图片、视频、Word、PDF、TXT，或点击下方按钮选择文件")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(96)

        pick_btn = QPushButton("选择文件")
        pick_btn.setObjectName("secondaryButton")
        pick_btn.clicked.connect(self.pick_files)

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.list_widget)
        layout.addWidget(pick_btn, alignment=Qt.AlignLeft)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        self.add_files(paths)

    def pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择附件",
            "",
            "艺术记录附件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.mp4 *.mov *.avi *.mkv *.doc *.docx *.pdf *.txt *.rtf *.md);;所有文件 (*.*)",
        )
        self.add_files(files)

    def add_files(self, files: list[str]) -> None:
        for file in files:
            path = Path(file)
            if path.is_file() and str(path) not in self.files:
                self.files.append(str(path))
        self.refresh()
        self.files_changed.emit()

    def refresh(self) -> None:
        self.list_widget.clear()
        if not self.files:
            QListWidgetItem("暂无待上传文件", self.list_widget)
            return
        for file in self.files:
            QListWidgetItem(Path(file).name, self.list_widget)


class EntryDialog(QDialog):
    def __init__(self, repo: JournalRepository, entry: Entry | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.repo = repo
        self.entry = entry
        self.timer_running = False
        self.current_segment_start: str | None = None
        self.time_segments: list[tuple[str, str, int]] = []
        self.live_timer = QTimer(self)
        self.live_timer.setInterval(1000)
        self.live_timer.timeout.connect(self.update_live_timer)
        self.setWindowTitle("编辑练习记录" if entry else "新增练习记录")
        self.setModal(True)
        self.setWindowFlag(Qt.Window, True)
        self.setMinimumSize(560, 520)
        self.resize(720, 660)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("dialogScroll")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 28, 28, 20)
        content_layout.setSpacing(16)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        title = QLabel("编辑练习记录" if entry else "新增练习记录")
        title.setObjectName("dialogTitle")
        content_layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        content_layout.addLayout(grid)

        self.title_edit = QLineEdit(entry.title if entry else "")
        self.title_edit.setPlaceholderText("例如：人物速写、小说第一章、色彩临摹")

        self.type_combo = QComboBox()
        self.type_combo.setEditable(True)
        default_types = ["绘画", "写作", "书法", "摄影", "音乐", "设计", "其他"]
        known_types = [t for t in self.repo.list_types() if t not in default_types]
        self.type_combo.addItems(default_types + known_types)
        if entry:
            self.type_combo.setCurrentText(entry.practice_type)

        self.date_edit = QDateEdit()
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        configure_date_edit(self.date_edit)
        self.date_edit.setDate(QDate.fromString(entry.practice_date, "yyyy-MM-dd") if entry else QDate.currentDate())

        self.start_edit = QTimeEdit()
        self.start_edit.setDisplayFormat("HH:mm")
        self.start_edit.setTime(QTime.fromString(entry.start_time, "HH:mm") if entry else current_minute())
        self.end_edit = QTimeEdit()
        self.end_edit.setDisplayFormat("HH:mm")
        self.end_edit.setTime(QTime.fromString(entry.end_time, "HH:mm") if entry else current_minute().addSecs(3600))

        self.duration_preview = QLabel()
        self.duration_preview.setObjectName("muted")
        self.start_edit.timeChanged.connect(self.update_duration)
        self.end_edit.timeChanged.connect(self.update_duration)
        self.timer_button = QPushButton("开始计时")
        self.timer_button.setObjectName("secondaryButton")
        self.timer_button.clicked.connect(self.toggle_timer)
        self.add_segment_button = QPushButton("增加时间段")
        self.add_segment_button.setObjectName("secondaryButton")
        self.add_segment_button.clicked.connect(self.add_manual_segment)
        self.segment_view = TimeSegmentsWidget()
        self.segment_view.delete_requested.connect(self.delete_time_segment)
        self.segment_view.segment_changed.connect(self.update_time_segment)

        self.tags_edit = QLineEdit(entry.tags if entry else "")
        self.tags_edit.setPlaceholderText("用逗号分隔，例如：速写, 人体, 复盘")

        grid.addWidget(QLabel("标题"), 0, 0)
        grid.addWidget(self.title_edit, 0, 1, 1, 3)
        grid.addWidget(QLabel("类型"), 1, 0)
        grid.addWidget(self.type_combo, 1, 1)
        grid.addWidget(QLabel("日期"), 1, 2)
        grid.addWidget(self.date_edit, 1, 3)
        grid.addWidget(QLabel("开始"), 2, 0)
        grid.addWidget(self.start_edit, 2, 1)
        grid.addWidget(QLabel("结束"), 2, 2)
        grid.addWidget(self.end_edit, 2, 3)
        grid.addWidget(QLabel("时长"), 3, 0)
        grid.addWidget(self.duration_preview, 3, 1)
        grid.addWidget(self.add_segment_button, 3, 2)
        grid.addWidget(self.timer_button, 3, 3)
        grid.addWidget(QLabel("时间段"), 4, 0)
        grid.addWidget(self.segment_view, 4, 1, 1, 3)
        grid.addWidget(QLabel("标签"), 5, 0)
        grid.addWidget(self.tags_edit, 5, 1, 1, 3)

        note_label = QLabel("文字记录")
        note_label.setObjectName("sectionTitle")
        self.note_edit = NoteTextEdit(entry.note if entry else "")
        self.note_edit.setPlaceholderText("写下练习目标、过程、卡住的地方、下一次要改进什么……")
        self.note_edit.setMinimumHeight(150)
        content_layout.addWidget(note_label)
        content_layout.addWidget(self.note_edit)

        self.drop_box = DropFilesBox()
        content_layout.addWidget(self.drop_box)

        if entry:
            existing = self.repo.list_attachments(entry.id)
            if existing:
                names = "、".join(item.original_name for item in existing)
                hint = QLabel(f"已有附件：{names}")
                hint.setObjectName("muted")
                hint.setWordWrap(True)
                content_layout.addWidget(hint)

        footer = QHBoxLayout()
        footer_widget = QFrame()
        footer_widget.setObjectName("dialogFooter")
        footer_widget.setLayout(footer)
        footer.setContentsMargins(20, 14, 20, 14)
        footer.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        cancel = QPushButton("取消")
        cancel.setObjectName("secondaryButton")
        cancel.setAutoDefault(False)
        cancel.setDefault(False)
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存记录")
        save.setObjectName("primaryButton")
        save.setAutoDefault(False)
        save.setDefault(False)
        save.clicked.connect(self.accept)
        footer.addWidget(cancel)
        footer.addWidget(save)
        layout.addWidget(footer_widget)
        self.load_initial_segments()
        self.update_duration()

    def toggle_timer(self) -> None:
        now = current_minute()
        if not self.timer_running:
            self.timer_running = True
            self.current_segment_start = qtime_to_text(now)
            self.date_edit.setDate(QDate.currentDate())
            self.start_edit.setTime(now)
            self.end_edit.setTime(now)
            self.update_duration()
            self.live_timer.start()
            self.timer_button.setText("暂停计时")
            self.timer_button.setObjectName("primaryButton")
            self.timer_button.style().unpolish(self.timer_button)
            self.timer_button.style().polish(self.timer_button)
            return

        self.timer_running = False
        self.live_timer.stop()
        self.end_edit.setTime(now)
        self.finish_current_timed_segment()
        self.timer_button.setText("继续计时")
        self.timer_button.setObjectName("secondaryButton")
        self.timer_button.style().unpolish(self.timer_button)
        self.timer_button.style().polish(self.timer_button)

    def update_live_timer(self) -> None:
        if not self.timer_running:
            return
        self.end_edit.setTime(current_minute())
        self.update_duration()

    def update_duration(self) -> None:
        current_minutes = duration_between(self.start_edit.time(), self.end_edit.time())
        total = self.total_segment_minutes()
        if self.timer_running:
            total += current_minutes
            self.duration_preview.setText(f"计时中 · 本段 {minutes_label(current_minutes)} · 总计 {minutes_label(total)}")
            return
        if self.time_segments:
            self.duration_preview.setText(f"总计 {minutes_label(total)}")
            return
        self.duration_preview.setText(minutes_label(current_minutes))

    def load_initial_segments(self) -> None:
        if not self.entry:
            self.refresh_segment_combo()
            return
        stored_segments = self.repo.list_time_segments(self.entry.id)
        if stored_segments:
            self.time_segments = [
                (segment.start_time, segment.end_time, segment.duration_minutes)
                for segment in stored_segments
            ]
        else:
            self.time_segments = [
                (self.entry.start_time, self.entry.end_time, self.entry.duration_minutes)
            ]
        if self.time_segments:
            start_time, end_time, _ = self.time_segments[-1]
            self.start_edit.setTime(QTime.fromString(start_time, "HH:mm"))
            self.end_edit.setTime(QTime.fromString(end_time, "HH:mm"))
        self.refresh_segment_combo()

    def refresh_segment_combo(self) -> None:
        self.segment_view.set_segments(self.time_segments)
        self.update_duration()

    def delete_time_segment(self, index: int) -> None:
        if 0 <= index < len(self.time_segments):
            del self.time_segments[index]
            self.refresh_segment_combo()

    def update_time_segment(self, index: int, start_time: str, end_time: str) -> None:
        if not 0 <= index < len(self.time_segments):
            return
        self.time_segments[index] = (start_time, end_time, segment_duration(start_time, end_time))
        self.update_duration()

    def add_manual_segment(self) -> None:
        start_time = qtime_to_text(self.start_edit.time())
        end_time = qtime_to_text(self.end_edit.time())
        duration_minutes = segment_duration(start_time, end_time)
        self.time_segments.append((start_time, end_time, duration_minutes))
        self.refresh_segment_combo()

    def finish_current_timed_segment(self) -> None:
        if self.current_segment_start is None:
            return
        end_time = qtime_to_text(self.end_edit.time())
        duration_minutes = segment_duration(self.current_segment_start, end_time)
        self.time_segments.append((self.current_segment_start, end_time, duration_minutes))
        self.current_segment_start = None
        self.refresh_segment_combo()

    def total_segment_minutes(self) -> int:
        return sum(segment[2] for segment in self.time_segments)

    def normalized_segments(self) -> list[tuple[str, str, int]]:
        if self.timer_running:
            self.end_edit.setTime(current_minute())
            self.finish_current_timed_segment()
            self.timer_running = False
            self.live_timer.stop()
        if self.time_segments:
            return list(self.time_segments)
        start_time = qtime_to_text(self.start_edit.time())
        end_time = qtime_to_text(self.end_edit.time())
        return [(start_time, end_time, segment_duration(start_time, end_time))]

    def values(self) -> dict[str, object]:
        segments = self.normalized_segments()
        start_time = segments[0][0]
        end_time = segments[-1][1]
        duration_minutes = sum(segment[2] for segment in segments)
        return {
            "title": self.title_edit.text(),
            "practice_type": self.type_combo.currentText(),
            "practice_date": qdate_to_text(self.date_edit.date()),
            "start_time": start_time,
            "end_time": end_time,
            "duration_minutes": duration_minutes,
            "note": self.note_edit.toPlainText(),
            "tags": self.tags_edit.text(),
            "files": list(self.drop_box.files),
            "time_segments": segments,
        }


class EntryCard(QFrame):
    selected = Signal(int)
    view_requested = Signal(int)
    edit_requested = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, entry: Entry, attachment_count: int):
        super().__init__()
        self.entry = entry
        self.setObjectName("entryCard")
        self.setCursor(Qt.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(entry.title)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        header.addWidget(title, 1)
        header.addWidget(chip(entry.practice_type, GOOGLE_BLUE))
        layout.addLayout(header)

        meta = QLabel(
            f"{entry.practice_date}  {entry.start_time}-{entry.end_time}  ·  {minutes_label(entry.duration_minutes)}"
        )
        meta.setObjectName("muted")
        layout.addWidget(meta)

        if entry.note:
            preview = timeline_note_preview(entry.note)
            note = QLabel(preview)
            note.setObjectName("bodyText")
            note.setWordWrap(True)
            layout.addWidget(note)

        footer = QHBoxLayout()
        if entry.tags:
            footer.addWidget(chip(entry.tags, GOOGLE_GREEN))
        if attachment_count:
            footer.addWidget(chip(f"{attachment_count} 个附件", GOOGLE_RED))
        footer.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        view_btn = QPushButton("查看")
        view_btn.setObjectName("textButton")
        view_btn.clicked.connect(lambda: self.view_requested.emit(entry.id))
        edit_btn = QPushButton("编辑")
        edit_btn.setObjectName("textButton")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(entry.id))
        del_btn = QPushButton("删除")
        del_btn.setObjectName("dangerTextButton")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(entry.id))
        footer.addWidget(view_btn)
        footer.addWidget(edit_btn)
        footer.addWidget(del_btn)
        layout.addLayout(footer)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.entry.id)
        super().mousePressEvent(event)


class SmoothScrollArea(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self.smooth_duration_ms = 360
        self.touchpad_pixel_multiplier = 3.2
        self.wheel_angle_multiplier = 1.35
        self.smooth_start_value = 0
        self.smooth_target_value = 0
        self.smooth_clock = QElapsedTimer()
        self.smooth_easing = QEasingCurve(QEasingCurve.OutCubic)
        self.smooth_timer = QTimer(self)
        self.smooth_timer.setInterval(16)
        self.smooth_timer.timeout.connect(self.advance_smooth_scroll)

    def smooth_scroll_to(self, value: int) -> None:
        bar = self.verticalScrollBar()
        target = max(bar.minimum(), min(bar.maximum(), value))
        if target == bar.value():
            return
        self.smooth_start_value = bar.value()
        self.smooth_target_value = target
        self.smooth_clock.restart()
        if not self.smooth_timer.isActive():
            self.smooth_timer.start()

    def current_scroll_target(self) -> int:
        if self.smooth_timer.isActive():
            return self.smooth_target_value
        return self.verticalScrollBar().value()

    def wheel_scroll_step(self, pixel_delta: int, angle_delta: int) -> int:
        if pixel_delta:
            return round(-pixel_delta * self.touchpad_pixel_multiplier)
        base_step = max(42, self.verticalScrollBar().singleStep() * 5)
        return round(-(angle_delta / 120) * base_step * self.wheel_angle_multiplier)

    def advance_smooth_scroll(self) -> None:
        elapsed = min(self.smooth_clock.elapsed(), self.smooth_duration_ms)
        progress = elapsed / self.smooth_duration_ms if self.smooth_duration_ms else 1
        eased = self.smooth_easing.valueForProgress(progress)
        value = self.smooth_start_value + (self.smooth_target_value - self.smooth_start_value) * eased
        self.verticalScrollBar().setValue(round(value))
        if elapsed >= self.smooth_duration_ms:
            self.smooth_timer.stop()
            self.verticalScrollBar().setValue(self.smooth_target_value)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        bar = self.verticalScrollBar()
        pixel_delta = event.pixelDelta().y()
        angle_delta = event.angleDelta().y()
        if not pixel_delta and not angle_delta:
            super().wheelEvent(event)
            return

        step = self.wheel_scroll_step(pixel_delta, angle_delta)
        self.smooth_scroll_to(self.current_scroll_target() + step)
        event.accept()


class DateHintBubble(QFrame):
    def __init__(self) -> None:
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setObjectName("dateHintBubble")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(0)
        self.label = QLabel()
        self.label.setObjectName("dateHintText")
        layout.addWidget(self.label)

        self.setWindowOpacity(0.0)
        self.fade_animation = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade_animation.setDuration(180)
        self.fade_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.fade_animation.finished.connect(self.hide_after_fade)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(60, 64, 67, 42))
        self.setGraphicsEffect(shadow)

        self.hide_when_faded = False
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.fade_out)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor("#e6e8eb"), 1))
        painter.setBrush(QBrush(QColor(SURFACE)))
        painter.drawRoundedRect(rect, 8, 8)

    def hide_after_fade(self) -> None:
        if self.hide_when_faded:
            self.hide()

    def show_date(self, date_text: str, global_pos, duration_ms: int = 0) -> None:
        if not date_text:
            return
        self.hide_timer.stop()
        self.hide_when_faded = False
        self.label.setText(date_text)
        self.adjustSize()
        self.move(self.clamped_position(global_pos))
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
        self.fade_animation.stop()
        self.fade_animation.setStartValue(self.windowOpacity())
        self.fade_animation.setEndValue(1.0)
        self.fade_animation.start()
        if duration_ms:
            self.hide_timer.start(duration_ms)

    def clamped_position(self, global_pos) -> QPoint:
        pos = QPoint(global_pos.x() + 14, global_pos.y() - self.height() // 2)
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            pos.setX(min(max(pos.x(), available.left() + 8), available.right() - self.width() - 8))
            pos.setY(min(max(pos.y(), available.top() + 8), available.bottom() - self.height() - 8))
        return pos

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        self.hide_when_faded = True
        self.fade_animation.stop()
        self.fade_animation.setStartValue(self.windowOpacity())
        self.fade_animation.setEndValue(0.0)
        self.fade_animation.start()


class TimelineRail(QWidget):
    jump_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.markers: list[dict[str, int | str]] = []
        self.count = 0
        self.active_index = 0
        self.scroll_ratio = 0.0
        self.logical_positions: list[float] = []
        self.logical_height = 0.0
        self.has_more_before = False
        self.has_more_after = False
        self.hover_index = -1
        self.hover_global_pos = QPoint()
        self.hover_delay_timer = QTimer(self)
        self.hover_delay_timer.setSingleShot(True)
        self.hover_delay_timer.setInterval(1000)
        self.hover_delay_timer.timeout.connect(self.show_hover_marker_date)
        self.date_hint = DateHintBubble()
        self.setFixedWidth(34)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setObjectName("timelineRail")

    def set_count(self, count: int) -> None:
        self.set_markers([{"card_index": index, "entry_count": 1, "date": ""} for index in range(max(0, count))])

    def set_markers(self, markers: list[dict[str, int | str]]) -> None:
        self.markers = markers
        self.count = len(markers)
        self.active_index = min(self.active_index, max(0, self.count - 1))
        self.rebuild_positions()
        self.update_overflow_flags()
        self.update()

    def set_active_index(self, index: int) -> None:
        self.active_index = min(max(0, index), max(0, self.count - 1))
        self.update()

    def set_scroll_ratio(self, ratio: float) -> None:
        self.scroll_ratio = min(1.0, max(0.0, ratio))
        self.update_overflow_flags()
        self.update()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.update_overflow_flags()

    def marker_card_index(self, index: int) -> int:
        if not 0 <= index < self.count:
            return -1
        return int(self.markers[index].get("card_index", index))

    def rebuild_positions(self) -> None:
        self.logical_positions = []
        if not self.markers:
            self.logical_height = 0
            return
        y = 0.0
        for index, marker in enumerate(self.markers):
            self.logical_positions.append(y)
            if index < len(self.markers) - 1:
                entry_count = int(marker.get("entry_count", 1))
                y += 30 + min(max(entry_count, 1), 8) * 10
        self.logical_height = y + 48

    def logical_span(self) -> float:
        if not self.logical_positions:
            return 0.0
        return self.logical_positions[-1] - self.logical_positions[0]

    def viewport_span(self) -> float:
        return max(0.0, self.height() - 48)

    def visible_offset(self) -> float:
        overflow = max(0.0, self.logical_span() - self.viewport_span())
        return overflow * self.scroll_ratio

    def update_overflow_flags(self) -> None:
        offset = self.visible_offset()
        self.has_more_before = offset > 1
        self.has_more_after = self.logical_span() - offset > self.viewport_span() + 1

    def logical_dot_y(self, index: int) -> float:
        if not 0 <= index < len(self.logical_positions):
            return self.height() / 2
        return self.logical_positions[index]

    def dot_y(self, index: int) -> float:
        visible_span = min(self.logical_span(), self.viewport_span())
        top = self.height() / 2 - visible_span / 2
        return top + self.logical_dot_y(index) - self.visible_offset()

    def visible_indices(self) -> list[int]:
        top = 18
        bottom = self.height() - 18
        return [index for index in range(self.count) if top <= self.dot_y(index) <= bottom]

    def draw_overflow_dots(self, painter: QPainter, bottom: bool) -> None:
        x = self.width() / 2
        color = QColor("#87cfff")
        if bottom:
            ys = [self.height() - 38, self.height() - 28, self.height() - 20]
            radii = [3.0, 2.3, 1.6]
        else:
            ys = [20, 28, 38]
            radii = [1.6, 2.3, 3.0]
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(color))
        for y, radius in zip(ys, radii):
            painter.drawEllipse(QPointF(x, y), radius, radius)

    def marker_date(self, index: int) -> str:
        if not 0 <= index < self.count:
            return ""
        return str(self.markers[index].get("date", ""))

    def index_at_y(self, y: float) -> int:
        if self.count <= 0:
            return -1
        nearest = min(range(self.count), key=lambda index: abs(self.dot_y(index) - y))
        return nearest if abs(self.dot_y(nearest) - y) <= 12 else -1

    def show_marker_date(self, index: int, global_pos, duration_ms: int) -> None:
        date_text = self.marker_date(index)
        if not date_text:
            return
        self.date_hint.show_date(date_text, global_pos, duration_ms)

    def show_hover_marker_date(self) -> None:
        if self.hover_index >= 0:
            self.show_marker_date(self.hover_index, self.hover_global_pos, 0)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        x = self.width() / 2
        blue = QColor("#5bbcff")
        pale_blue = QColor("#d9efff")
        if self.count:
            visible = self.visible_indices()
            painter.setPen(QPen(pale_blue, 3))
            if visible:
                start_y = self.dot_y(visible[0])
                end_y = self.dot_y(visible[-1])
                if self.has_more_before:
                    start_y = 18
                if self.has_more_after:
                    end_y = self.height() - 18
                painter.drawLine(QPointF(x, max(18, start_y)), QPointF(x, min(self.height() - 18, end_y)))
            elif self.has_more_before or self.has_more_after:
                painter.drawLine(QPointF(x, 18), QPointF(x, self.height() - 18))
        for index in self.visible_indices():
            y = self.dot_y(index)
            active = index == self.active_index
            painter.setBrush(QBrush(QColor("#1a73e8") if active else blue))
            painter.setPen(QPen(QColor("#ffffff"), 2))
            radius = 6 if active else 5
            painter.drawEllipse(QPointF(x, y), radius, radius)
        if self.has_more_before:
            self.draw_overflow_dots(painter, bottom=False)
        if self.has_more_after:
            self.draw_overflow_dots(painter, bottom=True)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if self.count <= 0:
            return
        y = event.position().y()
        nearest = self.index_at_y(y)
        if nearest < 0:
            return
        self.show_marker_date(nearest, event.globalPosition().toPoint(), 1000)
        self.jump_requested.emit(self.marker_card_index(nearest))
        self.set_active_index(nearest)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        index = self.index_at_y(event.position().y())
        self.hover_global_pos = event.globalPosition().toPoint()
        if index != self.hover_index:
            self.hover_index = index
            self.hover_delay_timer.stop()
            if index >= 0:
                self.date_hint.fade_out()
                self.hover_delay_timer.start()
            else:
                self.date_hint.fade_out()
        elif index >= 0:
            if self.date_hint.isVisible() and self.date_hint.windowOpacity() > 0:
                self.date_hint.move(self.date_hint.clamped_position(self.hover_global_pos))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self.hover_index = -1
        self.hover_delay_timer.stop()
        self.date_hint.fade_out()
        super().leaveEvent(event)


class TimelinePage(QWidget):
    entry_selected = Signal(int)
    entry_view_requested = Signal(int)
    entry_edit_requested = Signal(int)
    entry_delete_requested = Signal(int)
    entry_add_requested = Signal()

    def __init__(self, repo: JournalRepository):
        super().__init__()
        self.repo = repo
        self.date_filter_active = False
        self.cards: list[EntryCard] = []
        self.rail_marker_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 24, 26)
        layout.setSpacing(18)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("艺术练习时间线")
        title.setObjectName("pageTitle")
        subtitle = QLabel("记录每一次练习的时间、思考和作品素材。")
        subtitle.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        add_btn = QPushButton("新增记录")
        add_btn.setObjectName("primaryButton")
        add_btn.clicked.connect(self.entry_add_requested.emit)
        header.addWidget(add_btn)
        layout.addLayout(header)

        filters = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索标题、文字或标签")
        self.search_edit.textChanged.connect(self.refresh)
        self.type_filter = QComboBox()
        self.type_filter.currentTextChanged.connect(self.refresh)
        self.tag_filter = QComboBox()
        self.tag_filter.currentTextChanged.connect(self.refresh)
        self.date_filter = QDateEdit()
        self.date_filter.setDisplayFormat("yyyy-MM-dd")
        configure_date_edit(self.date_filter)
        self.date_filter.setDate(QDate.currentDate())
        self.date_filter.dateChanged.connect(self.apply_date_filter)
        self.date_filter.calendarWidget().clicked.connect(self.apply_date_filter)
        clear_btn = QPushButton("清除筛选")
        clear_btn.setObjectName("secondaryButton")
        clear_btn.clicked.connect(self.clear_filters)
        filters.addWidget(self.search_edit, 2)
        filters.addWidget(self.type_filter, 1)
        filters.addWidget(self.tag_filter, 1)
        filters.addWidget(self.date_filter, 1)
        filters.addWidget(clear_btn)
        layout.addLayout(filters)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        self.scroll = SmoothScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setObjectName("plainScroll")
        self.scroll.verticalScrollBar().valueChanged.connect(self.update_rail_active_dot)
        self.scroll.verticalScrollBar().rangeChanged.connect(lambda *_args: self.update_rail_active_dot())
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 10, 0)
        self.list_layout.setSpacing(12)
        self.scroll.setWidget(self.list_host)
        body.addWidget(self.scroll, 1)
        self.timeline_rail = TimelineRail()
        self.timeline_rail.jump_requested.connect(self.jump_to_entry)
        body.addWidget(self.timeline_rail)
        layout.addLayout(body, 1)
        self.refresh_type_filter()
        self.refresh_tag_filter()
        self.set_date_filter_inactive()
        self.refresh()

    def clear_filters(self) -> None:
        self.search_edit.clear()
        self.type_filter.setCurrentText("全部")
        self.tag_filter.setCurrentText("全部标签")
        self.set_date_filter_inactive()
        self.refresh()

    def set_date_filter_inactive(self) -> None:
        self.date_filter_active = False
        self.date_filter.blockSignals(True)
        self.date_filter.setDate(QDate.currentDate())
        self.date_filter.blockSignals(False)
        self.date_filter.lineEdit().setText("不限日期")

    def apply_date_filter(self, *_args) -> None:
        self.date_filter_active = True
        self.refresh()

    def refresh_type_filter(self) -> None:
        current = self.type_filter.currentText() or "全部"
        self.type_filter.blockSignals(True)
        self.type_filter.clear()
        self.type_filter.addItem("全部")
        for item in self.repo.list_types():
            self.type_filter.addItem(item)
        self.type_filter.setCurrentText(current if current in [self.type_filter.itemText(i) for i in range(self.type_filter.count())] else "全部")
        self.type_filter.blockSignals(False)

    def refresh_tag_filter(self) -> None:
        current = self.tag_filter.currentText() or "全部标签"
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem("全部标签")
        for item in self.repo.list_tags():
            self.tag_filter.addItem(item)
        values = [self.tag_filter.itemText(i) for i in range(self.tag_filter.count())]
        self.tag_filter.setCurrentText(current if current in values else "全部标签")
        self.tag_filter.blockSignals(False)

    def refresh(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.cards = []

        date_text = qdate_to_text(self.date_filter.date()) if self.date_filter_active else ""
        entries = self.repo.list_entries(
            search=self.search_edit.text(),
            practice_type=self.type_filter.currentText(),
            date_text=date_text,
            tag_filter=self.tag_filter.currentText(),
        )
        if not entries:
            empty = QLabel("还没有匹配的练习记录。点击“新增记录”开始。")
            empty.setObjectName("emptyState")
            empty.setAlignment(Qt.AlignCenter)
            self.list_layout.addWidget(empty, 1)
            self.timeline_rail.set_count(0)
            return

        rail_markers: list[dict[str, int | str]] = []
        for index, entry in enumerate(entries):
            count = len(self.repo.list_attachments(entry.id))
            card = EntryCard(entry, count)
            card.selected.connect(self.entry_selected.emit)
            card.view_requested.connect(self.entry_view_requested.emit)
            card.edit_requested.connect(self.entry_edit_requested.emit)
            card.delete_requested.connect(self.entry_delete_requested.emit)
            self.list_layout.addWidget(card)
            self.cards.append(card)
            if not rail_markers or rail_markers[-1]["date"] != entry.practice_date:
                rail_markers.append({"date": entry.practice_date, "card_index": index, "entry_count": 1})
            else:
                rail_markers[-1]["entry_count"] = int(rail_markers[-1]["entry_count"]) + 1
        self.list_layout.addItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))
        self.rail_marker_count = len(rail_markers)
        self.timeline_rail.set_markers(rail_markers)
        self.update_rail_active_dot()

    def jump_to_entry(self, index: int) -> None:
        if not 0 <= index < len(self.cards):
            return
        self.scroll.smooth_scroll_to(max(0, self.cards[index].y()))

    def update_rail_active_dot(self) -> None:
        if not self.cards:
            self.timeline_rail.set_active_index(0)
            self.timeline_rail.set_scroll_ratio(0)
            return
        bar = self.scroll.verticalScrollBar()
        ratio = 0 if bar.maximum() <= 0 else bar.value() / bar.maximum()
        self.timeline_rail.set_scroll_ratio(ratio)
        value = self.scroll.verticalScrollBar().value()
        marker_indices = range(self.timeline_rail.count)
        nearest = min(
            marker_indices,
            key=lambda index: abs(self.cards[self.timeline_rail.marker_card_index(index)].y() - value),
        )
        self.timeline_rail.set_active_index(nearest)


class DetailPanel(QFrame):
    edit_requested = Signal(int)
    attachments_changed = Signal(int)

    def __init__(self, repo: JournalRepository):
        super().__init__()
        self.repo = repo
        self.current_entry_id: int | None = None
        self.setObjectName("detailPanel")
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        self.scroll = SmoothScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setObjectName("detailScroll")
        self.content = QWidget()
        self.content.setObjectName("detailContent")
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(22, 26, 22, 26)
        self.layout.setSpacing(14)
        self.scroll.setWidget(self.content)
        outer_layout.addWidget(self.scroll, 1)
        self.render_empty()

    def clear(self) -> None:
        clear_layout(self.layout)

    def render_empty(self) -> None:
        self.clear()
        title = QLabel("记录详情")
        title.setObjectName("panelTitle")
        hint = QLabel("从时间线中选择一条记录，查看完整文字和附件。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        self.layout.addWidget(title)
        self.layout.addWidget(hint)
        self.layout.addStretch(1)

    def render_entry(self, entry_id: int) -> None:
        entry = self.repo.get_entry(entry_id)
        if not entry:
            self.render_empty()
            return
        self.current_entry_id = entry_id
        attachments = self.repo.list_attachments(entry_id)
        self.clear()

        title = QLabel(entry.title)
        title.setObjectName("panelTitle")
        title.setWordWrap(True)
        self.layout.addWidget(title)

        meta = QLabel(
            f"{entry.practice_type} · {entry.practice_date}\n{entry.start_time}-{entry.end_time} · {minutes_label(entry.duration_minutes)}"
        )
        meta.setObjectName("muted")
        meta.setWordWrap(True)
        self.layout.addWidget(meta)

        segments = entry_time_segments(self.repo, entry)
        segment_title = QLabel("时间段")
        segment_title.setObjectName("sectionTitle")
        self.layout.addWidget(segment_title)
        self.layout.addWidget(segment_dropdown(segments))

        if entry.tags:
            self.layout.addWidget(chip(entry.tags, GOOGLE_GREEN), alignment=Qt.AlignLeft)

        edit_btn = QPushButton("编辑这条记录")
        edit_btn.setObjectName("secondaryButton")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(entry_id))
        self.layout.addWidget(edit_btn, alignment=Qt.AlignLeft)

        note_title = QLabel("文字记录")
        note_title.setObjectName("sectionTitle")
        self.layout.addWidget(note_title)
        note = QLabel(entry.note or "没有填写文字记录。")
        note.setObjectName("bodyText")
        note.setWordWrap(True)
        self.layout.addWidget(note)

        attach_title = QLabel("附件")
        attach_title.setObjectName("sectionTitle")
        self.layout.addWidget(attach_title)
        if not attachments:
            empty = QLabel("暂无附件。")
            empty.setObjectName("muted")
            self.layout.addWidget(empty)
        for index, attachment in enumerate(attachments):
            self.layout.addWidget(self.attachment_widget(attachment, index, len(attachments)))
        self.layout.addStretch(1)

    def attachment_widget(self, attachment, index: int, total: int) -> QWidget:
        frame = QFrame()
        frame.setObjectName("attachmentFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        stored = Path(attachment.stored_path)
        if attachment.kind == "image" and stored.exists():
            pixmap = QPixmap(str(stored))
            if not pixmap.isNull():
                preview = QLabel()
                preview.setAlignment(Qt.AlignCenter)
                preview.setPixmap(pixmap.scaled(260, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                layout.addWidget(preview)

        name = QLabel(attachment.original_name)
        name.setObjectName("bodyText")
        name.setWordWrap(True)
        kind = QLabel(f"{attachment.kind} · {attachment.size // 1024} KB")
        kind.setObjectName("muted")
        open_btn = QPushButton("打开")
        open_btn.setObjectName("textButton")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(stored))))
        rename_btn = QPushButton("重命名")
        rename_btn.setObjectName("textButton")
        rename_btn.clicked.connect(lambda: self.rename_attachment(attachment.id))
        up_btn = QPushButton("上移")
        up_btn.setObjectName("textButton")
        up_btn.setEnabled(index > 0)
        up_btn.clicked.connect(lambda: self.move_attachment(attachment.id, -1))
        down_btn = QPushButton("下移")
        down_btn.setObjectName("textButton")
        down_btn.setEnabled(index < total - 1)
        down_btn.clicked.connect(lambda: self.move_attachment(attachment.id, 1))
        delete_btn = QPushButton("删除")
        delete_btn.setObjectName("dangerTextButton")
        delete_btn.clicked.connect(lambda: self.delete_attachment(attachment.id))
        actions = QHBoxLayout()
        actions.setSpacing(6)
        actions.addWidget(open_btn)
        actions.addWidget(rename_btn)
        actions.addWidget(up_btn)
        actions.addWidget(down_btn)
        actions.addWidget(delete_btn)
        actions.addStretch(1)
        layout.addWidget(name)
        layout.addWidget(kind)
        layout.addLayout(actions)
        return frame

    def rename_attachment(self, attachment_id: int) -> None:
        attachment = self.repo.get_attachment(attachment_id)
        if not attachment:
            return
        new_name, accepted = QInputDialog.getText(
            self,
            "重命名附件",
            "附件名称",
            text=attachment.original_name,
        )
        if not accepted:
            return
        self.repo.rename_attachment(attachment_id, new_name)
        self.refresh_current_entry()

    def delete_attachment(self, attachment_id: int) -> None:
        self.repo.delete_attachment(attachment_id, delete_file=True)
        self.refresh_current_entry()
        if self.current_entry_id is not None:
            self.attachments_changed.emit(self.current_entry_id)

    def move_attachment(self, attachment_id: int, direction: int) -> None:
        if self.current_entry_id is None:
            return
        attachments = self.repo.list_attachments(self.current_entry_id)
        ids = [item.id for item in attachments]
        try:
            index = ids.index(attachment_id)
        except ValueError:
            return
        target = index + direction
        if not 0 <= target < len(ids):
            return
        ids[index], ids[target] = ids[target], ids[index]
        self.repo.set_attachment_order(self.current_entry_id, ids)
        self.refresh_current_entry()

    def refresh_current_entry(self) -> None:
        if self.current_entry_id is not None:
            self.render_entry(self.current_entry_id)


class EntryDetailDialog(QDialog):
    def __init__(self, repo: JournalRepository, entry_id: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.repo = repo
        self.entry_id = entry_id
        self.setWindowTitle("查看记录")
        self.setModal(True)
        self.setWindowFlag(Qt.Window, True)
        self.setMinimumSize(560, 440)
        self.resize(760, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("dialogScroll")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 28, 28, 24)
        content_layout.setSpacing(14)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        entry = repo.get_entry(entry_id)
        if not entry:
            content_layout.addWidget(QLabel("记录不存在或已删除。"))
        else:
            title = QLabel(entry.title)
            title.setObjectName("dialogTitle")
            title.setWordWrap(True)
            content_layout.addWidget(title)
            meta = QLabel(
                f"{entry.practice_type} · {entry.practice_date} · {entry.start_time}-{entry.end_time} · {minutes_label(entry.duration_minutes)}"
            )
            meta.setObjectName("muted")
            meta.setWordWrap(True)
            content_layout.addWidget(meta)
            segments = entry_time_segments(repo, entry)
            segment_title = QLabel("时间段")
            segment_title.setObjectName("sectionTitle")
            content_layout.addWidget(segment_title)
            content_layout.addWidget(segment_dropdown(segments))
            if entry.tags:
                content_layout.addWidget(chip(entry.tags, GOOGLE_GREEN), alignment=Qt.AlignLeft)

            note_title = QLabel("文字记录")
            note_title.setObjectName("sectionTitle")
            content_layout.addWidget(note_title)
            note = QLabel(entry.note or "没有填写文字记录。")
            note.setObjectName("bodyText")
            note.setWordWrap(True)
            content_layout.addWidget(note)

            attachments = repo.list_attachments(entry_id)
            attach_title = QLabel("附件")
            attach_title.setObjectName("sectionTitle")
            content_layout.addWidget(attach_title)
            if not attachments:
                empty = QLabel("暂无附件。")
                empty.setObjectName("muted")
                content_layout.addWidget(empty)
            for attachment in attachments:
                content_layout.addWidget(self.attachment_widget(attachment))
        content_layout.addStretch(1)

        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 14, 20, 14)
        footer_layout.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("primaryButton")
        close_btn.clicked.connect(self.accept)
        footer_layout.addWidget(close_btn)
        layout.addWidget(footer)

    def attachment_widget(self, attachment) -> QWidget:
        frame = QFrame()
        frame.setObjectName("attachmentFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        stored = Path(attachment.stored_path)
        if attachment.kind == "image" and stored.exists():
            pixmap = QPixmap(str(stored))
            if not pixmap.isNull():
                preview = QLabel()
                preview.setAlignment(Qt.AlignCenter)
                preview.setPixmap(pixmap.scaled(520, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                layout.addWidget(preview)
        name = QLabel(attachment.original_name)
        name.setObjectName("bodyText")
        name.setWordWrap(True)
        kind = QLabel(f"{attachment.kind} · {attachment.size // 1024} KB")
        kind.setObjectName("muted")
        open_btn = QPushButton("打开")
        open_btn.setObjectName("secondaryButton")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(stored))))
        layout.addWidget(name)
        layout.addWidget(kind)
        layout.addWidget(open_btn, alignment=Qt.AlignLeft)
        return frame


class DeleteConfirmDialog(QDialog):
    def __init__(self, entry_title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("删除记录")
        self.setModal(True)
        self.setWindowFlag(Qt.Window, True)
        self.setMinimumSize(460, 210)
        self.resize(560, 240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 20)
        layout.setSpacing(14)

        title = QLabel("删除记录")
        title.setObjectName("dialogTitle")
        message = QLabel(f"确认删除“{entry_title}”吗？数据库记录会删除，已复制的附件文件会保留在资料库中。")
        message.setObjectName("bodyText")
        message.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(message)
        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        delete = QPushButton("删除")
        delete.setObjectName("dangerButton")
        delete.clicked.connect(self.accept)
        footer.addWidget(cancel)
        footer.addWidget(delete)
        layout.addLayout(footer)


PRACTICE_TYPE_COLORS = {
    "绘画": "#4285f4",
    "写作": "#34a853",
    "素描": "#fbbc04",
    "摄影": "#ea4335",
    "设计": "#9c27b0",
    "音乐": "#00acc1",
}
FALLBACK_TYPE_COLORS = ["#7e57c2", "#00acc1", "#ff7043", "#26a69a", "#ec407a", "#5c6bc0"]


def practice_type_color(practice_type: str) -> str:
    if practice_type in PRACTICE_TYPE_COLORS:
        return PRACTICE_TYPE_COLORS[practice_type]
    seed = sum(ord(char) for char in practice_type)
    return FALLBACK_TYPE_COLORS[seed % len(FALLBACK_TYPE_COLORS)]


class PracticeCalendarGrid(QWidget):
    date_selected = Signal(QDate)

    def __init__(self, parent_calendar: "PracticeCalendarWidget") -> None:
        super().__init__()
        self.parent_calendar = parent_calendar
        self.hover_date = QDate()
        self.hover_global_pos = QPoint()
        self.date_rects: dict[str, QRectF] = {}
        self.connection_rects: list[QRectF] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(186)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setObjectName("practiceCalendarGrid")
        self.hover_delay_timer = QTimer(self)
        self.hover_delay_timer.setSingleShot(True)
        self.hover_delay_timer.setInterval(450)
        self.hover_delay_timer.timeout.connect(self.show_hover_hint)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        width = max(560, self.width())
        return QSize(width, self.recommended_height(width))

    def recommended_height(self, width: int) -> int:
        first_offset = self.month_start().dayOfWeek() - 1
        row_count = max(5, (first_offset + self.month_days() + 6) // 7)
        column_width = max(1.0, width / 7)
        row_height = min(58.0, max(30.0, column_width * 0.34))
        return int(34 + row_count * row_height + 14)

    def month_start(self) -> QDate:
        return QDate(self.parent_calendar.month_date.year(), self.parent_calendar.month_date.month(), 1)

    def month_days(self) -> int:
        return calendar.monthrange(self.parent_calendar.month_date.year(), self.parent_calendar.month_date.month())[1]

    def date_to_position(self, date: QDate) -> tuple[int, int]:
        first = self.month_start()
        first_offset = first.dayOfWeek() - 1
        index = first_offset + date.day() - 1
        return index // 7, index % 7

    def has_practice(self, date: QDate) -> bool:
        return qdate_to_text(date) in self.parent_calendar.data

    def has_same_week_connection(self, date: QDate) -> bool:
        if not self.has_practice(date):
            return False
        row, _col = self.date_to_position(date)
        for neighbor in [date.addDays(-1), date.addDays(1)]:
            if neighbor.month() != date.month() or not self.has_practice(neighbor):
                continue
            neighbor_row, _neighbor_col = self.date_to_position(neighbor)
            if neighbor_row == row:
                return True
        return False

    def date_at(self, point: QPointF) -> QDate:
        for date_text, rect in self.date_rects.items():
            if rect.contains(point):
                return QDate.fromString(date_text, "yyyy-MM-dd")
        return QDate()

    def show_hover_hint(self) -> None:
        if not self.hover_date.isValid():
            return
        date_text = qdate_to_text(self.hover_date)
        day = self.parent_calendar.data.get(date_text)
        if not day:
            return
        detail = f"{date_text}  {day['duration']}  {day['primary_type']}"
        self.parent_calendar.date_hint.show_date(detail, self.hover_global_pos, 0)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        date = self.date_at(event.position())
        if date.isValid():
            self.date_selected.emit(date)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        date = self.date_at(event.position())
        self.hover_global_pos = event.globalPosition().toPoint()
        if date != self.hover_date:
            self.hover_date = date
            self.hover_delay_timer.stop()
            self.parent_calendar.date_hint.fade_out()
            if date.isValid() and self.has_practice(date):
                self.hover_delay_timer.start()
        elif date.isValid() and self.parent_calendar.date_hint.isVisible():
            self.parent_calendar.date_hint.move(self.parent_calendar.date_hint.clamped_position(self.hover_global_pos))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self.hover_date = QDate()
        self.hover_delay_timer.stop()
        self.parent_calendar.date_hint.fade_out()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        self.date_rects = {}
        self.connection_rects = []

        width = self.width()
        column_width = width / 7
        header_height = 28
        days = ["一", "二", "三", "四", "五", "六", "日"]
        painter.setPen(QColor(MUTED))
        for index, day in enumerate(days):
            rect = QRectF(index * column_width, 0, column_width, header_height)
            painter.drawText(rect, Qt.AlignCenter, day)

        days_in_month = self.month_days()
        first_offset = self.month_start().dayOfWeek() - 1
        row_count = max(5, (first_offset + days_in_month + 6) // 7)
        available_height = max(1.0, self.height() - header_height - 8)
        row_height = available_height / row_count
        top = header_height + max(4.0, (available_height - row_height * row_count) / 2)
        circle_size = min(58.0, max(22.0, row_height - 4), max(22.0, column_width - 16))
        day_font = QFont(painter.font())
        day_font.setPointSize(max(8, min(12, int(circle_size / 4))))
        duration_font = QFont(painter.font())
        duration_font.setPointSize(max(7, min(9, int(circle_size / 5))))

        for day in range(1, days_in_month):
            date = QDate(self.parent_calendar.month_date.year(), self.parent_calendar.month_date.month(), day)
            row, col = self.date_to_position(date)
            date_text = qdate_to_text(date)
            day_data = self.parent_calendar.data.get(date_text)
            next_date = date.addDays(1)
            if day_data and self.has_practice(next_date) and self.date_to_position(next_date)[0] == row:
                center_x = col * column_width + column_width / 2
                center_y = top + row * row_height + row_height / 2
                _next_row, next_col = self.date_to_position(next_date)
                next_center_x = next_col * column_width + column_width / 2
                color = QColor(str(day_data["color"]))
                connector_color = QColor(color)
                connector_color.setAlpha(54)
                rect = QRectF(center_x, center_y - circle_size / 2, next_center_x - center_x, circle_size)
                self.connection_rects.append(rect)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(connector_color))
                painter.drawRoundedRect(rect, circle_size / 2, circle_size / 2)

        for day in range(1, days_in_month + 1):
            date = QDate(self.parent_calendar.month_date.year(), self.parent_calendar.month_date.month(), day)
            row, col = self.date_to_position(date)
            center_x = col * column_width + column_width / 2
            center_y = top + row * row_height + row_height / 2
            date_text = qdate_to_text(date)
            self.date_rects[date_text] = QRectF(col * column_width, top + row * row_height, column_width, row_height)
            circle = QRectF(center_x - circle_size / 2, center_y - circle_size / 2, circle_size, circle_size)
            day_data = self.parent_calendar.data.get(date_text)
            selected = date == self.parent_calendar.selected_date
            today = date == QDate.currentDate()

            if day_data:
                fill = QColor(str(day_data["color"]))
                text_color = QColor("#ffffff")
            elif selected:
                fill = QColor("#87cfff")
                text_color = QColor("#ffffff")
            else:
                fill = QColor("#ffffff")
                text_color = QColor(TEXT)

            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(fill))
            painter.drawEllipse(circle)

            if selected and day_data:
                painter.setPen(QPen(QColor("#87cfff"), 3))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(circle.adjusted(2, 2, -2, -2))
            elif today:
                painter.setPen(QPen(QColor("#c6dafc"), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(circle.adjusted(2, 2, -2, -2))

            painter.setPen(text_color)
            if day_data:
                painter.setFont(day_font)
                if circle_size >= 34:
                    painter.drawText(circle.adjusted(0, 5, 0, -circle_size * 0.45), Qt.AlignCenter, str(day))
                    painter.setFont(duration_font)
                    painter.drawText(circle.adjusted(0, circle_size * 0.40, 0, -4), Qt.AlignCenter, str(day_data["duration"]))
                else:
                    painter.drawText(circle, Qt.AlignCenter, str(day))
            else:
                painter.setFont(day_font)
                painter.drawText(circle, Qt.AlignCenter, str(day))


class PracticeCalendarWidget(QFrame):
    def __init__(self, repo: JournalRepository):
        super().__init__()
        self.repo = repo
        self.month_date = QDate(QDate.currentDate().year(), QDate.currentDate().month(), 1)
        self.selected_date = QDate.currentDate()
        self.data: dict[str, dict[str, object]] = {}
        self.record_months: list[QDate] = []
        self.date_hint = DateHintBubble()
        self.setObjectName("practiceCalendar")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("练习日历")
        title.setObjectName("sectionTitle")
        subtitle = QLabel("彩色日期代表当天有练习，数字为当天总时长。")
        subtitle.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        self.prev_btn = QPushButton("<")
        self.prev_btn.setObjectName("calendarNavButton")
        self.next_btn = QPushButton(">")
        self.next_btn.setObjectName("calendarNavButton")
        self.month_label = QLabel()
        self.month_label.setObjectName("calendarMonthLabel")
        self.month_label.setAlignment(Qt.AlignCenter)
        self.prev_btn.clicked.connect(lambda: self.change_month(-1))
        self.next_btn.clicked.connect(lambda: self.change_month(1))
        header.addWidget(self.prev_btn)
        header.addWidget(self.month_label)
        header.addWidget(self.next_btn)
        layout.addLayout(header)

        self.grid = PracticeCalendarGrid(self)
        self.grid.date_selected.connect(self.select_date)
        layout.addWidget(self.grid)
        self.load_month()

    def refresh_record_months(self) -> None:
        self.record_months = []
        for month_text in self.repo.practice_months():
            month = QDate.fromString(f"{month_text}-01", "yyyy-MM-dd")
            if month.isValid():
                self.record_months.append(month)

    def nearest_record_month(self, offset: int) -> QDate:
        if offset < 0:
            previous = [month for month in self.record_months if month < self.month_date]
            return previous[-1] if previous else QDate()
        if offset > 0:
            following = [month for month in self.record_months if month > self.month_date]
            return following[0] if following else QDate()
        return QDate()

    def update_nav_buttons(self) -> None:
        self.prev_btn.setEnabled(self.nearest_record_month(-1).isValid())
        self.next_btn.setEnabled(self.nearest_record_month(1).isValid())

    def load_month(self) -> None:
        self.refresh_record_months()
        raw = self.repo.calendar_month(self.month_date.year(), self.month_date.month())
        self.data = {}
        for date_text, day in raw.items():
            primary_type = str(day["primary_type"])
            self.data[date_text] = {
                "minutes": int(day["minutes"]),
                "duration": duration_hhmm(int(day["minutes"])),
                "primary_type": primary_type,
                "types": day["types"],
                "color": practice_type_color(primary_type),
            }
        self.month_label.setText(self.month_date.toString("yyyy 年 MM 月"))
        self.update_nav_buttons()
        self.grid.update()

    def change_month(self, offset: int) -> None:
        target_month = self.nearest_record_month(offset)
        if not target_month.isValid():
            self.update_nav_buttons()
            return
        self.month_date = target_month
        self.selected_date = QDate(self.month_date.year(), self.month_date.month(), 1)
        self.load_month()

    def select_date(self, date: QDate) -> None:
        if not date.isValid():
            return
        self.selected_date = date
        if date.month() != self.month_date.month() or date.year() != self.month_date.year():
            self.month_date = QDate(date.year(), date.month(), 1)
            self.load_month()
        else:
            self.grid.update()

    def refresh(self) -> None:
        self.load_month()


class StatsPage(QWidget):
    def __init__(self, repo: JournalRepository):
        super().__init__()
        self.repo = repo
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(30, 26, 30, 26)
        self.layout.setSpacing(18)
        self.refresh()

    def clear(self) -> None:
        clear_layout(self.layout)

    def refresh(self) -> None:
        self.clear()
        stats = self.repo.stats()
        title = QLabel("练习统计")
        title.setObjectName("pageTitle")
        subtitle = QLabel("查看近期投入、总练习量和类型分布。")
        subtitle.setObjectName("muted")
        self.layout.addWidget(title)
        self.layout.addWidget(subtitle)

        week = stats["week"]
        month = stats["month"]
        total = stats["total"]
        self.metric_row_one = QHBoxLayout()
        self.metric_row_one.setSpacing(14)
        self.layout.addLayout(self.metric_row_one)
        self.metric_row_one.addWidget(
            self.metric_card("近 7 天", minutes_label(int(week["minutes"])), f"{week['count']} 次记录", GOOGLE_BLUE),
            1,
        )
        self.metric_row_one.addWidget(
            self.metric_card("本月", minutes_label(int(month["minutes"])), f"{month['count']} 次记录", GOOGLE_GREEN),
            1,
        )
        self.metric_row_one.addWidget(
            self.metric_card("全部", minutes_label(int(total["minutes"])), f"{total['count']} 次记录", GOOGLE_RED),
            1,
        )

        self.metric_row_two = QHBoxLayout()
        self.metric_row_two.setSpacing(14)
        self.layout.addLayout(self.metric_row_two)
        self.metric_row_two.addWidget(
            self.metric_card("连续天数", f"{stats['streak']} 天", "以今天有记录为起点", GOOGLE_YELLOW),
            1,
        )
        self.metric_row_two.addWidget(
            self.metric_card("总天数", f"{stats['total_days']} 天", "有练习记录的日期", "#5bbcff"),
            1,
        )

        self.practice_calendar = PracticeCalendarWidget(self.repo)
        self.layout.addWidget(self.practice_calendar)

        dist_title = QLabel("类型分布")
        dist_title.setObjectName("sectionTitle")
        self.layout.addWidget(dist_title)
        by_type = stats["by_type"]
        if not by_type:
            empty = QLabel("暂无统计数据。")
            empty.setObjectName("emptyState")
            self.layout.addWidget(empty)
        else:
            for row in by_type:
                self.layout.addWidget(
                    self.type_row(str(row["practice_type"]), int(row["minutes"]), int(row["count"]))
                )
        self.layout.addStretch(1)

    def metric_card(self, title: str, value: str, subtitle: str, color: str) -> QFrame:
        card = QFrame()
        card.setObjectName("metricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        top = QLabel(title)
        top.setStyleSheet(f"color: {color}; font-weight: 700;")
        val = QLabel(value)
        val.setObjectName("metricValue")
        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        layout.addWidget(top)
        layout.addWidget(val)
        layout.addWidget(sub)
        return card

    def type_row(self, practice_type: str, minutes: int, count: int) -> QFrame:
        row = QFrame()
        row.setObjectName("attachmentFrame")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 10, 14, 10)
        title = QLabel(practice_type)
        title.setObjectName("bodyText")
        meta = QLabel(f"{minutes_label(minutes)} · {count} 次")
        meta.setObjectName("muted")
        layout.addWidget(title, 1)
        layout.addWidget(meta)
        return row


class SettingsPage(QWidget):
    paths_changed = Signal()

    def __init__(self, repo: JournalRepository):
        super().__init__()
        self.repo = repo
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(18)

        title = QLabel("设置")
        title.setObjectName("pageTitle")
        subtitle = QLabel("资料库保存在本机，附件会复制到应用数据目录。")
        subtitle.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.info = QFrame()
        self.info.setObjectName("entryCard")
        self.info_layout = QVBoxLayout(self.info)
        self.info_layout.setContentsMargins(18, 16, 18, 16)
        self.info_layout.setSpacing(12)
        self.path_labels: dict[str, QLabel] = {}
        self.add_path_row("data_dir", "资料库根目录", "选择目录", self.choose_data_dir)
        self.add_path_row("db_path", "数据库文件", "选择文件", self.choose_db_path)
        self.add_path_row("attachments_dir", "附件目录", "选择目录", self.choose_attachments_dir)
        self.add_path_row("thumbnails_dir", "缩略图目录", "选择目录", self.choose_thumbnails_dir)
        policy = QLabel("保存策略：上传文件会复制进附件目录，原始文件删除后记录仍可访问。")
        policy.setObjectName("bodyText")
        policy.setWordWrap(True)
        self.info_layout.addWidget(policy)
        self.refresh_paths()
        layout.addWidget(self.info)

        export_btn = QPushButton("导出记录为 CSV")
        export_btn.setObjectName("primaryButton")
        export_btn.clicked.connect(self.export_csv)
        layout.addWidget(export_btn, alignment=Qt.AlignLeft)
        layout.addStretch(1)

    def add_path_row(self, key: str, label: str, button_text: str, callback) -> None:
        row = QFrame()
        row.setObjectName("pathRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(10)
        text_box = QVBoxLayout()
        title = QLabel(label)
        title.setObjectName("sectionTitle")
        value = QLabel()
        value.setObjectName("muted")
        value.setWordWrap(True)
        self.path_labels[key] = value
        text_box.addWidget(title)
        text_box.addWidget(value)
        row_layout.addLayout(text_box, 1)
        button = QPushButton(button_text)
        button.setObjectName("secondaryButton")
        button.clicked.connect(callback)
        row_layout.addWidget(button)
        self.info_layout.addWidget(row)

    def refresh_paths(self) -> None:
        self.path_labels["data_dir"].setText(str(self.repo.paths.data_dir))
        self.path_labels["db_path"].setText(str(self.repo.paths.db_path))
        self.path_labels["attachments_dir"].setText(str(self.repo.paths.attachments_dir))
        self.path_labels["thumbnails_dir"].setText(str(self.repo.paths.thumbnails_dir))

    def save_paths(self, paths: AppPaths) -> None:
        save_config(
            {
                "data_dir": str(paths.data_dir),
                "db_path": str(paths.db_path),
                "attachments_dir": str(paths.attachments_dir),
                "thumbnails_dir": str(paths.thumbnails_dir),
            },
            paths.root,
        )
        self.paths_changed.emit()

    def choose_data_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择资料库根目录", str(self.repo.paths.data_dir))
        if not folder:
            return
        data_dir = Path(folder).resolve()
        self.save_paths(
            AppPaths(
                root=self.repo.paths.root,
                data_dir=data_dir,
                db_path=data_dir / "art_journal.db",
                attachments_dir=data_dir / "attachments",
                thumbnails_dir=data_dir / "thumbnails",
            )
        )

    def choose_db_path(self) -> None:
        file, _ = QFileDialog.getSaveFileName(
            self,
            "选择数据库文件",
            str(self.repo.paths.db_path),
            "SQLite 数据库 (*.db);;所有文件 (*.*)",
        )
        if not file:
            return
        self.save_paths(
            AppPaths(
                root=self.repo.paths.root,
                data_dir=self.repo.paths.data_dir,
                db_path=Path(file).resolve(),
                attachments_dir=self.repo.paths.attachments_dir,
                thumbnails_dir=self.repo.paths.thumbnails_dir,
            )
        )

    def choose_attachments_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择附件目录", str(self.repo.paths.attachments_dir))
        if not folder:
            return
        self.save_paths(
            AppPaths(
                root=self.repo.paths.root,
                data_dir=self.repo.paths.data_dir,
                db_path=self.repo.paths.db_path,
                attachments_dir=Path(folder).resolve(),
                thumbnails_dir=self.repo.paths.thumbnails_dir,
            )
        )

    def choose_thumbnails_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择缩略图目录", str(self.repo.paths.thumbnails_dir))
        if not folder:
            return
        self.save_paths(
            AppPaths(
                root=self.repo.paths.root,
                data_dir=self.repo.paths.data_dir,
                db_path=self.repo.paths.db_path,
                attachments_dir=self.repo.paths.attachments_dir,
                thumbnails_dir=Path(folder).resolve(),
            )
        )

    def export_csv(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self,
            "导出 CSV",
            "art_practice_journal.csv",
            "CSV 文件 (*.csv)",
        )
        if not target:
            return
        entries = self.repo.list_entries()
        with open(target, "w", newline="", encoding="utf-8-sig") as fp:
            writer = csv.writer(fp)
            writer.writerow(["标题", "类型", "日期", "开始", "结束", "分钟", "标签", "文字记录", "附件数"])
            for entry in entries:
                writer.writerow(
                    [
                        entry.title,
                        entry.practice_type,
                        entry.practice_date,
                        entry.start_time,
                        entry.end_time,
                        entry.duration_minutes,
                        entry.tags,
                        entry.note,
                        len(self.repo.list_attachments(entry.id)),
                    ]
                )
        QMessageBox.information(self, "导出完成", f"已导出到：\n{target}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.paths = get_app_paths()
        self.repo = JournalRepository(self.paths)
        self.setWindowTitle("Art Practice Journal")
        self.resize(1280, 820)
        self.setMinimumSize(980, 680)

        root = QWidget()
        root.setObjectName("appRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)

        layout.addWidget(self.sidebar())

        self.stack = QStackedWidget()
        self.timeline = TimelinePage(self.repo)
        self.stats_page = StatsPage(self.repo)
        self.stats_scroll = SmoothScrollArea()
        self.stats_scroll.setWidgetResizable(True)
        self.stats_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.stats_scroll.setObjectName("plainScroll")
        self.stats_scroll.setWidget(self.stats_page)
        self.settings_page = SettingsPage(self.repo)
        self.stack.addWidget(self.timeline)
        self.stack.addWidget(self.stats_scroll)
        self.stack.addWidget(self.settings_page)
        self.content_splitter = QSplitter(Qt.Horizontal)
        self.content_splitter.setObjectName("contentSplitter")
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(self.stack)
        self.detail = DetailPanel(self.repo)
        self.content_splitter.addWidget(self.detail)
        self.content_splitter.setStretchFactor(0, 1)
        self.content_splitter.setStretchFactor(1, 0)
        self.content_splitter.setSizes([850, 360])
        layout.addWidget(self.content_splitter, 1)

        self.timeline.entry_selected.connect(self.detail.render_entry)
        self.timeline.entry_view_requested.connect(self.view_entry)
        self.timeline.entry_edit_requested.connect(self.edit_entry)
        self.timeline.entry_delete_requested.connect(self.delete_entry)
        self.timeline.entry_add_requested.connect(self.add_entry)
        self.detail.edit_requested.connect(self.edit_entry)
        self.detail.attachments_changed.connect(lambda _entry_id: self.refresh_all(self.detail.current_entry_id))
        self.settings_page.paths_changed.connect(self.reload_repository)

    def sidebar(self) -> QFrame:
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(230)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(20, 24, 20, 24)
        layout.setSpacing(12)

        logo = QLabel('<span style="color:#4285f4;">A</span><span style="color:#ea4335;">r</span><span style="color:#fbbc04;">t</span> Journal')
        logo.setObjectName("logo")
        layout.addWidget(logo)

        self.timeline_btn = self.nav_button("时间线", 0)
        self.stats_btn = self.nav_button("统计", 1)
        self.settings_btn = self.nav_button("设置", 2)
        layout.addWidget(self.timeline_btn)
        layout.addWidget(self.stats_btn)
        layout.addWidget(self.settings_btn)
        self.timeline_btn.setChecked(True)
        layout.addStretch(1)

        add_btn = QPushButton("新增记录")
        add_btn.setObjectName("primaryButton")
        add_btn.clicked.connect(self.add_entry)
        layout.addWidget(add_btn)
        return side

    def nav_button(self, text: str, index: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("navButton")
        btn.setCheckable(True)
        btn.clicked.connect(lambda: self.show_page(index))
        return btn

    def show_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate([self.timeline_btn, self.stats_btn, self.settings_btn]):
            btn.setChecked(i == index)
        self.detail.setVisible(index == 0)
        if index == 1:
            self.stats_page.refresh()

    def add_entry(self) -> None:
        dialog = EntryDialog(self.repo, parent=self)
        self.prepare_dialog(dialog)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        entry_id = self.repo.create_entry(
            str(values["title"]),
            str(values["practice_type"]),
            str(values["practice_date"]),
            str(values["start_time"]),
            str(values["end_time"]),
            int(values["duration_minutes"]),
            str(values["note"]),
            str(values["tags"]),
            values["time_segments"],
        )
        files = values["files"]
        if files:
            self.repo.add_attachments(entry_id, files, str(values["practice_date"]))
        self.refresh_all(entry_id)

    def edit_entry(self, entry_id: int) -> None:
        entry = self.repo.get_entry(entry_id)
        if not entry:
            return
        dialog = EntryDialog(self.repo, entry=entry, parent=self)
        self.prepare_dialog(dialog)
        if dialog.exec() != QDialog.Accepted:
            return
        values = dialog.values()
        self.repo.update_entry(
            entry_id,
            str(values["title"]),
            str(values["practice_type"]),
            str(values["practice_date"]),
            str(values["start_time"]),
            str(values["end_time"]),
            int(values["duration_minutes"]),
            str(values["note"]),
            str(values["tags"]),
            values["time_segments"],
        )
        files = values["files"]
        if files:
            self.repo.add_attachments(entry_id, files, str(values["practice_date"]))
        self.refresh_all(entry_id)

    def view_entry(self, entry_id: int) -> None:
        self.detail.render_entry(entry_id)
        dialog = EntryDetailDialog(self.repo, entry_id, parent=self)
        self.prepare_dialog(dialog)
        dialog.exec()

    def delete_entry(self, entry_id: int) -> None:
        entry = self.repo.get_entry(entry_id)
        if not entry:
            return
        dialog = DeleteConfirmDialog(entry.title, parent=self)
        self.prepare_dialog(dialog)
        if dialog.exec() != QDialog.Accepted:
            return
        self.repo.delete_entry(entry_id)
        self.refresh_all()
        self.detail.render_empty()

    def prepare_dialog(self, dialog: QDialog) -> None:
        available_height = max(520, self.height() - 80)
        dialog.resize(min(dialog.width(), self.width() - 100), min(dialog.height(), available_height))
        dialog.move(self.frameGeometry().center() - dialog.rect().center())

    def reload_repository(self) -> None:
        self.paths = get_app_paths()
        self.repo = JournalRepository(self.paths)
        self.timeline.repo = self.repo
        self.stats_page.repo = self.repo
        self.settings_page.repo = self.repo
        self.detail.repo = self.repo
        self.settings_page.refresh_paths()
        self.refresh_all()
        self.detail.render_empty()

    def refresh_all(self, selected_entry_id: int | None = None) -> None:
        self.timeline.refresh_type_filter()
        self.timeline.refresh_tag_filter()
        self.timeline.refresh()
        self.stats_page.refresh()
        if selected_entry_id:
            self.detail.render_entry(selected_entry_id)


def apply_style(app: QApplication) -> None:
    app.setStyleSheet(
        f"""
        QWidget {{
            color: {TEXT};
            font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", Arial, sans-serif;
            font-size: 14px;
        }}
        #appRoot {{
            background: {APP_BG};
        }}
        QDialog {{
            background: {SURFACE};
        }}
        #sidebar {{
            background: {SURFACE};
            border-right: 1px solid {BORDER};
        }}
        #logo {{
            font-size: 24px;
            font-weight: 800;
            padding-bottom: 16px;
        }}
        #pageTitle {{
            font-size: 30px;
            font-weight: 750;
            letter-spacing: 0px;
        }}
        #dialogTitle {{
            font-size: 24px;
            font-weight: 750;
        }}
        #panelTitle {{
            font-size: 22px;
            font-weight: 750;
        }}
        #sectionTitle {{
            font-size: 15px;
            font-weight: 700;
            padding-top: 8px;
        }}
        #muted {{
            color: {MUTED};
        }}
        #bodyText {{
            color: {TEXT};
            line-height: 1.4;
        }}
        QLineEdit, QTextEdit, QComboBox, QDateEdit, QTimeEdit, QListWidget {{
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 8px;
            padding: 9px 11px;
            selection-background-color: {GOOGLE_BLUE};
        }}
        QTextEdit {{
            padding: 11px;
        }}
        QPushButton {{
            border-radius: 8px;
            padding: 9px 14px;
            font-weight: 650;
            border: 1px solid transparent;
        }}
        #primaryButton {{
            background: {GOOGLE_BLUE};
            color: white;
        }}
        #primaryButton:hover {{
            background: #1765cc;
        }}
        #secondaryButton {{
            background: {SURFACE};
            color: {GOOGLE_BLUE};
            border: 1px solid {BORDER};
        }}
        #secondaryButton:hover {{
            background: #f1f6ff;
        }}
        #textButton {{
            background: transparent;
            color: {GOOGLE_BLUE};
            padding: 6px 8px;
        }}
        #dangerTextButton {{
            background: transparent;
            color: {GOOGLE_RED};
            padding: 6px 8px;
        }}
        #dangerButton {{
            background: {GOOGLE_RED};
            color: white;
        }}
        #dangerButton:hover {{
            background: #c5221f;
        }}
        #navButton {{
            background: transparent;
            text-align: left;
            padding: 11px 14px;
            color: {MUTED};
        }}
        #navButton:checked {{
            background: #e8f0fe;
            color: {GOOGLE_BLUE};
        }}
        #navButton:hover {{
            background: #f1f3f4;
        }}
        #entryCard, #metricCard {{
            background: {SURFACE};
            border: 1px solid #e6e8eb;
            border-radius: 8px;
        }}
        #entryCard:hover {{
            border: 1px solid #c6dafc;
            background: #ffffff;
        }}
        #cardTitle {{
            font-size: 18px;
            font-weight: 750;
        }}
        #metricValue {{
            font-size: 26px;
            font-weight: 800;
        }}
        #practiceCalendar {{
            background: {SURFACE};
            border: 1px solid #e6e8eb;
            border-radius: 8px;
        }}
        #practiceCalendarGrid {{
            background: {SURFACE};
        }}
        #calendarMonthLabel {{
            color: {TEXT};
            font-size: 16px;
            font-weight: 750;
            min-width: 116px;
        }}
        #calendarNavButton {{
            background: {SURFACE};
            color: {GOOGLE_BLUE};
            border: 1px solid {BORDER};
            border-radius: 8px;
            min-width: 34px;
            max-width: 34px;
            padding: 8px 0px;
        }}
        #calendarNavButton:hover {{
            background: #f1f6ff;
            border: 1px solid #c6dafc;
        }}
        #calendarNavButton:disabled {{
            background: #f8fafd;
            color: #b8c7dc;
            border: 1px solid #eef1f5;
        }}
        #detailPanel {{
            background: {SURFACE};
            border-left: 1px solid {BORDER};
        }}
        #contentSplitter::handle {{
            background: #e6e8eb;
            width: 4px;
        }}
        #contentSplitter::handle:hover {{
            background: #c6dafc;
        }}
        #detailScroll {{
            border: none;
            background: {SURFACE};
        }}
        #detailContent {{
            background: {SURFACE};
        }}
        #attachmentFrame, #dropBox {{
            background: #fbfcff;
            border: 1px solid {BORDER};
            border-radius: 8px;
        }}
        #dialogFooter {{
            background: {SURFACE};
            border-top: 1px solid {BORDER};
        }}
        #dialogScroll {{
            border: none;
            background: {SURFACE};
        }}
        #dialogScroll > QWidget > QWidget {{
            background: {SURFACE};
        }}
        #pathRow {{
            background: transparent;
        }}
        #segmentPanel {{
            background: transparent;
        }}
        #segmentSummary, #segmentRow {{
            background: #fbfcff;
            border: 1px solid {BORDER};
            border-radius: 8px;
        }}
        #segmentToggleButton {{
            background: {SURFACE};
            color: {GOOGLE_BLUE};
            border: 1px solid {BORDER};
            padding: 6px 10px;
        }}
        #segmentToggleButton:hover {{
            background: #f1f6ff;
        }}
        #segmentTimeEdit {{
            min-width: 76px;
            max-width: 92px;
            padding: 6px 8px;
        }}
        #segmentDeleteButton {{
            background: {SURFACE};
            color: {GOOGLE_RED};
            border: 1px solid {BORDER};
            border-radius: 8px;
            padding: 0px;
            font-weight: 800;
        }}
        #segmentDeleteButton:hover {{
            background: #fce8e6;
            border: 1px solid #f4b7b1;
        }}
        #emptyState {{
            color: {MUTED};
            background: {SURFACE};
            border: 1px dashed {BORDER};
            border-radius: 8px;
            padding: 32px;
        }}
        #plainScroll {{
            border: none;
            background: transparent;
        }}
        #dateHintBubble {{
            background: transparent;
            border: none;
        }}
        #dateHintText {{
            color: #3c4043;
            font-size: 12px;
            font-weight: 650;
            letter-spacing: 0px;
        }}
        QScrollArea > QWidget > QWidget {{
            background: transparent;
        }}
        QCalendarWidget QWidget {{
            background: {SURFACE};
            color: {TEXT};
            alternate-background-color: #f8fafd;
        }}
        QCalendarWidget QToolButton {{
            background: {SURFACE};
            color: {TEXT};
            border: none;
            border-radius: 8px;
            padding: 8px 10px;
            font-weight: 650;
        }}
        QCalendarWidget QToolButton:hover {{
            background: #eef6ff;
        }}
        QCalendarWidget QMenu {{
            background: {SURFACE};
            color: {TEXT};
            border: 1px solid {BORDER};
        }}
        QCalendarWidget QSpinBox {{
            background: {SURFACE};
            color: {TEXT};
            border: 1px solid {BORDER};
            border-radius: 8px;
            padding: 6px 8px;
        }}
        QCalendarWidget QAbstractItemView {{
            background: {SURFACE};
            color: {TEXT};
            selection-background-color: #e8f0fe;
            selection-color: {GOOGLE_BLUE};
            border: 1px solid #eef0f3;
            border-radius: 10px;
            gridline-color: transparent;
            outline: 0;
        }}
        QCalendarWidget QAbstractItemView::item {{
            border-radius: 16px;
            padding: 6px;
        }}
        QCalendarWidget QAbstractItemView::item:hover {{
            background: #eef6ff;
            color: {GOOGLE_BLUE};
        }}
        QCalendarWidget QHeaderView::section {{
            background: #f8fafd;
            color: {MUTED};
            border: none;
            padding: 8px;
            font-weight: 650;
        }}
        """
    )


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Art Practice Journal")
    apply_style(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
