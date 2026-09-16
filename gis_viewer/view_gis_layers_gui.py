import sys
import json
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QFileDialog, QTextEdit,
                             QSplitter, QLabel, QTableWidget, QTableWidgetItem,
                             QToolBar, QAction, QStatusBar, QFrame, QMenu,
                             QTreeWidget, QTreeWidgetItem, QCheckBox, QColorDialog)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import Qt, QUrl, QSize, QSettings
from PyQt5.QtGui import QIcon, QFont
import folium
from folium import plugins
import geopandas as gpd
from shapely.geometry import shape
import tempfile
import os
from datetime import datetime

# Custom Modern Style
MODERN_STYLE = """
QMainWindow {
    background-color: #f5f5f5;
}

QToolBar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #ffffff, stop:1 #e8e8e8);
    border: none;
    border-bottom: 1px solid #d0d0d0;
    spacing: 8px;
    padding: 8px;
}

QPushButton {
    background-color: #4CAF50;
    color: white;
    border: none;
    padding: 10px 20px;
    text-align: center;
    font-size: 13px;
    font-weight: bold;
    border-radius: 6px;
    min-width: 120px;
}

QPushButton:hover {
    background-color: #45a049;
}

QPushButton:pressed {
    background-color: #3d8b40;
}

QPushButton#secondaryBtn {
    background-color: #2196F3;
}

QPushButton#secondaryBtn:hover {
    background-color: #0b7dda;
}

QLabel#headerLabel {
    font-size: 14px;
    font-weight: bold;
    color: #333333;
    padding: 8px;
    background-color: #ffffff;
    border-radius: 4px;
}

QLabel#infoLabel {
    font-size: 12px;
    color: #666666;
    padding: 5px 10px;
    background-color: #e3f2fd;
    border-radius: 4px;
    border-left: 3px solid #2196F3;
}

QTableWidget {
    background-color: white;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    gridline-color: #f0f0f0;
    font-size: 12px;
}

QTableWidget::item {
    padding: 5px;
}

QTableWidget::item:selected {
    background-color: #e3f2fd;
    color: #1976d2;
}

QHeaderView::section {
    background-color: #f5f5f5;
    padding: 8px;
    border: none;
    border-bottom: 2px solid #2196F3;
    font-weight: bold;
    color: #333333;
}

QTextEdit {
    background-color: white;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 8px;
    font-size: 12px;
    font-family: 'Consolas', 'Courier New', monospace;
}

QFrame#sidePanel {
    background-color: white;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
}

QTreeWidget {
    background-color: white;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    font-size: 12px;
}

QTreeWidget::item {
    padding: 5px;
    border-bottom: 1px solid #f0f0f0;
}

QTreeWidget::item:selected {
    background-color: #e3f2fd;
    color: #1976d2;
}

QTreeWidget::item:hover {
    background-color: #f5f5f5;
}

QTreeWidget::branch:has-children:closed {
    image: url(none);
}

QTreeWidget::branch:has-children:open {
    image: url(none);
}

QStatusBar {
    background-color: #2c3e50;
    color: white;
    font-size: 11px;
}

QSplitter::handle {
    background-color: #d0d0d0;
}

QSplitter::handle:horizontal {
    width: 2px;
}

QSplitter::handle:vertical {
    height: 2px;
}
"""

class GISViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.gdf = None
        self.temp_html = None
        self.settings = QSettings('GISViewerPro', 'GISViewer')
        self.recent_files = self.load_recent_files()
        self.layers = []  # List to store multiple layers
        self.active_layer_idx = None
        self.initUI()
        
    def initUI(self):
        self.setWindowTitle('GIS Viewer Pro - Desktop Mapping Application')
        self.setGeometry(100, 100, 1600, 900)
        
        # Apply custom style
        self.setStyleSheet(MODERN_STYLE)
        
        # Create toolbar
        self.create_toolbar()
        
        # Create status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage('Ready')
        
        # Add permanent widget to status bar for file info
        self.status_file_label = QLabel('No file loaded')
        self.status_file_label.setStyleSheet('''
            QLabel {
                padding: 3px 10px;
                background-color: #e3f2fd;
                border-radius: 3px;
                border-left: 3px solid #2196F3;
                font-size: 11px;
                color: #666666;
            }
        ''')
        self.statusBar.addPermanentWidget(self.status_file_label)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 0, 5, 5)
        main_layout.setSpacing(0)
        
        # Main splitter - 3 panels (removed info bar)
        main_splitter = QSplitter(Qt.Horizontal)
        
        # LEFT PANEL: Table of Contents (TOC)
        toc_panel = QFrame()
        toc_panel.setObjectName('sidePanel')
        toc_panel.setMinimumWidth(250)
        toc_panel.setMaximumWidth(400)
        toc_layout = QVBoxLayout(toc_panel)
        toc_layout.setContentsMargins(10, 10, 10, 10)
        toc_layout.setSpacing(10)
        
        # TOC Header
        toc_header_layout = QHBoxLayout()
        toc_header = QLabel('📚 Table of Contents')
        toc_header.setObjectName('headerLabel')
        toc_header_layout.addWidget(toc_header)
        
        # Add layer button (small)
        add_layer_btn = QPushButton('+')
        add_layer_btn.setMaximumWidth(30)
        add_layer_btn.setToolTip('Add new layer')
        add_layer_btn.clicked.connect(self.load_file)
        toc_header_layout.addWidget(add_layer_btn)
        
        toc_layout.addLayout(toc_header_layout)
        
        # TOC Tree Widget
        self.toc_tree = QTreeWidget()
        self.toc_tree.setHeaderLabels(['Layers'])
        self.toc_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.toc_tree.customContextMenuRequested.connect(self.show_layer_context_menu)
        self.toc_tree.itemClicked.connect(self.on_layer_clicked)
        self.toc_tree.itemChanged.connect(self.on_layer_visibility_changed)
        toc_layout.addWidget(self.toc_tree)
        
        # Layer count label
        self.layer_count_label = QLabel('No layers loaded')
        self.layer_count_label.setStyleSheet('font-size: 10px; color: #888;')
        toc_layout.addWidget(self.layer_count_label)
        
        main_splitter.addWidget(toc_panel)
        
        # MIDDLE PANEL: Map view
        map_container = QFrame()
        map_container.setStyleSheet("""
            QFrame {
                background-color: white;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
            }
        """)
        map_layout = QVBoxLayout(map_container)
        map_layout.setContentsMargins(0, 0, 0, 0)
        
        self.map_view = QWebEngineView()
        map_layout.addWidget(self.map_view)
        
        main_splitter.addWidget(map_container)
        
        # RIGHT PANEL: Attribute panel (existing)
        side_panel = QFrame()
        side_panel.setObjectName('sidePanel')
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(15, 15, 15, 15)
        side_layout.setSpacing(15)
        
        # Header
        attr_header = QLabel('📊 Feature Information')
        attr_header.setObjectName('headerLabel')
        side_layout.addWidget(attr_header)
        
        # Attribute table
        table_label = QLabel('Attributes:')
        table_label.setStyleSheet('font-weight: bold; color: #555; font-size: 11px;')
        side_layout.addWidget(table_label)
        
        self.attr_table = QTableWidget()
        self.attr_table.setColumnCount(2)
        self.attr_table.setHorizontalHeaderLabels(['Property', 'Value'])
        self.attr_table.horizontalHeader().setStretchLastSection(True)
        self.attr_table.setAlternatingRowColors(True)
        side_layout.addWidget(self.attr_table)
        
        # Statistics
        stats_header = QLabel('📈 Layer Statistics')
        stats_header.setObjectName('headerLabel')
        side_layout.addWidget(stats_header)
        
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setMaximumHeight(180)
        side_layout.addWidget(self.stats_text)
        
        main_splitter.addWidget(side_panel)
        main_splitter.setSizes([300, 800, 500])
        
        main_layout.addWidget(main_splitter)
        
        # Load initial empty map
        self.load_initial_map()
        
    def create_toolbar(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(toolbar)
        
        # Load file button with dropdown menu
        load_btn = QPushButton('📂 Open File')
        load_btn.clicked.connect(self.load_file)
        
        # Create recent files menu
        self.recent_menu = QMenu(self)
        self.update_recent_files_menu()
        
        load_btn.setMenu(self.recent_menu)
        toolbar.addWidget(load_btn)
        
        # Recent files action (separate button)
        recent_action = QAction('📋 Recent Files', self)
        recent_action.setMenu(self.recent_menu)
        toolbar.addAction(recent_action)
        
        toolbar.addSeparator()
        
        # Clear history button
        clear_action = QAction('🗑️ Clear History', self)
        clear_action.triggered.connect(self.clear_recent_files)
        clear_action.setStatusTip('Clear recent files history')
        toolbar.addAction(clear_action)
        
        toolbar.addSeparator()
        
        # Zoom buttons
        zoom_in_action = QAction('🔍+ Zoom In', self)
        zoom_in_action.setStatusTip('Zoom in to map')
        toolbar.addAction(zoom_in_action)
        
        zoom_out_action = QAction('🔍- Zoom Out', self)
        zoom_out_action.setStatusTip('Zoom out from map')
        toolbar.addAction(zoom_out_action)
        
        toolbar.addSeparator()
        
        # Info button
        info_action = QAction('ℹ️ About', self)
        info_action.triggered.connect(self.show_about)
        toolbar.addAction(info_action)
        
        # Style toolbar actions
        for action in toolbar.actions():
            widget = toolbar.widgetForAction(action)
            if widget and isinstance(widget, QPushButton):
                widget.setStyleSheet("""
                    QPushButton {
                        background-color: transparent;
                        border: 1px solid #d0d0d0;
                        padding: 6px 12px;
                        border-radius: 4px;
                    }
                    QPushButton:hover {
                        background-color: #e8e8e8;
                    }
                """)
        
    def show_about(self):
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.about(self, 'About GIS Viewer Pro',
                         '<h3>GIS Viewer Pro</h3>'
                         '<p>A modern desktop GIS application for viewing and analyzing spatial data.</p>'
                         '<p><b>Features:</b></p>'
                         '<ul>'
                         '<li>Support for Shapefile, GeoJSON, and File Geodatabase</li>'
                         '<li>Interactive map with multiple basemaps</li>'
                         '<li>Feature inspection and attribute viewing</li>'
                         '<li>Automatic area and length calculation</li>'
                         '<li>Measurement tools</li>'
                         '</ul>'
                         '<p><b>Version:</b> 2.0</p>')
        
    def load_initial_map(self):
        m = folium.Map(
            location=[0.5071, 101.4478],
            zoom_start=13,
            tiles='OpenStreetMap'
        )
        
        self.temp_html = tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='w')
        m.save(self.temp_html.name)
        self.temp_html.close()
        
        self.map_view.setUrl(QUrl.fromLocalFile(self.temp_html.name))
        
    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Shapefile, GeoJSON, or Geodatabase",
            "",
            "GIS Files (*.shp *.geojson *.json *.gdb);;Shapefile (*.shp);;GeoJSON (*.geojson *.json);;File Geodatabase (*.gdb);;All Files (*.*)"
        )
        
        if file_path:
            try:
                self.statusBar.showMessage('Loading file...')
                
                # Check if it's a geodatabase
                if file_path.endswith('.gdb'):
                    import fiona
                    layers = fiona.listlayers(file_path)
                    
                    if not layers:
                        self.info_label.setText('❌ No layers found in geodatabase')
                        self.statusBar.showMessage('Error: No layers found')
                        return
                    
                    if len(layers) == 1:
                        layer = layers[0]
                    else:
                        from PyQt5.QtWidgets import QInputDialog
                        layer, ok = QInputDialog.getItem(
                            self, 
                            "Select Layer",
                            "Choose layer to load:",
                            layers,
                            0,
                            False
                        )
                        if not ok:
                            self.statusBar.showMessage('Cancelled')
                            return
                    
                    self.gdf = gpd.read_file(file_path, layer=layer)
                else:
                    self.gdf = gpd.read_file(file_path)
                
                # Convert to WGS84 if needed
                if self.gdf.crs and self.gdf.crs != 'EPSG:4326':
                    self.gdf = self.gdf.to_crs('EPSG:4326')
                
                # Add layer to layers list
                layer_info = {
                    'name': os.path.basename(file_path),
                    'path': file_path,
                    'gdf': self.gdf,
                    'visible': True,
                    'color': self.get_random_color(),
                    'opacity': 0.5
                }
                self.layers.append(layer_info)
                self.active_layer_idx = len(self.layers) - 1
                
                # Update TOC
                self.update_toc()
                
                # Update info in status bar
                file_name = os.path.basename(file_path)
                self.status_file_label.setText(f'✅ {file_name} | {len(self.gdf)} features | {self.gdf.geom_type.unique()[0]}')
                self.statusBar.showMessage(f'Successfully loaded {len(self.gdf)} features')
                
                # Add to recent files
                self.add_to_recent_files(file_path)
                
                # Create map
                self.create_map()
                
                # Show statistics
                self.show_statistics()
                
            except Exception as e:
                self.status_file_label.setText(f'❌ Error: {str(e)[:50]}...')
                self.statusBar.showMessage('Error loading file')
    
    def update_toc(self):
        """Update Table of Contents tree"""
        self.toc_tree.clear()
        
        if not self.layers:
            self.layer_count_label.setText('No layers loaded')
            return
        
        visible_count = sum(1 for l in self.layers if l['visible'])
        self.layer_count_label.setText(f'{len(self.layers)} layer(s) loaded | {visible_count} visible')
        
        for idx, layer in enumerate(self.layers):
            item = QTreeWidgetItem(self.toc_tree)
            
            # Set checkbox state
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if layer['visible'] else Qt.Unchecked)
            item.setData(0, Qt.UserRole, idx)  # Store layer index
            
            # Icon based on geometry type
            geom_type = layer['gdf'].geom_type.unique()[0]
            if geom_type in ['Polygon', 'MultiPolygon']:
                icon = '🟦'
            elif geom_type in ['LineString', 'MultiLineString']:
                icon = '📏'
            elif geom_type in ['Point', 'MultiPoint']:
                icon = '📍'
            else:
                icon = '📄'
            
            # Color indicator
            color_box = f'[{layer["color"]}]'
            item.setText(0, f'{icon} {layer["name"]}')
            
            # Add feature count and visibility status as child
            info_item = QTreeWidgetItem(item)
            visibility = "👁️ Visible" if layer['visible'] else "👁️‍🗨️ Hidden"
            info_item.setText(0, f'  {len(layer["gdf"])} features | {visibility}')
            info_item.setFlags(info_item.flags() & ~Qt.ItemIsUserCheckable)
            
            # Highlight active layer
            if idx == self.active_layer_idx:
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
                item.setBackground(0, Qt.lightGray)
        
        self.toc_tree.expandAll()
    
    def on_layer_clicked(self, item, column):
        """Handle layer click in TOC"""
        layer_idx = item.data(0, Qt.UserRole)
        if layer_idx is not None:
            self.active_layer_idx = layer_idx
            self.gdf = self.layers[layer_idx]['gdf']
            self.update_toc()
            self.show_statistics()
            self.statusBar.showMessage(f'Active layer: {self.layers[layer_idx]["name"]}')
    
    def on_layer_visibility_changed(self, item, column):
        """Handle layer visibility toggle"""
        layer_idx = item.data(0, Qt.UserRole)
        if layer_idx is not None:
            is_checked = item.checkState(0) == Qt.Checked
            self.layers[layer_idx]['visible'] = is_checked
            
            # Force refresh map with all visible layers
            self.create_map()
            
            status = 'visible' if is_checked else 'hidden'
            self.statusBar.showMessage(f'Layer "{self.layers[layer_idx]["name"]}" is now {status}')
            
            # Update layer count label
            visible_count = sum(1 for l in self.layers if l['visible'])
            self.layer_count_label.setText(f'{len(self.layers)} layer(s) loaded | {visible_count} visible')
    
    def show_layer_context_menu(self, position):
        """Show context menu for layer in TOC"""
        item = self.toc_tree.itemAt(position)
        if item is None:
            return
        
        layer_idx = item.data(0, Qt.UserRole)
        if layer_idx is None:
            return
        
        menu = QMenu(self)
        
        # Zoom to layer
        zoom_action = QAction('🔍 Zoom to Layer', self)
        zoom_action.triggered.connect(lambda: self.zoom_to_layer(layer_idx))
        menu.addAction(zoom_action)
        
        menu.addSeparator()
        
        # Change color
        color_action = QAction('🎨 Change Color', self)
        color_action.triggered.connect(lambda: self.change_layer_color(layer_idx))
        menu.addAction(color_action)
        
        # Change opacity
        opacity_action = QAction('💧 Change Opacity', self)
        opacity_action.triggered.connect(lambda: self.change_layer_opacity(layer_idx))
        menu.addAction(opacity_action)
        
        menu.addSeparator()
        
        # Remove layer
        remove_action = QAction('🗑️ Remove Layer', self)
        remove_action.triggered.connect(lambda: self.remove_layer(layer_idx))
        menu.addAction(remove_action)
        
        # Open attribute table
        attr_action = QAction('📊 Attribute Table', self)
        attr_action.triggered.connect(lambda: self.show_full_attribute_table(layer_idx))
        menu.addAction(attr_action)
        
        menu.exec_(self.toc_tree.viewport().mapToGlobal(position))
    
    def zoom_to_layer(self, layer_idx):
        """Zoom map to layer extent"""
        self.active_layer_idx = layer_idx
        self.gdf = self.layers[layer_idx]['gdf']
        self.create_map()
        self.statusBar.showMessage(f'Zoomed to {self.layers[layer_idx]["name"]}')
    
    def change_layer_color(self, layer_idx):
        """Change layer color"""
        current_color = self.layers[layer_idx]['color']
        color = QColorDialog.getColor(Qt.blue, self, 'Select Layer Color')
        
        if color.isValid():
            self.layers[layer_idx]['color'] = color.name()
            self.create_map()
            self.statusBar.showMessage(f'Color changed for {self.layers[layer_idx]["name"]}')
    
    def change_layer_opacity(self, layer_idx):
        """Change layer opacity"""
        from PyQt5.QtWidgets import QInputDialog
        opacity, ok = QInputDialog.getDouble(
            self,
            'Change Opacity',
            'Enter opacity (0.0 - 1.0):',
            self.layers[layer_idx]['opacity'],
            0.0, 1.0, 2
        )
        
        if ok:
            self.layers[layer_idx]['opacity'] = opacity
            self.create_map()
            self.statusBar.showMessage(f'Opacity changed for {self.layers[layer_idx]["name"]}')
    
    def remove_layer(self, layer_idx):
        """Remove layer from TOC"""
        from PyQt5.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, 'Remove Layer',
            f'Remove layer "{self.layers[layer_idx]["name"]}"?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            removed_name = self.layers[layer_idx]['name']
            self.layers.pop(layer_idx)
            
            # Update active layer
            if self.active_layer_idx == layer_idx:
                self.active_layer_idx = len(self.layers) - 1 if self.layers else None
                self.gdf = self.layers[self.active_layer_idx]['gdf'] if self.layers else None
            elif self.active_layer_idx > layer_idx:
                self.active_layer_idx -= 1
            
            self.update_toc()
            self.create_map()
            self.statusBar.showMessage(f'Removed layer: {removed_name}')
            
            if self.layers:
                self.show_statistics()
            else:
                self.stats_text.clear()
                self.attr_table.setRowCount(0)
    
    def show_full_attribute_table(self, layer_idx):
        """Show full attribute table in a dialog"""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTableWidget, QHeaderView
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f'Attribute Table - {self.layers[layer_idx]["name"]}')
        dialog.setGeometry(200, 200, 800, 600)
        
        layout = QVBoxLayout(dialog)
        
        table = QTableWidget()
        gdf = self.layers[layer_idx]['gdf']
        
        # Set columns
        columns = [col for col in gdf.columns if col != 'geometry']
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setRowCount(len(gdf))
        
        # Fill data
        for row_idx, row in gdf.iterrows():
            for col_idx, col_name in enumerate(columns):
                item = QTableWidgetItem(str(row[col_name]))
                table.setItem(row_idx, col_idx, item)
        
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(True)
        
        layout.addWidget(table)
        dialog.exec_()
    
    def create_map(self):
        """Create map with all visible layers"""
        if not self.layers:
            self.load_initial_map()
            return
        
        # Get bounds from all visible layers
        all_bounds = []
        visible_count = 0
        
        for layer in self.layers:
            if layer['visible'] and len(layer['gdf']) > 0:
                try:
                    bounds = layer['gdf'].total_bounds
                    all_bounds.append(bounds)
                    visible_count += 1
                except:
                    continue
        
        if not all_bounds:
            self.load_initial_map()
            self.statusBar.showMessage('No visible layers')
            return
        
        # Update status
        self.statusBar.showMessage(f'Rendering {visible_count} visible layer(s)...')
        
        # Calculate combined bounds
        min_x = min(b[0] for b in all_bounds)
        min_y = min(b[1] for b in all_bounds)
        max_x = max(b[2] for b in all_bounds)
        max_y = max(b[3] for b in all_bounds)
        
        center = [(min_y + max_y) / 2, (min_x + max_x) / 2]
        
        # Create base map
        m = folium.Map(
            location=center,
            zoom_start=10,
            tiles='OpenStreetMap',
            control_scale=True
        )
        
        # Add alternative base maps (but OpenStreetMap stays default)
        folium.TileLayer('CartoDB dark_matter', name='Dark Map').add_to(m)
        folium.TileLayer('CartoDB positron', name='Light Map').add_to(m)
        # OpenStreetMap is already the default base layer
        
        # Add each visible layer - THIS IS THE KEY PART
        layers_rendered = 0
        for layer_idx, layer in enumerate(self.layers):
            # Skip if not visible
            if not layer['visible']:
                continue
            
            gdf = layer['gdf']
            layer_color = layer['color']
            layer_opacity = layer['opacity']
            layer_name = layer['name']
            
            # Create a feature group for this layer
            feature_group = folium.FeatureGroup(name=layer_name, show=True)
            
            # Convert to GeoJSON
            try:
                geojson_data = json.loads(gdf.to_json())
            except Exception as e:
                print(f"Error converting layer {layer_name} to GeoJSON: {e}")
                continue
            
            # Add each feature to the feature group
            feature_count = 0
            for idx, feature in enumerate(geojson_data['features']):
                try:
                    geom = shape(feature['geometry'])
                    
                    props = feature['properties'].copy() if feature['properties'] else {}
                    
                    # Add calculated measurements
                    if geom.geom_type in ['Polygon', 'MultiPolygon']:
                        area = geom.area * 111320 * 111320
                        perimeter = geom.length * 111320
                        props['Area_m2'] = f"{area:.2f}"
                        props['Perimeter_m'] = f"{perimeter:.2f}"
                    elif geom.geom_type in ['LineString', 'MultiLineString']:
                        length = geom.length * 111320
                        props['Length_m'] = f"{length:.2f}"
                    
                    feature['properties'] = props
                    
                    # Create popup HTML
                    popup_html = f'''
                    <div style="font-family: Arial; font-size: 12px; max-width: 250px;">
                        <b style="color: {layer_color}; font-size: 14px;">{layer_name}</b><br>
                        <i>Feature {idx + 1} of {len(geojson_data['features'])}</i>
                        <hr style="margin: 5px 0; border: none; border-top: 1px solid #ddd;">
                    '''
                    
                    if props:
                        for key, value in list(props.items())[:10]:  # Limit to 10 properties
                            popup_html += f'<b>{key}:</b> {value}<br>'
                        if len(props) > 10:
                            popup_html += f'<i>... and {len(props) - 10} more properties</i><br>'
                    else:
                        popup_html += '<i>No properties</i><br>'
                    
                    popup_html += '</div>'
                    
                    # Style for this feature
                    feature_style = {
                        'fillColor': layer_color,
                        'color': '#000000',
                        'weight': 1.5,
                        'fillOpacity': layer_opacity,
                        'opacity': 0.8
                    }
                    
                    highlight_style = {
                        'fillColor': '#FFFF00',
                        'color': '#FF0000',
                        'weight': 3,
                        'fillOpacity': 0.7
                    }
                    
                    # Add GeoJson to feature group
                    folium.GeoJson(
                        feature,
                        style_function=lambda x, style=feature_style: style,
                        highlight_function=lambda x, hstyle=highlight_style: hstyle,
                        popup=folium.Popup(popup_html, max_width=300),
                        tooltip=f'{layer_name} - Feature {idx + 1}'
                    ).add_to(feature_group)
                    
                    feature_count += 1
                    
                except Exception as e:
                    print(f"Error adding feature {idx} from layer {layer_name}: {e}")
                    continue
            
            # Add the complete feature group to map
            if feature_count > 0:
                feature_group.add_to(m)
                layers_rendered += 1
                print(f"✓ Added layer '{layer_name}' with {feature_count} features")
            else:
                print(f"✗ Skipped layer '{layer_name}' - no features rendered")
        
        # Add controls
        plugins.Fullscreen(position='topright').add_to(m)
        plugins.MeasureControl(
            position='topleft',
            primary_length_unit='meters',
            primary_area_unit='sqmeters',
            secondary_length_unit='kilometers',
            secondary_area_unit='sqkilometers'
        ).add_to(m)
        
        # Layer control - IMPORTANT: collapsed=False to see all layers
        folium.LayerControl(collapsed=False, position='topright').add_to(m)
        
        # Fit map to combined bounds with padding
        m.fit_bounds([[min_y, min_x], [max_y, max_x]], padding=[30, 30])
        
        # Save and load map
        if self.temp_html:
            try:
                os.unlink(self.temp_html.name)
            except:
                pass
        
        self.temp_html = tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8')
        m.save(self.temp_html.name)
        self.temp_html.close()
        
        self.map_view.setUrl(QUrl.fromLocalFile(self.temp_html.name))
        
        # Update status
        self.statusBar.showMessage(f'Successfully rendered {layers_rendered} layer(s) with total {sum(len(l["gdf"]) for l in self.layers if l["visible"])} features')
        bounds = self.gdf.total_bounds
        center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]
        
        m = folium.Map(
            location=center,
            zoom_start=13,
            tiles='OpenStreetMap'
        )
        
        folium.TileLayer('CartoDB positron', name='Light Map').add_to(m)
        folium.TileLayer('CartoDB dark_matter', name='Dark Map').add_to(m)
        
        def style_function(feature):
            return {
                'fillColor': '#3388ff',
                'color': '#000000',
                'weight': 2,
                'fillOpacity': 0.5
            }
        
        def highlight_function(feature):
            return {
                'fillColor': '#ffff00',
                'color': '#ff0000',
                'weight': 3,
                'fillOpacity': 0.7
            }
        
        geojson_data = json.loads(self.gdf.to_json())
        
        for idx, feature in enumerate(geojson_data['features']):
            geom = shape(feature['geometry'])
            
            props = feature['properties'].copy()
            
            if geom.geom_type in ['Polygon', 'MultiPolygon']:
                props['Area_m2'] = f"{geom.area * 111320 * 111320:.2f}"
                props['Perimeter_m'] = f"{geom.length * 111320:.2f}"
            elif geom.geom_type in ['LineString', 'MultiLineString']:
                props['Length_m'] = f"{geom.length * 111320:.2f}"
            
            feature['properties'] = props
            feature['id'] = idx
            
            popup_html = '<div style="font-family: Arial; font-size: 12px; max-width: 250px;">'
            popup_html += f'<b style="color: #2196F3;">Feature {idx}</b><br><hr style="margin: 5px 0;">'
            for key, value in props.items():
                popup_html += f'<b>{key}:</b> {value}<br>'
            popup_html += '</div>'
            
            folium.GeoJson(
                feature,
                style_function=style_function,
                highlight_function=highlight_function,
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f'Feature {idx} - Click for details'
            ).add_to(m)
        
        plugins.Fullscreen().add_to(m)
        plugins.MeasureControl(
            position='topleft',
            primary_length_unit='meters',
            primary_area_unit='sqmeters'
        ).add_to(m)
        
        folium.LayerControl().add_to(m)
        
        m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
        
        if self.temp_html:
            os.unlink(self.temp_html.name)
        
        self.temp_html = tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='w')
        m.save(self.temp_html.name)
        self.temp_html.close()
        
        self.map_view.setUrl(QUrl.fromLocalFile(self.temp_html.name))
    
    def show_statistics(self):
        if not self.layers or self.active_layer_idx is None:
            return
        
        gdf = self.layers[self.active_layer_idx]['gdf']
        layer_name = self.layers[self.active_layer_idx]['name']
        
        gdf = self.layers[self.active_layer_idx]['gdf']
        layer_name = self.layers[self.active_layer_idx]['name']
        
        stats = f"📁 Layer: {layer_name}\n"
        stats += f"{'='*40}\n"
        stats += f"Total Features: {len(gdf)}\n"
        stats += f"Geometry Type: {gdf.geom_type.unique()[0]}\n"
        stats += f"CRS: {gdf.crs}\n\n"
        
        stats += f"📋 Attributes\n"
        stats += f"{'='*40}\n"
        for col in gdf.columns:
            if col != 'geometry':
                stats += f"  • {col}: {gdf[col].dtype}\n"
        
        if gdf.geom_type.unique()[0] in ['Polygon', 'MultiPolygon']:
            total_area = gdf.geometry.area.sum() * 111320 * 111320
            stats += f"\n📐 Measurements\n"
            stats += f"{'='*40}\n"
            stats += f"Total Area: {total_area:,.2f} m²\n"
            stats += f"Total Area: {total_area/1000000:.2f} km²"
        elif gdf.geom_type.unique()[0] in ['LineString', 'MultiLineString']:
            total_length = gdf.geometry.length.sum() * 111320
            stats += f"\n📐 Measurements\n"
            stats += f"{'='*40}\n"
            stats += f"Total Length: {total_length:,.2f} m\n"
            stats += f"Total Length: {total_length/1000:.2f} km"
        
        self.stats_text.setText(stats)
        
        if len(gdf) > 0:
            self.show_feature_attributes(0)
    
    def show_feature_attributes(self, idx):
        if not self.layers or self.active_layer_idx is None:
            return
        
        gdf = self.layers[self.active_layer_idx]['gdf']
        
        if idx >= len(gdf):
            return
        
        feature = gdf.iloc[idx]
        
        self.attr_table.setRowCount(0)
        
        row = 0
        for col in gdf.columns:
            if col != 'geometry':
                self.attr_table.insertRow(row)
                self.attr_table.setItem(row, 0, QTableWidgetItem(str(col)))
                self.attr_table.setItem(row, 1, QTableWidgetItem(str(feature[col])))
                row += 1
        
        geom = feature.geometry
        self.attr_table.insertRow(row)
        self.attr_table.setItem(row, 0, QTableWidgetItem('Geometry Type'))
        self.attr_table.setItem(row, 1, QTableWidgetItem(geom.geom_type))
        row += 1
        
        if geom.geom_type in ['Polygon', 'MultiPolygon']:
            area = geom.area * 111320 * 111320
            perimeter = geom.length * 111320
            
            self.attr_table.insertRow(row)
            self.attr_table.setItem(row, 0, QTableWidgetItem('Area (m²)'))
            self.attr_table.setItem(row, 1, QTableWidgetItem(f'{area:,.2f}'))
            row += 1
            
            self.attr_table.insertRow(row)
            self.attr_table.setItem(row, 0, QTableWidgetItem('Perimeter (m)'))
            self.attr_table.setItem(row, 1, QTableWidgetItem(f'{perimeter:,.2f}'))
            
        elif geom.geom_type in ['LineString', 'MultiLineString']:
            length = geom.length * 111320
            
            self.attr_table.insertRow(row)
            self.attr_table.setItem(row, 0, QTableWidgetItem('Length (m)'))
            self.attr_table.setItem(row, 1, QTableWidgetItem(f'{length:,.2f}'))
    
    def get_random_color(self):
        """Generate random color for new layers"""
        import random
        colors = [
            '#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', 
            '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E2',
            '#52B788', '#F4A261', '#E76F51', '#2A9D8F'
        ]
        return random.choice(colors)
    
    def load_recent_files(self):
        """Load recent files from settings"""
        recent = self.settings.value('recent_files', [])
        if not isinstance(recent, list):
            recent = []
        return recent
    
    def save_recent_files(self):
        """Save recent files to settings"""
        self.settings.setValue('recent_files', self.recent_files)
    
    def add_to_recent_files(self, file_path):
        """Add file to recent files list"""
        # Normalize path
        file_path = os.path.abspath(file_path)
        
        # Create file entry with metadata
        file_entry = {
            'path': file_path,
            'name': os.path.basename(file_path),
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'size': os.path.getsize(file_path) if os.path.exists(file_path) else 0
        }
        
        # Remove if already exists
        self.recent_files = [f for f in self.recent_files if f.get('path') != file_path]
        
        # Add to beginning
        self.recent_files.insert(0, file_entry)
        
        # Keep only last 10 files
        self.recent_files = self.recent_files[:10]
        
        # Save to settings
        self.save_recent_files()
        
        # Update menu
        self.update_recent_files_menu()
    
    def update_recent_files_menu(self):
        """Update recent files menu"""
        self.recent_menu.clear()
        
        if not self.recent_files:
            action = QAction('(No recent files)', self)
            action.setEnabled(False)
            self.recent_menu.addAction(action)
            return
        
        for i, file_entry in enumerate(self.recent_files):
            file_path = file_entry.get('path', '')
            file_name = file_entry.get('name', os.path.basename(file_path))
            file_date = file_entry.get('date', 'Unknown date')
            
            # Check if file still exists
            exists = os.path.exists(file_path)
            icon = '📁' if exists else '❌'
            
            # Create menu text
            menu_text = f"{icon} {file_name}"
            if not exists:
                menu_text += " (Not found)"
            
            action = QAction(menu_text, self)
            action.setStatusTip(f"{file_path} - Last opened: {file_date}")
            
            if exists:
                action.triggered.connect(lambda checked, path=file_path: self.load_file_direct(path))
            else:
                action.setEnabled(False)
            
            self.recent_menu.addAction(action)
            
            # Add separator after every 5 items
            if (i + 1) % 5 == 0 and i < len(self.recent_files) - 1:
                self.recent_menu.addSeparator()
    
    def load_file_direct(self, file_path):
        """Load file directly from path"""
        if not os.path.exists(file_path):
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'File Not Found', 
                              f'The file could not be found:\n{file_path}\n\n'
                              'It may have been moved or deleted.')
            # Remove from recent files
            self.recent_files = [f for f in self.recent_files if f.get('path') != file_path]
            self.save_recent_files()
            self.update_recent_files_menu()
            return
        
        try:
            self.statusBar.showMessage(f'Loading {os.path.basename(file_path)}...')
            
            # Check if it's a geodatabase
            if file_path.endswith('.gdb'):
                import fiona
                layers = fiona.listlayers(file_path)
                
                if not layers:
                    self.info_label.setText('❌ No layers found in geodatabase')
                    self.statusBar.showMessage('Error: No layers found')
                    return
                
                if len(layers) == 1:
                    layer = layers[0]
                else:
                    from PyQt5.QtWidgets import QInputDialog
                    layer, ok = QInputDialog.getItem(
                        self, 
                        "Select Layer",
                        "Choose layer to load:",
                        layers,
                        0,
                        False
                    )
                    if not ok:
                        self.statusBar.showMessage('Cancelled')
                        return
                
                self.gdf = gpd.read_file(file_path, layer=layer)
            else:
                self.gdf = gpd.read_file(file_path)
            
            # Convert to WGS84 if needed
            if self.gdf.crs and self.gdf.crs != 'EPSG:4326':
                self.gdf = self.gdf.to_crs('EPSG:4326')
            
            # Update info in status bar
            file_name = os.path.basename(file_path)
            self.status_file_label.setText(f'✅ {file_name} | {len(self.gdf)} features | {self.gdf.geom_type.unique()[0]}')
            self.statusBar.showMessage(f'Successfully loaded {len(self.gdf)} features')
            
            # Add to recent files
            self.add_to_recent_files(file_path)
            
            # Add layer to layers list
            layer_info = {
                'name': os.path.basename(file_path),
                'path': file_path,
                'gdf': self.gdf,
                'visible': True,
                'color': self.get_random_color(),
                'opacity': 0.5
            }
            self.layers.append(layer_info)
            self.active_layer_idx = len(self.layers) - 1
            
            # Update TOC
            self.update_toc()
            
            # Create map
            self.create_map()
            
            # Show statistics
            self.show_statistics()
            
        except Exception as e:
            self.status_file_label.setText(f'❌ Error: {str(e)[:50]}...')
            self.statusBar.showMessage('Error loading file')
    
    def clear_recent_files(self):
        """Clear recent files history"""
        from PyQt5.QtWidgets import QMessageBox
        reply = QMessageBox.question(self, 'Clear History',
                                     'Are you sure you want to clear all recent files?',
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.recent_files = []
            self.save_recent_files()
            self.update_recent_files_menu()
            self.statusBar.showMessage('Recent files cleared')
    
    def closeEvent(self, event):
        if self.temp_html:
            try:
                os.unlink(self.temp_html.name)
            except:
                pass
        event.accept()

def main():
    app = QApplication(sys.argv)
    
    # Set application-wide font
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    viewer = GISViewer()
    viewer.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()