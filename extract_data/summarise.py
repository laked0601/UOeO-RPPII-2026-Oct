"""

"""


# Rows of the summary table: (heading shown, key in parsed["balance_sheet"]).
TABLE_ROWS = [
    ("Tangible assets", "tangible_assets"),
    ("Cash at bank and in hand", "cash_at_bank_and_in_hand"),
    ("Creditors due within one year", "creditors_due_within_one_year"),
    ("Net current liabilities", "net_current_liabilities"),
    ("Total assets less current liabilities", "total_assets_less_current_liabilities"),
    ("Creditors due after more than one year", "creditors_due_after_more_than_one_year"),
    ("Net assets", "net_assets"),
    ("Called up share capital", "called_up_share_capital"),
    ("Profit and loss reserves", "profit_and_loss_reserves"),
    ("Total equity", "total_equity"),
]


def money(value):
    """Format an integer as pounds in prose, e.g. £1,234 or -£1,234."""
    if value is None:
        return "n/a"
    return f"-£{abs(value):,}" if value < 0 else f"£{value:,}"


def cell(value):
    """Format a figure for the table, accounting style: negatives in brackets."""
    if value is None:
        return "n/a"
    return f"({abs(value):,})" if value < 0 else f"{value:,}"


def change_phrase(now, before):
    """Describe a year-on-year movement, e.g. 'up £157 from £20,169'."""
    if now is None or before is None:
        return ""
    diff = now - before
    if diff == 0:
        return f"unchanged from {money(before)}"
    return f"{'up' if diff > 0 else 'down'} {money(abs(diff))} from {money(before)}"


def balance_sheet_table(bs, cur, prior):
    """Build an aligned text table: label | current year | prior year | change."""
    width = max(len(label) for label, _ in TABLE_ROWS)
    lines = [f"{'Balance sheet (£)':<{width}}  {cur:>10}  {prior:>10}  {'Change':>10}"]
    for label, key in TABLE_ROWS:
        figures = bs.get(key) or {}
        now, before = figures.get(cur), figures.get(prior)
        diff = None if now is None or before is None else now - before
        lines.append(f"{label:<{width}}  {cell(now):>10}  {cell(before):>10}  {cell(diff):>10}")
    return lines


def summarise(parsed):
    """Return a multi-line text summary of one parsed filing."""
    co, bs = parsed["company"], parsed["balance_sheet"]
    cur, prior = (str(y) for y in co["years"])

    def fig(key, year=cur):
        return (bs.get(key) or {}).get(year)

    # --- header ---
    lines = [f"{co['name']} (company no. {co['registration_number']})"]
    if co.get("address"):
        lines.append(f"Registered office: {co['address']}")
    if co.get("directors"):
        lines.append("Director(s): " + ", ".join(co["directors"]))
    lines.append(f"Balance sheet date: {co['balance_sheet_date']}")
    lines.append("")

    # --- key observations ---
    net_assets = fig("net_assets")
    lines.append(f"Net assets are {money(net_assets)}, {change_phrase(net_assets, fig('net_assets', prior))}.")

    # Net current liabilities are stored negative: below zero means short-term
    # debts exceed current assets, which is worth flagging.
    working_capital = fig("net_current_liabilities")
    if working_capital is not None and working_capital < 0:
        lines.append(f"Short-term debts exceed current assets by {money(-working_capital)}.")

    long_term = fig("creditors_due_after_more_than_one_year")
    if long_term:
        lines.append(f"Long-term creditors (due after more than one year) are {money(-long_term)}.")

    employees = parsed.get("employees_total")
    if employees:
        lines.append(f"Average employees (including directors): {employees.get(cur)}.")
    lines.append("")

    # --- table of figures for both years ---
    lines.extend(balance_sheet_table(bs, cur, prior))

    if parsed["warnings"]:
        lines += ["", "Warnings (check the figures against the PDF):"]
        lines += [f"  - {w}" for w in parsed["warnings"]]
    return "\n".join(lines)
