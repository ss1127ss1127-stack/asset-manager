"""集計・分類・将来予測のロジック。

UI（app.py）から切り離しておくことで、ライフプラン機能を
追加するときにここを拡張しやすくする。すべて純粋関数。
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

import config


# --- 年月のパース ----------------------------------------------------------
_YM_RE = re.compile(r"(\d{4})\D*?(\d{1,2})")


def parse_year_month(value: str) -> pd.Timestamp | pd.NaT:
    """「2024-01」「2024/1」「2024年1月」「202401」などを月初の Timestamp に。

    解釈できない場合は NaT を返す。
    """
    if value is None:
        return pd.NaT
    s = str(value).strip()
    if not s:
        return pd.NaT
    m = _YM_RE.search(s)
    if not m:
        return pd.NaT
    year, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12):
        return pd.NaT
    try:
        return pd.Timestamp(year=year, month=month, day=1)
    except ValueError:
        return pd.NaT


def with_parsed_date(df: pd.DataFrame) -> pd.DataFrame:
    """年月をパースした `_date` 列を付与した DataFrame を返す。"""
    out = df.copy()
    out["_date"] = out[config.COL_YEAR_MONTH].map(parse_year_month)
    return out


def sorted_year_months(df: pd.DataFrame) -> list[str]:
    """データに存在する年月を時系列順（解釈不能は末尾）で返す。"""
    if df.empty:
        return []
    tmp = with_parsed_date(df)[[config.COL_YEAR_MONTH, "_date"]].drop_duplicates(
        subset=config.COL_YEAR_MONTH
    )
    tmp = tmp.sort_values("_date", na_position="last")
    return tmp[config.COL_YEAR_MONTH].tolist()


# --- 総資産推移 ------------------------------------------------------------
def monthly_total(df: pd.DataFrame) -> pd.DataFrame:
    """年月ごとの資産合計。列: 年月, _date, 合計（_date 昇順）。"""
    if df.empty:
        return pd.DataFrame(columns=[config.COL_YEAR_MONTH, "_date", "合計"])
    tmp = with_parsed_date(df)
    grouped = (
        tmp.groupby([config.COL_YEAR_MONTH, "_date"], dropna=False)[config.COL_AMOUNT]
        .sum()
        .reset_index()
        .rename(columns={config.COL_AMOUNT: "合計"})
        .sort_values("_date", na_position="last")
        .reset_index(drop=True)
    )
    return grouped


def owner_monthly_total(df: pd.DataFrame) -> pd.DataFrame:
    """年月 × 名義 ごとの資産合計（積み上げグラフ用）。

    列: 年月, _date, 名義, 合計（_date 昇順）。
    """
    cols = [config.COL_YEAR_MONTH, "_date", config.COL_OWNER, "合計"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    tmp = with_parsed_date(df)
    grouped = (
        tmp.groupby(
            [config.COL_YEAR_MONTH, "_date", config.COL_OWNER], dropna=False
        )[config.COL_AMOUNT]
        .sum()
        .reset_index()
        .rename(columns={config.COL_AMOUNT: "合計"})
        .sort_values("_date", na_position="last")
        .reset_index(drop=True)
    )
    return grouped


# --- ポートフォリオ構成（カテゴリ別） --------------------------------------
def portfolio_by_category(df: pd.DataFrame, year_month: str) -> pd.Series:
    """指定年月のカテゴリ別合計（金額降順の Series）。"""
    sub = df[df[config.COL_YEAR_MONTH] == year_month]
    if sub.empty:
        return pd.Series(dtype=float)
    return (
        sub.groupby(config.COL_CATEGORY)[config.COL_AMOUNT]
        .sum()
        .sort_values(ascending=False)
    )


# --- 安全資産 vs リスク資産 ------------------------------------------------
def classify_asset(category: str) -> str:
    """カテゴリ名から「安全資産」「リスク資産」「その他」を判定する。"""
    name = str(category)
    if any(kw in name for kw in config.RISK_ASSET_KEYWORDS):
        return "リスク資産"
    if any(kw in name for kw in config.SAFE_ASSET_KEYWORDS):
        return "安全資産"
    return "その他"


def safe_risk_breakdown(df: pd.DataFrame, year_month: str) -> pd.Series:
    """指定年月の 安全資産 / リスク資産 / その他 別合計。"""
    sub = df[df[config.COL_YEAR_MONTH] == year_month]
    if sub.empty:
        return pd.Series(dtype=float)
    klass = sub[config.COL_CATEGORY].map(classify_asset)
    return sub.groupby(klass)[config.COL_AMOUNT].sum()


# --- 複利シミュレーション --------------------------------------------------
def average_monthly_increase(totals: pd.DataFrame) -> float:
    """総資産推移から、月平均の増加額を推定する。

    最初の月から最新の月までの増加分を経過月数で割った値。
    データが1点しかない場合は 0。
    """
    valid = totals.dropna(subset=["_date"])
    if len(valid) < 2:
        return 0.0
    first, last = valid.iloc[0], valid.iloc[-1]
    months = (last["_date"].year - first["_date"].year) * 12 + (
        last["_date"].month - first["_date"].month
    )
    if months <= 0:
        return 0.0
    return float((last["合計"] - first["合計"]) / months)


def project_future(
    totals: pd.DataFrame,
    annual_rate: float = config.DEFAULT_ANNUAL_RATE,
    years: int = config.DEFAULT_PROJECTION_YEARS,
    monthly_contribution: float | None = None,
) -> pd.DataFrame:
    """現在の資産額を起点に、年利 + 毎月積立で将来を予測する。

    モデル: 毎月末に「月平均増加額」を積み立て、資産全体は
    月利 (1+年利)^(1/12)-1 で複利成長する。

    戻り値: 列 _date, 予測額（起点の月＝現在を含む）。
    """
    valid = totals.dropna(subset=["_date"])
    if valid.empty:
        return pd.DataFrame(columns=["_date", "予測額"])

    start_date = valid.iloc[-1]["_date"]
    balance = float(valid.iloc[-1]["合計"])
    if monthly_contribution is None:
        monthly_contribution = average_monthly_increase(totals)

    monthly_rate = (1.0 + annual_rate) ** (1.0 / 12.0) - 1.0
    n_months = int(years * 12)

    dates = [start_date]
    values = [balance]
    for i in range(1, n_months + 1):
        balance = balance * (1.0 + monthly_rate) + monthly_contribution
        dates.append(start_date + pd.DateOffset(months=i))
        values.append(balance)

    return pd.DataFrame({"_date": dates, "予測額": values})
