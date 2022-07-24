from collections import defaultdict, namedtuple
from dataclasses import dataclass
from enum import Enum
import enum
import json
import logging
from pathlib import Path
from scipy import stats
from typing import Any, DefaultDict, Dict, List, MutableMapping, NamedTuple, Optional, Set, Tuple, Union
import pandas as pd
import numpy as np
import pyperclip
from PySide6.QtCore import (
    QObject,
    Slot,
    QSortFilterProxyModel,
    Signal,
    QSize,
    QThread,
    QSemaphore,
    Qt,
    QBasicTimer,
    QCoreApplication,
    QModelIndex,
    QPersistentModelIndex,
    QAbstractTableModel,
)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QTableView,
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
    QMenuBar,
    QWidgetAction,
    QSpinBox,
)
from pyqtgraph import (
    PlotWidget,
    DateAxisItem,
    AxisItem,
    PlotCurveItem,
    PlotDataItem,
    ViewBox,
    Point,
    functions,
    mkPen,
)
from QTableWidgetFloatItem import QTableWidgetFloatItem
from cache import PersistMapping
from classjobConfig import ClassJobConfig
from ff14marketcalc import get_profit, get_revenue, print_recipe
from gathererWorker.gathererWorker import GathererWindow
from itemCleaner.itemCleaner import ItemCleanerForm
from retainerWorker.models import ListingData
from universalis.models import Listings
from craftingWorker import CraftingWorker
from retainerWorker.retainerWorker import RetainerWorker
from universalis.universalis import (
    UniversalisManager,
    get_listings,
    set_seller_id,
)
from universalis.universalis import save_to_disk as universalis_save_to_disk
from xivapi.models import ClassJob, Item, Recipe, RecipeCollection
from xivapi.xivapi import (
    XivapiManager,
    get_classjob_doh_list,
    get_recipe_by_id,
    get_recipes,
    search_recipes,
)
from xivapi.xivapi import save_to_disk as xivapi_save_to_disk

logging.basicConfig(
    level=logging.INFO,
    format=" %(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(".data/debug.log"), logging.StreamHandler()],
)

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)

world_id = 55


def create_default_directories() -> None:
    Path(".data/").mkdir(exist_ok=True)
    # Path(".logs/").mkdir(exist_ok=True)


create_default_directories()


