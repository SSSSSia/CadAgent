"""Parameter edit dialog for parametric rebuild (P12.2).

Lists the extracted parameter store in an editable table; on accept the
caller feeds the (possibly modified) values to agent.tools.rebuild_with_params,
which replays the session's successful code history deterministically.
"""
from __future__ import annotations

from PySide6 import QtWidgets

from ui.strings import t


class ParamsDialog(QtWidgets.QDialog):
    """Edit named parameters and trigger a deterministic model rebuild."""

    def __init__(self, parent, params: dict, can_rebuild: bool):
        super().__init__(parent)
        self.setWindowTitle(t("params_title"))
        self.setMinimumWidth(320)
        self._params = dict(params)
        self._accepted_params: dict | None = None

        layout = QtWidgets.QVBoxLayout(self)

        if not can_rebuild:
            note = QtWidgets.QLabel(t("params_no_history"))
            note.setWordWrap(True)
            layout.addWidget(note)
        elif not params:
            note = QtWidgets.QLabel(t("params_none"))
            note.setWordWrap(True)
            layout.addWidget(note)

        self.table = QtWidgets.QTableWidget(len(params), 2, self)
        self.table.setHorizontalHeaderLabels([t("param_col"), t("value_col")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.DoubleClicked
            | QtWidgets.QAbstractItemView.EditTrigger.SelectedClicked
        )
        from PySide6 import QtCore
        for row, (name, value) in enumerate(sorted(params.items())):
            name_item = QtWidgets.QTableWidgetItem(name)
            # Read-only name column
            name_item.setFlags(
                name_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable
            )
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(value)))
        self.table.setColumnWidth(0, 110)
        layout.addWidget(self.table)

        hint = QtWidgets.QLabel(t("params_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setText(t("rebuild"))
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText(t("cancel"))
        self._ok_button.setEnabled(can_rebuild and bool(params))
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        """Validate values as int/float, then accept."""
        result: dict = {}
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            if name_item is None or value_item is None:
                continue
            name = name_item.text().strip()
            raw = value_item.text().strip()
            try:
                value = float(raw) if "." in raw or "e" in raw.lower() else int(raw)
            except ValueError:
                QtWidgets.QMessageBox.warning(
                    self, t("invalid_value_title"),
                    t("invalid_value_body", raw=raw, name=name),
                )
                return
            result[name] = value
        self._accepted_params = result
        self.accept()

    def result_params(self) -> dict | None:
        """New parameter values when accepted, else None."""
        return self._accepted_params
