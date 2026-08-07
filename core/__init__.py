try:
    import pydantic
    if not hasattr(pydantic, "VERSION"):
        pydantic.VERSION = getattr(pydantic, "__version__", "2.0")
except Exception:
    pass
