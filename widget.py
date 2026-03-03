from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QScrollArea, QFrame, QComboBox, QSizeGrip, QProgressBar)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QPixmap
import sqlite3
from datetime import datetime
import webbrowser
import sys
import os

class CollectionThread(QThread):
    progress_update = pyqtSignal(str, int, int)  # source, count, completed_count
    finished = pyqtSignal(int)  # total count
    
    def run(self):
        from database import init_db, load_config
        from collectors.arxiv_collector import collect_arxiv
        from collectors.hackernews_collector import collect_hackernews
        from collectors.rss_collector import collect_rss
        from collectors.reddit_collector import collect_reddit
        from collectors.twitter_collector import collect_twitter
        from collectors.anthropic_scraper import collect_anthropic
        
        config = load_config()
        session = init_db(config['database']['path'])
        
        collectors = [
            ("arXiv", collect_arxiv),
            ("HackerNews", collect_hackernews),
            ("RSS", collect_rss),
            ("Twitter", collect_twitter),
            ("Reddit", collect_reddit),
            ("Anthropic", collect_anthropic)
        ]
        
        total = 0
        for idx, (name, collector) in enumerate(collectors, 1):
            try:
                count = collector(session, config)
                total += count
                self.progress_update.emit(name, count, idx)
            except Exception as e:
                self.progress_update.emit(name, 0, idx)
        
        self.finished.emit(total)

class ArticleCard(QFrame):
    def __init__(self, title, source, date, url, is_new=False):
        super().__init__()
        self.url = url
        self.setStyleSheet("""
            QFrame {
                background: transparent;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            }
            QFrame:hover {
                background-color: rgba(255, 255, 255, 0.05);
            }
        """)
        self.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(3)
        layout.setContentsMargins(16, 12, 16, 12)
        
        title_text = f"✨ {title}" if is_new else title
        title_label = QLabel(title_text[:90] + "..." if len(title_text) > 90 else title_text)
        title_label.setWordWrap(True)
        title_label.setFont(QFont("SF Pro", 15))
        title_label.setStyleSheet("color: #ffffff; border: none;")
        layout.addWidget(title_label)
        
        meta = QLabel(f"{source} · {date}")
        meta.setFont(QFont("SF Pro", 13))
        meta.setStyleSheet("color: rgba(255, 255, 255, 0.5); border: none;")
        layout.addWidget(meta)
        
    def mousePressEvent(self, event):
        webbrowser.open(self.url)

class NewsWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Inference News")
        self.setGeometry(100, 100, 450, 600)
        self.setMinimumSize(350, 400)
        self.setMaximumSize(600, 900)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Set window icon
        icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        container = QFrame(self)
        container.setGeometry(0, 0, self.width(), self.height())
        container.setObjectName("container")
        container.setStyleSheet("""
            #container {
                background-color: rgba(28, 28, 30, 0.95);
                border-radius: 20px;
            }
        """)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        header = QFrame()
        header.setStyleSheet("background: transparent;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 20, 20, 16)
        header_layout.setSpacing(8)
        
        top_row = QHBoxLayout()
        title = QLabel("⚡ Inference News")
        title.setFont(QFont("SF Pro", 20, QFont.Bold))
        title.setStyleSheet("color: #39FF14;")
        top_row.addWidget(title)
        top_row.addStretch()
        
        sync_btn = QPushButton("↻")
        sync_btn.setFixedSize(28, 28)
        sync_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 14px;
                color: rgba(255, 255, 255, 0.6);
                font-size: 18px;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(57, 255, 20, 0.3);
                color: #39FF14;
            }
        """)
        sync_btn.clicked.connect(self.sync_articles)
        top_row.addWidget(sync_btn)
        
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 14px;
                color: rgba(255, 255, 255, 0.6);
                font-size: 14px;
                border: none;
            }
            QPushButton:hover {
                background-color: rgba(255, 59, 48, 0.3);
                color: #ff3b30;
            }
        """)
        close_btn.clicked.connect(self.close)
        top_row.addWidget(close_btn)
        header_layout.addLayout(top_row)
        
        filter_row = QHBoxLayout()
        self.source_filter = QComboBox()
        self.source_filter.setFixedHeight(36)
        self.source_filter.setMinimumWidth(250)
        self.source_filter.view().setMinimumWidth(300)
        self.source_filter.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.source_filter.view().setStyleSheet("""
            QListView {
                background-color: rgba(28, 28, 30, 0.98);
                border: none;
                border-radius: 8px;
                outline: none;
                padding: 6px;
                font-size: 16px;
            }
            QListView::item {
                background-color: transparent;
                color: #ffffff;
                padding: 8px 12px;
                border: none;
                border-radius: 6px;
            }
            QListView::item:hover {
                background-color: rgba(255, 255, 255, 0.08);
            }
            QListView::item:selected {
                background-color: rgba(255, 255, 255, 0.12);
            }
        """)
        self.source_filter.setStyleSheet("""
            QComboBox {
                background-color: rgba(255, 255, 255, 0.08);
                border: none;
                border-radius: 8px;
                padding-left: 14px;
                padding-right: 14px;
                color: #ffffff;
                font-size: 16px;
            }
            QComboBox:hover {
                background-color: rgba(255, 255, 255, 0.12);
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: right;
                width: 0px;
                border: none;
            }
        """)
        self.source_filter.currentTextChanged.connect(self.load_articles)
        filter_row.addWidget(self.source_filter)
        
        self.stats_label = QLabel()
        self.stats_label.setFont(QFont("SF Pro", 11))
        self.stats_label.setStyleSheet("color: rgba(255, 255, 255, 0.5);")
        filter_row.addWidget(self.stats_label)
        filter_row.addStretch()
        header_layout.addLayout(filter_row)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: rgba(255, 255, 255, 0.1);
                border: none;
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background-color: #39FF14;
                border-radius: 2px;
            }
        """)
        self.progress_bar.hide()
        header_layout.addWidget(self.progress_bar)
        
        self.progress_label = QLabel()
        self.progress_label.setFont(QFont("SF Pro", 11))
        self.progress_label.setStyleSheet("color: rgba(255, 255, 255, 0.6); padding: 4px 20px;")
        self.progress_label.hide()
        header_layout.addWidget(self.progress_label)
        
        layout.addWidget(header)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                background: transparent; 
                border: none;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 4px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.3);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self.scroll_layout = QVBoxLayout(scroll_content)
        self.scroll_layout.setSpacing(0)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        # Add resize grip
        size_grip = QSizeGrip(container)
        size_grip.setStyleSheet("QSizeGrip { width: 16px; height: 16px; }")
        grip_layout = QHBoxLayout()
        grip_layout.addStretch()
        grip_layout.addWidget(size_grip)
        layout.addLayout(grip_layout)
        
        self.load_sources()
        self.load_articles()
        
        timer = QTimer(self)
        timer.timeout.connect(self.load_articles)
        timer.start(7200000)  # 2 hours
    
    def load_sources(self):
        from database import init_db, load_config
        config = load_config()
        init_db(config['database']['path'])
        
        conn = sqlite3.connect('articles.db')
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT source FROM articles ORDER BY source")
        sources = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        self.source_filter.addItem("all")
        for source in sources:
            self.source_filter.addItem(source)
    
    def sync_articles(self):
        sender = self.sender()
        sender.setEnabled(False)
        sender.setText("...")
        
        self.progress_bar.show()
        self.progress_bar.setValue(0)
        self.progress_label.show()
        self.progress_label.setText("Starting...")
        
        self.collection_thread = CollectionThread()
        self.collection_thread.progress_update.connect(self.update_progress)
        self.collection_thread.finished.connect(lambda total: self.collection_finished(sender, total))
        self.collection_thread.start()
    
    def update_progress(self, source, count, completed):
        progress = int((completed / 6) * 100)
        self.progress_bar.setValue(progress)
        self.progress_label.setText(f"{source}: {count} new")
    
    def collection_finished(self, button, total):
        self.progress_label.setText(f"Done! {total} new articles")
        QTimer.singleShot(2000, lambda: self.progress_bar.hide())
        QTimer.singleShot(2000, lambda: self.progress_label.hide())
        button.setEnabled(True)
        button.setText("↻")
        
        self.source_filter.clear()
        self.load_sources()
        self.load_articles()
        
    def load_articles(self):
        while self.scroll_layout.count():
            child = self.scroll_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        conn = sqlite3.connect('articles.db')
        cursor = conn.cursor()
        
        # Clean old articles (older than 6 months)
        cursor.execute("DELETE FROM articles WHERE published_date < datetime('now', '-180 days')")
        conn.commit()
        
        source_filter = self.source_filter.currentText()
        
        if source_filter == "all":
            cursor.execute("SELECT COUNT(*) FROM articles WHERE published_date >= datetime('now', '-180 days')")
            count = cursor.fetchone()[0]
            self.stats_label.setText(f"{count} articles")
            
            cursor.execute("""
                SELECT title, source, url, published_date 
                FROM articles 
                WHERE published_date >= datetime('now', '-180 days')
                ORDER BY published_date DESC 
                LIMIT 10
            """)
        else:
            cursor.execute("SELECT COUNT(*) FROM articles WHERE source = ? AND published_date >= datetime('now', '-180 days')", (source_filter,))
            count = cursor.fetchone()[0]
            self.stats_label.setText(f"{count} articles")
            
            cursor.execute("""
                SELECT title, source, url, published_date 
                FROM articles 
                WHERE source = ? AND published_date >= datetime('now', '-180 days')
                ORDER BY published_date DESC 
                LIMIT 10
            """, (source_filter,))
        
        articles = cursor.fetchall()
        conn.close()
        
        now = datetime.now()
        for title, source, url, date in articles:
            date_obj = datetime.fromisoformat(date) if date else now
            date_str = date_obj.strftime("%b %d")
            is_new = (now - date_obj).days == 0  # Only today's articles
            card = ArticleCard(title, source, date_str, url, is_new)
            self.scroll_layout.addWidget(card)
        
        self.scroll_layout.addStretch()
    
    def mousePressEvent(self, event):
        self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
        event.accept()
    
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Update container size when widget is resized
        container = self.findChild(QFrame, "container")
        if container:
            container.setGeometry(0, 0, self.width(), self.height())

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    icon_path = os.path.join(os.path.dirname(__file__), 'icon_rounded.png')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    widget = NewsWidget()
    widget.show()
    sys.exit(app.exec_())
