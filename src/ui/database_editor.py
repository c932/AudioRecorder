from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, 
                             QTableWidgetItem, QPushButton, QHeaderView, QMessageBox, 
                             QLineEdit, QLabel, QComboBox, QCheckBox)
from PyQt6.QtCore import Qt
from src.core.exercise_manager import ExerciseManager

class DatabaseEditor(QDialog):
    def __init__(self, parent=None, manager=None):
        super().__init__(parent)
        self.setWindowTitle("Database Editor (题库编辑器)")
        self.resize(900, 600)
        
        if manager:
            self.manager = manager
        else:
            # Fallback (should typically not happen in main flow)
            self.manager = ExerciseManager("src/data/words.json")
            
        self.all_items = []
        self.filtered_items = []
        
        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Filter Bar
        filter_layout = QHBoxLayout()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Search word or translation...")
        self.txt_search.textChanged.connect(self.apply_filter)
        
        self.combo_group = QComboBox()
        self.combo_group.addItem("All Groups")
        self.combo_group.currentIndexChanged.connect(self.apply_filter)
        
        filter_layout.addWidget(QLabel("Search:"))
        filter_layout.addWidget(self.txt_search)
        filter_layout.addWidget(QLabel("Group:"))
        filter_layout.addWidget(self.combo_group)
        layout.addLayout(filter_layout)
        
        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Group", "Word", "Phonetic", "Translation"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch) # Word stretch
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch) # Trans stretch
        self.table.itemChanged.connect(self.on_item_changed)
        layout.addWidget(self.table)
        
        # Actions
        btn_box = QHBoxLayout()
        
        btn_delete = QPushButton("Delete Selected (删除选中)")
        btn_delete.setStyleSheet("color: red;")
        btn_delete.clicked.connect(self.delete_selected)
        
        btn_clean = QPushButton("Smart Clean (智能清理)")
        btn_clean.setStyleSheet("color: #1976D2;")
        btn_clean.setToolTip("Apply cleaning rules to selected or visible items")
        btn_clean.clicked.connect(self.batch_clean_data)

        self.btn_save = QPushButton("Save Changes (保存修改)")
        self.btn_save.setEnabled(False) # Enable on edit
        self.btn_save.clicked.connect(self.save_changes)
        
        btn_box.addWidget(btn_delete)
        btn_box.addWidget(btn_clean)
        btn_box.addStretch()
        btn_box.addWidget(self.btn_save)
        
        layout.addLayout(btn_box)
        
    def load_data(self):
        groups = self.manager.get_groups()
        self.combo_group.clear()
        self.combo_group.addItem("All Groups")
        self.combo_group.addItems(groups)
        
        self.all_items = []
        # Flatten data
        words = self.manager.exercises.get("words", [])
        sentences = self.manager.exercises.get("sentences", [])
        self.all_items = words + sentences
        
        # Tag them with original reference for updates? 
        # Actually modifying the list dicts directly is fine as long as we keep references.
        # But we need to know which list they came from if we wanted to support adding.
        # For now, just editing existing objects.
        
        self.apply_filter()
        
    def apply_filter(self):
        search_text = self.txt_search.text().lower()
        filter_group = self.combo_group.currentText()
        
        self.filtered_items = []
        for item in self.all_items:
            # Group Filter
            group = item.get('group', 'Default')
            if filter_group != "All Groups" and group != filter_group:
                continue
                
            # Search Filter
            if search_text:
                if (search_text not in item.get('text', '').lower() and 
                    search_text not in item.get('translation', '').lower()):
                    continue
            
            self.filtered_items.append(item)
            
        self.populate_table()
        
    def populate_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.filtered_items))
        
        for row, item in enumerate(self.filtered_items):
            # Group (0)
            self.table.setItem(row, 0, QTableWidgetItem(item.get("group", "Default")))
            # Word (1)
            self.table.setItem(row, 1, QTableWidgetItem(item.get("text", "")))
            # Phonetic (2)
            self.table.setItem(row, 2, QTableWidgetItem(item.get("phonetic", "")))
            # Translation (3)
            self.table.setItem(row, 3, QTableWidgetItem(item.get("translation", "")))
            
            # Store item ref
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, item)
            
        self.table.blockSignals(False)
        
    def on_item_changed(self, item):
        self.btn_save.setEnabled(True)
        self.btn_save.setText("Save Changes *")
        
        # Update object DIRECTLY from list (UserRole often returns a copy in PyQt6!)
        row = item.row()
        if row >= len(self.filtered_items):
            return # Safety check
            
        data_item = self.filtered_items[row]
        # print(f"[DEBUG] Mutating item ID: {id(data_item)}") # Debug print
        
        col = item.column()
        val = item.text().strip()
        
        if col == 0: data_item['group'] = val
        elif col == 1: data_item['text'] = val
        elif col == 2: data_item['phonetic'] = val
        elif col == 3: data_item['translation'] = val
        
    def delete_selected(self):
        # Must sort reverse to keep indices valid during deletion from list
        rows = sorted(set(index.row() for index in self.table.selectedIndexes()), reverse=True)
        if not rows:
            return
            
        confirm = QMessageBox.question(self, "Delete", f"Delete {len(rows)} items?", 
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
            
        for row in rows:
            if row < len(self.filtered_items):
                data_item = self.filtered_items[row]
                
                # Brute force remove from manager lists
                # Remove by IDENTITY to be safe
                for lst_name in ["words", "sentences"]:
                    lst = self.manager.exercises.get(lst_name, [])
                    # Find index by identity
                    tgt_idx = -1
                    for i, x in enumerate(lst):
                        if x is data_item:
                            tgt_idx = i
                            break
                    if tgt_idx >= 0:
                        lst.pop(tgt_idx)
                        
                # Remove from local all_items
                if data_item in self.all_items:
                    self.all_items.remove(data_item)
                    
        self.apply_filter()
        self.btn_save.setEnabled(True)
        self.btn_save.setText("Save Changes *")
    
    def batch_clean_data(self):
        """Applies regex cleaning to filtered items (or selected items if any)."""
        import re
        
        # Determine scope: Selected rows OR Visible rows?
        # Let's go with: If Selection > 0, clean selection. Else clean ALL Visible.
        target_rows = sorted(set(index.row() for index in self.table.selectedIndexes()))
        is_selection = True
        if not target_rows:
            target_rows = range(self.table.rowCount())
            is_selection = False
            
        if not target_rows:
            return

        scope_str = "SELECTED" if is_selection else "VISIBLE"
        confirm = QMessageBox.question(self, "Smart Clean", 
                                       f"Run cleaning rules on {len(target_rows)} {scope_str} items?\n\n"
                                       "This will:\n"
                                       "- Strip trailing numbers from words\n"
                                       "- Remove leaked text (e.g. '4 hear...') from translation\n"
                                       "- Fix fused tags like 'entryn.'",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if confirm != QMessageBox.StandardButton.Yes:
            return
            
        count_changed = 0
        for row in target_rows:
            if row < len(self.filtered_items):
                data_item = self.filtered_items[row]
            else:
                continue
                
            changed = False
            
            # 1. Clean Word: Remove trailing numbers
            # e.g. "break 15" -> "break"
            old_text = data_item.get('text', '')
            new_text = re.sub(r'\s+\d+$', '', old_text).strip()
            
            # 1.1 Fix fused POS in Word: "entryn." -> "entry"
            fused_match = re.search(r'([a-zA-Z]{2,})((?:n|v|adj|adv|prep|conj|pron|num|art|vi|vt)\.?)$', new_text)
            if fused_match:
                new_text = fused_match.group(1)
            
            if new_text != old_text:
                data_item['text'] = new_text
                changed = True
                
            # 2. Clean Translation: Remove leaked next-line content
            # e.g. "冒险, 奇遇 4 hear from..." -> "冒险, 奇遇"
            old_trans = data_item.get('translation', '')
            new_trans = old_trans
            
            # Rule A: Remove " 12 word..." at end
            clean_match = re.search(r'\s+\d+\s+[a-zA-Z].*$', new_trans)
            if clean_match:
                new_trans = new_trans[:clean_match.start()].strip()
            
            # Rule B: Remove leading POS if stuck: "n.冒险" -> "冒险"
            # (Only if Chinese follows immediately or space)
            new_trans = re.sub(r'^(n|v|adj|adv|prep|conj)\.\s*', '', new_trans).strip()
            
            if new_trans != old_trans:
                data_item['translation'] = new_trans
                changed = True
                
            if changed:
                count_changed += 1
                
        if count_changed > 0:
            QMessageBox.information(self, "Done", f"Cleaned {count_changed} items!")
            self.populate_table() # Refresh UI
            self.btn_save.setEnabled(True)
            self.btn_save.setText("Save Changes *")
        else:
            QMessageBox.information(self, "Done", "No items needed cleaning.")

    def save_changes(self):
        self.manager.save_data()
        self.btn_save.setEnabled(False)
        self.btn_save.setText("Save Changes (保存修改)")
        QMessageBox.information(self, "Saved", "Database updated successfully.")