class MainWindow(QMainWindow):
    class RecipeTableView(QTableView):
        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            # self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.verticalHeader().hide()
            self.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.setSortingEnabled(True)
            self.sortByColumn(7, Qt.DescendingOrder)
        
        def add_recipe(self, recipe: Recipe) -> None:
            self.model().add_recipe(recipe)
            self.resizeColumnsToContents()

        def set_profit(self, recipe_id: int, profit: float) -> None:
            self.model().set_profit(recipe_id, profit)
            self.resizeColumnsToContents()

    class RecipeTableProxyModel(QSortFilterProxyModel):
        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.setDynamicSortFilter(True)

        def lessThan(self, left, right):
            left_data = self.sourceModel().data(left, Qt.UserRole)
            right_data = self.sourceModel().data(right, Qt.UserRole)
            if left_data is not None and right_data is not None:
                return left_data < right_data
            else:
                return super().lessThan(left, right)
            # elif right_data is None:
            #     return False
            # else:
            #     return True

        def filterAcceptsRow(
            self,
            source_row: int,
            source_parent: Union[QModelIndex, QPersistentModelIndex],
        ) -> bool:
            # source_model = self.sourceModel()
            # if (
            #     len(self.gathering_item_id_filter_set) == 0
            #     or source_model.table_data[source_row][-1]
            #     in self.gathering_item_id_filter_set
            # ):
            #     return super().filterAcceptsRow(source_row, source_parent)
            # return False
            return super().filterAcceptsRow(source_row, source_parent)

        def add_recipe(self, recipe: Recipe) -> None:
            self.sourceModel().add_recipe(recipe)

        def set_profit(self, recipe_id: int, profit: float) -> None:
            self.sourceModel().set_profit(recipe_id, profit)

    class RecipeTableModel(QAbstractTableModel):
        @dataclass
        class RowData:
            classjob_abbreviation: str  # Job
            classjob_level: int  # Lvl
            item_name: str  # Item
            profit: Optional[float] = None  # Profit
            velocity: Optional[float] = None  # Velocity
            listing_count: Optional[int] = None  # Lists
            speed: Optional[float] = None  # Sp
            score: Optional[float] = None  # Score
            recipe_id: int = None
            # revenue: Optional[float] = None
            # market_cost: Optional[float] = None
            # crafting_cost: Optional[float] = None

            def __getitem__(self, item: int) -> Any:
                if item == 0:
                    return self.classjob_abbreviation
                elif item == 1:
                    return self.classjob_level
                elif item == 2:
                    return self.item_name
                elif item == 3:
                    return self.profit
                elif item == 4:
                    return self.velocity
                elif item == 5:
                    return self.listing_count
                elif item == 6:
                    return self.speed
                elif item == 7:
                    return self.score
                elif item == 8:
                    return self.recipe_id
                # elif item == 9:
                #     return self.revenue
                # elif item == 10:
                #     return self.market_cost
                # elif item == 11:
                #     return self.crafting_cost
                else:
                    raise IndexError(f"Invalid index {item}")

        def __init__(self, parent: Optional[QObject] = None) -> None:
            super().__init__(parent)
            self.table_data: List[MainWindow.RecipeTableModel.RowData] = []
            self.recipe_id_to_row_index_dict: Dict[int, int] = {}
            self.header_data: List[str] = [
                "Job",
                "Lvl",
                "Item",
                "Profit",
                "Velocity",
                "Lists",
                "Sp",
                "Score",
            ]

        def rowCount(
            self, parent: Union[QModelIndex, QPersistentModelIndex] = None
        ) -> int:
            return len(self.table_data)

        def columnCount(
            self, parent: Union[QModelIndex, QPersistentModelIndex] = None
        ) -> int:
            return 8

        def data(  # type: ignore[override]
            self,
            index: QModelIndex,
            role: Qt.ItemDataRole = Qt.DisplayRole,
        ) -> Any:
            if not index.isValid():
                return None
            if role == Qt.DisplayRole:
                column = index.column()
                cell_data = self.table_data[index.row()][column]
                if cell_data is None:
                    return ""
                if column == 3 or column == 7:  # profit, score
                    return f"{cell_data:,.0f}"
                elif column == 4 or column == 6:  # velocity, speed
                    return f"{cell_data:,.2f}"
                elif (
                    column <= 2 or column == 5
                ):  # classjob_abbreviation, classjob_level, item_name, listing_count
                    return cell_data
                else:
                    return cell_data
            elif role == Qt.UserRole:
                return self.table_data[index.row()][index.column()]
            return None

        def headerData(  # type: ignore[override]
            self,
            section: int,
            orientation: Qt.Orientation,
            role: Qt.ItemDataRole = Qt.DisplayRole,
        ) -> Optional[str]:
            if orientation == Qt.Horizontal and role == Qt.DisplayRole:
                return self.header_data[section]
            return None

        def add_recipe(self, recipe: Recipe) -> None:
            recipe_id = recipe.ID
            _logger.debug(f"recipe_table_model.add_recipe: {recipe_id}")
            if recipe_id not in self.recipe_id_to_row_index_dict:
                row_count = self.rowCount()
                self.beginInsertRows(QModelIndex(), row_count, row_count)
                row_data = self.RowData(
                    classjob_abbreviation=recipe.ClassJob.Abbreviation,
                    classjob_level=recipe.RecipeLevelTable.ClassJobLevel,
                    item_name=recipe.ItemResult.Name,
                    recipe_id=recipe_id,
                )
                self.table_data.append(row_data)
                self.recipe_id_to_row_index_dict[row_data.recipe_id] = row_count
                self.endInsertRows()

        def set_profit(self, recipe_id: int, profit: float) -> None:
            row_index = self.recipe_id_to_row_index_dict[recipe_id]
            # self.table_data[row_index].profit = profit
            row_data = self.table_data[row_index]
            row_data.profit = profit
            if row_data.velocity is not None:
                row_data.score = profit * row_data.velocity
                self.dataChanged.emit(
                    self.index(row_index, 3), self.index(row_index, 7)
                )
            else:
                self.dataChanged.emit(
                    self.index(row_index, 3), self.index(row_index, 3)
                )

        # def update_recipe_revenue(self, recipe_id: int, revenue: float) -> None:
        #     row_index = self.recipe_id_to_row_index_dict[recipe_id]
        #     _logger.debug(f"recipe_table_model.update_recipe_revenue: {recipe_id}, revenue: {revenue}")
        #     self.table_data[row_index].revenue = revenue
        #     # self.table_data[row_index] = self.table_data[row_index]._replace(
        #     #     revenue=revenue
        #     # )
        #     # self.dataChanged(
        #     #     self.index(row_index, 3), self.index(row_index, 3)
        #     # )

        # def update_recipe_market_cost(self, recipe_id: int, market_cost: float) -> None:
        #     row_index = self.recipe_id_to_row_index_dict[recipe_id]
        #     _logger.debug(f"recipe_table_model.update_recipe_market_cost: {recipe_id}, market_cost: {market_cost}")
        #     self.table_data[row_index].market_cost = market_cost

        # @Slot(Listings)
        # def add_listings(self, listings: Listings) -> None:
        #     _logger.debug(f"recipe_table_model.add_listings: {listings.itemID}")
        #     if listings.recipe_id in self.recipe_id_to_column_dict:
        #         column = self.recipe_id_to_column_dict[listings.recipe_id]
        #         row_data = self.table_data[column]
        #         row_data.listing_count = listings.listing_count
        #         row_data.profit = listings.profit
        #         row_data.score = listings.score
        #         self.dataChanged.emit(self.index(column, 0), self.index(column, 8))

        # @Slot(RowData)
        # def update_table(self, row_data: RowData) -> None:
        #     if row_data.recipe_id in self.recipe_id_to_column_dict:
        #         column = self.recipe_id_to_column_dict[row_data.recipe_id]
        #         self.table_data[column] = row_data
        #     else:
        #         row_count = self.rowCount()
        #         self.beginInsertRows(QModelIndex(), row_count, row_count)
        #         self.table_data.append(row_data)
        #         self.recipe_id_to_column_dict[row_data.recipe_id] = row_count
        #         self.endInsertRows()

    # class RecipeListTable(QTableWidget):
    #     def __init__(self, *args):
    #         super().__init__(*args)
    #         self.setColumnCount(8)
    #         self.setHorizontalHeaderLabels(
    #             ["Job", "Lvl", "Item", "Profit", "Velocity", "Lists", "Sp", "Score"]
    #         )
    #         self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    #         self.verticalHeader().hide()
    #         self.setEditTriggers(QAbstractItemView.NoEditTriggers)

    #         # recipe_id -> row
    #         self.table_data: Dict[int, List[QTableWidgetItem]] = {}

    #     def clear_contents(self) -> None:
    #         self.clearContents()
    #         self.setRowCount(0)
    #         self.table_data.clear()

    #     def remove_rows_above_level(
    #         self, classjob_id: int, classjob_level: int
    #     ) -> None:
    #         keys_to_remove = []
    #         for recipe_id in self.table_data.keys():
    #             recipe = get_recipe_by_id(recipe_id)
    #             if (
    #                 recipe.ClassJob.ID == classjob_id
    #                 and recipe.RecipeLevelTable.ClassJobLevel > classjob_level
    #             ):
    #                 keys_to_remove.append(recipe_id)
    #         print(f"Removing {len(keys_to_remove)} rows")
    #         for key in keys_to_remove:
    #             self.removeRow(self.table_data[key][0].row())
    #             del self.table_data[key]

    #     @Slot(Recipe, float, Listings)
    #     def on_recipe_table_update(
    #         self, recipe: Recipe, profit: float, velocity: float, listing_count: int
    #     ) -> None:
    #         if recipe.ID in self.table_data:
    #             row = self.table_data[recipe.ID]
    #             row[3].setText(f"{profit:,.0f}")
    #             row[4].setText(f"{velocity:.2f}")
    #             row[5].setText(f"{listing_count}")
    #             row[6].setText(f"{velocity / max(listing_count, 1):,.2f}")
    #             row[7].setText(f"{profit * velocity:,.0f}")
    #         else:
    #             row: List[QTableWidgetItem] = []
    #             row.append(QTableWidgetItem(recipe.ClassJob.Abbreviation))
    #             row.append(QTableWidgetItem(str(recipe.RecipeLevelTable.ClassJobLevel)))
    #             row.append(QTableWidgetItem(recipe.ItemResult.Name))
    #             row.append(QTableWidgetFloatItem(f"{profit:,.0f}"))
    #             row.append(QTableWidgetFloatItem(f"{velocity:.2f}"))
    #             row.append(QTableWidgetItem(str(listing_count)))
    #             row.append(QTableWidgetFloatItem(f"{velocity / max(listing_count, 1):,.2f}"))
    #             row.append(QTableWidgetFloatItem(f"{profit * velocity:,.0f}"))
    #             self.insertRow(self.rowCount())
    #             self.setItem(self.rowCount() - 1, 0, row[0])
    #             self.setItem(self.rowCount() - 1, 1, row[1])
    #             self.setItem(self.rowCount() - 1, 2, row[2])
    #             self.setItem(self.rowCount() - 1, 3, row[3])
    #             self.setItem(self.rowCount() - 1, 4, row[4])
    #             self.setItem(self.rowCount() - 1, 5, row[5])
    #             self.setItem(self.rowCount() - 1, 6, row[6])
    #             self.setItem(self.rowCount() - 1, 7, row[7])
    #             self.table_data[recipe.ID] = row
    #         self.sortItems(7, Qt.DescendingOrder)

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
            listing_prices = [
                listing.pricePerUnit
                for listing in listings.listings
                if listing.sellerID != self.seller_id
            ]
            if len(listing_prices) > 0:
                return min(listing_prices)
            else:
                return np.inf

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
                "right": MainWindow.PriceGraph.FmtAxesItem(orientation="right"),
            }
            super().__init__(parent, background, plotItem, **kargs)

            self.p1 = self.plotItem
            self.p1.getAxis("left").setLabel("Velocity", color="#00ffff")
            self.p1_pen = mkPen(color="#00ff00", width=2)

            ## create a new ViewBox, link the right axis to its coordinate system
            self.p2 = ViewBox()
            self.p1.showAxis("right")
            self.p1.scene().addItem(self.p2)
            self.p1.getAxis("right").linkToView(self.p2)
            self.p2.setXLink(self.p1)
            self.p1.getAxis("right").setLabel("Purchases", color="#00ff00")
            # # self.p1.vb.setLogMode("y", True)
            # self.p2.setLogMode(self.p1.getAxis("right"), True)
            # self.p1.getAxis("right").setLogMode(False, True)
            # self.p1.getAxis("right").enableAutoSIPrefix(False)

            ## create third ViewBox.
            ## this time we need to create a new axis as well.
            self.p3 = ViewBox()
            self.ax3 = MainWindow.PriceGraph.FmtAxesItem(orientation="right")
            self.p1.layout.addItem(self.ax3, 2, 3)
            self.p1.scene().addItem(self.p3)
            self.ax3.linkToView(self.p3)
            self.p3.setXLink(self.p1)
            self.p3.setYLink(self.p2)
            self.ax3.setZValue(-10000)
            self.ax3.setLabel("Listings", color="#ff00ff")
            self.ax3.hide()
            self.ax3.setGrid(128)
            # self.ax3.setLogMode(False, True)
            # self.p3.setLogMode("y", True)
            # self.ax3.hideAxis()
            # self.ax3.setLogMode(False, True)
            # self.ax3.enableAutoSIPrefix(False)

            self.updateViews()
            self.p1.vb.sigResized.connect(self.updateViews)

        @Slot()
        def updateViews(self) -> None:
            self.p2.setGeometry(self.p1.vb.sceneBoundingRect())
            self.p3.setGeometry(self.p1.vb.sceneBoundingRect())
            self.p2.linkedViewChanged(self.p1.vb, self.p2.XAxis)
            self.p3.linkedViewChanged(self.p1.vb, self.p3.XAxis)

        def auto_range(self):
            self.p2.enableAutoRange(axis="y")
            self.p3.enableAutoRange(axis="y")
            self.p1.vb.updateAutoRange()
            self.p2.updateAutoRange()
            self.p3.updateAutoRange()

            bounds = [np.inf, -np.inf]
            for items in (
                self.p1.vb.addedItems,
                self.p2.addedItems,
                self.p3.addedItems,
            ):
                for item in items:
                    _bounds = item.dataBounds(0)
                    if _bounds[0] is None or _bounds[1] is None:
                        continue
                    bounds[0] = min(_bounds[0], bounds[0])
                    bounds[1] = max(_bounds[1], bounds[1])
            if bounds[0] != np.inf and bounds[1] != -np.inf:
                self.p1.vb.setRange(xRange=bounds)

            bounds = [np.inf, -np.inf]
            for items in (
                self.p2.addedItems,
                self.p3.addedItems,
            ):
                for item in items:
                    _bounds = item.dataBounds(1)
                    if _bounds[0] is None or _bounds[1] is None:
                        continue
                    bounds[0] = min(_bounds[0], bounds[0])
                    bounds[1] = max(_bounds[1], bounds[1])
            if bounds[0] != np.inf and bounds[1] != -np.inf:
                self.p2.setRange(yRange=bounds)

        def wheelEvent(self, ev, axis=None):
            super().wheelEvent(ev)
            for vb in (
                self.p1.vb,
                self.p2,
                self.p3,
            ):
                if axis in (0, 1):
                    mask = [False, False]
                    mask[axis] = vb.state["mouseEnabled"][axis]
                else:
                    mask = vb.state["mouseEnabled"][:]
                s = 1.02 ** (
                    (ev.angleDelta().y() - ev.angleDelta().x())
                    * vb.state["wheelScaleFactor"]
                )  # actual scaling factor
                s = [(None if m is False else s) for m in mask]
                center = Point(
                    functions.invertQTransform(vb.childGroup.transform()).map(
                        ev.position()
                    )
                )

                vb._resetTarget()
                vb.scaleBy(s, center)
                ev.accept()
                vb.sigRangeChangedManually.emit(mask)

    # class JobLevelWidget(QWidget):
    #     def __init__(self, parent: Optional[QWidget] = ..., f: Qt.WindowFlags = ...) -> None:
    #         super().__init__(parent, f)

    class ClassJobLevelLayout(QHBoxLayout):
        joblevel_value_changed = Signal(int, int)

        def __init__(self, parent: QWidget, classjob_config: ClassJobConfig) -> None:
            self.classjob = ClassJob(**classjob_config.dict())
            super().__init__()
            self.label = QLabel(parent)
            self.label.setText(classjob_config.Abbreviation)
            self.label.setAlignment(Qt.AlignRight)  # type: ignore
            self.label.setAlignment(Qt.AlignCenter)  # type: ignore
            self.addWidget(self.label)
            self.spinbox = QSpinBox(parent)
            self.spinbox.setMaximum(90)
            self.spinbox.setValue(classjob_config.level)
            self.addWidget(self.spinbox)

            self.spinbox.valueChanged.connect(self.on_spinbox_value_changed)  # type: ignore

        def on_spinbox_value_changed(self, value: int) -> None:
            _logger.info(f"{self.classjob.Abbreviation} level changed to {value}")
            self.joblevel_value_changed.emit(self.classjob.ID, value)

    retainer_listings_changed = Signal(Listings)
    classjob_level_changed = Signal(int, int)
    auto_refresh_listings_changed = Signal(bool)
    search_recipes = Signal(str)
    request_listings = Signal(int, int, bool)
    request_recipe = Signal(int, bool)
    # close_signal = Signal()

    class ItemRecipeIndex(NamedTuple):
        """
        Position of an item in the recipe list.
        """
        recipe_id: int
        index: Optional[int] # None is itemResult

    class AquireAction(NamedTuple):
        """
        Action to aquire recipe result.
        """
        class AquireActionEnum(enum.Enum):
            BUY = enum.auto()
            CRAFT = enum.auto()
            GATHER = enum.auto()
        action: AquireActionEnum
        cost: float

    def __init__(self):
        super().__init__()

        self.item_id_to_recipe_index_dict: DefaultDict[int, Set[MainWindow.ItemRecipeIndex]] = defaultdict(set)
        self.recipe_id_to_revenue_dict: Dict[int, float] = {}
        self.recipe_id_to_market_cost_dict: Dict[int, float] = {}
        self.recipe_id_to_crafting_cost_dict: Dict[int, float] = {}
        self.recipe_id_to_aquire_action_dict: Dict[int, MainWindow.AquireAction] = {}

        # Layout
        self.main_widget = QWidget()

        self.menu_bar = QMenuBar(self)
        self.setMenuBar(self.menu_bar)
        self.item_cleaner_action = QWidgetAction(self)
        self.item_cleaner_action.setText("Item Cleaner")
        self.menu_bar.addAction(self.item_cleaner_action)
        self.item_cleaner_action.triggered.connect(self.on_item_cleaner_menu_clicked)
        self.gatherer_action = QWidgetAction(self)
        self.gatherer_action.setText("Gatherer")
        self.menu_bar.addAction(self.gatherer_action)
        self.gatherer_action.triggered.connect(self.on_gatherer_menu_clicked)

        self.main_layout = QVBoxLayout()
        self.classjob_level_layout = QHBoxLayout()
        self.main_layout.addLayout(self.classjob_level_layout)
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
        # self.analyze_button = QPushButton(self)
        # self.analyze_button.setText("Analyze")
        # self.search_layout.addWidget(self.analyze_button)
        # self.analyze_button.clicked.connect(self.on_table_double_clicked)
        self.search_label = QLabel(self)
        self.search_label.setText("Search:")
        self.search_layout.addWidget(self.search_label)
        self.search_lineedit = QLineEdit(self)
        self.search_lineedit.returnPressed.connect(self.on_search_return_pressed)
        self.search_layout.addWidget(self.search_lineedit)
        self.search_refresh_button = QPushButton(self)
        self.search_refresh_button.setText("Refresh")
        self.search_refresh_button.clicked.connect(self.on_refresh_button_clicked)
        self.search_layout.addWidget(self.search_refresh_button)
        self.table_search_layout.addLayout(self.search_layout)

        self.recipe_table_model = MainWindow.RecipeTableModel(self)
        self.recipe_table_proxy_model = MainWindow.RecipeTableProxyModel(self)
        self.recipe_table_proxy_model.setSourceModel(self.recipe_table_model)
        self.recipe_table_view = MainWindow.RecipeTableView(self)
        self.recipe_table_view.setModel(self.recipe_table_proxy_model)
        self.recipe_table_view.setSortingEnabled(True)
        self.recipe_table_view.doubleClicked.connect(self.on_table_double_clicked)
        self.recipe_table_view.clicked.connect(self.on_table_clicked)
        self.table_search_layout.addWidget(self.recipe_table_view)

        # self.table = MainWindow.RecipeListTable(self)
        # self.table.cellDoubleClicked.connect(self.on_table_double_clicked)
        # self.table.cellClicked.connect(self.on_table_clicked)
        # self.table_search_layout.addWidget(self.table)

        self.table_search_widget.setLayout(self.table_search_layout)
        self.left_splitter.addWidget(self.table_search_widget)

        self.recipe_textedit = QTextEdit(self)
        self.left_splitter.addWidget(self.recipe_textedit)

        self.seller_id = (
            "4d9521317c92e33772cd74a166c72b0207ab9edc5eaaed5a1edb52983b70b2c2"
        )
        set_seller_id(self.seller_id)

        self.retainer_table = MainWindow.RetainerTable(self, self.seller_id)
        self.retainer_table.cellClicked.connect(self.on_retainer_table_clicked)
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

        self.xivapi_manager = XivapiManager(world_id)
        self._xivapi_manager_thread = QThread()
        self.xivapi_manager.moveToThread(self._xivapi_manager_thread)
        self._xivapi_manager_thread.finished.connect(self.xivapi_manager.deleteLater)
        self.xivapi_manager.status_bar_set_text_signal.connect(
            self.status_bar_label.setText
        )
        self.classjob_level_changed.connect(
            self.xivapi_manager.set_classjob_id_level_max_slot
        )
        # self.xivapi_manager.recipe_received.connect(self.recipe_table_model.add_recipe)
        self.request_recipe.connect(self.xivapi_manager.request_recipe)
        self.xivapi_manager.recipe_received.connect(self.on_recipe_received)
        # self._xivapi_manager_thread.start(QThread.LowPriority)

        # Classjob level stuff!
        _logger.info("Getting classjob list...")
        classjob_list: List[ClassJob] = get_classjob_doh_list()
        self.classjob_config = PersistMapping[int, ClassJobConfig](
            "classjob_config.bin",
            {
                classjob.ID: ClassJobConfig(**classjob.dict(), level=0)
                for classjob in classjob_list
            },
        )
        self.classjob_level_layout_list = []
        for classjob_config in self.classjob_config.values():
            self.classjob_level_layout_list.append(
                _classjob_level_layout := MainWindow.ClassJobLevelLayout(
                    self, classjob_config
                )
            )
            self.classjob_level_layout.addLayout(_classjob_level_layout)
            _classjob_level_layout.joblevel_value_changed.connect(
                self.on_classjob_level_value_changed
            )
            _classjob_level_layout.joblevel_value_changed.emit(
                classjob_config.ID, classjob_config.level
            )

        self.universalis_manager = UniversalisManager(self.seller_id, world_id)
        self.universalis_manager.moveToThread(self._xivapi_manager_thread)
        self._xivapi_manager_thread.finished.connect(
            self.universalis_manager.deleteLater
        )
        self.universalis_manager.status_bar_set_text_signal.connect(
            self.status_bar_label.setText
        )
        self.request_listings.connect(self.universalis_manager.request_listings)
        self.universalis_manager.listings_received_signal.connect(
            self.on_listings_received
        )
        self._xivapi_manager_thread.start(QThread.LowPriority)

        self.retainerworker_thread = QThread()
        self.retainerworker = RetainerWorker(
            seller_id=self.seller_id, world_id=world_id
        )
        self.retainerworker.moveToThread(self.retainerworker_thread)
        # self.retainerworker_thread.started.connect(self.retainerworker.run)
        self.retainerworker_thread.finished.connect(self.retainerworker.deleteLater)

        # self.crafting_worker.seller_listings_matched_signal.connect(
        #     self.retainerworker.on_retainer_listings_changed
        # )
        self.retainerworker.listing_data_updated.connect(
            self.retainer_table.on_listing_data_updated
        )

        # self.crafting_worker_thread.start(QThread.LowPriority)
        # self.crafting_worker_thread.start()
        # self.retainerworker.load_cache(
        #     self.crafting_worker.seller_listings_matched_signal
        # )
        self.retainerworker_thread.start(QThread.LowPriority)

    @Slot(int, int)
    def on_classjob_level_value_changed(
        self, classjob_id: int, classjob_level: int
    ) -> None:
        _logger.debug(f"Classjob {classjob_id} level changed to {classjob_level}")
        self.classjob_config[classjob_id].level = classjob_level
        # classjob_config = self.classjob_config[classjob_id]
        # classjob_config.level = classjob_level
        # self.classjob_config[classjob_id] = classjob_config
        # self.table.remove_rows_above_level(classjob_id, classjob_level)
        # print(f"Removed rows above level {classjob_level}")
        self.classjob_level_changed.emit(classjob_id, classjob_level)

    @Slot()
    def on_item_cleaner_menu_clicked(self) -> None:
        pass
        # form = ItemCleanerForm(self, self.crafting_worker.get_item_crafting_value_table)
        # # TODO: Connect this
        # # self.crafting_worker.crafting_value_table_changed.connect(self.form.on_crafting_value_table_changed)
        # form.show()

    @Slot()
    def on_gatherer_menu_clicked(self) -> None:
        form = GathererWindow(world_id, self)
        form.show()

    @Slot()
    def on_search_return_pressed(self):
        pass
        # self.table.clear_contents()
        # self.search_recipes.emit(self.search_lineedit.text())

    @Slot(int, int)
    def on_retainer_table_clicked(self, row: int, column: int):
        for row_group_list in self.retainer_table.table_data.values():
            for widget_list in row_group_list:
                if widget_list[0].row() != row:
                    continue
                pyperclip.copy(widget_list[2].text())
                return

    @Slot(int, int)
    def on_table_clicked(self, row: int, column: int):
        pass
        # for recipe_id, row_widget_list in self.table.table_data.items():
        #     if row_widget_list[0].row() == row:
        #         break
        # pyperclip.copy(row_widget_list[2].text())
        # self.plot_listings(
        #     get_listings(get_recipe_by_id(recipe_id).ItemResult.ID, world_id)
        # )

    @Slot(int, int)
    def on_table_double_clicked(self, row: int, column: int):
        pass
        # for recipe_id, row_widget_list in self.table.table_data.items():
        #     if row_widget_list[0].row() == row:
        #         break
        # item_name = row_widget_list[2].text()
        # print(f"item name: {item_name}")
        # self.status_bar_label.setText(f"Processing {item_name}...")
        # QCoreApplication.processEvents()
        # recipe = get_recipe_by_id(recipe_id)
        # self.recipe_textedit.setText(print_recipe(recipe, world_id))
        # profit = get_profit(recipe, world_id)
        # listings = get_listings(recipe.ItemResult.ID, world_id)
        # self.table.on_recipe_table_update(
        #     recipe, profit, listings.regularSaleVelocity, len(listings.listings)
        # )
        # self.status_bar_label.setText(f"Done processing {item_name}...")

    @Slot(Recipe)
    def on_recipe_received(self, recipe: Recipe) -> None:
        _logger.debug(
            f"Recipe {recipe.ID} wants listings for item {recipe.ItemResult.ID}"
        )
        self.request_listings.emit(recipe.ItemResult.ID, world_id, True)
        recipe_id = recipe.ID
        self.item_id_to_recipe_index_dict[recipe.ItemResult.ID].add(MainWindow.ItemRecipeIndex(recipe_id, None))
        item: Item
        ingredient_recipes: List[Recipe]
        for ingredient_index in range(9):
            if item := getattr(recipe, f"ItemIngredient{ingredient_index}"):
                self.request_listings.emit(item.ID, world_id, True)
                self.item_id_to_recipe_index_dict[item.ID].add(MainWindow.ItemRecipeIndex(recipe_id, ingredient_index))
                if ingredient_recipes := getattr(
                    recipe, f"ItemIngredientRecipe{ingredient_index}"
                ):
                    for ingredient_recipe in ingredient_recipes:
                        self.request_recipe.emit(ingredient_recipe.ID, True)
        self.recipe_table_view.add_recipe(recipe)

    @Slot(Listings)
    def on_listings_received(self, listings: Listings) -> None:
        item_id = listings.itemID
        _logger.debug(f"on_listings_received: {item_id}")
        revenue = get_revenue(listings)
        market_cost = listings.minPrice
        recipe: Optional[Recipe]
        for recipe_id, item_recipe_index in self.item_id_to_recipe_index_dict[item_id]:
            # This might break if an item is its own ingredient.
            # Should include all revenue before any crafting_cost calculation.
            recipe = self.xivapi_manager.request_recipe(recipe_id)
            assert recipe is not None
            # if item is recipe result
            if item_recipe_index is None:
                self.recipe_id_to_revenue_dict[recipe_id] = revenue
                self.recipe_id_to_market_cost_dict[recipe_id] = market_cost
                self.process_aquire_action(recipe_id)
            else:
                self.process_crafting_cost(recipe)

    def process_crafting_cost(self, recipe: Recipe) -> None:
        ingredient_recipes: List[Recipe]
        crafting_cost: Optional[float] = None
        _logger.debug(f"process_crafting_cost: {recipe.ID}")
        for ingredient_index in range(9):
            if ingredient_recipes := getattr(
                recipe, f"ItemIngredientRecipe{ingredient_index}"
            ):
                ingredient_cost = np.inf
                for ingredient_recipe in ingredient_recipes:
                    self.request_recipe.emit(ingredient_recipe.ID, True)
                    if ingredient_recipe.ID in self.recipe_id_to_aquire_action_dict:
                        ingredient_cost = min(ingredient_cost, self.recipe_id_to_aquire_action_dict[ingredient_recipe.ID].cost)
                    else:
                        _logger.debug(f"Cannot calculate crafting cost for {recipe.ID}: {ingredient_recipe.ID} not in recipe_id_to_aquire_action_dict")
                        return
                crafting_cost = ingredient_cost if crafting_cost is None else crafting_cost + ingredient_cost
        _logger.debug(f"Crafting cost for {recipe.ID}: {crafting_cost}")
        self.recipe_id_to_crafting_cost_dict[recipe.ID] = crafting_cost if crafting_cost is not None else np.inf
        self.process_aquire_action(recipe.ID)


    def process_aquire_action(self, recipe_id: int) -> None:
        _logger.debug(f"process_aquire_action: {recipe_id}")
        if (crafting_cost := self.recipe_id_to_crafting_cost_dict.get(recipe_id)) and (market_cost := self.recipe_id_to_market_cost_dict.get(recipe_id)):
            if crafting_cost < market_cost:
                self.recipe_id_to_aquire_action_dict[recipe_id] = MainWindow.AquireAction(
                    MainWindow.AquireAction.AquireActionEnum.CRAFT,
                    market_cost,
                )
            else:
                self.recipe_id_to_aquire_action_dict[recipe_id] = MainWindow.AquireAction(
                    MainWindow.AquireAction.AquireActionEnum.BUY,
                    market_cost,
                )
            self.process_profit(recipe_id)


    def process_profit(self, recipe_id: int) -> None:
        _logger.debug(f"process_profit: {recipe_id}")
        if (revenue := self.recipe_id_to_revenue_dict.get(recipe_id)) and (aquire_action := self.recipe_id_to_aquire_action_dict.get(recipe_id)):
            profit = revenue - aquire_action.cost
            self.recipe_table_view.set_profit(recipe_id, profit)

    def plot_listings(self, listings: Listings) -> None:
        self.price_graph.p1.clear()
        self.price_graph.p2.clear()
        self.price_graph.p3.clear()
        listings.history.sort_index(inplace=True)
        listings.listing_history.sort_index(inplace=True)
        self.price_graph.p1.plot(
            x=np.asarray(listings.history.index[1:]),
            y=(3600 * 24 * 7)
            / np.asarray(
                pd.Series(listings.history.index)
                - pd.Series(listings.history.index).shift(periods=1)
            )[1:],
            pen="c",
            symbol="o",
            symbolSize=5,
            symbolBrush=("c"),
        )

        if len(listings.history.index) > 2:
            # smoothing: https://stackoverflow.com/a/63511354/7552308
            # history_df = listings.history[["Price"]].apply(
            #     savgol_filter, window_length=5, polyorder=2
            # )
            # self.price_graph.p2.addItem(
            #     p2 := PlotDataItem(
            #         np.asarray(history_df.index),
            #         history_df["Price"].values,
            #         pen=self.price_graph.p1_pen,
            #         symbol="o",
            #         symbolSize=5,
            #         symbolBrush=("g"),
            #     ),
            # )
            self.price_graph.p2.addItem(
                p2 := PlotDataItem(
                    np.asarray(listings.history.index),
                    listings.history["Price"].values,
                    pen=self.price_graph.p1_pen,
                    symbol="o",
                    symbolSize=5,
                    symbolBrush=("g"),
                ),
            )

        if (
            listings.listing_history.index.size > 2
            and listings.listing_history["Price"].max()
            - listings.listing_history["Price"].min()
            > 0
        ):
            listing_history_df = listings.listing_history[
                (np.abs(stats.zscore(listings.listing_history)) < 3).all(axis=1)
            ]
            if listing_history_df.index.size != listings.listing_history.index.size:
                _logger.info("Ignoring outliers:")
                _logger.info(
                    listings.listing_history.loc[
                        listings.listing_history.index.difference(
                            listing_history_df.index
                        )
                    ]["Price"]
                )
        else:
            listing_history_df = listings.listing_history
        self.price_graph.p3.addItem(
            p3 := PlotDataItem(
                np.asarray(listing_history_df.index),
                listing_history_df["Price"].values,
                pen="m",
                symbol="o",
                symbolSize=5,
                symbolBrush=("m"),
            ),
        )
        # p3.setLogMode(False, True)
        self.price_graph.auto_range()

    @Slot()
    def on_refresh_button_clicked(self):
        self.search_lineedit.clear()
        self.table.clear_contents()
        self.auto_refresh_listings_changed.emit(True)

    def closeEvent(self, event):
        print("exiting ui...")
        # self.crafting_worker_thread.setPriority(QThread.NormalPriority)
        # self.crafting_worker.stop()
        # self.crafting_worker_thread.quit()
        # self.crafting_worker_thread.wait()
        # print("crafting worker closed")

        # self._xivapi_manager_thread.
        # self.xivapi_manager.moveToThread(QThread.currentThread())
        # self.close_signal.connect(
        #     self.xivapi_manager.save_to_disk, Qt.BlockingQueuedConnection
        # )
        # self.close_signal.emit()
        self._xivapi_manager_thread.quit()
        self._xivapi_manager_thread.wait()
        # self.xivapi_manager.moveToThread(QThread.currentThread())
        self.xivapi_manager.save_to_disk()
        print("xivapi saved")

        self.universalis_manager.save_to_disk()
        print("universalis saved")

        self.retainerworker_thread.quit()
        self.retainerworker_thread.wait()
        print("retainer worker closed")
        self.classjob_config.save_to_disk()
        print("classjob config saved")
        universalis_save_to_disk()
        print("universalis saved")
        xivapi_save_to_disk()
        print("xivapi saved")
        self.retainerworker.save_cache()
        print("retainer cache saved")
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication([])

    main_window = MainWindow()
    main_window.show()

    app.exec()

# Ideas:
# Better caching of persistent data
# look for matching retainers when pulling all data, not just in a few loops
