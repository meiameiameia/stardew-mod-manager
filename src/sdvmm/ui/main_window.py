from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from sdvmm.app.inventory_presenter import (
    build_findings_text,
    build_package_inspection_text,
    build_sandbox_install_plan_text,
    build_sandbox_install_result_text,
    build_update_report_text,
)
from sdvmm.app.shell_service import (
    SCAN_TARGET_CONFIGURED_REAL_MODS,
    SCAN_TARGET_SANDBOX_MODS,
    AppShellError,
    AppShellService,
)
from sdvmm.domain.models import AppConfig, ModUpdateReport, ModsInventory, SandboxInstallPlan


class MainWindow(QMainWindow):
    def __init__(self, shell_service: AppShellService) -> None:
        super().__init__()
        self._shell_service = shell_service
        self._config: AppConfig | None = None
        self._pending_install_plan: SandboxInstallPlan | None = None
        self._current_inventory: ModsInventory | None = None
        self._current_update_report: ModUpdateReport | None = None
        self._row_remote_links: dict[int, str] = {}

        self.setWindowTitle("Stardew Mod Manager - Local Scan")
        self.resize(950, 600)

        self._mods_path_input = QLineEdit()
        self._mods_path_input.setPlaceholderText("/path/to/Stardew/Mods")
        self._zip_path_input = QLineEdit()
        self._zip_path_input.setPlaceholderText("/path/to/package.zip")
        self._sandbox_mods_path_input = QLineEdit()
        self._sandbox_mods_path_input.setPlaceholderText("/path/to/Sandbox/Mods")
        self._sandbox_archive_path_input = QLineEdit()
        self._sandbox_archive_path_input.setPlaceholderText("/path/to/Sandbox/.sdvmm-archive")
        self._overwrite_checkbox = QCheckBox("Allow overwrite with archive")
        self._scan_target_combo = QComboBox()
        self._scan_target_combo.addItem("Configured Mods path", SCAN_TARGET_CONFIGURED_REAL_MODS)
        self._scan_target_combo.addItem("Sandbox Mods target", SCAN_TARGET_SANDBOX_MODS)

        self._mods_table = QTableWidget(0, 6)
        self._mods_table.setHorizontalHeaderLabels(
            ["Name", "UniqueID", "Installed", "Remote", "Update state", "Folder"]
        )
        self._mods_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._mods_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self._findings_box = QPlainTextEdit()
        self._findings_box.setReadOnly(True)

        self._status_label = QLabel()
        self._scan_context_label = QLabel("Scan context: not set")

        self._zip_path_input.textChanged.connect(self._invalidate_pending_plan)
        self._sandbox_mods_path_input.textChanged.connect(self._invalidate_pending_plan)
        self._sandbox_archive_path_input.textChanged.connect(self._invalidate_pending_plan)
        self._overwrite_checkbox.toggled.connect(self._invalidate_pending_plan)
        self._scan_target_combo.currentIndexChanged.connect(self._refresh_scan_context_preview)
        self._mods_path_input.textChanged.connect(self._refresh_scan_context_preview)
        self._sandbox_mods_path_input.textChanged.connect(self._refresh_scan_context_preview)

        self._build_layout()
        self._load_startup_state()

    def _build_layout(self) -> None:
        container = QWidget()
        root_layout = QVBoxLayout(container)

        path_layout = QGridLayout()
        path_layout.addWidget(QLabel("Mods directory"), 0, 0)
        path_layout.addWidget(self._mods_path_input, 0, 1)

        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self._on_browse)
        path_layout.addWidget(browse_button, 0, 2)

        path_layout.addWidget(QLabel("Zip package"), 1, 0)
        path_layout.addWidget(self._zip_path_input, 1, 1)

        browse_zip_button = QPushButton("Browse zip")
        browse_zip_button.clicked.connect(self._on_browse_zip)
        path_layout.addWidget(browse_zip_button, 1, 2)

        path_layout.addWidget(QLabel("Sandbox Mods target"), 2, 0)
        path_layout.addWidget(self._sandbox_mods_path_input, 2, 1)

        browse_sandbox_button = QPushButton("Browse sandbox")
        browse_sandbox_button.clicked.connect(self._on_browse_sandbox_mods)
        path_layout.addWidget(browse_sandbox_button, 2, 2)

        path_layout.addWidget(QLabel("Sandbox archive path"), 3, 0)
        path_layout.addWidget(self._sandbox_archive_path_input, 3, 1)

        browse_archive_button = QPushButton("Browse archive")
        browse_archive_button.clicked.connect(self._on_browse_sandbox_archive)
        path_layout.addWidget(browse_archive_button, 3, 2)

        path_layout.addWidget(self._overwrite_checkbox, 4, 1)
        path_layout.addWidget(QLabel("Scan target"), 5, 0)
        path_layout.addWidget(self._scan_target_combo, 5, 1)

        actions_row = QHBoxLayout()
        save_button = QPushButton("Save config")
        save_button.clicked.connect(self._on_save_config)
        actions_row.addWidget(save_button)

        scan_button = QPushButton("Scan")
        scan_button.clicked.connect(self._on_scan)
        actions_row.addWidget(scan_button)

        inspect_button = QPushButton("Inspect zip")
        inspect_button.clicked.connect(self._on_inspect_zip)
        actions_row.addWidget(inspect_button)

        plan_install_button = QPushButton("Plan install")
        plan_install_button.clicked.connect(self._on_plan_install)
        actions_row.addWidget(plan_install_button)

        run_install_button = QPushButton("Install to sandbox")
        run_install_button.clicked.connect(self._on_run_install)
        actions_row.addWidget(run_install_button)

        check_updates_button = QPushButton("Check updates")
        check_updates_button.clicked.connect(self._on_check_updates)
        actions_row.addWidget(check_updates_button)

        open_remote_button = QPushButton("Open remote page")
        open_remote_button.clicked.connect(self._on_open_remote_page)
        actions_row.addWidget(open_remote_button)
        actions_row.addStretch(1)

        root_layout.addLayout(path_layout)
        root_layout.addLayout(actions_row)
        root_layout.addWidget(QLabel("Installed mods"))
        root_layout.addWidget(self._mods_table)
        root_layout.addWidget(QLabel("Warnings and findings"))
        root_layout.addWidget(self._findings_box)
        root_layout.addWidget(self._scan_context_label)
        root_layout.addWidget(self._status_label)

        self.setCentralWidget(container)

    def _load_startup_state(self) -> None:
        state = self._shell_service.load_startup_config()
        self._config = state.config

        if state.config is not None:
            self._mods_path_input.setText(str(state.config.mods_path))
            self._set_status(f"Loaded saved config from {self._shell_service.state_file}")

        if state.message:
            self._findings_box.setPlainText(state.message)
            self._set_status(state.message)

        self._refresh_scan_context_preview()

    def _on_browse(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Mods directory",
            self._mods_path_input.text() or "",
        )
        if selected:
            self._mods_path_input.setText(selected)

    def _on_browse_zip(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select zip package",
            self._zip_path_input.text() or "",
            "Zip packages (*.zip)",
        )
        if selected:
            self._pending_install_plan = None
            self._zip_path_input.setText(selected)

    def _on_browse_sandbox_mods(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select sandbox Mods directory",
            self._sandbox_mods_path_input.text() or "",
        )
        if selected:
            self._pending_install_plan = None
            self._sandbox_mods_path_input.setText(selected)
            if not self._sandbox_archive_path_input.text().strip():
                self._sandbox_archive_path_input.setText(str(Path(selected) / ".sdvmm-archive"))

    def _on_browse_sandbox_archive(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select sandbox archive directory",
            self._sandbox_archive_path_input.text() or "",
        )
        if selected:
            self._pending_install_plan = None
            self._sandbox_archive_path_input.setText(selected)

    def _on_save_config(self) -> None:
        try:
            self._config = self._shell_service.save_mods_directory(
                mods_dir_text=self._mods_path_input.text(),
                existing_config=self._config,
            )
        except AppShellError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            self._set_status(str(exc))
            return

        self._set_status(f"Saved config to {self._shell_service.state_file}")

    def _on_scan(self) -> None:
        try:
            result = self._shell_service.scan_with_target(
                scan_target=self._current_scan_target(),
                configured_mods_path_text=self._mods_path_input.text(),
                sandbox_mods_path_text=self._sandbox_mods_path_input.text(),
            )
        except AppShellError as exc:
            QMessageBox.critical(self, "Scan failed", str(exc))
            self._set_status(str(exc))
            return

        self._render_inventory(result.inventory)
        self._set_scan_context(result.scan_path, self._scan_target_label(result.target_kind))
        self._set_status(f"Scan complete: {len(result.inventory.mods)} mods")

    def _on_inspect_zip(self) -> None:
        try:
            inspection = self._shell_service.inspect_zip(self._zip_path_input.text())
        except AppShellError as exc:
            QMessageBox.critical(self, "Zip inspection failed", str(exc))
            self._set_status(str(exc))
            return

        self._pending_install_plan = None
        self._findings_box.setPlainText(build_package_inspection_text(inspection))
        self._set_status(f"Zip inspection complete: {len(inspection.mods)} mod(s) detected")

    def _on_plan_install(self) -> None:
        try:
            plan = self._shell_service.build_sandbox_install_plan(
                package_path_text=self._zip_path_input.text(),
                sandbox_mods_path_text=self._sandbox_mods_path_input.text(),
                sandbox_archive_path_text=self._sandbox_archive_path_input.text(),
                allow_overwrite=self._overwrite_checkbox.isChecked(),
                configured_real_mods_path=self._config.mods_path if self._config else None,
            )
        except AppShellError as exc:
            self._pending_install_plan = None
            QMessageBox.critical(self, "Install plan failed", str(exc))
            self._set_status(str(exc))
            return

        self._pending_install_plan = plan
        self._findings_box.setPlainText(build_sandbox_install_plan_text(plan))
        self._set_status(f"Install plan ready: {len(plan.entries)} entry(ies)")

    def _on_run_install(self) -> None:
        if self._pending_install_plan is None:
            message = "Create an install plan before executing sandbox install."
            QMessageBox.warning(self, "No install plan", message)
            self._set_status(message)
            return

        yes = QMessageBox.question(
            self,
            "Confirm sandbox install",
            (
                "Execute sandbox install now?\n"
                f"Target: {self._pending_install_plan.sandbox_mods_path}\n"
                f"Archive: {self._pending_install_plan.sandbox_archive_path}\n"
                "Overwrite operations in plan: "
                f"{'yes' if any(entry.action == 'overwrite_with_archive' for entry in self._pending_install_plan.entries) else 'no'}\n"
                f"Entries: {len(self._pending_install_plan.entries)}"
            ),
        )
        if yes != QMessageBox.StandardButton.Yes:
            self._set_status("Sandbox install cancelled.")
            return

        try:
            result = self._shell_service.execute_sandbox_install_plan(self._pending_install_plan)
        except AppShellError as exc:
            QMessageBox.critical(self, "Sandbox install failed", str(exc))
            self._set_status(str(exc))
            return

        self._render_inventory(result.inventory)
        self._findings_box.setPlainText(build_sandbox_install_result_text(result))
        self._set_current_scan_target(SCAN_TARGET_SANDBOX_MODS)
        self._set_scan_context(result.scan_context_path, "sandbox Mods directory")
        self._set_status(f"Sandbox install complete: {len(result.installed_targets)} target(s)")

    def _on_check_updates(self) -> None:
        if self._current_inventory is None:
            message = "Scan a target first before checking metadata/update state."
            QMessageBox.warning(self, "No inventory", message)
            self._set_status(message)
            return

        try:
            report = self._shell_service.check_updates(self._current_inventory)
        except AppShellError as exc:
            QMessageBox.critical(self, "Update check failed", str(exc))
            self._set_status(str(exc))
            return

        self._current_update_report = report
        self._apply_update_report(report)
        self._findings_box.setPlainText(build_update_report_text(report))
        self._set_status(f"Update check complete: {len(report.statuses)} mod(s)")

    def _on_open_remote_page(self) -> None:
        if self._current_update_report is None:
            message = "Run update check first to populate remote links."
            QMessageBox.warning(self, "No metadata", message)
            self._set_status(message)
            return

        row = self._mods_table.currentRow()
        if row < 0:
            message = "Select a mod row first."
            QMessageBox.warning(self, "No selection", message)
            self._set_status(message)
            return

        url = self._row_remote_links.get(row)
        if not url:
            message = "No remote page is available for the selected mod."
            QMessageBox.information(self, "No remote link", message)
            self._set_status(message)
            return

        if not QDesktopServices.openUrl(QUrl(url)):
            message = f"Could not open remote page: {url}"
            QMessageBox.critical(self, "Open failed", message)
            self._set_status(message)
            return

        self._set_status(f"Opened remote page: {url}")

    def _render_inventory(self, inventory: ModsInventory) -> None:
        self._current_inventory = inventory
        self._current_update_report = None
        self._row_remote_links = {}
        self._mods_table.setRowCount(len(inventory.mods))

        for row, mod in enumerate(inventory.mods):
            self._mods_table.setItem(row, 0, QTableWidgetItem(mod.name))
            self._mods_table.setItem(row, 1, QTableWidgetItem(mod.unique_id))
            self._mods_table.setItem(row, 2, QTableWidgetItem(mod.version))
            self._mods_table.setItem(row, 3, QTableWidgetItem("-"))
            self._mods_table.setItem(row, 4, QTableWidgetItem("not_checked"))
            self._mods_table.setItem(row, 5, QTableWidgetItem(mod.folder_path.name))

        self._mods_table.resizeColumnsToContents()
        self._findings_box.setPlainText(build_findings_text(inventory))

    def _apply_update_report(self, report: ModUpdateReport) -> None:
        if self._current_inventory is None:
            return

        by_folder = {status.folder_path: status for status in report.statuses}
        self._row_remote_links = {}

        for row, mod in enumerate(self._current_inventory.mods):
            status = by_folder.get(mod.folder_path)
            if status is None:
                self._mods_table.setItem(row, 3, QTableWidgetItem("-"))
                self._mods_table.setItem(row, 4, QTableWidgetItem("metadata_unavailable"))
                continue

            self._mods_table.setItem(row, 3, QTableWidgetItem(status.remote_version or "-"))
            self._mods_table.setItem(row, 4, QTableWidgetItem(status.state))
            if status.remote_link is not None:
                self._row_remote_links[row] = status.remote_link.page_url

    def _set_status(self, text: str) -> None:
        self._status_label.setText(text)

    def _set_scan_context(self, path: Path, label: str) -> None:
        self._scan_context_label.setText(f"Scan context: {label} ({path})")

    def _invalidate_pending_plan(self, *_: object) -> None:
        self._pending_install_plan = None

    def _refresh_scan_context_preview(self, *_: object) -> None:
        target = self._current_scan_target()
        if target == SCAN_TARGET_CONFIGURED_REAL_MODS:
            path_text = self._mods_path_input.text().strip() or "<unset>"
        else:
            path_text = self._sandbox_mods_path_input.text().strip() or "<unset>"
        self._scan_context_label.setText(
            f"Selected scan target: {self._scan_target_label(target)} ({path_text})"
        )

    def _current_scan_target(self) -> str:
        return str(self._scan_target_combo.currentData())

    def _set_current_scan_target(self, target: str) -> None:
        index = self._scan_target_combo.findData(target)
        if index >= 0:
            self._scan_target_combo.setCurrentIndex(index)

    @staticmethod
    def _scan_target_label(target: str) -> str:
        if target == SCAN_TARGET_CONFIGURED_REAL_MODS:
            return "configured Mods directory"
        return "sandbox Mods directory"
