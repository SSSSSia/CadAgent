"""Parameter edit dialog for parametric rebuild (P12.2).

Lists the extracted parameter store in an editable table; on accept the
caller feeds the (possibly modified) values to agent.tools.rebuild_with_params,
which replays the session's successful code history deterministically.
"""
from __future__ import annotations

from PySide6 import QtWidgets


class ParamsDialog(QtWidgets.QDialog):
    """Edit named parameters and trigger a deterministic model rebuild."""

    def __init__(self, parent, params: dict, can_rebuild: bool):
        super().__init__(parent)
        self.setWindowTitle("Parameters")
        self.setMinimumWidth(320)
        self._params = dict(params)
        self._accepted_params: dict | None = None

        layout = QtWidgets.QVBoxLayout(self)

        if not can_rebuild:
            note = QtWidgets.QLabel(
                "No rebuildable code history in this session yet — parameters "
                "are still injected into the Agent's context."
            )
            note.setWordWrap(True)
            layout.addWidget(note)
        elif not params:
            note = QtWidgets.QLabel(
                "No named parameters extracted yet. Define them at the top of "
                "your code (e.g. OD = 200) and they will appear here."
            )
            note.setWordWrap(True)
            layout.addWidget(note)

        self.table = QtWidgets.QTableWidget(len(params), 2, self)
        self.table.setHorizontalHeaderLabels(["Parameter", "Value"])
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

        hint = QtWidgets.QLabel(
            "Rebuild replays this session's modeling code with the new values "
            "(no LLM call). The previous state stays undoable."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setText("Rebuild")
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel).setText("Cancel")
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
                    self, "Invalid value",
                    f"'{raw}' is not a number. Parameter {name} must be "
                    "an integer or decimal value.",
                )
                return
            result[name] = value
        self._accepted_params = result
        self.accept()

    def result_params(self) -> dict | None:
        """New parameter values when accepted, else None."""
        return self._accepted_params
