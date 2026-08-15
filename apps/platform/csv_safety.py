DANGEROUS_SPREADSHEET_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def spreadsheet_safe_cell(value):
    """Return text safe to open as a spreadsheet cell without formula execution."""

    if value is None:
        return ""
    text = str(value)
    if text.startswith(DANGEROUS_SPREADSHEET_PREFIXES):
        return "'" + text
    return text
