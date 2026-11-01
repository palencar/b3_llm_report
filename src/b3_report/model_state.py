"""Representacao reversivel para reduzir repeticao de chaves no envio ao modelo."""

from copy import deepcopy

MODEL_STATE_VERSION = "cvm-table-v1"


def compact_model_state(state):
    """Mantem todas as linhas/valores; nunca corta ou resume demonstrativos."""
    compact = deepcopy(state)
    if not isinstance(compact, dict):
        return compact
    snapshot = compact.get("snapshot", compact)
    if not isinstance(snapshot, dict):
        return compact
    sources = snapshot.get("source_data", {})
    if not isinstance(sources, dict):
        return compact
    rows = sources.get("cvm")
    if isinstance(rows, list) and rows and all(isinstance(row, dict) for row in rows):
        columns = list(rows[0])
        # Tabela so representa objetos homogeneos sem confundir ausencia e null.
        if columns and all(set(row) == set(columns) for row in rows):
            sources["cvm"] = {"encoding": MODEL_STATE_VERSION, "columns": columns,
                              "rows": [[row[column] for column in columns] for row in rows]}
    return compact
