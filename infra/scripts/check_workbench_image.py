"""Verify the actual analyst runtime and reject accidental ML dependencies."""

from importlib import import_module

for dependency in ("quant_workbench.pages", "edgar_pipeline", "plotly", "psycopg", "sqlalchemy"):
    import_module(dependency)

for excluded in ("torch", "torch_geometric", "ml_pipeline"):
    try:
        import_module(excluded)
    except ModuleNotFoundError as exc:
        if exc.name != excluded:
            raise
    else:
        raise RuntimeError(f"Unexpected analyst image dependency: {excluded}")
print("Workbench imports passed; torch, torch_geometric and ml_pipeline absent.")
