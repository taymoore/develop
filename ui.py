import json
import signal
from turtle import pen
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel
import pandas as pd
import numpy as np
import pyperclip
from PySide6.QtCore import Slot, Signal, QSize, QThread, QSemaphore, Qt, QBasicTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QMainWindow,
    QLineEdit,
    QTextEdit,
    QLabel,
    QHeaderView,
    QAbstractItemView,
    QPushButton,
)
from pyqtgraph import PlotWidget, DateAxisItem, AxisItem, PlotCurveItem, ViewBox
from ff14marketcalc import get_profit, print_recipe
from retainerWorker.models import ListingData
from universalis.models import Listings
from worker import Worker
from retainerWorker.retainerWorker import RetainerWorker
from universalis.universalis import get_listings, universalis_mutex
from universalis.universalis import save_to_disk as universalis_save_to_disk
from xivapi.models import Recipe, RecipeCollection
from xivapi.xivapi import (
    get_classjob_doh_list,
    get_recipes,
    search_recipes,
    xivapi_mutex,
)
from xivapi.xivapi import save_to_disk as xivapi_save_to_disk

world_id = 55


class MainWindow(QMainWindow):
    class RecipeListTable(QTableWidget):
        def __init__(self, *args):
            super().__init__(*args)
            self.setColumnCount(5)
            self.setHorizontalHeaderLabels(
                ["Job", "Item", "Profit", "Velocity", "Score"]
            )
            self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.verticalHeader().hide()

            self.setEditTriggers(QAbstractItemView.NoEditTriggers)

            self.recipe_list: List[Recipe] = []

        def clear_contents(self) -> None:
            self.clearContents()
            self.setRowCount(0)
            self.recipe_list.clear()

        def add_recipes(
            self,
            row_data: Optional[List[Tuple[str, str, float, float, Recipe]]] = None,
            recipe_list: List[Recipe] = [],
        ):
            if row_data is None:
                row_data = []
            # TODO: Pass this recipe_list to the worker
            if len(recipe_list) > 0:
                for recipe in recipe_list:
                    row_data.append(
                        (
                            recipe.ClassJob.Abbreviation,
                            recipe.ItemResult.Name,
                            get_profit(recipe, world_id),
                            get_listings(
                                recipe.ItemResult.ID, world_id
                            ).regularSaleVelocity,
                            recipe,
                        )
                    )
                row_data.sort(key=lambda row: row[2] * row[3], reverse=True)
            for row_index, row in enumerate(row_data):
                self.insertRow(self.rowCount())
                self.setItem(row_index, 0, QTableWidgetItem(row[0]))
                self.setItem(row_index, 1, QTableWidgetItem(row[1]))
                self.setItem(row_index, 2, QTableWidgetItem(f"{row[2]:,.0f}"))
                self.setItem(
                    row_index,
                    3,
                    QTableWidgetItem(f"{row[3]:.2f}"),
                )
                self.setItem(row_index, 4, QTableWidgetItem(f"{row[2] * row[3]:,.0f}"))
                self.recipe_list.append(row[4])

        queue_worker_task = Signal()

    class RetainerTable(QTableWidget):
        def __init__(self, parent: QWidget, seller_id: int):
            super().__init__(parent)
            self.setColumnCount(4)
            self.setHorizontalHeaderLabels(
                ["Retainer", "Item", "Listed Price", "Min Price"]
            )
            self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.verticalHeader().hide()
            self.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.seller_id = seller_id
            self.table_data: Dict[
                int, List[List[QTableWidgetItem]]
            ] = {}  # itemID -> row -> column
            self.good_color = QColor(0, 255, 0, 50)
            self.bad_color = QColor(255, 0, 0, 50)

        def clear_contents(self) -> None:
            self.clearContents()
            self.setRowCount(0)
            self.table_data.clear()

        def get_min_price(self, listings: Listings) -> float:
            return min(
                [
                    listing.pricePerUnit
                    for listing in listings.listings
                    if listing.sellerID != self.seller_id
                ]
            )

        @Slot(list)
        def on_listing_data_updated(self, listing_data: ListingData) -> None:
            row_list_index = 0
            row_list = self.table_data.setdefault(listing_data.item.ID, [])
            for listing in listing_data.listings.listings:
                if listing.sellerID == self.seller_id:
                    if row_list_index < len(row_list):
                        row_data = row_list[row_list_index]
                        row_data[2].setText(f"{listing.pricePerUnit:,.0f}")
                        row_data[3].setText(
                            f"{self.get_min_price(listing_data.listings):,.0f}"
                        )
                    else:
                        row_data = [
                            QTableWidgetItem(listing.retainerName),
                            QTableWidgetItem(listing_data.item.Name),
                            QTableWidgetItem(f"{listing.pricePerUnit:,.0f}"),
                            QTableWidgetItem(
                                f"{self.get_min_price(listing_data.listings):,.0f}"
                            ),
                        ]
                        row_count = self.rowCount()
                        self.insertRow(row_count)
                        for column_index, widget in enumerate(row_data):
                            self.setItem(row_count, column_index, widget)
                        row_list.append(row_data)
                    if listing.pricePerUnit <= listing_data.listings.minPrice:
                        color = self.good_color
                    else:
                        color = self.bad_color
                    for table_widget_item in row_data:
                        table_widget_item.setBackground(color)
                    row_list_index += 1

    class PriceGraph(PlotWidget):
        class FmtAxesItem(AxisItem):
            def __init__(
                self,
                orientation,
                pen=None,
                textPen=None,
                linkView=None,
                parent=None,
                maxTickLength=-5,
                showValues=True,
                text="",
                units="",
                unitPrefix="",
                **args,
            ):
                super().__init__(
                    orientation,
                    pen,
                    textPen,
                    linkView,
                    parent,
                    maxTickLength,
                    showValues,
                    text,
                    units,
                    unitPrefix,
                    **args,
                )

            def tickStrings(self, values, scale, spacing):
                return [f"{v:,.0f}" for v in values]

        def __init__(self, parent=None, background="default", plotItem=None, **kargs):
            kargs["axisItems"] = {
                "bottom": DateAxisItem(),
                "left": MainWindow.PriceGraph.FmtAxesItem(orientation="left"),
            }
            super().__init__(parent, background, plotItem, **kargs)

            # self.plotItem.setLabels(left="Price")
            self.plotItem.getAxis("left").setLabel("Price", color="#00ff00")
            self.p2 = ViewBox()
            self.plotItem.showAxis("right")
            self.plotItem.scene().addItem(self.p2)
            self.plotItem.getAxis("right").linkToView(self.p2)
            self.p2.setXLink(self.plotItem)
            self.plotItem.getAxis("right").setLabel("Velocity", color="#00ffff")
            self.p2.setMouseEnabled(y=True)
            self.updateViews()
            self.plotItem.vb.sigResized.connect(self.updateViews)
            self.plotItem.vb.sigRangeChanged.connect(self.updateViews)

        @Slot()
        def updateViews(self) -> None:
            self.p2.setGeometry(self.plotItem.vb.sceneBoundingRect())
            # self.p2.linkedViewChanged(self.plotItem, self.p2.XAxis)

    retainer_listings_changed = Signal(Listings)

    def __init__(self):
        super().__init__()

        self.refreshing_table = True

        self.main_widget = QWidget()
        self.main_layout = QVBoxLayout()
        self.centre_splitter = QSplitter()
        self.left_splitter = QSplitter()
        self.left_splitter.setOrientation(Qt.Orientation.Vertical)
        self.right_splitter = QSplitter()
        self.right_splitter.setOrientation(Qt.Orientation.Vertical)
        self.centre_splitter.addWidget(self.left_splitter)
        self.centre_splitter.addWidget(self.right_splitter)
        self.table_search_layout = QVBoxLayout()
        self.table_search_layout.setContentsMargins(0, 0, 0, 0)
        self.table_search_widget = QWidget()

        self.search_layout = QHBoxLayout()
        self.search_label = QLabel(self)
        self.search_label.setText("Search:")
        self.search_layout.addWidget(self.search_label)
        self.search_qlineedit = QLineEdit(self)
        self.search_qlineedit.returnPressed.connect(self.on_search_return_pressed)
        self.search_layout.addWidget(self.search_qlineedit)
        self.search_refresh_button = QPushButton(self)
        self.search_refresh_button.setText("Refresh")
        self.search_refresh_button.clicked.connect(self.on_refresh_button_clicked)
        self.search_layout.addWidget(self.search_refresh_button)
        self.table_search_layout.addLayout(self.search_layout)

        self.table = MainWindow.RecipeListTable(self)
        self.table.cellDoubleClicked.connect(self.on_table_double_clicked)
        self.table_search_layout.addWidget(self.table)

        self.table_search_widget.setLayout(self.table_search_layout)
        self.left_splitter.addWidget(self.table_search_widget)

        self.recipe_textedit = QTextEdit(self)
        self.left_splitter.addWidget(self.recipe_textedit)

        self.seller_id = (
            "4d9521317c92e33772cd74a166c72b0207ab9edc5eaaed5a1edb52983b70b2c2"
        )

        self.retainer_table = MainWindow.RetainerTable(self, self.seller_id)
        self.retainer_table.cellDoubleClicked.connect(
            self.on_retainer_table_double_clicked
        )
        self.right_splitter.addWidget(self.retainer_table)

        self.price_graph = MainWindow.PriceGraph(self)
        # self.price_graph = MainWindow.PriceGraph()
        self.right_splitter.addWidget(self.price_graph)
        self.right_splitter.setSizes([1, 1])

        self.main_layout.addWidget(self.centre_splitter)
        self.main_widget.setLayout(self.main_layout)
        self.setCentralWidget(self.main_widget)

        self.status_bar_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_bar_label, 1)

        self.setMinimumSize(QSize(1000, 600))

        # classjob_list = get_classjob_doh_list()

        # https://realpython.com/python-pyqt-qthread/
        self.worker_thread = QThread(self)
        self.worker = Worker(
            classjob_level_max_dict={
                8: 70,
                9: 70,
                10: 69,
                11: 78,
                12: 70,
                13: 73,
                14: 70,
                15: 67,
            },
            world=world_id,
            seller_id=self.seller_id,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_queue_recipe_list: List[
            Recipe
        ] = []  # Respective mutex is self.queue_worker_task

        self.worker.status_bar_update_signal.connect(self.status_bar_label.setText)
        self.worker.table_refresh_signal.connect(self.on_worker_update)

        self.retainerworker_thread = QThread()
        self.retainerworker = RetainerWorker(
            seller_id=self.seller_id, world_id=world_id
        )
        self.retainerworker.moveToThread(self.retainerworker_thread)
        # self.retainerworker_thread.started.connect(self.retainerworker.run)
        self.retainerworker_thread.finished.connect(self.retainerworker.deleteLater)

        self.retainer_listings_changed.connect(
            self.retainerworker.on_retainer_listings_changed
        )
        self.worker.retainer_listings_changed.connect(
            self.retainerworker.on_retainer_listings_changed
        )
        self.retainerworker.listing_data_updated.connect(
            self.retainer_table.on_listing_data_updated
        )

        self.worker_thread.start()
        self.retainerworker_thread.start()
        self.load_retainer_worker_cache()

    def load_retainer_worker_cache(self) -> None:
        try:
            listings_list: List[Listings] = [
                Listings.parse_raw(listings)
                for listings in json.load(open(".data/retainer_worker_cache.json", "r"))
            ]
            for listings in listings_list:
                self.retainer_listings_changed.emit(listings)
        except:
            pass

    @Slot()
    def on_search_return_pressed(self):
        self.refreshing_table = False
        xivapi_mutex.lock()
        recipes = search_recipes(self.search_qlineedit.text())
        xivapi_mutex.unlock()
        self.table.clear_contents()
        universalis_mutex.lock()
        self.table.add_recipes(recipe_list=recipes)
        universalis_mutex.unlock()

    @Slot(int, int)
    def on_retainer_table_double_clicked(self, row: int, column: int):
        for row_group_list in self.retainer_table.table_data.values():
            for widget_list in row_group_list:
                if widget_list[0].row() != row:
                    continue
                pyperclip.copy(widget_list[1].text())
                return

    @Slot(int, int)
    def on_table_double_clicked(self, row: int, column: int):
        item_name = self.table.recipe_list[row].ItemResult.Name
        pyperclip.copy(item_name)
        self.status_bar_label.setText(f"Processing {item_name}...")

        universalis_mutex.lock()
        listings: Listings = get_listings(
            self.table.recipe_list[row].ItemResult.ID, world_id, cache_timeout_s=10
        )
        if any(listing.sellerID == self.seller_id for listing in listings.listings):
            self.retainer_listings_changed.emit(listings)

        self.recipe_textedit.setText(
            print_recipe(self.table.recipe_list[row], world_id)
        )
        universalis_mutex.unlock()

        # self.price_graph.plot(listings.History.to_dict())
        self.price_graph.clear()
        self.price_graph.p2.clear()
        self.price_graph.plotItem.plot(
            listings.History.index, listings.History["Price"].values, pen="g"
        )
        # self.price_graph.plotItem.plot(
        #     (3600 * 24 * 7)
        #     / np.asarray(
        #         pd.Series(listings.History.index)
        #         - pd.Series(listings.History.index).shift(periods=1)
        #     ),
        #     pen="b",
        # )
        if len(listings.History.index) > 2:
            # smoothing: https://stackoverflow.com/a/63511354/7552308
            self.price_graph.p2.addItem(
                p2 := PlotCurveItem(
                    x=np.asarray(listings.History.index[1:]),
                    y=(3600 * 24 * 7)
                    / np.asarray(
                        pd.Series(listings.History.index)
                        - pd.Series(listings.History.index).shift(periods=1)
                    )[1:],
                    pen="c",
                ),
            )
            self.price_graph.p2.autoRange(item=p2)
            self.price_graph.p2.enableAutoRange(self.price_graph.p2, True, True)
            # self.price_graph.plotItem.enableAutoScale()
            self.price_graph.plotItem.vb.enableAutoRange(
                self.price_graph.plotItem, True, True
            )

    @Slot()
    def on_refresh_button_clicked(self):
        self.refreshing_table = True
        self.worker.refresh_recipe_request_sem.release()

    @Slot()
    def on_worker_update(self):
        if self.refreshing_table:
            self.refresh_table()

    def refresh_table(self):
        self.table.clear_contents()
        universalis_mutex.lock()
        self.table.add_recipes(self.worker.table_row_data)
        universalis_mutex.unlock()

    def closeEvent(self, event):
        self.worker.stop()
        self.status_bar_label.setText("Exiting...")
        self.worker_thread.quit()
        self.worker_thread.wait()
        self.retainerworker_thread.quit()
        self.retainerworker_thread.wait()
        universalis_save_to_disk()
        xivapi_save_to_disk()
        self.retainerworker.save_cache()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication([])

    main_window = MainWindow()
    main_window.show()

    app.exec()
