"""
Standard names for the row labels that vary between filings.

Raw labels are always kept; the "standard" name is an extra field that lets
different filings be compared (and decides the heading in standardise.py).
"""

import re

from extract_data.parsing.tables import NOTE_REF

# Standard names for labels that vary between filings.  Raw labels are always
# kept; "standard" is an extra column that lets different filings be compared.
# Matching is exact (after tidying case, punctuation and "(Note 2)"), because
# near matches are dangerous: "Intangible assets" is not "Tangible assets".
STANDARD_LABELS = {
    "total_assets": ["total assets"],
    "total_liabilities": ["total liabilities"],
    "total_equity": ["total equity", "total shareholders' funds", "shareholders' funds", "total equity and reserves",
                     "capital and reserves", "total capital and reserves", "shareholders' deficit"],
    "total_equity_and_liabilities": ["total liabilities and equity", "total equity and liabilities"],
    "net_assets": ["net assets", "net liabilities", "net assets/(liabilities)", "net assets (liabilities)"],
    "fixed_assets": ["fixed assets", "total fixed assets", "non-current assets", "total non-current assets"],
    "tangible_assets": ["tangible assets", "tangible fixed assets", "property, plant and equipment"],
    "intangible_assets": ["intangible assets", "intangible fixed assets"],
    "investments": ["investments", "fixed asset investments", "investments in subsidiaries",
                    "investment in subsidiary", "investment in subsidiaries"],
    "current_assets": ["current assets", "total current assets"],
    "stocks": ["stocks", "inventories"],
    "debtors": ["debtors", "trade and other receivables", "trade receivables",
                "debtors: amounts falling due within one year"],
    "cash": ["cash at bank and in hand", "cash and cash equivalents", "cash"],
    "creditors_within_one_year": ["creditors: amounts falling due within one year",
                                  "current liabilities: amounts falling due within one year",
                                  "creditors: amount falling due within one year",
                                  "amounts falling due within one year", "trade and other payables",
                                  "total current liabilities"],
    "creditors_after_one_year": ["creditors: amounts falling due after more than one year",
                                 "creditors: amount falling due after more than one year",
                                 "amounts falling due after more than one year", "total non-current liabilities"],
    "provisions": ["provisions for liabilities", "provisions", "other provisions",
                   "provisions for liabilities and charges"],
    "deferred_tax": ["provision for deferred taxation", "provisions for deferred taxation", "deferred taxation",
                     "deferred tax", "deferred tax liability"],
    "net_current_assets": ["net current assets", "net current liabilities", "net current assets/(liabilities)",
                           "net current assets (liabilities)"],
    "total_assets_less_current_liabilities": ["total assets less current liabilities"],
    "share_capital": ["called up share capital", "share capital", "issued share capital"],
    "share_premium": ["share premium", "share premium account"],
    "retained_earnings": ["profit and loss reserves", "profit and loss account", "retained earnings",
                          "retained profits", "revenue reserves", "revenue reserve", "accumulated surplus"],
    "revaluation_reserve": ["revaluation reserve", "revaluation reserves"],
    "other_reserves": ["other reserves", "other reserves classified as equity"],
    "members_capital": ["members' capital classified as equity", "members' capital",
                        "members' capital classified as a liability"],
    "loans_due_to_members": ["loans and other debts due to members",
                             "loans and other debts due to members within one year",
                             "amounts due to members"],
    "non_controlling_interests": ["non-controlling interests", "non controlling interests", "minority interests"],
    "turnover": ["turnover", "revenue", "sales"],
    "other_operating_income": ["other operating income"],
    "dividend_income": ["dividend income", "dividends received"],
    "interest_receivable": ["interest receivable", "interest receivable and similar income", "interest income",
                            "interest and other income", "bank interest receivable"],
    "cost_of_sales": ["cost of sales"],
    "gross_profit": ["gross profit", "gross profit/(loss)", "gross loss", "gross surplus", "gross surplus/(deficit)"],
    "administrative_expenses": ["administrative expenses", "administration expenses"],
    "interest_payable": ["interest payable", "interest payable and similar expenses",
                         "interest payable and similar charges", "finance costs", "finance expense"],
    "operating_profit": ["operating profit", "operating profit/(loss)", "operating (loss)/profit", "operating loss",
                         "operating profit or loss"],
    "profit_before_tax": ["profit before taxation", "profit before tax", "income before taxation",
                          "income before tax", "loss before taxation", "loss before tax",
                          "profit/(loss) before taxation", "(loss)/profit before taxation",
                          "profit on ordinary activities before taxation",
                          "loss on ordinary activities before taxation",
                          "profit/(loss) on ordinary activities before taxation", "surplus before taxation",
                          "surplus/(deficit) before taxation",
                          "surplus/(deficit) on ordinary activities before taxation",
                          "surplus on ordinary activities before taxation"],
    "tax": ["taxation", "tax on profit", "tax on profit on ordinary activities", "taxation credit/(charge)",
            "income tax expense", "tax on loss", "tax on profit/(loss)", "tax on (loss)/profit",
            "tax on profit or loss"],
    "profit_for_period": ["profit for the financial year", "profit for the year", "profit for the period",
                          "profit for the financial period", "income for the period", "loss for the year",
                          "loss for the financial year", "loss for the financial period",
                          "profit/(loss) for the year", "profit/(loss) for the financial year",
                          "(loss)/profit for the financial year", "retained profit for the year",
                          "loss for the financial period before members remuneration and profit share",
                          "profit for the financial period before members remuneration and profit share",
                          "surplus for the year", "surplus for the financial year", "surplus/(deficit) for the year",
                          "surplus/(deficit) for the financial year", "deficit for the year",
                          "deficit for the financial year"],
    "comprehensive_income": ["total comprehensive income for the year", "comprehensive income for the period",
                             "total comprehensive income for the period", "total comprehensive income",
                             "total comprehensive (loss)/profit for the period"],
    "dividends_paid": ["dividends paid", "dividends"],
}

STANDARD_LOOKUP = {variant: name for name, variants in STANDARD_LABELS.items() for variant in variants}


def normalise_label(label):
    """
    A label tidied for matching: lower case, no '(Note 2)', single spaces, no space around '/'.
    """
    text = NOTE_REF.sub("", label).lower().replace("’", "'")
    text = re.sub(r"\s*/\s*", "/", re.sub(r"\s+", " ", text))  # "surplus / (deficit)" -> "surplus/(deficit)"

    return text.strip(" :.")


def standard_label(label):
    """
    Map a printed label to a standard name ('total_equity'), or None.
    """
    return STANDARD_LOOKUP.get(normalise_label(label))
