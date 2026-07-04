"""Google Sheets との入出力をまとめたモジュール。

- サービスアカウント認証（credentials.json）
- データベースシートの読み込み / 追記（APPEND）
- マスタシートの選択肢読み込み

Streamlit からはここの関数だけを呼ぶ。認証クライアントは使い回す。
"""

from __future__ import annotations

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

import config


def _load_credentials() -> Credentials:
    """サービスアカウント認証情報を「ハイブリッド方式」で読み込む。

    優先順位:
      1) Streamlit Cloud の st.secrets["gcp_service_account"]（本番デプロイ）
      2) ローカルの credentials.json（開発環境）

    st.secrets は secrets.toml が存在しないと参照時に例外を送出するため、
    try-except で包み、見つからなければ 2) にフォールバックする。
    """
    # --- 1) Streamlit Community Cloud（st.secrets）------------------------
    try:
        import streamlit as st  # ローカルの CLI 実行でも import 自体は可能

        if "gcp_service_account" in st.secrets:
            # AttrDict を通常の dict に変換してからクレデンシャル化する
            info = dict(st.secrets["gcp_service_account"])
            return Credentials.from_service_account_info(
                info, scopes=config.SCOPES
            )
    except Exception:
        # secrets が未設定 / streamlit 文脈外 の場合はローカルへフォールバック
        pass

    # --- 2) ローカルの credentials.json ----------------------------------
    if config.CREDENTIALS_PATH.exists():
        return Credentials.from_service_account_file(
            str(config.CREDENTIALS_PATH), scopes=config.SCOPES
        )

    raise FileNotFoundError(
        "認証情報が見つかりません。\n"
        "・本番（Streamlit Cloud）: Secrets に [gcp_service_account] を設定してください。\n"
        f"・ローカル: サービスアカウント鍵を {config.CREDENTIALS_PATH} に配置してください。"
    )


def get_client() -> gspread.Client:
    """サービスアカウントで認証した gspread クライアントを返す。"""
    creds = _load_credentials()
    return gspread.authorize(creds)


def get_spreadsheet(client: gspread.Client | None = None):
    """対象スプレッドシートを開く。"""
    client = client or get_client()
    return client.open_by_key(config.SPREADSHEET_ID)


def _records_to_df(records: list[dict]) -> pd.DataFrame:
    """get_all_records の結果を DataFrame 化し、金額を数値に整える。"""
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=config.DATABASE_COLUMNS)
    # 列を既定の並びに揃える（不足列は空で補完）
    for col in config.DATABASE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[config.DATABASE_COLUMNS].copy()
    df[config.COL_AMOUNT] = _to_numeric_amount(df[config.COL_AMOUNT])
    df[config.COL_YEAR_MONTH] = df[config.COL_YEAR_MONTH].astype(str).str.strip()
    # 年月が空の行は集計対象外
    df = df[df[config.COL_YEAR_MONTH] != ""].reset_index(drop=True)
    return df


def _to_numeric_amount(series: pd.Series) -> pd.Series:
    """「¥1,234」「1,234円」などの表記を数値に変換する。"""
    cleaned = (
        series.astype(str)
        .str.replace(r"[¥￥,，円\s]", "", regex=True)
        .replace({"": "0", "nan": "0"})
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0)


def load_database(client: gspread.Client | None = None) -> pd.DataFrame:
    """データベースシート全体を DataFrame で取得する。"""
    ws = get_spreadsheet(client).worksheet(config.DATABASE_SHEET)
    return _records_to_df(ws.get_all_records())


def load_masters(client: gspread.Client | None = None) -> dict[str, list[str]]:
    """マスタシートから 名義 / 口座名 / カテゴリ の選択肢を読み込む。

    戻り値: {"名義": [...], "口座名": [...], "カテゴリ": [...]}
    各列は重複を除き、入力順を保ったまま返す。
    """
    ws = get_spreadsheet(client).worksheet(config.MASTER_SHEET)
    records = ws.get_all_records()
    df = pd.DataFrame(records)

    masters: dict[str, list[str]] = {}
    for col in config.MASTER_COLUMNS:
        # シート上の見出し（「名義マスタ」等）を優先し、無ければ論理名にフォールバック
        header = config.MASTER_HEADERS.get(col, col)
        source = header if header in df.columns else col
        if source in df.columns:
            values = (
                df[source].astype(str).str.strip().replace("", pd.NA).dropna().tolist()
            )
            # 入力順を保ったまま重複除去
            masters[col] = list(dict.fromkeys(values))
        else:
            masters[col] = []
    return masters


def load_sim_settings(
    client: gspread.Client | None = None,
) -> dict[str, float]:
    """『シミュレーション設定』シートから 項目→数値 の辞書を読み込む。

    - シートが存在しない場合は、デフォルト値で自動作成してから返す。
    - シートはあるが一部キーが欠けている場合は、その分だけデフォルトで補完する。
    これにより「ユーザーがシート側を書き換えれば次回リロードで自動反映」される。
    """
    defaults = config.default_sim_settings()
    ss = get_spreadsheet(client)

    try:
        ws = ss.worksheet(config.SIM_SETTINGS_SHEET)
    except gspread.WorksheetNotFound:
        _create_sim_settings_sheet(ss, defaults)
        return defaults

    records = ws.get_all_records()
    settings = dict(defaults)  # デフォルトを土台にシートの値で上書き
    for rec in records:
        key = str(rec.get(config.SIM_KEY_COL, "")).strip()
        if not key:
            continue
        raw = rec.get(config.SIM_VALUE_COL, "")
        value = _to_numeric_amount(pd.Series([raw])).iloc[0]
        settings[key] = float(value)
    return settings


def set_sim_setting(
    key: str, value, client: gspread.Client | None = None
) -> None:
    """『シミュレーション設定』シートの1項目を更新する（無ければ追記）。"""
    ss = get_spreadsheet(client)
    try:
        ws = ss.worksheet(config.SIM_SETTINGS_SHEET)
    except gspread.WorksheetNotFound:
        _create_sim_settings_sheet(ss, config.default_sim_settings())
        ws = ss.worksheet(config.SIM_SETTINGS_SHEET)
    cell = ws.find(str(key), in_column=1)
    if cell:
        ws.update_cell(cell.row, 2, value)
    else:
        ws.append_row([str(key), value], value_input_option="USER_ENTERED")


def _create_sim_settings_sheet(spreadsheet, defaults: dict[str, float]) -> None:
    """『シミュレーション設定』シートを作成し、デフォルト値を書き込む。"""
    ws = spreadsheet.add_worksheet(
        title=config.SIM_SETTINGS_SHEET,
        rows=len(defaults) + 5,
        cols=2,
    )
    rows = [[config.SIM_KEY_COL, config.SIM_VALUE_COL]]
    rows += [[key, value] for key, value in defaults.items()]
    ws.update(rows, value_input_option="USER_ENTERED")


def append_record(
    year_month: str,
    owner: str,
    account: str,
    category: str,
    amount: float,
    note: str = "",
    client: gspread.Client | None = None,
) -> None:
    """データベースシートに1行追記する。列順は config.DATABASE_COLUMNS。"""
    ws = get_spreadsheet(client).worksheet(config.DATABASE_SHEET)
    row = [year_month, owner, account, category, amount, note]
    ws.append_row(row, value_input_option="USER_ENTERED")
